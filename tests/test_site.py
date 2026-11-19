import json
import re
import unittest
from pathlib import Path

DOCS = Path(__file__).resolve().parent.parent / "docs"
STATIC = Path(__file__).resolve().parent.parent / "hub" / "static"


class SiteTests(unittest.TestCase):
    def test_every_local_link_and_image_on_the_pages_site_exists(self):
        pages = list(DOCS.rglob("*.html"))
        self.assertGreaterEqual(len(pages), 2)
        for page in pages:
            for ref in re.findall(r'(?:src|href)="([^"#?]+)', page.read_text(encoding="utf-8")):
                if re.match(r"^(https?:|mailto:|data:)", ref):
                    continue
                target = (page.parent / ref).resolve()
                self.assertTrue(target.exists() or (target / "index.html").exists(), f"{page.name}: {ref}")

    def test_manifests_point_at_real_icons(self):
        for manifest, base in ((DOCS / "manifest.webmanifest", DOCS), (STATIC / "manifest.webmanifest", None)):
            data = json.loads(manifest.read_text())
            self.assertEqual(data["display"], "standalone")
            for icon in data["icons"]:
                f = (base / icon["src"]) if base else (STATIC / Path(icon["src"]).name)
                self.assertTrue(f.is_file(), icon["src"])
                self.assertTrue(f.read_bytes().startswith(b"\x89PNG"))

    def test_the_shell_is_set_up_for_the_home_screen(self):
        shell = (Path(__file__).resolve().parent.parent / "hub" / "shell.html").read_text(encoding="utf-8")
        for needle in ('rel="manifest"', 'rel="apple-touch-icon"', "viewport-fit=cover", "apple-mobile-web-app-capable", 'name="theme-color"',
                       "safe-area-inset-bottom"):
            self.assertIn(needle, shell)

    def test_no_server_details_in_the_public_site(self):
        for f in list(DOCS.rglob("*.html")) + list(DOCS.rglob("*.css")) + [Path(__file__).resolve().parent.parent / "README.md"]:
            text = f.read_text(encoding="utf-8")
            self.assertNotRegex(text, r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b(?<!100\.64\.0\.1)(?<!127\.0\.0\.1)(?<!0\.0\.0\.0)", f.name)
            self.assertNotIn(".ssh", text, f.name)


if __name__ == "__main__":
    unittest.main()
