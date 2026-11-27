"""Serve exact review bytes on a private, capability-scoped loopback URL."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
from secrets import token_urlsafe
from urllib.parse import urlsplit


def serve_review(body):
    root = Path(__file__).resolve().parents[2]
    files = set(
        json.loads((root / "config/pages-publication-allowlist.json").read_bytes())["files"]
    )
    files.update(("airport-diagrams.js", "data/airport-diagrams.json"))
    prefix = "/" + token_urlsafe(24) + "/"

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path = urlsplit(self.path).path
            if not path.startswith(prefix):
                self.send_error(404)
                return
            name = path.removeprefix(prefix) or "index.html"
            if name not in files:
                self.send_error(404)
                return
            if name == "data/notams.json":
                content = body
            else:
                path = (root / name).resolve()
                if root not in path.parents:
                    self.send_error(404)
                    return
                content = path.read_bytes()
            self.send_response(200)
            media = "text/javascript" if name.endswith(".js") else mimetypes.guess_type(name)[0]
            self.send_header("Content-Type", media or "application/octet-stream")
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header(
                "Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'"
            )
            self.end_headers()
            self.wfile.write(content)

        def log_message(self, *_args):
            pass

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        print(f"http://127.0.0.1:{server.server_port}{prefix}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
