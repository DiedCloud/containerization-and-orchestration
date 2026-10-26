"""Lab-only Alertmanager webhook: acknowledge only after writing JSON to stdout.

No durable queue or deduplication. A 200 response proves acceptance by this
process, not durable storage in Loki. Repeated deliveries are logged as-is.
"""

import json
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        # Suppress the standard unstructured access log.
        pass

    def reply(self, status, body):
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self.reply(200, b"ok\n") if self.path == "/health" else self.reply(404, b"not found\n")

    def do_POST(self):
        if self.path != "/alerts":
            self.reply(404, b"not found\n")
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.reply(400, b"invalid content length\n")
            return
        if not 0 < size <= 1024 * 1024:
            self.reply(413, b"expected a body of at most 1 MiB\n")
            return
        try:
            payload = json.loads(self.rfile.read(size))
        except (ValueError, UnicodeDecodeError):
            self.reply(400, b"invalid JSON\n")
            return
        if not isinstance(payload, dict) or not isinstance(payload.get("alerts"), list):
            self.reply(400, b"expected an object with an alerts array\n")
            return
        print(json.dumps({
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": "INFO",
            "msg": "alertmanager webhook received",
            "notification": payload,
        }), flush=True)
        self.reply(200, b"accepted\n")


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
