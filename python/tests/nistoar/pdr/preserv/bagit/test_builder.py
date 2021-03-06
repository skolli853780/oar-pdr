import os, sys, pdb, shutil, logging, json, re
from cStringIO import StringIO
from shutil import copy2 as filecopy, rmtree
from io import BytesIO
import warnings as warn
import unittest as test
from collections import OrderedDict

from nistoar.testing import *
import nistoar.pdr.preserv.bagit.builder as bldr
import nistoar.pdr.exceptions as exceptions
from nistoar.pdr.utils import read_nerd

# datadir = tests/nistoar/pdr/preserv/data
datadir = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "data", "simplesip"
)

loghdlr = None
rootlog = None
def setUpModule():
    ensure_tmpdir()
#    logging.basicConfig(filename=os.path.join(tmpdir(),"test_builder.log"),
#                        level=logging.INFO)
    rootlog = logging.getLogger()
    loghdlr = logging.FileHandler(os.path.join(tmpdir(),"test_builder.log"))
    loghdlr.setLevel(logging.INFO)
    loghdlr.setFormatter(logging.Formatter(bldr.DEF_BAGLOG_FORMAT))
    rootlog.addHandler(loghdlr)

def tearDownModule():
    global loghdlr
    if loghdlr:
        if rootlog:
            rootlog.removeLog(loghdlr)
        loghdlr = None
    rmtmpdir()

class TestBuilder(test.TestCase):

    testsip = os.path.join(datadir, "simplesip")

    def setUp(self):
        self.tf = Tempfiles()
        self.cfg = {
            "init_bag_info": {
                'NIST-BagIt-Version': "X.3",
                "Organization-Address": ["100 Bureau Dr.",
                                         "Gaithersburg, MD 20899"]
            }
        }

        self.bag = bldr.BagBuilder(self.tf.root, "testbag", self.cfg)
        self.tf.track("testbag")
        self.tf.track("issued-ids.json")

    def tearDown(self):
        self.bag._unset_logfile()
        self.bag = None
        self.tf.clean()

    def test_ctor(self):
        self.assertEqual(self.bag.bagname, "testbag")
        self.assertEqual(self.bag.bagdir, os.path.join(self.tf.root, "testbag"))
        self.assertTrue(self.bag.log)
        self.assertFalse(self.bag._loghdlr)
        self.assertEqual(self.bag.logname, "preserv.log")
        self.assertIsNone(self.bag.id)
        self.assertIsNone(self.bag.ediid)

        baginfo = self.bag.cfg['init_bag_info']
        self.assertEqual(baginfo['NIST-BagIt-Version'], 'X.3')
        self.assertEqual(baginfo['Contact-Email'], ["datasupport@nist.gov"],
                         "Failed to load default config params")

    def test_download_url(self):
        self.assertEqual(self.bag._download_url('goob',
                                                os.path.join("foo", "bar.json")),
                         "https://data.nist.gov/od/ds/goob/foo/bar.json")

    def test_ensure_bagdir(self):
        self.bag.ensure_bagdir()

        self.assertTrue(os.path.exists(self.bag.bagdir))

    def test_fix_id(self):
        self.assertIsNone(self.bag._fix_id(None))
        fixed = "ark:/88434/pdr06f90"
        self.assertEqual(self.bag._fix_id(fixed), fixed)
        self.assertEqual(self.bag._fix_id("Ark:/88434/pdr06f90"), fixed)
        self.assertEqual(self.bag._fix_id("ARK:/88434/pdr06f90"), fixed)
        self.assertEqual(self.bag._fix_id("/88434/pdr06f90"), fixed)
        self.assertEqual(self.bag._fix_id("88434/pdr06f90"), fixed)

        self.bag = bldr.BagBuilder(self.tf.root, "testbag", id="88434/pdr06f90")
        self.assertEqual(self.bag.id, fixed)

    def test_mint_id(self):
        ediid = 'EBC9DB05EDEA5B0EE043065706812DF81'
        self.assertEqual(self.bag._mint_id(ediid), 'ark:/88434/mds00nbc5c')
        
    def test_logging(self):
        self.test_ensure_bagdir()
        
        # test log setup
        self.assertTrue(self.bag._loghdlr)
        self.bag.record("First message")
        self.bag.log.warn("Warning")
        self.bag.log.debug("oops")
#        self.bag._unset_logfile()
        logfile = os.path.join(self.bag.bagdir,self.bag.logname)
        self.assertTrue(os.path.exists(logfile))
        with open(logfile) as fd:
            lines = fd.readlines()
        self.assertEqual(len(lines), 3)
        self.assertIn("Created ", lines[0])
        self.assertIn(self.bag.bagname, lines[0])
        self.assertIn("First message", lines[1])
        self.assertIn("Warning", lines[2])

    def test_ensure_bag_structure(self):
        self.bag.ensure_bag_structure()

        self.assertTrue(os.path.exists(self.bag.bagdir))
        self.assertTrue(os.path.exists(os.path.join(self.bag.bagdir,"data")))
        self.assertTrue(os.path.exists(os.path.join(self.bag.bagdir,"metadata")))

        # test indepodent and extra directories
        self.bag.cfg['extra_tag_dirs'] = ['metameta']
        self.bag.ensure_bag_structure()

        self.assertTrue(os.path.exists(self.bag.bagdir))
        self.assertTrue(os.path.exists(os.path.join(self.bag.bagdir,"data")))
        self.assertTrue(os.path.exists(os.path.join(self.bag.bagdir,"metadata")))
        self.assertTrue(os.path.exists(os.path.join(self.bag.bagdir,"metameta")))
        
    def test_ensure_datafile_dirs(self):
        ddir = os.path.join("trial1","gold")
        path = os.path.join(ddir,"file.dat")
        self.bag.ensure_datafile_dirs(path)

        self.assertTrue(os.path.exists(self.bag.bagdir))
        self.assertTrue(os.path.exists(os.path.join(self.bag.bagdir,"data")))
        self.assertTrue(os.path.exists(os.path.join(self.bag.bagdir,"metadata")))
        self.assertTrue(os.path.exists(os.path.join(self.bag.bagdir,"metadata")))
        
        self.assertTrue(os.path.exists(os.path.join(self.bag.bagdir,
                                                    "data",ddir)))
        self.assertTrue(os.path.exists(os.path.join(self.bag.bagdir,
                                                    "metadata",path)))

        # is indepotent
        self.bag.ensure_datafile_dirs(path)
        self.assertTrue(os.path.exists(os.path.join(self.bag.bagdir,
                                                    "data",ddir)))
        self.assertTrue(os.path.exists(os.path.join(self.bag.bagdir,
                                                    "metadata",path)))

        # test illegal paths
        with self.assertRaises(Exception):
            self.bag.ensure_datafile_dirs("/foo/bar")
        with self.assertRaises(Exception):
            self.bag.ensure_datafile_dirs("foo/../../bar")

    def test_ensure_ansc_collmd(self):
        path = os.path.join("trial1","gold")
        self.bag.ensure_ansc_collmd(path)

        self.assertTrue(os.path.exists(self.bag.bagdir))
        self.assertTrue(os.path.exists(os.path.join(self.bag.bagdir,"data")))
        self.assertTrue(os.path.exists(os.path.join(self.bag.bagdir,"metadata")))
        
        self.assertFalse(os.path.exists(os.path.join(self.bag.bagdir,
                                                     "data",path)))
        self.assertTrue(os.path.exists(os.path.join(self.bag.bagdir,
                                              "metadata","trial1","nerdm.json")))
        self.assertFalse(os.path.exists(os.path.join(self.bag.bagdir,
                                                     "metadata",path)))

        # is indepotent
        self.bag.ensure_ansc_collmd(path)
        self.assertFalse(os.path.exists(os.path.join(self.bag.bagdir,
                                                     "data",path)))
        self.assertTrue(os.path.exists(os.path.join(self.bag.bagdir,
                                              "metadata","trial1","nerdm.json")))
        self.assertFalse(os.path.exists(os.path.join(self.bag.bagdir,
                                                     "metadata",path)))

        # test illegal paths
        with self.assertRaises(ValueError):
            self.bag.ensure_ansc_collmd("/foo/bar")
        with self.assertRaises(ValueError):
            self.bag.ensure_ansc_collmd("foo/../../bar")

    def test_ensure_metadata_dirs(self):
        path = os.path.join("trial1","gold")
        self.bag.ensure_metadata_dirs(path)

        self.assertTrue(os.path.exists(self.bag.bagdir))
        self.assertTrue(os.path.exists(os.path.join(self.bag.bagdir,"data")))
        self.assertTrue(os.path.exists(os.path.join(self.bag.bagdir,"metadata")))
        
        self.assertFalse(os.path.exists(os.path.join(self.bag.bagdir,
                                                     "data",path)))
        self.assertTrue(os.path.exists(os.path.join(self.bag.bagdir,
                                                    "metadata",path)))

        # is indepotent
        self.bag.ensure_metadata_dirs(path)
        self.assertTrue(os.path.exists(os.path.join(self.bag.bagdir,
                                                    "metadata",path)))

        # test illegal paths
        with self.assertRaises(ValueError):
            self.bag.ensure_metadata_dirs("/foo/bar")
        with self.assertRaises(ValueError):
            self.bag.ensure_metadata_dirs("foo/../../bar")


    def test_pod_file(self):
        self.assertEquals(self.bag.pod_file(),
                      os.path.join(self.bag.bagdir,"metadata","pod.json"))

    def test_nerdm_file_for(self):
        path = os.path.join("trial1","gold","file.dat")
        self.assertEquals(self.bag.nerdm_file_for(path),
                      os.path.join(self.bag.bagdir,"metadata",path,"nerdm.json"))
        self.assertEquals(self.bag.nerdm_file_for(""),
                      os.path.join(self.bag.bagdir,"metadata","nerdm.json"))

    def test_annot_file_for(self):
        path = os.path.join("trial1","gold","file.dat")
        self.assertEquals(self.bag.annot_file_for(path),
                      os.path.join(self.bag.bagdir,"metadata",path,"annot.json"))
        self.assertEquals(self.bag.annot_file_for(""),
                      os.path.join(self.bag.bagdir,"metadata","annot.json"))
        
    def test_add_metadata_for_coll(self):
        path = os.path.join("trial1","gold")
        md = { "foo": "bar", "gurn": "goob", "numbers": [ 1,3,5]}
        need = self.bag.init_collmd_for(path)
        need.update(md)

        self.bag.add_metadata_for_coll(path, md)
        mdf = os.path.join(self.bag.bagdir, "metadata", path, "nerdm.json")
        self.assertTrue(os.path.exists(mdf))
        with open(mdf) as fd:
            data = json.load(fd)
        self.assertEquals(data, need)
        
    def test_add_metadata_for_file(self):
        path = os.path.join("trial1","gold", "file.dat")
        md = { "foo": "bar", "gurn": "goob", "numbers": [ 1,3,5]}
        need = self.bag.init_filemd_for(path)
        need.update(md)

        self.bag.add_metadata_for_file(path, md)
        mdf = os.path.join(self.bag.bagdir, "metadata", path, "nerdm.json")
        self.assertTrue(os.path.exists(mdf))
        with open(mdf) as fd:
            data = json.load(fd)
        self.assertEquals(data, need)
        
    def test_init_filemd_for(self):
        path = os.path.join("trial1","gold","file.dat")
        need = {
            "@id": "cmps/"+path,
            "@type": [ "nrdp:DataFile", "nrdp:DownloadableFile", "dcat:Distribution" ],
            "filepath": path,
            "_extensionSchemas": [ "https://data.nist.gov/od/dm/nerdm-schema/pub/v0.1#/definitions/DataFile" ]
        }
        mdf = os.path.join(self.bag.bagdir, "metadata", path, "nerdm.json")
        self.assertFalse(os.path.exists(mdf))
        self.assertEqual(self.bag._distbase, "https://data.nist.gov/od/ds/")

        md = self.bag.init_filemd_for(path)
        self.assertEquals(md, need)
        self.assertFalse(os.path.exists(mdf))
        self.assertFalse(self.bag.ediid)
        self.assertNotIn('downloadURL', md)

        md = self.bag.init_filemd_for(path, True)
        self.assertTrue(os.path.exists(mdf))
        with open(mdf) as fd:
            data = json.load(fd)
        self.assertEquals(data, md)

        self.bag._ediid = "gooberid"
        dlurl = "https://data.nist.gov/od/ds/gooberid/trial1/gold/file.dat"
        md = self.bag.init_filemd_for(path)
        self.assertTrue(self.bag.ediid)
        self.assertIn('downloadURL', md)
        self.assertEqual(md['downloadURL'], dlurl)

        self.cfg['distrib_service_baseurl'] = "https://testdata.nist.gov/od/ds"
        self.bag = bldr.BagBuilder(self.tf.root, "testbag", self.cfg)
        self.assertEqual(self.bag._distbase, "https://testdata.nist.gov/od/ds/")
        self.bag._ediid = "gooberid"
        dlurl = "https://testdata.nist.gov/od/ds/gooberid/trial1/gold/file.dat"
        md = self.bag.init_filemd_for(path)
        self.assertTrue(self.bag.ediid)
        self.assertIn('downloadURL', md)
        self.assertEqual(md['downloadURL'], dlurl)

    def test_init_filemd_for_encoding(self):
        path = os.path.join("trial 1","1%gold","iron+wine.dat")
        epath = "trial%201/1%25gold/iron%2Bwine.dat"
        self.bag._ediid = "gooberid"
        need = {
            "@id": "cmps/"+epath,
            "@type": [ "nrdp:DataFile", "nrdp:DownloadableFile", "dcat:Distribution" ],
            "filepath": path,
            "downloadURL": "https://data.nist.gov/od/ds/gooberid/trial%201/1%25gold/iron%2Bwine.dat",
            "_extensionSchemas": [ "https://data.nist.gov/od/dm/nerdm-schema/pub/v0.1#/definitions/DataFile" ]
        }
        mdf = os.path.join(self.bag.bagdir, "metadata", path, "nerdm.json")
        self.assertFalse(os.path.exists(mdf))
        self.assertEqual(self.bag._distbase, "https://data.nist.gov/od/ds/")

        md = self.bag.init_filemd_for(path)
        self.assertEquals(md, need)
        self.assertFalse(os.path.exists(mdf))

    def test_init_filemd_for_checksumfile(self):
        path = os.path.join("trial1","gold","file.dat")
        need = {
            "@id": "cmps/"+path,
            "@type": [ "nrdp:ChecksumFile", "nrdp:DownloadableFile", "dcat:Distribution" ],
            "filepath": path,
            "_extensionSchemas": [ "https://data.nist.gov/od/dm/nerdm-schema/pub/v0.1#/definitions/ChecksumFile" ]
        }
        mdf = os.path.join(self.bag.bagdir, "metadata", path, "nerdm.json")
        self.assertFalse(os.path.exists(mdf))
        self.assertEqual(self.bag._distbase, "https://data.nist.gov/od/ds/")

        md = self.bag.init_filemd_for(path, disttype="ChecksumFile")
        self.assertEquals(md, need)
        self.assertFalse(os.path.exists(mdf))
        self.assertFalse(self.bag.ediid)
        self.assertNotIn('downloadURL', md)

        path2 = path+".md5"
        need['@id'] = "cmps/"+path2
        need['filepath'] = path2
        mdf = os.path.join(self.bag.bagdir, "metadata", path2, "nerdm.json")
        self.assertFalse(os.path.exists(mdf))
        self.assertEqual(self.bag._distbase, "https://data.nist.gov/od/ds/")

        md = self.bag.init_filemd_for(path2, disttype="ChecksumFile")
        self.assertEquals(md, need)
        self.assertFalse(os.path.exists(mdf))
        self.assertFalse(self.bag.ediid)
        self.assertNotIn('downloadURL', md)

        path2 = path+".sha256"
        need['@id'] = "cmps/"+path2
        need['filepath'] = path2
        need['describes'] = "cmps/"+path
        need['description'] = "SHA-256 checksum value for " + \
                              os.path.basename(path)
        need['algorithm'] = {'@type': 'Thing', 'tag': 'sha256'}
        mdf = os.path.join(self.bag.bagdir, "metadata", path2, "nerdm.json")
        self.assertFalse(os.path.exists(mdf))
        self.assertEqual(self.bag._distbase, "https://data.nist.gov/od/ds/")

        md = self.bag.init_filemd_for(path2, disttype="ChecksumFile")
        self.assertEquals(md, need)
        self.assertFalse(os.path.exists(mdf))
        self.assertFalse(self.bag.ediid)
        self.assertNotIn('downloadURL', md)

    def test_examine(self):
        path = os.path.join("trial1","gold","trial1.json")
        need = {
            "@id": "cmps/"+path,
            "@type": [ "nrdp:DataFile", "nrdp:DownloadableFile", "dcat:Distribution" ],
            "filepath": path,
            "_extensionSchemas": [ "https://data.nist.gov/od/dm/nerdm-schema/pub/v0.1#/definitions/DataFile" ],
            "size": 69,
            "mediaType": "application/json",
            "checksum": {
                "algorithm": { "@type": "Thing", "tag": "sha256" },
                "hash": \
              "d155d99281ace123351a311084cd8e34edda6a9afcddd76eb039bad479595ec9"
            }
        }
        datafile = os.path.join(datadir, "trial1.json")

        mdata = self.bag.init_filemd_for(path, write=False, examine=datafile)
        self.assertEquals(mdata, need)

    def test_init_collmd_for(self):
        path = os.path.join("trial1","gold")
        md = self.bag.init_collmd_for(path)
        need = {
            "@id": "cmps/"+path,
            "@type": [ "nrdp:Subcollection" ],
            "filepath": path,
            "_extensionSchemas": [ "https://data.nist.gov/od/dm/nerdm-schema/pub/v0.1#/definitions/Subcollection" ]
        }
        mdf = os.path.join(self.bag.bagdir, "metadata", path, "nerdm.json")
        self.assertFalse(os.path.exists(mdf))

        md = self.bag.init_collmd_for(path)
        self.assertEquals(md, need)
        self.assertFalse(os.path.exists(mdf))

        md = self.bag.init_collmd_for(path, True)
        self.assertTrue(os.path.exists(mdf))
        with open(mdf) as fd:
            data = json.load(fd)
        self.assertEquals(data, md)

    def test_add_data_file(self):
        path = os.path.join("trial1","gold","trial1.json")
        bagfilepath = os.path.join(self.bag.bagdir, 'data',path)
        bagmdpath = os.path.join(self.bag.bagdir, 'metadata',path,"nerdm.json")
        self.assertFalse( os.path.exists(bagfilepath) )
        self.assertFalse( os.path.exists(bagmdpath) )

        self.bag.add_data_file(path, os.path.join(datadir,"trial1.json"))
        self.assertTrue( os.path.exists(bagfilepath) )
        self.assertTrue( os.path.exists(bagmdpath) )

        need = {
            "@id": "cmps/"+path,
            "@type": [ "nrdp:DataFile", "nrdp:DownloadableFile", "dcat:Distribution" ],
            "filepath": path,
            "_extensionSchemas": [ "https://data.nist.gov/od/dm/nerdm-schema/pub/v0.1#/definitions/DataFile" ],
            "size": 69,
            "mediaType": "application/json",
            "checksum": {
                "algorithm": { "@type": "Thing", "tag": "sha256" },
                "hash": \
              "d155d99281ace123351a311084cd8e34edda6a9afcddd76eb039bad479595ec9"
            }
        }
        with open(bagmdpath) as fd:
            data = json.load(fd)
        self.assertEqual(data, need)
        
    def test_add_data_no_file(self):
        path = os.path.join("trial1","gold","trial1.json")
        bagfilepath = os.path.join(self.bag.bagdir, 'data',path)
        bagmdpath = os.path.join(self.bag.bagdir, 'metadata',path,"nerdm.json")
        self.assertFalse( os.path.exists(bagfilepath) )
        self.assertFalse( os.path.exists(bagmdpath) )

        self.bag.add_data_file(path)
        self.assertFalse( os.path.exists(bagfilepath) )
        self.assertTrue( os.path.exists(bagmdpath) )

        need = {
            "@id": "cmps/"+path,
            "@type": [ "nrdp:DataFile", "nrdp:DownloadableFile", "dcat:Distribution" ],
            "filepath": path,
            "_extensionSchemas": [ "https://data.nist.gov/od/dm/nerdm-schema/pub/v0.1#/definitions/DataFile" ]
        }
        with open(bagmdpath) as fd:
            data = json.load(fd)
        self.assertEqual(data, need)

    def test_add_res_nerd(self):
        self.assertIsNone(self.bag.ediid)
        with open(os.path.join(datadir, "_nerdm.json")) as fd:
            mdata = json.load(fd)

        self.bag.add_res_nerd(mdata)
        self.assertEqual(self.bag.ediid, mdata['ediid'])
        ddir = os.path.join(self.bag.bagdir,"data")
        mdir = os.path.join(self.bag.bagdir,"metadata")
        nerdfile = os.path.join(mdir,"nerdm.json")
        self.assertTrue(os.path.isdir(ddir))
        self.assertTrue(os.path.isdir(mdir))
        self.assertTrue(os.path.exists(nerdfile))
#        self.assertTrue(os.path.exists(os.path.join(ddir,
#                                "1491_optSortSphEvaluated20160701.cdf")))
        self.assertTrue(os.path.exists(os.path.join(mdir,
                          "1491_optSortSphEvaluated20160701.cdf","nerdm.json")))
#        self.assertTrue(os.path.exists(os.path.join(ddir,
#                                "1491_optSortSphEvaluated20160701.cdf.sha256")))
        self.assertTrue(os.path.exists(os.path.join(mdir,
                    "1491_optSortSphEvaluated20160701.cdf.sha256","nerdm.json")))
        self.assertEqual(len([f for f in os.listdir(mdir)
                                if not f.startswith('.') and
                                   not f.endswith('.json')]), 6)
        
        with open(nerdfile) as fd:
            data = json.load(fd)
        self.assertEqual(data['ediid'], '3A1EE2F169DD3B8CE0531A570681DB5D1491')
        self.assertEqual(len(data['components']), 1)
        self.assertNotIn('inventory', data)
        self.assertNotIn('dataHierarchy', data)

        with open(os.path.join(mdir,
                  "1491_optSortSphEvaluated20160701.cdf","nerdm.json")) as fd:
            data = json.load(fd)
        self.assertEqual(data['filepath'],"1491_optSortSphEvaluated20160701.cdf")
            
    def test_add_res_nerd_nofilemd(self):
        with open(os.path.join(datadir, "_nerdm.json")) as fd:
            mdata = json.load(fd)

        self.bag.add_res_nerd(mdata, False)
        ddir = os.path.join(self.bag.bagdir,"data")
        mdir = os.path.join(self.bag.bagdir,"metadata")
        nerdfile = os.path.join(mdir,"nerdm.json")
        self.assertTrue(os.path.isdir(ddir))
        self.assertTrue(os.path.isdir(mdir))
        self.assertTrue(os.path.exists(nerdfile))

        self.assertEqual(len([f for f in os.listdir(mdir)
                                if not f.startswith('.') and
                                   not f.endswith('.json')]), 0)

    def test_update_ediid(self):
        self.assertIsNone(self.bag.ediid)
        with open(os.path.join(datadir, "_nerdm.json")) as fd:
            mdata = json.load(fd)
        self.bag.add_res_nerd(mdata)
        self.assertIsNotNone(self.bag.ediid)

        destpath = "foo/bar.json"
        dlurl = "https://data.nist.gov/od/ds/"+self.bag.ediid+'/'+destpath
        self.bag.init_filemd_for(destpath, write=True)
        with open(self.bag.nerdm_file_for(destpath)) as fd:
            mdata = json.load(fd)
        self.assertTrue(mdata['downloadURL'], dlurl)

        self.bag.ediid = "gurn"

        with open(self.bag.nerdm_file_for("")) as fd:
            mdata = json.load(fd)
        self.assertEqual(mdata['ediid'], 'gurn')
        dlurl = "https://data.nist.gov/od/ds/gurn/"+destpath
        with open(self.bag.nerdm_file_for(destpath)) as fd:
            mdata = json.load(fd)
        self.assertEqual(mdata['downloadURL'], dlurl)

    def test_add_annotation_for(self):
        mdata = { "foo": "bar" }
        self.bag.add_annotation_for("goob", mdata)
        annotfile = os.path.join(self.bag.bagdir,"metadata","goob", "annot.json")
                                 
        self.assertTrue(os.path.isfile(annotfile))

        with open(annotfile) as fd:
            data = json.load(fd)
        self.assertEqual(data, mdata)
                        
        self.bag.add_annotation_for("", mdata)
        annotfile = os.path.join(self.bag.bagdir,"metadata","goob", "annot.json")
        self.assertTrue(os.path.isfile(annotfile))
        
        with open(annotfile) as fd:
            data = json.load(fd)
        self.assertEqual(data, mdata)


    def test_add_ds_pod(self):
        self.assertIsNone(self.bag.ediid)
        podfile = os.path.join(datadir, "_pod.json")
        with open(podfile) as fd:
            poddata = json.load(fd)
        self.bag.add_ds_pod(poddata, convert=False)
        self.assertTrue(os.path.exists(self.bag.pod_file()))
        self.assertIsNone(self.bag.ediid)
        with open(self.bag.pod_file()) as fd:
            data = json.load(fd)
        self.assertEqual(data, poddata)
        self.assertFalse(os.path.exists(self.bag.nerdm_file_for("")))
        self.assertFalse(os.path.exists(self.bag.nerdm_file_for("trial1.json")))
        self.assertFalse(os.path.exists(self.bag.nerdm_file_for("trial3/trial3a.json")))

    def test_add_ds_pod_convert(self):
        self.assertIsNone(self.bag.ediid)
        podfile = os.path.join(datadir, "_pod.json")
        with open(podfile) as fd:
            poddata = json.load(fd)
        self.bag.add_ds_pod(poddata, convert=True, savefilemd=False)
        self.assertTrue(os.path.exists(self.bag.pod_file()))
        self.assertEqual(self.bag.ediid, poddata['identifier'])

        nerdfile = self.bag.nerdm_file_for("")
        self.assertTrue(os.path.exists(nerdfile))
        with open(nerdfile) as fd:
            data = json.load(fd)
        self.assertEqual(data['modified'], poddata['modified'])
        self.assertEqual(data['@id'], "ark:/88434/mds00hw91v")
        self.assertFalse(os.path.exists(self.bag.nerdm_file_for("trial1.json")))
        self.assertFalse(os.path.exists(self.bag.nerdm_file_for("trial3/trial3a.json")))

    def test_add_ds_pod_filemd(self):
        podfile = os.path.join(datadir, "_pod.json")
        with open(podfile) as fd:
            poddata = json.load(fd)
        #pdb.set_trace()
        self.bag.add_ds_pod(poddata, convert=True, savefilemd=True)
        self.assertTrue(os.path.exists(self.bag.pod_file()))

        nerdfile = self.bag.nerdm_file_for("")
        self.assertTrue(os.path.exists(nerdfile))
        with open(nerdfile) as fd:
            data = json.load(fd)
        self.assertEqual(data['modified'], poddata['modified'])
        self.assertEqual(data['@id'], "ark:/88434/mds00hw91v")
        self.assertTrue(os.path.exists(self.bag.nerdm_file_for("trial1.json")))
        self.assertTrue(os.path.exists(self.bag.nerdm_file_for("trial3/trial3a.json")))
        nerdfile = self.bag.nerdm_file_for("trial3/trial3a.json")
        with open(nerdfile) as fd:
            data = json.load(fd)
        self.assertEquals(data['filepath'], "trial3/trial3a.json")
        self.assertEquals(data['@id'], "cmps/trial3/trial3a.json")

    def test_remove_component(self):
        path = os.path.join("trial1","gold","trial1.json")
        bagfilepath = os.path.join(self.bag.bagdir, 'data',path)
        bagmdpath = os.path.join(self.bag.bagdir, 'metadata',path,"nerdm.json")
        self.assertFalse( os.path.exists(bagfilepath) )
        self.assertFalse( os.path.exists(bagmdpath) )
        self.assertFalse( os.path.exists(os.path.dirname(bagmdpath)) )
        self.assertFalse( os.path.exists(os.path.dirname(bagfilepath)) )

        # add and remove data and metadata
        self.bag.add_data_file(path, os.path.join(datadir,"trial1.json"))
        self.assertTrue( os.path.exists(bagfilepath) )
        self.assertTrue( os.path.exists(bagmdpath) )

        self.assertTrue(self.bag.remove_component(path))
        self.assertFalse( os.path.exists(bagfilepath) )
        self.assertFalse( os.path.exists(bagmdpath) )
        self.assertFalse( os.path.exists(os.path.dirname(bagmdpath)) )
        self.assertTrue( os.path.exists(os.path.dirname(bagfilepath)) )

        # add and remove just metadata
        self.bag.init_filemd_for(path, write=True,
                                 examine=os.path.join(datadir,"trial1.json"))
        self.assertFalse( os.path.exists(bagfilepath) )
        self.assertTrue( os.path.exists(bagmdpath) )

        self.assertTrue(self.bag.remove_component(path))
        self.assertFalse( os.path.exists(bagfilepath) )
        self.assertFalse( os.path.exists(bagmdpath) )
        self.assertFalse( os.path.exists(os.path.dirname(bagmdpath)) )
        self.assertTrue( os.path.exists(os.path.dirname(bagfilepath)) )

        # just a data file exists
        self.assertFalse( os.path.exists(os.path.join(self.bag.bagdir,
                                                      "data", "trial1.json")) )
        filecopy(os.path.join(datadir,"trial1.json"),
                 os.path.join(self.bag.bagdir, "data", "trial1.json"))
        self.assertTrue( os.path.exists(os.path.join(self.bag.bagdir,
                                                      "data", "trial1.json")) )
        self.assertTrue(self.bag.remove_component("trial1.json"))
        self.assertFalse( os.path.exists(os.path.join(self.bag.bagdir,
                                                      "data", "trial1.json")) )

    def test_remove_component_trim(self):
        gold = os.path.join("trial1","gold")
        golddir = os.path.join(self.bag.bagdir, "data", gold)
        t1path = os.path.join(gold, "trial1.json")
        t2path = os.path.join("trial1","trial2.json")
        t1bagfilepath = os.path.join(self.bag.bagdir, 'data',t1path)
        t1bagmdpath = os.path.join(self.bag.bagdir, 'metadata',
                                   t1path,"nerdm.json")
        t2bagfilepath = os.path.join(self.bag.bagdir, 'data',t2path)
        t2bagmdpath = os.path.join(self.bag.bagdir, 'metadata',
                                   t2path,"nerdm.json")
        self.assertFalse( os.path.exists(t1bagfilepath) )
        self.assertFalse( os.path.exists(t1bagmdpath) )
        self.assertFalse( os.path.exists(os.path.dirname(t1bagmdpath)) )
        self.assertFalse( os.path.exists(os.path.dirname(t1bagfilepath)) )

        self.bag.add_data_file(t1path, os.path.join(datadir,"trial1.json"))
        self.bag.add_data_file(t2path, os.path.join(datadir,"trial2.json"))
        self.assertTrue( os.path.exists(t1bagfilepath) )
        self.assertTrue( os.path.exists(t1bagmdpath) )
        self.assertTrue( os.path.exists(t2bagfilepath) )
        self.assertTrue( os.path.exists(t2bagmdpath) )

        self.assertTrue(self.bag.remove_component(t1path, True))

        self.assertFalse( os.path.exists(t1bagfilepath) )
        self.assertFalse( os.path.exists(t1bagmdpath) )
        self.assertFalse( os.path.exists(os.path.dirname(t1bagmdpath)) )
        self.assertFalse( os.path.exists(os.path.dirname(t1bagfilepath)) )
        self.assertFalse( os.path.exists(os.path.dirname(os.path.dirname(t1bagmdpath))) )

        self.assertFalse( os.path.exists( golddir ) )
        self.assertTrue( os.path.exists(t2bagfilepath) )
        self.assertTrue( os.path.exists(t2bagmdpath) )

    def test_write_data_manifest(self):
        manfile = os.path.join(self.bag.bagdir, "manifest-sha256.txt")
        datafiles = [ "trial1.json", "trial2.json", 
                      os.path.join("trial3", "trial3a.json") ]
        for df in datafiles:
            self.bag.add_data_file(df, os.path.join(datadir, df))

        self.bag.write_data_manifest(False)
        self.assertTrue(os.path.exists(manfile))
        c = 0
        fc = {}
        with open(manfile) as fd:
            for line in fd:
                c += 1
                parts = line.strip().split(' ', 1)
                self.assertEqual(len(parts), 2,
                                 "Bad manifest file syntax, line %d: %s" %
                                 (c, line.rstrip()))
                self.assertTrue(parts[1].startswith('data/'),
                                "Incorrect path name: "+parts[1])
                self.assertIn(parts[1][5:], datafiles)
                dfp = os.path.join(self.bag.bagdir, parts[1])
                self.assertTrue(os.path.exists(dfp),
                                "Datafile not found: "+parts[1])
                self.assertEqual(parts[0], bldr.checksum_of(dfp))
        self.assertEqual(c, len(datafiles))

        self.bag.write_data_manifest(True)
        self.assertTrue(os.path.exists(manfile))
        c = 0
        fc = {}
        with open(manfile) as fd:
            for line in fd:
                c += 1
                parts = line.strip().split(' ', 1)
                self.assertEqual(len(parts), 2,
                                 "Bad manifest file syntax, line %d: %s" %
                                 (c, line.rstrip()))
                self.assertTrue(parts[1].startswith('data/'),
                                "Incorrect path name: "+parts[1])
                self.assertIn(parts[1][5:], datafiles)
                dfp = os.path.join(self.bag.bagdir, parts[1])
                self.assertTrue(os.path.exists(dfp),
                                "Datafile not found: "+parts[1])
                self.assertEqual(parts[0], bldr.checksum_of(dfp))
        self.assertEqual(c, len(datafiles))

    def test_trim_metadata_folders(self):
        manfile = os.path.join(self.bag.bagdir, "manifest-sha256.txt")
        datafiles = [ "trial1.json", "trial2.json", 
                      os.path.join("trial3", "trial3a.json") ]
        for df in datafiles:
            self.bag.add_data_file(df, os.path.join(datadir, df))
        metadir = os.path.join(self.bag.bagdir,"metadata")
        t3dir = os.path.join(metadir,"trial3")

        empties = [ os.path.join(t3dir,"cal","volt"),
                    os.path.join(t3dir,"cal","temp"),
                    os.path.join(metadir,"trial1.json","special") ]
        for d in empties:
            os.makedirs(d)

        for d in empties:
            self.assertTrue(os.path.isdir(d))

        self.bag.trim_metadata_folders()

        for d in empties:
            self.assertTrue(not os.path.exists(d))
        self.assertTrue(not os.path.exists(os.path.join(t3dir,"cal")))
        
    def test_trim_data_folders(self):
        manfile = os.path.join(self.bag.bagdir, "manifest-sha256.txt")
        datafiles = [ "trial1.json", "trial2.json", 
                      os.path.join("trial3", "trial3a.json") ]
        bdatadir = os.path.join(self.bag.bagdir,"data")
        metadir = os.path.join(self.bag.bagdir,"metadata")
        t3dir = os.path.join(bdatadir,"trial3")
        for df in datafiles:
            self.bag.add_data_file(df, os.path.join(datadir, df))

        # create some empty data directories
        empties = [ os.path.join("trial3","cal","volt"),
                    os.path.join("trial3","cal","temp") ]
        for d in empties:
            os.makedirs(os.path.join(bdatadir, d))
        os.makedirs(os.path.join(metadir,"cal","volt"))
        
        # remove a data file so we are left with just its metadata
        t2mdir = os.path.join(metadir, "trial2.json")
        os.remove(os.path.join(bdatadir, "trial2.json"))
        os.remove(os.path.join(bdatadir, "trial3", "trial3a.json"))

        for d in empties:
            self.assertTrue(os.path.isdir(os.path.join(bdatadir, d)))
        for df in datafiles:
            self.assertTrue(os.path.isdir(os.path.join(metadir,df)))

        self.bag.trim_data_folders(False)

        for d in empties:
            self.assertTrue(not os.path.exists(os.path.join(bdatadir, d)))
            self.assertTrue(not os.path.exists(os.path.join(metadir, d)))
        self.assertTrue(not os.path.exists(os.path.join(t3dir,"cal")))

        for df in datafiles:
            self.assertTrue(os.path.isdir(os.path.join(metadir,df)))
        self.assertTrue(os.path.isdir(os.path.join(metadir,"trial2.json")))
        self.assertTrue(os.path.exists(os.path.join(metadir,
                                                    "trial3","trial3a.json")))

        # try again with rmmeta=True
        for d in empties:
            d = os.path.join(bdatadir, d)
            if not os.path.exists(d):
                os.makedirs(d)

        self.bag.trim_data_folders(True)
        
        for d in empties:
            self.assertTrue(not os.path.exists(os.path.join(bdatadir, d)))
            self.assertTrue(not os.path.exists(os.path.join(metadir, d)))
        self.assertTrue(not os.path.exists(os.path.join(t3dir,"cal")))

        self.assertTrue(os.path.isdir(os.path.join(metadir,"trial1.json")))
        self.assertTrue(os.path.isdir(os.path.join(metadir,"trial2.json")))
        self.assertTrue(not os.path.exists(os.path.join(bdatadir, "trial3")))
        self.assertTrue(not os.path.exists(os.path.join(metadir, "trial3")))

        
    def test_ensure_comp_metadata(self):
        manfile = os.path.join(self.bag.bagdir, "manifest-sha256.txt")
        datafiles = [ "trial1.json", "trial2.json" ]
        nomd_datafile = os.path.join("trial3", "trial3a.json") 
        bdatadir = os.path.join(self.bag.bagdir,"data")
        metadir = os.path.join(self.bag.bagdir,"metadata")
        t3dir = os.path.join(bdatadir,"trial3")
        for df in datafiles:
            self.bag.add_data_file(df, os.path.join(datadir, df))
        self.bag.add_data_file(nomd_datafile,
                               os.path.join(datadir, nomd_datafile),
                               initmd=False)

        for df in datafiles + [nomd_datafile]:
            self.assertTrue( os.path.isfile(os.path.join(bdatadir, df)) )
        for df in datafiles:
            self.assertTrue( os.path.isfile(os.path.join(metadir, df,
                                                         "nerdm.json")) )
        self.assertFalse( os.path.exists(os.path.join(metadir, nomd_datafile,
                                                      "nerdm.json")) )

        self.bag.ensure_comp_metadata(False)

        for df in datafiles:
            self.assertTrue( os.path.isfile(os.path.join(metadir, df,
                                                         "nerdm.json")) )
        mdfile = os.path.join(metadir, nomd_datafile, "nerdm.json")
        self.assertTrue( os.path.isfile(mdfile) )

        data = read_nerd(mdfile)
        for prop in "@id @type filepath".split():
            self.assertIn(prop, data)
        for prop in "mediaType checksum size".split():
            self.assertNotIn(prop, data)

        # now try it with examine=True
        rmtree(os.path.join(metadir, nomd_datafile))
        for df in datafiles + [nomd_datafile]:
            self.assertTrue( os.path.isfile(os.path.join(bdatadir, df)) )
        for df in datafiles:
            self.assertTrue( os.path.isfile(os.path.join(metadir, df,
                                                         "nerdm.json")) )
        self.assertFalse( os.path.exists(os.path.join(metadir, nomd_datafile)) )

        self.bag.ensure_comp_metadata(True)

        for df in datafiles:
            self.assertTrue( os.path.isfile(os.path.join(metadir, df,
                                                         "nerdm.json")) )
        mdfile = os.path.join(metadir, nomd_datafile, "nerdm.json")
        self.assertTrue( os.path.isfile(mdfile) )

        data = read_nerd(mdfile)
        for prop in "@id @type filepath mediaType checksum size".split():
            self.assertIn(prop, data)

    def test_write_mbag_files(self):
        manfile = os.path.join(self.bag.bagdir, "manifest-sha256.txt")
        datafiles = [ "trial1.json", "trial2.json", 
                      os.path.join("trial3", "trial3a.json") ]
        for df in datafiles:
            self.bag.add_data_file(df, os.path.join(datadir, df))

        mbtag = os.path.join(self.bag.bagdir,"multibag", "member-bags.tsv")
        fltag = os.path.join(self.bag.bagdir,"multibag", "file-lookup.tsv")
                             
        self.assertTrue(not os.path.exists(mbtag))
        self.assertTrue(not os.path.exists(fltag))

        # pdb.set_trace()
        self.bag.write_mbag_files()

        self.assertTrue(os.path.exists(mbtag))
        self.assertTrue(os.path.exists(fltag))

        with open(mbtag) as fd:
            lines = fd.readlines()
        self.assertEqual(lines, [self.bag.bagname+'\n'])

        members = [os.path.join("data", d) for d in datafiles] + \
                  ["metadata/pod.json", "metadata/nerdm.json"] + \
                  [os.path.join("metadata", d, "nerdm.json") for d in datafiles]
        
        # FIX: component order is significant!
        # with open(fltag) as fd:
        #    i = 0;
        #    for line in fd:
        #        self.assertEqual(line.strip(), members[i]+' '+self.bag.bagname)
        #        i += 1
        #
        with open(fltag) as fd:
            lines = set([line.strip() for line in fd])
        for member in members:
            self.assertIn(member+'\t'+self.bag.bagname, lines)

    def test_write_bagit_ver(self):
        self.bag.cfg['bagit_version'] = "0.98"
        self.bag.write_bagit_ver()
        data = OrderedDict()
        delim = re.compile(":\s*")
        with open(os.path.join(self.bag.bagdir, "bagit.txt")) as fd:
            for line in fd:
                parts = delim.split(line.strip(), 1)
                data[parts[0]] = parts[1]
        self.assertEqual(data.keys(), ["BagIt-Version",
                                       "Tag-File-Character-Encoding"])
        self.assertEqual(data.values(), ["0.98", "UTF-8"])

    def test_write_baginfo_data(self):
        data = self.bag.cfg['init_bag_info']
        infofile = os.path.join(self.bag.bagdir,"bag-info.txt")
        self.assertFalse(os.path.exists(infofile))

        self.bag.write_baginfo_data(data, overwrite=True)

        self.assertTrue(os.path.exists(infofile))
        with open(infofile) as fd:
            lines = fd.readlines()
        self.assertIn("Source-Organization: "+
                      "National Institute of Standards and Technology\n",
                      lines)
        self.assertIn("Contact-Email: datasupport@nist.gov\n", lines)
        self.assertIn("Multibag-Version: 0.3\n", lines)
        self.assertEqual(len([l for l in lines
                                if "Organization-Address: " in l]), 2)

        data = OrderedDict([
            ("Goober-Name", "Gurn Cranston"),
            ("Foo", "Bar")
        ])
        self.bag.write_baginfo_data(data, overwrite=True)

        self.assertTrue(os.path.exists(infofile))
        with open(infofile) as fd:
            lines = fd.readlines()
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0], "Goober-Name: Gurn Cranston\n")
        self.assertEqual(lines[1], "Foo: Bar\n")

        data = self.bag.cfg['init_bag_info']
        data['Foo'] = "Bang"
        self.bag.write_baginfo_data(data, overwrite=False)

        with open(infofile) as fd:
            lines = fd.readlines()
        self.assertIn("Goober-Name: Gurn Cranston\n", lines)
        self.assertIn("Foo: Bar\n", lines)
        self.assertEqual(lines[0], "Goober-Name: Gurn Cranston\n")
        self.assertEqual(lines[1], "Foo: Bar\n")
        self.assertIn("Source-Organization: "+
                      "National Institute of Standards and Technology\n",
                      lines)
        self.assertIn("Contact-Email: datasupport@nist.gov\n", lines)
        self.assertIn("Multibag-Version: 0.3\n", lines)
        self.assertEqual(len([l for l in lines
                                if "Organization-Address: " in l]), 2)
        self.assertEqual(len([l for l in lines
                                if "Foo: " in l]), 2)

    def test_ensure_baginfo(self):
        path = os.path.join("trial1","gold","trial1.json")
        datafile = os.path.join(datadir,"trial1.json")
        datafilesz = os.stat(datafile).st_size
        podfile = os.path.join(datadir, "_pod.json")

        self.bag.add_data_file(path, datafile)
        path = os.path.join("trial1","trial2.json")
        self.bag.add_data_file(path, datafile)
        with open(podfile) as fd:
            pod = json.load(fd)
        self.bag.add_ds_pod(pod, convert=True)

        self.bag.ensure_baginfo()

        infofile = os.path.join(self.bag.bagdir, "bag-info.txt")
        self.assertTrue(os.path.exists(infofile))
        with open(infofile) as fd:
            lines = fd.readlines()

        self.assertIn("Source-Organization: "+
                      "National Institute of Standards and Technology\n",
                      lines)
        self.assertIn("Contact-Email: datasupport@nist.gov\n", lines)
        self.assertIn("Multibag-Version: 0.3\n", lines)
        self.assertEqual(len([l for l in lines
                                if "Organization-Address: " in l]), 2)
        self.assertIn("Internal-Sender-Identifier: "+self.bag.bagname+'\n',
                      lines)
        self.assertEqual(len([l for l in lines
                                if "External-Identifier: " in l]), 2)
        wrapping = [l for l in lines if ':' not in l]
        self.assertEqual(len(wrapping), 1)
        self.assertEqual(len([l for l in wrapping if l.startswith(' ')]), 1)

        oxum = [l for l in lines if "Payload-Oxum: " in l]
        self.assertEqual(len(oxum), 1)
        oxum = [int(n) for n in oxum[0].split(': ')[1].split('.')]
        self.assertEqual(oxum[1], 2)
        self.assertEqual(oxum[0], 2*datafilesz)
        bagsz = [l for l in lines if "Bag-Size: " in l]
        self.assertEqual(len(bagsz), 1)
        bagsz = bagsz[0]
        self.assertIn("kB", bagsz)

    def test_format_bytes(self):
        self.assertEqual(self.bag._format_bytes(108), "108 B")
        self.assertEqual(self.bag._format_bytes(34569), "34.57 kB")
        self.assertEqual(self.bag._format_bytes(9834569), "9.835 MB")
        self.assertEqual(self.bag._format_bytes(19834569), "19.83 MB")
        self.assertEqual(self.bag._format_bytes(14419834569), "14.42 GB")

    def test_write_about(self):
        self.bag.ensure_bagdir()
        with self.assertRaises(bldr.BagProfileError):
            self.bag.write_about_file()
        
        with open(os.path.join(datadir, "_nerdm.json")) as fd:
            mdata = json.load(fd)
        self.bag.add_res_nerd(mdata)
        with self.assertRaises(bldr.BagProfileError):
            self.bag.write_about_file()
        
        podfile = os.path.join(datadir, "_pod.json")
        with open(podfile) as fd:
            poddata = json.load(fd)
        self.bag.add_ds_pod(poddata, convert=False)

        aboutfile = os.path.join(self.bag.bagdir,"about.txt")
        self.assertTrue( not os.path.exists(aboutfile) )
        self.bag.write_about_file()
        self.assertTrue( os.path.exists(aboutfile) )

        with open(aboutfile) as fd:
            lines = fd.readlines()

        # pdb.set_trace()
        self.assertIn("NIST Public Data", lines[0])
        self.assertIn("OptSortSph:", lines[2])
        self.assertIn("Zachary Levine [1] and John J. Curry [1]", lines[4])
        self.assertIn("[1] National ", lines[5])
        self.assertIn("Identifier: doi:10.18434/", lines[6])
        self.assertIn("(ark:/88434/", lines[6])
        self.assertIn("Contact: Zachary ", lines[8])
        self.assertIn(" (zachary.levine@nist.gov)", lines[8])
        self.assertIn("         100 Bureau ", lines[9])
        self.assertIn("         Mail Stop", lines[10])
        self.assertIn("         Gaithersburg, ", lines[11])
        self.assertIn("         Phone: 1-301-975-", lines[12])
        self.assertIn("Software to", lines[14])
        self.assertIn("More information:", lines[17])
        self.assertIn("https://doi.org/10.18434/", lines[18])
            
    def test_ensure_baginfo(self):
        # prep the test bag
        self.bag.ensure_bagdir()
        with self.assertRaises(bldr.BagProfileError):
            self.bag.write_about_file()
        
        with open(os.path.join(datadir, "_nerdm.json")) as fd:
            mdata = json.load(fd)
        # see if we deal with blank paragraphs
        mdata['description'].extend(["  ", "(blank paragraph above)"])
        self.bag.add_res_nerd(mdata)
        with self.assertRaises(bldr.BagProfileError):
            self.bag.write_about_file()
        
        podfile = os.path.join(datadir, "_pod.json")
        with open(podfile) as fd:
            poddata = json.load(fd)
        self.bag.add_ds_pod(poddata, convert=False)

        # create the bag-info.txt file
        self.bag.ensure_baginfo(True)

        baginfof = os.path.join(self.bag.bagdir,"bag-info.txt")
        self.assertTrue(os.path.exists(baginfof))

        # check the bag-info contents
        # pdb.set_trace()
        bidata = {}
        fmtre = re.compile("^[\w\-]+\s*:\s*(\S.*$)")
        cntre = re.compile("^\s+")
        spre = re.compile("\s+")
        i = 0
        param = None
        with open(baginfof) as fd:
            for line in fd:
                i += 1
                if cntre.match(line):
                    if not param:
                        self.fail("bag-info.txt format error at line "+str(i)+
                                  ": expected param name on first line")
                    else:
                        bidata[param][-1] += ' ' + line.strip()
                    continue

                param = spre.split(line, 1)[0].rstrip(':')
                if param not in bidata:
                    bidata[param] = []
                m = fmtre.search(line)
                if m:
                    bidata[param].append(m.group(1))
                else:
                    self.fail("bag-info.txt format error at line "+str(i))

        self.assertIn("External-Description", bidata)
        self.assertIn("Bagging-Date", bidata)
        self.assertIn("Bag-Group-Identifier", bidata)
        self.assertIn("Internal-Sender-Identifier", bidata)
        self.assertIn("Bag-Size", bidata)
        self.assertIn("Payload-Oxum", bidata)
        self.assertIn("Source-Organization", bidata)
        self.assertIn("Organization-Address", bidata)
        self.assertIn("Contact-Name", bidata)
        self.assertIn("Contact-Email", bidata)
        self.assertIn("NIST-BagIt-Version", bidata)
        self.assertIn("Contact-Name", bidata)

        self.assertTrue(len([v for v in bidata['External-Identifier']
                               if v.startswith('ark:')]) > 0,
                        "Missing ARK ID in External-Identifier")
        # DOI only appears in bag-info if it is in the nerdm record
        self.assertTrue(len([v for v in bidata['External-Identifier']
                               if v.startswith('doi:')]) > 0,
                        "Missing DOI ID in External-Identifier")
        
        empty = []
        for param in bidata:
            if not bidata[param] or any([v.strip()=="" for v in bidata[param]]):
                empty.append(param)
        if len(empty) > 0:
            self.fail("Empty bag-info values found for "+str(empty))


if __name__ == '__main__':
    test.main()
