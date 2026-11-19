import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT                                         # forsiden ligger i roden, som hos Flower
PAGES = [ROOT / "index.html", ROOT / "download" / "index.html"]
STATIC = Path(__file__).resolve().parent.parent / "hub" / "static"


class SiteTests(unittest.TestCase):
    def test_every_local_link_and_image_on_the_pages_site_exists(self):
        for page in PAGES:
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

    def test_the_service_worker_only_touches_its_own_files_and_is_registered(self):
        sw = (ROOT / "sw.js").read_text()
        self.assertIn("url.origin !== location.origin", sw)                 # aldrig dashboardet eller andre domæner
        for shell in ("./", "download/", "assets/site.css", "manifest.webmanifest"):
            self.assertIn(shell, sw)
        for page in PAGES:
            self.assertIn("serviceWorker.register(", page.read_text(encoding="utf-8"))

    def test_the_global_overview_is_a_pinned_button_and_every_bot_page_names_its_bot(self):
        shell = (Path(__file__).resolve().parent.parent / "hub" / "shell.html").read_text(encoding="utf-8")
        self.assertIn('id="home"', shell)
        self.assertIn("Alle botter", shell)
        self.assertIn("function botHead()", shell)                          # ingen bot-side uden tydelig overskrift
        self.assertNotIn('mk(OV, "Overblik"', shell)                        # ligger ikke længere i rækken, der ruller væk
        self.assertIn("!(cur && cur.configured && cur.up)", shell)          # bundmenuen vises kun, når botten kan vises

    def test_the_shell_is_set_up_for_the_home_screen(self):
        shell = (Path(__file__).resolve().parent.parent / "hub" / "shell.html").read_text(encoding="utf-8")
        for needle in ('rel="manifest"', 'rel="apple-touch-icon"', "viewport-fit=cover", "apple-mobile-web-app-capable", 'name="theme-color"',
                       "safe-area-inset-bottom"):
            self.assertIn(needle, shell)

    def test_no_server_details_in_the_public_site(self):
        for f in PAGES + [ROOT / "assets" / "site.css", ROOT / "sw.js", ROOT / "README.md"]:
            text = f.read_text(encoding="utf-8")
            self.assertNotRegex(text, r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b(?<!100\.64\.0\.1)(?<!127\.0\.0\.1)(?<!0\.0\.0\.0)", f.name)
            self.assertNotIn(".ssh", text, f.name)


if __name__ == "__main__":
    unittest.main()
