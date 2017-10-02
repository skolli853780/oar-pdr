"""
Tools for reading data from a bag
"""

import os, logging, re, json, hashlib
from collections import OrderedDict

from .. import PreservationSystem, read_nerd, read_pod
from .. import NERDError, PODError, StateException
from .exceptions import BadBagRequest, ComponentNotFound, BagFormatError
from ... import def_jq_libdir, def_merge_etcdir
from ....nerdm.merge import MergerFactory, Merger
from ....nerdm.convert import ComponentCounter, HierarchyBuilder

POD_FILENAME = "pod.json"
NERDMD_FILENAME = "nerdm.json"
ANNOTS_FILENAME = "annot.json"
DEFAULT_MERGE_CONVENTION = "dev"

JQLIB = def_jq_libdir

class NISTBag(PreservationSystem):
    """
    an interface for reading data in a NIST-compliant BagIt bag.
    """

    # NOTE: this is an incomplete implementation 

    def __init__(self, rootdir, merge_annots=False):
        if not os.path.isdir(rootdir):
            raise StateException("Bag directory does not exist as a directory: "+
                                 rootdir, sys=self)
        self._dir = rootdir
        self._name = os.path.basename(rootdir)

        self._datadir = os.path.join(rootdir, "data")
        self._metadir = os.path.join(rootdir, "metadata")

        self._mergeannots = merge_annots

    @property
    def dir(self):
        """
        the path to the root directory of the bag
        """
        return self._dir

    @property
    def name(self):
        """
        the bag's name
        """
        return self._name

    @property
    def data_dir(self):
        """
        the path to the data directory for the bag
        """
        return self._datadir

    def _full_dpath(self, comppath):
        return os.path.join(self.data_dir, comppath)

    @property
    def metadata_dir(self):
        """
        the path to the metadata directory for the bag
        """
        return self._metadir

    def pod_file(self):
        return os.path.join(self._metadir, POD_FILENAME)

    def nerd_file_for(self, destpath):
        return os.path.join(self._metadir, destpath, NERDMD_FILENAME)

    def nerd_metadata_for(self, filepath, merge_annots=None):
        """
        return the component metadata for a given path to a component.

        :param merge_annots bool or Merger:  merge in any annotation data 
                                   found for the component.  (Default is the 
                                   value of the 'merge_annots' constructor 
                                   argument.)  For a complete bag, annotations 
                                   will already be merged into main NERDm 
                                   metadata; however, if this is not the case, 
                                   yet, one can merge on the fly while creating 
                                   the record.  If the value is a Merger object
                                   that object will be used to merge in the 
                                   annotations.
        """
        nerdfile = self.nerd_file_for(filepath)
        if not os.path.exists(nerdfile):
          raise ComponentNotFound("Component not found: " + filepath, 
                                  os.path.basename(self._name))
        out = self.read_nerd(nerdfile)

        if merge_annots is None:
            merge_annots = self._mergeannots
        annotfile = os.path.join(os.path.dirname(nerdfile), ANNOTS_FILENAME)
        if merge_annots and os.path.exists(annotfile):
            if merge_annots is True:
                merge_annots = DEFAULT_MERGE_CONVENTION
            compmerger = MergerFactory.make_merger(merge_annots, 'Component')
            
            if isinstance(merge_annots, Merger):
                compmerger = merge_annots
            else:
                compmerger = MergerFactory.make_merger(merge_annots, 'Component')

            annots = self.read_nerd(annotfile)
            comp = compmerger.merge(comp, annots)

        return out

    def nerdm_record(self, merge_annots=None):
        """
        return a full NERDm resource record for the data in this bag.

        :param merge_annots bool:  merge in any annotation data found in the bag.
                                   (Default is the value of the 'merge_annots'
                                   constructor argument.)  For a complete bag,
                                   annotations will already be merged into main
                                   NERDm metadata; however, if this is not the 
                                   case, yet, one can merge on the fly while 
                                   creating the record.  
        """
        if merge_annots is None:
            merge_annots = self._mergeannots
        if merge_annots is True:
            merge_annots = DEFAULT_MERGE_CONVENTION
        compmerger = None
        if merge_annots:
            compmerger = MergerFactory.make_merger(merge_annots, 'Component')

        out = None
        for root, subdirs, files in os.walk(self._metadir):
            if root == self._metadir:
                out = self.nerd_metadata_for("")
                if 'components' not in out:
                    out['components'] = []

                if merge_annots:
                    annotfile = os.path.join(root,ANNOTS_FILENAME)
                    if os.path.exists(annotfile):
                        annots = self.read_nerd(annotfile)
                        merger = MergerFactory.make_merger(merger_annots,
                                                           'Resource')
                        out = merger.merge(out, annots)

            elif NERDMD_FILENAME in files:
                comp = self.read_nerd(os.path.join(root, NERDMD_FILENAME))

                if merge_annots:
                    annotfile = os.path.join(root,ANNOTS_FILENAME)
                    if os.path.exists(annotfile):
                        annots = self.read_nerd(annotfile)
                        comp = compmerger.merge(comp, annots)

                out['components'].append(comp)

        if 'inventory' not in out:
            self.update_inventory_in(out)
        self.update_hierarchy_in(out)
        
        return out

    @classmethod
    def update_inventory_in(cls, resmd):
        """
        For the given NERDm record, add or update its 'inventory' 
        property to reflect its current set of components.
        """
        resmd['inventory'] = {}

        if 'components' in resmd:
            components = resmd['components']
            cc = ComponentCounter(JQLIB)
            resmd['inventory'] = cc.inventory(components)

        return resmd

    @classmethod
    def update_hierarchy_in(cls, resmd):
        """
        For the given NERDm record, add or update its 'dataHierarchy' 
        property to reflect its current set of components.  If the 
        components do not include any DataFile or Subcollection components,
        the 'dataHierarchy' property will be remove from the given record (or
        otherwise not added).  
        """
        hier = []
        if 'dataHierarchy' in resmd:
            del resmd['dataHierarchy']
        if 'components' in resmd:
            hb = HierarchyBuilder(JQLIB)
            hier = hb.build_hierarchy(resmd['components'])
        if hier:
            resmd['dataHierarchy'] = hier

        return resmd

    def comp_exists(self, comppath):
        """
        return True if the given path points to an existing component.
        The component is not guaranteed to be complete in its description.
        To exist, the path must exist either under the bag's data directory 
        or as a directory under the metadata directory.
        """
        if comppath == "":
            return True

        path = self._full_dpath(comppath)
        if os.path.exists(path):
            return True

        path = os.path.join(self.metadata_dir, comppath)
        if os.path.isdir(path):
            return True

        return False

    def is_data_file(self, comppath):
        """
        return True if the given component path appears to point to a 
        data file.
        """
        if not comppath:
            return False

        path = self._full_dpath(comppath)
        if os.path.isfile(path):
            return True

        path = self.nerd_file_for(comppath)
        if os.path.exists(path):
            mdata = self.read_nerd(path)
            return any([t for t in mdata['@type'] if ':DataFile' in t])

        return False

    def is_subcoll(self, comppath):
        """
        return True if the given component path appears to point to a 
        data file.
        """
        if comppath == "":
            # the root collection is considered a subcollection
            return True
        if not comppath:
            return False

        path = self._full_dpath(comppath)
        if os.path.isdir(path):
            return True

        path = self.nerd_file_for(comppath)
        if os.path.exists(path):
            mdata = self.read_nerd(path)
            return any([t for t in mdata['@type'] if ':Subcollection' in t])

        return False

    def subcoll_children(self, comppath):
        """
        return a list of a subcollection's contents (i.e it's direct children 
        only).  Each entry is just the basename of the component's filepath
        value.  
        """
        if not self.is_subcoll(comppath):
            raise BadBagRequest("Does not point to a subcollection: "+comppath,
                                bagname=self.name, sys=self)

        children = set()
        cdir = self._full_dpath(comppath)
        if os.path.exists(cdir):
            for c in os.listdir(cdir):
                if not c.startswith('.') and not c.startswith('_'):
                    children.add( c )

        cdir = os.path.join(self.metadata_dir, comppath)
        if os.path.exists(cdir):
            # add in child metadata directories that have a nerdm.json file
            for c in os.listdir(cdir):
                if not c.startswith('.') and not c.startswith('_') \
                   and os.path.exists(os.path.join(cdir,c,NERDMD_FILENAME)):
                    children.add( c )

        return list(children)
    
    def read_nerd(self, nerdfile):
        return read_nerd(nerdfile)

    def read_pod(self, podfile):
        return read_pod(podfile)

    def iter_data_files(self):
        """
        iterate through the data files available under the data directory.

        :return generator:  
        """
        for dir, subdirs, files in os.walk(self.data_dir):
            reldir = dir[len(self.data_dir)+1:]
            for f in files:
                # if f.startswith('.'):
                #     continue
                yield os.path.join(reldir, f)

    def iter_fetch_records(self):
        """
        iterate through the file fetching info from the bag's fetch file.  Each
        iteration returns a 3-tuple of URL, length, and bag file path for a file
        available for fetching.  The file paths are always relative to the 
        bag's base directory.  
        """
        fetchfile = os.path.join(self.dir, "fetch.txt")
        if os.path.exists(fetchfile):
            with open(fetchfile) as fd:
                for line in fd:
                    out = line.strip().split()
                    if len(out) != 3 or len([i for i in out if len(i) > 0]) != 3:
                        raise BagFormatError('Bad fetch.txt line syntax: "' +
                                             line + '"')
                    yield tuple(out)

    def iter_tagfile_lines(self, filepath):
        """
        iterate through the lines contained in tagfile with a given path.

        :param filepath str:  the full path to tag file (not relative to the 
                              bag's base directory).
        """
        with open(filepath) as fd:
            for line in fd:
                yield line.rstrip()

    def get_baginfo(self, altfile=None):
        """
        return the name-value data from the bag's bag-info.txt file as an
        OrderedDict dictionary with array values.  An empty dictionary is 
        returned if the file does not exist.

        :param altfile str:   path to the bag-info.txt file that should be 
                              read; if not provided, the standard "bag-info.txt"
                              file inside the bag will be read.  
        """
        out = OrderedDict()
        infofile = altfile
        if not infofile:
            infofile = os.path.join(self.dir, "bag-info.txt")
        if not os.path.exists(infofile):
            return out

        leadspc = re.compile("^\s+")
        taglines = self.iter_tagfile_lines(infofile)
        try:
            line = taglines.next()
        except StopIteration, ex:
            return out

        def parseline():
            parts = [p.strip() for p in line.split(':', 1)]
            if len(parts) < 2:
                parts.append('')
            if parts[0] in out:
                out[parts[0]].append(parts[1])
            else:
                out[parts[0]] = [ parts[1] ]

        for nxtline in taglines:
            if leadspc.match(nxtline):
                line += leadspc.sub(' ',nxtline)
                continue
            parseline()
            line = nxtline
            
        parseline()
                    
        return out
    
