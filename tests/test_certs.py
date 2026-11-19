import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from hub import certs, doctor

FAKE_PEM = ("-----BEGIN CERTIFICATE-----\n" + "A" * 64 + "\n-----END CERTIFICATE-----\n") * 400      # > MIN_BYTES


class CertsTests(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, {}, clear=False)
        self.env.start()
        os.environ.pop("SSL_CERT_FILE", None)
        self.addCleanup(self.env.stop)

    def no_store(self):
        return mock.patch("hub.certs.ssl.get_default_verify_paths", return_value=SimpleNamespace(cafile="/findes/ikke.pem", capath=None))

    def fake_run(self, rc=0, out=FAKE_PEM):
        return lambda cmd, **kw: SimpleNamespace(returncode=rc, stdout=out)

    def test_nothing_is_done_when_python_already_has_certificates(self):
        with tempfile.TemporaryDirectory() as d:
            ca = Path(d) / "ca.pem"
            ca.write_text("x")
            with mock.patch("hub.certs.ssl.get_default_verify_paths", return_value=SimpleNamespace(cafile=str(ca), capath=None)):
                self.assertFalse(certs.needs_fix())
                self.assertIsNone(certs.setup(Path(d), say=lambda *_: None))
        self.assertNotIn("SSL_CERT_FILE", os.environ)

    def test_an_explicit_ssl_cert_file_is_respected(self):
        with tempfile.TemporaryDirectory() as d, self.no_store():
            f = Path(d) / "mit.pem"
            f.write_text("x")
            os.environ["SSL_CERT_FILE"] = str(f)
            self.assertFalse(certs.needs_fix())

    def test_missing_store_builds_a_file_from_the_keychain_and_sets_the_env(self):
        msgs = []
        with tempfile.TemporaryDirectory() as d, self.no_store():
            self.assertTrue(certs.needs_fix())
            path = certs.setup(Path(d), say=msgs.append, run=self.fake_run())
            self.assertEqual(path, str(Path(d) / "cacert.pem"))
            self.assertEqual(os.environ["SSL_CERT_FILE"], path)
            self.assertGreater(Path(path).stat().st_size, certs.MIN_BYTES)
        self.assertTrue(any("rod-certifikater mangler" in m for m in msgs))

    def test_a_fresh_cached_file_is_reused_without_asking_the_keychain(self):
        calls = []
        def run(cmd, **kw):
            calls.append(cmd)
            return SimpleNamespace(returncode=0, stdout=FAKE_PEM)
        with tempfile.TemporaryDirectory() as d, self.no_store():
            certs.setup(Path(d), say=lambda *_: None, run=run)
            n = len(calls)
            os.environ.pop("SSL_CERT_FILE")
            certs.setup(Path(d), say=lambda *_: None, run=run)
            self.assertEqual(len(calls), n)

    def test_an_unreadable_keychain_is_reported_not_crashed_on(self):
        msgs = []
        with tempfile.TemporaryDirectory() as d, self.no_store():
            self.assertIsNone(certs.setup(Path(d), say=msgs.append, run=self.fake_run(rc=1, out="")))
        self.assertNotIn("SSL_CERT_FILE", os.environ)
        self.assertTrue(any("Install Certificates.command" in m for m in msgs))

    def test_the_doctor_blames_python_not_the_network_for_trusted_issuers(self):
        import ssl
        err = ssl.SSLCertVerificationError(1, "unable to get local issuer certificate")
        with mock.patch("hub.doctor.socket.gethostbyname", return_value="1.2.3.4"), \
             mock.patch("hub.doctor.http.client.HTTPSConnection", side_effect=err), \
             mock.patch("hub.doctor.issuer_of", return_value="DigiCert Inc"):
            ok, msg = doctor.check("query1.finance.yahoo.com")
        self.assertFalse(ok)
        self.assertIn("Pythons rod-certifikater mangler", msg)
        self.assertIn("ikke dit netværk", msg)
        with mock.patch("hub.doctor.socket.gethostbyname", return_value="1.2.3.4"), \
             mock.patch("hub.doctor.http.client.HTTPSConnection", side_effect=err), \
             mock.patch("hub.doctor.issuer_of", return_value="Skolens Filter"):
            ok, msg = doctor.check("x")
        self.assertIn("overvåger", msg)                                    # ukendt udsteder: stadig mistanke om overvågning


if __name__ == "__main__":
    unittest.main()
