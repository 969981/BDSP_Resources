import importlib.util
import unittest
from pathlib import Path

spec=importlib.util.spec_from_file_location("unpack",Path(__file__).resolve().parents[1]/"scripts"/"bdsp_unpack.py")
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

class TestAudit(unittest.TestCase):
    def test_headers(self):
        for h,k in [(b"UnityFS\0","UnityFS"),(b"NSO0","NSO"),(b"\xaf\x1b\xb1\xfa","IL2CPPMetadata"),(b"BKHD","WwiseBank"),(b"RIFF","RIFF"),(b"other","Unknown")]:
            self.assertEqual(m.classify(Path("x"),h),k)
        self.assertEqual(m.classify(Path("x.assets"),b""),"UnitySerializedCandidate")
        self.assertEqual(m.classify(Path("x.resS"),b""),"UnityStream")
    def test_shards(self):
        for i in range(100):
            self.assertIn(m.shard_for(str(i),8),range(8))
            self.assertEqual(m.shard_for(str(i),8),m.shard_for(str(i),8))
    def test_safe(self):
        self.assertNotIn("/",m.safe("../x"))
        self.assertNotIn("\\",m.safe("a\\b"))
