"""Local HTTPS certificates that phones accept (generated with the `openssl` command, no Python packages).

Why: the first version created one self-signed certificate with only a Common Name, marked CA:TRUE, and without
subjectAltName / extendedKeyUsage. Since iOS 13, Apple requires TLS server certificates to carry the host in
subjectAltName (the CN is ignored) and the serverAuth extended key usage, with a validity of at most 825 days;
connections to servers that violate this fail. Such a certificate can also never be trusted properly.

Now (like mkcert):
  data/tls/neurosonic-ca.crt / .key      local root CA "NeuroSonic Local CA" (installed once on the phone)
  data/tls/server.crt / server.key       server certificate signed by that CA:
        subjectAltName = IP:<LAN IPs>, IP:127.0.0.1, DNS:localhost, DNS:<hostname>, DNS:<hostname>.local
        extendedKeyUsage = serverAuth, keyUsage = digitalSignature, keyEncipherment, basicConstraints = CA:FALSE
        validity 397 days, SHA-256, RSA 2048
The server certificate is regenerated automatically when the LAN address changes or it is close to expiry.
The CA private key never leaves data/tls/. Browser security is not disabled anywhere.
"""
import datetime
import hashlib
import ipaddress
import json
import shutil
import socket
import ssl
import subprocess
from pathlib import Path

CA_NAME = "NeuroSonic Local CA"
SERVER_DAYS = 397
CA_DAYS = 825


class TLSSetupError(RuntimeError):
    pass


def lan_ips():
    """IPv4 addresses of this machine that a phone on the LAN could use (best effort, no packets sent)."""
    ips = set()
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))  # TEST-NET address; UDP connect only selects the outgoing interface
            ips.add(s.getsockname()[0])
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    good = []
    for ip in ips:
        a = ipaddress.ip_address(ip)
        if not (a.is_loopback or a.is_link_local or a.is_unspecified):
            good.append(ip)
    return sorted(good)


def _openssl():
    exe = shutil.which("openssl")
    if not exe:
        for cand in (r"C:\Program Files\Git\usr\bin\openssl.exe", r"C:\Program Files\Git\mingw64\bin\openssl.exe"):
            if Path(cand).exists():
                return cand
        raise TLSSetupError("HTTPS needs the 'openssl' command (included in Git for Windows); not found")
    return exe


def _run(args, cwd):
    r = subprocess.run([_openssl(), *args], cwd=cwd, capture_output=True, text=True)
    if r.returncode:
        raise TLSSetupError(f"openssl {' '.join(args[:2])} failed: {r.stderr.strip()[-500:]}")
    return r.stdout


def fingerprint_sha256(cert_path):
    der = ssl.PEM_cert_to_DER_cert(Path(cert_path).read_text())
    h = hashlib.sha256(der).hexdigest().upper()
    return " ".join(h[i:i + 2] for i in range(0, len(h), 2))


def _not_after(cert_path, cwd):
    out = _run(["x509", "-in", str(cert_path), "-noout", "-enddate"], cwd).strip()  # notAfter=Nov  2 05:33:39 2027 GMT
    return datetime.datetime.strptime(out.split("=", 1)[1], "%b %d %H:%M:%S %Y %Z")


def ensure_certificates(tls_dir, extra_ips=()):
    """Create/refresh the local CA and server certificate. Returns dict with paths, SANs and CA fingerprint."""
    tls_dir = Path(tls_dir)
    tls_dir.mkdir(parents=True, exist_ok=True)
    ca_crt, ca_key = tls_dir / "neurosonic-ca.crt", tls_dir / "neurosonic-ca.key"
    srv_crt, srv_key, meta_p = tls_dir / "server.crt", tls_dir / "server.key", tls_dir / "server.json"
    cwd = str(tls_dir)

    if not (ca_crt.exists() and ca_key.exists()):
        _run(["req", "-x509", "-newkey", "rsa:2048", "-nodes", "-sha256", "-days", str(CA_DAYS),
              "-keyout", ca_key.name, "-out", ca_crt.name, "-subj", f"/CN={CA_NAME}/O=NeuroSonic",
              "-addext", "basicConstraints=critical,CA:TRUE,pathlen:0",
              "-addext", "keyUsage=critical,keyCertSign,cRLSign",
              "-addext", "subjectKeyIdentifier=hash"], cwd)

    host = socket.gethostname()
    ips = sorted(set(lan_ips()) | set(extra_ips) | {"127.0.0.1"})
    dns = sorted({"localhost", host, f"{host}.local"})
    want = {"ips": ips, "dns": dns, "ca_fingerprint": fingerprint_sha256(ca_crt)}

    fresh = False
    if srv_crt.exists() and srv_key.exists() and meta_p.exists():
        try:
            have = json.loads(meta_p.read_text())
            fresh = (set(want["ips"]) <= set(have.get("ips", [])) and set(want["dns"]) <= set(have.get("dns", []))
                     and have.get("ca_fingerprint") == want["ca_fingerprint"]
                     and _not_after(srv_crt, cwd) - datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) > datetime.timedelta(days=14))
        except (ValueError, TLSSetupError):
            fresh = False
    if not fresh:
        san = ",".join([f"IP:{i}" for i in ips] + [f"DNS:{d}" for d in dns])
        ext = tls_dir / "server.ext"
        ext.write_text("basicConstraints=critical,CA:FALSE\n"
                       "keyUsage=critical,digitalSignature,keyEncipherment\n"
                       "extendedKeyUsage=serverAuth\n"
                       f"subjectAltName={san}\n"
                       "subjectKeyIdentifier=hash\nauthorityKeyIdentifier=keyid,issuer\n")
        _run(["req", "-new", "-newkey", "rsa:2048", "-nodes", "-keyout", srv_key.name, "-out", "server.csr",
              "-subj", "/CN=NeuroSonic local server/O=NeuroSonic"], cwd)
        _run(["x509", "-req", "-in", "server.csr", "-CA", ca_crt.name, "-CAkey", ca_key.name, "-CAcreateserial",
              "-days", str(SERVER_DAYS), "-sha256", "-extfile", ext.name, "-out", srv_crt.name], cwd)
        (tls_dir / "server.csr").unlink(missing_ok=True)
        meta_p.write_text(json.dumps(want, indent=1))
    return {"ca_cert": ca_crt, "server_cert": srv_crt, "server_key": srv_key, "ips": ips, "dns": dns,
            "ca_fingerprint": want["ca_fingerprint"]}


def server_ssl_context(info):
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(info["server_cert"], info["server_key"])
    return ctx
