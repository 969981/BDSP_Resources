import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from bdsp_focus import parse_key
class FocusTest(unittest.TestCase):
    def test_key(self):
        self.assertEqual(parse_key("pm0493_16_02_01_dp"),(493,16,2,1,"dp"))
        self.assertEqual(parse_key("pm0000_00_00_00_l"),(0,0,0,0,"l"))
        with self.assertRaises(ValueError): parse_key("pm1_00_00_00_l")
