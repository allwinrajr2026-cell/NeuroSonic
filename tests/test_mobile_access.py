"""Phone (LAN) access regressions, 2026-11-02 iPhone "stays loading" report.

Root causes found and tested here:
  1. TLS handshake ran in accept() on the main thread -> one idle/slow client froze the whole HTTPS server.
  2. Certificate lacked subjectAltName/serverAuth (CN-only, CA:TRUE): rejected by iOS 13+.
  3. (environment) Windows Firewall on a 'Public' network with no inbound rule -> phone packets dropped;
     the start-up check must detect it and print the exact fix (tested with mocked system calls).
Plus: correct MIME types for every module the page imports, LAN binding, the CA setup page, and no
JavaScript syntax that older iOS WebKit cannot parse.
"""
import http.client
import re
import shutil
import socket
import ssl
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from tests._common import ROOT
from neurosonic import netcheck
from neurosonic.server import make_handler, make_server, make_setup_server, serve_in_thread
from neurosonic.tls import ensure_certificates, lan_ips, server_ssl_context

HAVE_OPENSSL = bool(shutil.which("openssl") or Path(r"C:\Program Files\Git\usr\bin\openssl.exe").exists())


def openssl_text(cert):
    exe = shutil.which("openssl") or r"C:\Program Files\Git\usr\bin\openssl.exe"
    return subprocess.run([exe, "x509", "-in", str(cert), "-noout", "-text"], capture_output=True, text=True,
                          check=True).stdout


class _NoService:
    """The static-file and setup tests never touch the detection service."""


@unittest.skipUnless(HAVE_OPENSSL, "openssl not available")
class TestHttpsServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.td = Path(tempfile.mkdtemp(prefix="ns_tls_"))
        cls.tls = ensure_certificates(cls.td)
        cls.httpd = make_server(_NoService(), None, "127.0.0.1", 0, ssl_context=server_ssl_context(cls.tls))
        cls.httpd.handshake_timeout = 2.0
        serve_in_thread(cls.httpd)
        cls.port = cls.httpd.server_address[1]
        # client context that VERIFIES the certificate chain and the host name (what a phone does once the CA
        # is installed) - no verification is disabled here
        cls.client = ssl.create_default_context(cafile=str(cls.tls["ca_cert"]))

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        shutil.rmtree(cls.td, ignore_errors=True)

    def get(self, path="/", host="127.0.0.1", timeout=5):
        c = http.client.HTTPSConnection(host, self.port, timeout=timeout, context=self.client)
        try:
            c.request("GET", path)
            r = c.getresponse()
            return r.status, r.getheader("Content-Type"), r.read()
        finally:
            c.close()

    def test_idle_connection_does_not_block_other_clients(self):
        # Reproduced bug: with the listening socket TLS-wrapped, this request hung until the idle socket closed.
        idle = [socket.create_connection(("127.0.0.1", self.port)) for _ in range(3)]
        try:
            time.sleep(0.3)
            t = time.time()
            status, _, body = self.get("/")
            self.assertEqual(status, 200)
            self.assertIn(b"NeuroSonic", body)
            self.assertLess(time.time() - t, 2.0)
        finally:
            for s in idle:
                s.close()

    def test_garbage_and_plain_http_do_not_break_server(self):
        for payload in (b"GET / HTTP/1.1\r\nHost: x\r\n\r\n", b"\x00\x01garbage"):
            s = socket.create_connection(("127.0.0.1", self.port))
            s.sendall(payload)
            s.close()
        self.assertEqual(self.get("/")[0], 200)

    def test_certificate_verifies_for_ip_and_localhost(self):
        self.assertEqual(self.get("/", host="127.0.0.1")[0], 200)   # IP SAN
        self.assertEqual(self.get("/", host="localhost")[0], 200)   # DNS SAN

    def test_mime_types_of_every_page_asset(self):
        status, ctype, html = self.get("/")
        self.assertEqual((status, ctype), (200, "text/html; charset=utf-8"))
        self.assertEqual(self.get("/style.css")[1], "text/css; charset=utf-8")
        # follow the module graph exactly as the browser does
        todo, seen = ["/js/app.js"], set()
        while todo:
            p = todo.pop()
            if p in seen:
                continue
            seen.add(p)
            st, ct, js = self.get(p)
            self.assertEqual(st, 200, p)
            self.assertEqual(ct, "text/javascript; charset=utf-8", p)
            for rel in re.findall(rb'from\s+"\./([\w.]+)"', js):
                todo.append("/js/" + rel.decode())
        self.assertEqual(seen, {"/js/app.js", "/js/speech.js", "/js/nav.js", "/js/eventsim.js", "/js/mapview.js", "/js/recorder.js"})
        for src in re.findall(rb'(?:src|href)="(/[^"]+)"', html):
            self.assertEqual(self.get(src.decode())[0], 200, src)


@unittest.skipUnless(HAVE_OPENSSL, "openssl not available")
class TestCertificates(unittest.TestCase):
    def setUp(self):
        self.td = Path(tempfile.mkdtemp(prefix="ns_cert_"))

    def tearDown(self):
        shutil.rmtree(self.td, ignore_errors=True)

    def test_ios_requirements(self):
        info = ensure_certificates(self.td)
        txt = openssl_text(info["server_cert"])
        self.assertIn("X509v3 Subject Alternative Name", txt)
        self.assertIn("IP Address:127.0.0.1", txt)
        self.assertIn("DNS:localhost", txt)
        for ip in lan_ips():
            self.assertIn(f"IP Address:{ip}", txt)
        self.assertIn("TLS Web Server Authentication", txt)      # extendedKeyUsage = serverAuth
        self.assertIn("CA:FALSE", txt)
        self.assertIn("Issuer: CN=NeuroSonic Local CA", txt)
        days = ssl.cert_time_to_seconds(re.search(r"Not After : (.+)", txt).group(1).strip()) - \
            ssl.cert_time_to_seconds(re.search(r"Not Before: (.+)", txt).group(1).strip())
        self.assertLessEqual(days / 86400, 825)                  # Apple: max 825 days
        self.assertIn("CA:TRUE", openssl_text(info["ca_cert"]))

    def test_reused_and_regenerated_when_address_changes(self):
        a = ensure_certificates(self.td)
        mtime = a["server_cert"].stat().st_mtime_ns
        b = ensure_certificates(self.td)
        self.assertEqual(b["server_cert"].stat().st_mtime_ns, mtime)          # unchanged -> reused
        c = ensure_certificates(self.td, extra_ips=["10.9.8.7"])
        self.assertIn("IP Address:10.9.8.7", openssl_text(c["server_cert"]))  # new LAN address -> new cert
        self.assertEqual(c["ca_fingerprint"], a["ca_fingerprint"])           # CA kept (phone stays set up)


@unittest.skipUnless(HAVE_OPENSSL, "openssl not available")
class TestSetupPageAndLanBinding(unittest.TestCase):
    def test_setup_server_serves_only_page_and_ca(self):
        td = Path(tempfile.mkdtemp(prefix="ns_setup_"))
        try:
            info = ensure_certificates(td)
            srv = make_setup_server(info["ca_cert"], "https://192.0.2.10:8765", info["ca_fingerprint"], "127.0.0.1", 0)
            serve_in_thread(srv)
            port = srv.server_address[1]

            def get(p):
                c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                c.request("GET", p)
                r = c.getresponse()
                out = (r.status, r.getheader("Content-Type"), r.read())
                c.close()
                return out
            st, ct, page = get("/")
            self.assertEqual(st, 200)
            self.assertIn(info["ca_fingerprint"].encode(), page)
            self.assertIn(b"https://192.0.2.10:8765", page)
            st, ct, crt = get("/neurosonic-ca.crt")
            self.assertEqual((st, ct), (200, "application/x-x509-ca-cert"))
            self.assertEqual(crt, info["ca_cert"].read_bytes())
            self.assertNotIn(b"PRIVATE KEY", crt)
            for p in ("/api/status", "/api/history", "/neurosonic-ca.key", "/../data/tls/neurosonic-ca.key"):
                self.assertEqual(get(p)[0], 404, p)
            srv.shutdown()
            srv.server_close()
        finally:
            shutil.rmtree(td, ignore_errors=True)

    def test_binds_all_interfaces_and_answers_on_lan_address(self):
        ips = lan_ips()
        if not ips:
            self.skipTest("no LAN address")
        httpd = make_server(_NoService(), None, "0.0.0.0", 0)
        serve_in_thread(httpd)
        try:
            for ip in ips:   # from this laptop (does not go through the firewall; see netcheck for that)
                c = http.client.HTTPConnection(ip, httpd.server_address[1], timeout=5)
                c.request("GET", "/")
                self.assertEqual(c.getresponse().status, 200, ip)
                c.close()
        finally:
            httpd.shutdown()
            httpd.server_close()


class TestExclusivePort(unittest.TestCase):
    def test_second_instance_cannot_share_the_port(self):
        # Regression (2026-11-02): with SO_REUSEADDR on Windows a second app bound the same port silently and a
        # stale old instance answered requests. A second bind must now fail.
        first = make_server(_NoService(), None, "0.0.0.0", 0)
        try:
            port = first.server_address[1]
            with self.assertRaises(OSError):
                make_server(_NoService(), None, "0.0.0.0", port)
        finally:
            first.server_close()


class TestNetworkCheck(unittest.TestCase):
    def test_public_network_without_rule_is_reported_with_fix(self):
        def fake_ps(cmd, timeout=15):
            return 0, '{"InterfaceAlias":"WiFi","NetworkCategory":0}'
        no_rule = subprocess.CompletedProcess([], 1, "\nNo rules match the specified criteria.\n", "")
        with mock.patch.object(netcheck, "_ps", fake_ps), mock.patch.object(netcheck.sys, "platform", "win32"), \
                mock.patch.object(netcheck.subprocess, "run", return_value=no_rule):
            rep = netcheck.windows_report([8765, 8766])
        self.assertEqual(rep["profiles"], [{"interface": "WiFi", "category": "Public"}])
        self.assertFalse(rep["rule_present"])
        self.assertIn('Set-NetConnectionProfile -InterfaceAlias "WiFi" -NetworkCategory Private', rep["fix_commands"])
        self.assertIn('New-NetFirewallRule -DisplayName "NeuroSonic LAN" -Direction Inbound -Action Allow -Protocol TCP '
                      '-LocalPort 8765,8766 -RemoteAddress LocalSubnet -Profile Private', rep["fix_commands"])

    def test_private_network_with_rule_is_clean(self):
        ok_rule = subprocess.CompletedProcess([], 0, "Rule Name: NeuroSonic LAN\n", "")
        with mock.patch.object(netcheck, "_ps", lambda c, timeout=15: (0, '[{"InterfaceAlias":"WiFi","NetworkCategory":1}]')), \
                mock.patch.object(netcheck.sys, "platform", "win32"), \
                mock.patch.object(netcheck.subprocess, "run", return_value=ok_rule):
            rep = netcheck.windows_report([8765])
        self.assertEqual(rep["warnings"], [])
        self.assertEqual(rep["fix_commands"], [])


class TestOldWebKitSyntax(unittest.TestCase):
    def test_no_optional_chaining_or_nullish_operators(self):
        # iOS < 13.4 WebKit cannot parse these; a parse error would stop the whole module graph.
        for f in (ROOT / "web" / "js").glob("*.js"):
            code = "\n".join(line.split("//")[0] for line in f.read_text(encoding="utf-8").splitlines())
            self.assertNotRegex(code, r"\?\?|\?\.(?!\d)", f.name)


if __name__ == "__main__":
    unittest.main()
