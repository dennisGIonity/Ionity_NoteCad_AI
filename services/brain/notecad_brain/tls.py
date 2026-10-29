# Ionity Business Mind Map (IBMM) - Brain | Ionity Global (Pty) Ltd | AEDI
# Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
# Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
"""TLS for the farm network (POPIA review, fix 4). On the LAN the brain speaks HTTPS with its own certificate, made
once per data folder and kept for ten years. No certificate authority vouches for it: phones and other brains trust
exactly this certificate, by its SHA-256 fingerprint, which the pairing QR and every invite link carry (pinning).
A new certificate therefore means pairing again, so it is never replaced on its own."""
from __future__ import annotations

import datetime as dt
import hashlib
import ipaddress
import socket
import ssl
from pathlib import Path


def ensure_cert(folder: str | Path) -> tuple[Path, Path]:
    """(cert.pem, key.pem) in folder, made the first time: an EC P-256 key and a self-signed certificate naming this
    PC and its addresses now (clients pin the certificate, so a later address change does not matter)."""
    folder = Path(folder)
    cert, key = folder / "cert.pem", folder / "key.pem"
    if cert.is_file() and key.is_file():
        return cert, key
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    folder.mkdir(parents=True, exist_ok=True)
    k = ec.generate_private_key(ec.SECP256R1())
    host = socket.gethostname()
    names: list[x509.GeneralName] = [x509.DNSName(host), x509.DNSName("localhost"),
                                     x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
    for ip in local_ips():
        names.append(x509.IPAddress(ipaddress.ip_address(ip)))
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"IBMM brain on {host}"),
                         x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Ionity Business Mind Map (IBMM)")])
    now = dt.datetime.now(dt.timezone.utc)
    c = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(k.public_key())
         .serial_number(x509.random_serial_number()).not_valid_before(now - dt.timedelta(days=1))
         .not_valid_after(now + dt.timedelta(days=3650))
         .add_extension(x509.SubjectAlternativeName(names), critical=False)
         .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
         .sign(k, hashes.SHA256()))
    key.write_bytes(k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                    serialization.NoEncryption()))
    cert.write_bytes(c.public_bytes(serialization.Encoding.PEM))
    return cert, key


def fingerprint(cert: str | Path) -> str:
    """SHA-256 of the certificate (DER), lowercase hex: what clients pin."""
    der = ssl.PEM_cert_to_DER_cert(Path(cert).read_text(encoding="ascii"))
    return hashlib.sha256(der).hexdigest()


def pinned_context(cert: str | Path) -> ssl.SSLContext:
    """A client context that trusts only this certificate (another brain syncing with a hub on the LAN). The name is
    not checked: the pin is the check, and LAN addresses change."""
    ctx = ssl.create_default_context(cadata=Path(cert).read_text(encoding="ascii"))
    ctx.check_hostname = False
    return ctx


def local_ips() -> list[str]:
    ips: list[str] = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("192.0.2.1", 9))  # picks the LAN interface; sends nothing
        ips.append(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        for *_, addr in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = str(addr[0])
            if ip not in ips and not ip.startswith("127."):
                ips.append(ip)
    except OSError:
        pass
    return ips
