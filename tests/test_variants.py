import json
import subprocess
import sys
import unittest

from hub.__main__ import ROOT, commands
from hub.server import load_bots


class VariantTests(unittest.TestCase):
    def test_new_bots_have_own_ports_files_and_costs(self):
        by = {b["key"]: b for b in load_bots()}
        for k in ("atlasglobal", "orionmid", "novaclassic"):
            self.assertIn(k, by)
        self.assertEqual(by["nova"]["repo"], by["novaclassic"]["repo"])
        self.assertNotEqual(by["orion"]["port"], by["orionmid"]["port"])
        self.assertEqual(by["orionmid"]["launch"]["overrides"]["config"]["STATE_FILE"], "state-mid.json")
        self.assertTrue(all("costs" in b for b in by.values()))

    def test_nova_classic_uses_its_own_config_file(self):
        cmd, _ = commands({b["key"]: b for b in load_bots()}["novaclassic"])[0]
        self.assertIn(str(ROOT / "variants" / "nova-classic.toml"), cmd)
        self.assertTrue((ROOT / "variants" / "nova-classic.toml").is_file())

    def test_override_prelude_adds_removes_and_replaces(self):
        import tempfile, textwrap, pathlib
        with tempfile.TemporaryDirectory() as d:
            pathlib.Path(d, "fakecfg.py").write_text("S = {'A'}\nL = [{'name': 'x'}, {'name': 'y'}]\nV = 1\n")
            b = {"port": 9, "launch": {"kind": "patch", "config": "fakecfg", "args": ["run"],
                                       "overrides": {"fakecfg": {"+S": ["B"], "-L": ["x"], "V": 2}}}}
            code = commands(b)[0][0][2].split("sys.argv")[0] + "print(sorted(c.S), [i['name'] for i in c.L], c.V, c.DASHBOARD_PORT)"
            out = subprocess.run([sys.executable, "-c", code], cwd=d, capture_output=True, text=True)
            self.assertEqual(out.stdout.strip(), "['A', 'B'] ['y'] 2 9", out.stderr)


if __name__ == "__main__":
    unittest.main()
