"""
This module implements a validator for the base BagIt standard
"""
import os, re
from collections import OrderedDict

from .base import Validator, ValidatorBase, ValidationIssue, _VIE, _VIW, _VIR
from ..bag import NISTBag
from ..builder import checksum_of

csfunctions = {
    "sha256":  checksum_of
}

class BagItValidator(ValidatorBase):
    """
    A validator that runs tests for compliance to the base BagIt standard
    """
    profile = "BagIt v0.97"

    def __init__(self, config=None):
        super(BagItValidator, self).__init__(config)

    def test_bagit_txt(self, bag):
        """
        test that the bagit.txt file exists and has the required contents
        """
        out = []
        bagitf = os.path.join(bag.dir, "bagit.txt")
        if os.path.exists(bagitf):
            baginfo = bag.get_baginfo(bagitf)
            try:
                if baginfo['BagIt-Version'] != ["0.97"]:
                    out.append( self._err("2.1.1-3",
                                     "bagit.txt: BagIt-Version not set to 0.97"))
            except KeyError:
                out.append( self._err("2.1.1-2",
                                   "bagit.txt: missing element: BagIt-Version") )
            try:
                if baginfo['Tag-File-Character-Encoding'] != ["UTF-8"]:
                    out.append( self._err("2.1.1-5",
                                     "bagit.txt: Tag-File-Character-Encoding "+
                                     "not set to UTF-8"))
            except KeyError:
                out.append( self._err("2.1.1-4",
                                      "bagit.txt: missing element: " +
                                      "Tag-File-Character-Encoding") )

            if len(out) == 0 and \
               baginfo.keys() != ["BagIt-Version","Tag-File-Character-Encoding"]:
                out.append( self._rec("2.1.1-6",
                                      "bagit.txt: recommend using this " +
                                      "element order: BagIt-Version " +
                                      "Tag-File-Character-Encoding") )

        else:
            out.append(self._err("2.1.1-1", "bag-info.txt file is missing"))

        return out

    def test_data_dir(self, bag):
        """
        test that the data directory exists
        """
        out = []
        if not os.path.exists(os.path.join(bag.dir, "data")):
            out += [ self._err("2.1.2", "Missing payload directory, data/") ]
        return out

    def test_manifest(self, bag):
        out = []
        tcfg = self.cfg.get("test_manifest", {})
        check = tcfg.get('check_checksums', True)

        manire = re.compile(r'^manifest-(\w+).txt$')
        manifests = [f for f in os.listdir(bag.dir) if manire.match(f)]
        if len(manifests) > 0:
            for mfile in manifests:
                alg = manire.match(mfile).group(1)
                csfunc = None
                if alg in csfunctions:
                    csfunc = csfunctions[alg]

                badlines = []
                notdata = []
                paths = OrderedDict()
                with open(os.path.join(bag.dir, mfile)) as fd:
                    i = 0
                    for line in fd:
                        i += 1
                        parts = line.split()
                        if len(parts) != 2:
                            badlines.append(i)
                            continue
                        if parts[1].startswith('*'):
                            parts[1] = parts[1][1:]
                            parts.append('*')

                        if not parts[1].startswith('data/'):
                            notdata.append(parts[1])
                        else:
                            paths[parts[1]] = parts[0]

                if badlines:
                    if len(badlines) > 4:
                        badlines[3] = "..."
                        badlines = badlines[:4]
                    out += [self._err("2.1.3-2",
                                      "{0} format issues found (lines {1})"
                                      .format(mfile, ", ".join([str(b)
                                                        for b in badlines])))]

                if notdata:
                    s = (len(notdata) > 1 and "s") or ""
                    out += [self._err("2.1.3-3",
                  "bag-info.txt lists {0} non-payload (i.e. under data/) file{1}"
                                      .format(len(notdata), s))]

                # make sure all paths exist
                badpaths = []
                for datap in paths:
                    fp = os.path.join(bag.dir, datap)
                    if not os.path.exists(fp):
                        badpaths.append(datap)
                    elif not os.path.isfile(fp):
                        out += [self._err("2.1.3-7",
                                          "Manifest entry is not a file: "+
                                          datap)]

                if badpaths:
                    for datap in badpaths[:4]:
                        out += [self._err("3-1-2",
                                        "Path in manifest missing in payload: "+
                                          datap)]
                    if len(badpaths) > 4:
                        addl = len(badpaths) - 3
                        out[-1] = self._err("3-1-2",
                   "{0} additional files missing from payload (data/) directory"
                                            .format(addl))

                # check that all files in the payload are listed in the manifest
                notfound = []
                failed = []
                for root, subdirs, files in os.walk(bag.data_dir):
                    for f in files:
                        fp = os.path.join(root, f)
                        assert fp.startswith(bag.dir+'/')
                        datap = fp[len(bag.dir)+1:]

                        if datap not in paths:
                            notfound.append(datap)
                        elif check and csfunc and csfunc(fp) != paths[datap]:
                            failed.append(datap)

                if notfound:
                    for datap in notfound[:4]:
                        out += [self._rec("2.1.3-4",
                                          "Payload file not listed in {0}: {1}"
                                          .format(mfile, datap))]
                    if len(notfound) > 4:
                        addl = len(notfound) - 3
                        out[-1] = self._rec("2.1.3-4",
                          "{0} additional payload (data/) files missing from {1}"
                                            .format(addl, mfile))
                if failed:
                    for datap in failed[:4]:
                        out += [self._err("2.1.3-5",
                        "{0}: Recorded checksum does not match payload file: {1}"
                                     .format(mfile, datap))]
                    if len(notfound) > 4:
                        addl = len(notfound) - 3
                        out[-1] = self._err("2.1.3-5",
            "{0}: Checksums don't match for {1} additional payload (data/) files"
                                       .format(mfile, addl))

        else:
            out += [self._err("2.1.3-1", "No manifest-<alg>.txt files found")]

        return out
            
    def test_baginfo(self, bag):
        out = []
        baginfof = os.path.join(bag.dir, "bag-info.txt")

        if os.path.exists(baginfof):
            out += self.check_baginfo_format(baginfof)
            baginfo = bag.get_baginfo()

        else:
            out += [self._rec("2.2.2-1", "Recommend adding a bag-info.txt file")]

        return out

    def check_baginfo_format(self, baginfof):
        out = []

        badlines = []
        fmtre = re.compile("^[\w\-]+\s*:\s*\S.*$")
        cntre = re.compile("^\s+")
        i = 0
        with open(baginfof) as fd:
            for line in fd:
                i += 1
                if not fmtre.match(line) and (i == 1 or not cntre.match(line)):
                    badlines.append(i)

        if badlines:
            if len(badlines) > 4:
                badlines[3] = '...'
                badlines = badlines[:4]

            out += [self._err("2.2.2-2",
                              "bag-info.txt format issues found (lines {0})"
                              .format(", ".join([str(b) for b in badlines])))]

        return out
