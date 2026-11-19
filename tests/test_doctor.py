import http.server
import shutil
import ssl
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path

from hub import doctor
from hub.server import load_bots


class DoctorTests(unittest.TestCase):
    def test_status_codes_are_explained_in_danish(self):
        self.assertFalse(doctor.status_verdict(451)[0])
        self.assertIn("spærret", doctor.status_verdict(451)[1])
        self.assertFalse(doctor.status_verdict(403)[0])
        for ok in (200, 301, 404, 405, 429):
            self.assertTrue(doctor.status_verdict(ok)[0], ok)

    def test_a_missing_address_is_reported_as_a_dns_problem(self):
        ok, msg = doctor.check("findes-ikke.invalid")
        self.assertFalse(ok)
        self.assertIn("DNS", msg)

    def test_every_active_bot_lists_the_hosts_it_needs(self):
        for b in load_bots():
            self.assertTrue(b.get("hosts"), b["key"])
            for h in b["hosts"]:
                self.assertRegex(h, r"^[a-z0-9.-]+$")

    @unittest.skipUnless(shutil.which("openssl"), "openssl mangler")
    def test_an_intercepting_proxy_certificate_is_recognised_and_named(self):
        """Samme situation som 'self-signed certificate in certificate chain': et certifikat, ingen stoler på."""
        with tempfile.TemporaryDirectory() as d:
            key, crt = Path(d) / "k.pem", Path(d) / "c.pem"
            subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(key), "-out", str(crt), "-days", "1",
                            "-subj", "/O=Skolens Filter/CN=localhost", "-addext", "subjectAltName=DNS:localhost"],
                           check=True, capture_output=True)
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.load_cert_chain(str(crt), str(key))

            class H(http.server.BaseHTTPRequestHandler):
                def do_GET(self):
                    self.send_response(200); self.end_headers()
                def log_message(self, *a):
                    pass
            srv = http.server.HTTPServer(("127.0.0.1", 0), H)
            srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            try:
                ok, msg = doctor.check("localhost", srv.server_address[1])
            finally:
                srv.shutdown()
        self.assertFalse(ok)
        self.assertIn("certifikatet afvises", msg)
        self.assertIn("Skolens Filter", msg)                     # udstederen afsløres, så man kan se hvem der overvåger


if __name__ == "__main__":
    unittest.main()
