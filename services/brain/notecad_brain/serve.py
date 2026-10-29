# Ionity Business Mind Map (IBMM) - Brain | Ionity Global (Pty) Ltd | AEDI
# Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
# Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
"""Runs the brain (tools/start_brain.ps1 calls this):

    python -m notecad_brain.serve --port 8788                      this PC only: http://127.0.0.1:8788
    python -m notecad_brain.serve --port 8788 --lan                ... and phones: https://<LAN address>:9788

Plain HTTP stays on loopback; the farm network gets HTTPS only, with the certificate of tls.py (POPIA review, fix 4).
The log goes to <logs>/api.log, a new file every Monday, four weeks kept, with tokens and tickets blanked (fix 3)."""
from __future__ import annotations

import argparse
import asyncio
import logging
import logging.handlers
import os
import re
from pathlib import Path

SECRET = re.compile(r"((?<=[?&])(?:token|ticket|t|c)=|%26t%3D|%3Ft%3D|%26c%3D)[^&\s\"']+|(Bearer\s+)[^\s\"']+", re.I)


def redact(text: str) -> str:
    """Blank anything that can stand for a person in a log line: tokens, tickets, invite codes, pairing links."""
    return SECRET.sub(lambda m: (m.group(1) or m.group(2)) + "***", text)


class Redact(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        clean = redact(msg)
        if clean != msg:
            record.msg, record.args = clean, None
        return True


def setup_logging(logs: str | Path, keep_weeks: int = 4) -> None:
    Path(logs).mkdir(parents=True, exist_ok=True)
    h = logging.handlers.TimedRotatingFileHandler(Path(logs) / "api.log", when="W0", backupCount=keep_weeks,
                                                  encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    h.addFilter(Redact())
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(h)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        lg.handlers.clear()
        lg.propagate = True


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="notecad_brain.serve")
    ap.add_argument("--port", type=int, default=8788)
    ap.add_argument("--lan", action="store_true", help="also HTTPS on the farm network")
    ap.add_argument("--tls-port", type=int, default=None, help="default: --port + 1000")
    ap.add_argument("--tls-dir", default=None, help="where cert.pem and key.pem live (default: <data>/tls)")
    ap.add_argument("--logs", default=None, help="log folder (default: <data>/logs)")
    a = ap.parse_args(argv)

    import uvicorn

    from .config import Settings
    data = Path(Settings().audio_dir).parent
    setup_logging(a.logs or data / "logs")
    tls_port = a.tls_port or a.port + 1000
    if a.lan:
        from .tls import ensure_cert, fingerprint
        cert, key = ensure_cert(a.tls_dir or data / "tls")
        os.environ["NC_BRAIN_BIND"] = "0.0.0.0"
        os.environ["NC_BRAIN_TLS_PORT"] = str(tls_port)
        os.environ["NC_BRAIN_TLS_CERT"] = str(cert)
        logging.getLogger("notecad.brain").info("LAN: https on port %s, certificate %s", tls_port, fingerprint(cert))

    from .api import create_app
    app = create_app()
    servers = [uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=a.port, log_config=None))]
    if a.lan:
        servers.append(uvicorn.Server(uvicorn.Config(app, host="0.0.0.0", port=tls_port, log_config=None,
                                                     lifespan="off", ssl_certfile=str(cert), ssl_keyfile=str(key))))

    async def run():
        await asyncio.gather(*(s.serve() for s in servers))
    asyncio.run(run())


if __name__ == "__main__":
    main()
