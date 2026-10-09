import json
import os
import re
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import assets
from profile import build_profile
from render import DEFAULT_ORDER, layout, render_home, render_profile
from steamapi import API_KEY, SteamError, clear_api_cache, resolve_steamid
from store import list_profiles

SAMPLE_ID = "76561198845368806"
STATIC_DIR = os.path.abspath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "static"))


def home(error=None):
    return render_home(error, list_profiles())


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def respond(self, status, body, content_type="text/html; charset=utf-8"):
        payload = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def respond_bytes(self, status, payload, content_type, cache="no-store"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", cache)
        self.end_headers()
        self.wfile.write(payload)

    def serve_asset(self, query):
        url = query.get("u", [""])[0]
        got = assets.get(url, query.get("g", [""])[0])
        if not got:
            return self.respond(404, "no such asset")
        body, content_type = got
        self.respond_bytes(200, body, content_type, cache="public, max-age=31536000, immutable")

    def serve_static(self, name, content_type):
        try:
            with open(os.path.join(STATIC_DIR, name), "rb") as handle:
                body = handle.read()
        except OSError:
            return self.respond(404, "no such file")
        self.respond_bytes(200, body, content_type, cache="public, max-age=31536000")

    def route(self, path, query, refresh=False):
        if path == "/asset":
            return self.serve_asset(query)
        if path == "/style.css":
            return self.serve_static("style.css", "text/css; charset=utf-8")
        if path in ("/", "/index.html"):
            return self.respond(200, home())

        match = re.fullmatch(r"/(\d{17})(\.json)?", path)
        if not match:
            return self.respond(404, layout("Not found", '<div class="err">No such page.</div>'))

        steamid, as_json = match.group(1), bool(match.group(2))
        order = query.get("sort", [DEFAULT_ORDER])[0]
        try:
            profile = build_profile(steamid, force=refresh)
        except SteamError as exc:
            if as_json:
                return self.respond(404, json.dumps({"error": str(exc)}),
                                    "application/json")
            return self.respond(200, home(str(exc)))

        if as_json:
            return self.respond(200, json.dumps(profile, indent=2),
                                "application/json")
        return self.respond(200, render_profile(profile, order))

    def do_GET(self):
        try:
            self.dispatch()
        except SteamError as exc:
            self.respond(500, home(str(exc)))
        except Exception as exc:  # never drop the connection on an unexpected error
            self.log_message("unhandled error: %r", exc)
            self.respond(500, home(f"Something broke: {exc}"))

    def dispatch(self):
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        refresh = query.get("refresh", ["0"])[0] == "1"
        if parsed.path == "/search":
            target = query.get("id", [""])[0]
            if not target.strip():
                return self.respond(400, home("Enter a SteamID or profile URL."))
            try:
                steamid = resolve_steamid(target)
            except SteamError as exc:
                return self.respond(200, home(str(exc)))
            if refresh:
                clear_api_cache()

            params = "refresh=1" if refresh else ""
            sort = query.get("sort", [DEFAULT_ORDER])[0]
            if sort != DEFAULT_ORDER:
                params += f"&sort={sort}"
            location = f"/{steamid}" + (f"?{params}" if params else "")
            self.send_response(303)
            self.send_header("Location", location)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.route(parsed.path, query, refresh=refresh)

    def log_message(self, fmt, *args):
        print(f"  {self.address_string()} {fmt % args}")


def main():
    if not API_KEY:
        print("Set STEAM_API_KEY first: https://steamcommunity.com/dev/apikey")
        return
    port = int(os.environ.get("PORT", 8000))
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"steamstats on http://localhost:{port} - try /{SAMPLE_ID}")
    server.serve_forever()
