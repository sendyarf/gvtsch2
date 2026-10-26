"""
Public JSON server for gvtsch2.

Serves the generated JSON files (sch.json and friends) as read-only HTTP
endpoints so the frontend (a different project) can fetch them, e.g.:

    fetch("https://your-vps:8787/sch.json")

Features:
- Read-only: only serves a whitelist of *.json files, never directories,
  never writes, never follows paths outside the base directory.
- CORS enabled (*) so any frontend origin can read the data.
- But last-modified / version stamping is skipped; clients may pass
  `?v=<anything>` and we still return the current file.

Usage:
    python serve_public.py                 # host 0.0.0.0:8787, serves cwd
    python serve_public.py --port 9000
    GVT_SERVE_FILES="sch.json,soco.json" python serve_public.py

Works as a PM2 app too (see ecosystem.config.js -> gvtsch2-serve).
"""
import argparse
import http.server
import mimetypes
import os
import socketserver
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_FILES = [
    "sch.json",
    "live.json",
    "flashscore.json",
    "soco.json",
    "bolaloca.json",
    "sofascore.json",
    "sportsonline.json",
    "truckrefuse.json",
    "timstreams.json",
    "90phut.json",
    "colatv.json",
]
DEFAULT_PORT = 8787


def parse_args():
    ap = argparse.ArgumentParser(description="Read-only JSON server for gvtsch2 outputs")
    ap.add_argument("--host", default=os.environ.get("GVT_SERVE_HOST", "0.0.0.0"))
    ap.add_argument("--port", type=int, default=int(os.environ.get("GVT_SERVE_PORT", DEFAULT_PORT)))
    ap.add_argument("--files", default=os.environ.get("GVT_SERVE_FILES", ",".join(DEFAULT_FILES)))
    return ap.parse_args()


class Handler(http.server.BaseHTTPRequestHandler):
    # Whitelist set in main() because it depends on args.
    allowed = set()

    def do_GET(self):
        path = self.path.split("?", 1)[0].strip("/").lstrip("..").replace("\\", "")
        if path == "":
            # Root: list which files are available.
            import json
            listing = {
                "service": "gvtsch2 public json",
                "files": sorted(f for f in self.allowed if f),
                "hint": "fetch /sch.json for the merged schedule",
            }
            body = json.dumps(listing).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)
            return

        if path not in self.allowed:
            self.send_error(404, f"Not found: {path}")
            return

        file_path = os.path.join(BASE_DIR, path)
        if not os.path.isfile(file_path):
            self.send_error(404, f"Not ready yet: {path}")
            return

        try:
            with open(file_path, "rb") as fh:
                body = fh.read()
        except OSError as e:
            self.send_error(500, f"Read error: {e}")
            return

        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Max-Age", "86400")
        self.end_headers()

    def log_message(self, fmt, *args):
        # keep PM2 logs readable
        print(f"[serve] {self.address_string()} - {fmt % args}", flush=True)


def main():
    args = parse_args()
    Handler.allowed = {f.strip() for f in args.files.split(",") if f.strip()}

    class QuietServer(socketserver.ThreadingTCPServer):
        daemon_threads = True
        allow_reuse_address = True

    httpd = QuietServer((args.host, args.port), Handler)
    print(f"Serving {len(Handler.allowed)} json file(s) at http://{args.host}:{args.port}/")
    print("Files:", ", ".join(sorted(Handler.allowed)))
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("Stopped.")


if __name__ == "__main__":
    main()