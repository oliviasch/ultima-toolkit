import json
import os
import re
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import assets
from profile import build_profile
from render import DEFAULT_ORDER, layout, render_home, render_profile
from steamapi import API_KEY, SteamError, clear_api_cache, resolve_steamid
from store import MAX_TAGS, list_profiles, load_profile, parse_tags, save_profile

SAMPLE_ID = "76561198845368806" # me :)
STATIC_DIR = os.path.abspath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "static"))
CLIENT_GONE = (BrokenPipeError, ConnectionResetError)


def home(error=None):
    return render_home(error, list_profiles())


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def respond(self, status, body, content_type="text/html; charset=utf-8"):
        payload = body.encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        except CLIENT_GONE:
            self.close_connection = True

    def respond_bytes(self, status, payload, content_type, cache="no-store"):
        try:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", cache)
            self.end_headers()
            self.wfile.write(payload)
        except CLIENT_GONE:
            self.close_connection = True

    def respond_json(self, status, payload):
        self.respond_bytes(status, json.dumps(payload).encode("utf-8"),
                           "application/json", cache="no-store")

    def serve_asset(self, query):
        url = query.get("u", [""])[0]
        got = assets.get(url, query.get("g", [""])[0])
        if not got:
            self.log_message("asset unavailable: %s", url)
            return self.respond_bytes(200, assets.PLACEHOLDER, "image/svg+xml",
                                      cache="public, max-age=3600")
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
        if path == "/app.js":
            return self.serve_static("app.js", "application/javascript; charset=utf-8")
        if path in ("/", "/index.html"):
            return self.respond(200, home())

        match = re.fullmatch(r"/(\d{17})(\.json)?", path)
        if not match:
            return self.respond(404, layout("Not found", '<div class="err">No such page.</div>'))

        steamid, as_json = match.group(1), bool(match.group(2))
        order = query.get("sort", [DEFAULT_ORDER])[0]
        tag = query.get("tag", [""])[0]
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
        return self.respond(200, render_profile(profile, order, tag))

    def serve_tags(self, form):
        wants_json = ("application/json" in self.headers.get("Accept", "")
                      or form.get("json", [""])[0] == "1")

        def fail(status, message):
            if wants_json:
                return self.respond_json(status, {"error": message})
            return self.respond(status, layout("Bad request",
                                               f'<div class="err">{message}</div>'))

        steamid = form.get("steamid", [""])[0].strip()
        appid = form.get("appid", [""])[0].strip()
        sort = form.get("sort", [DEFAULT_ORDER])[0]
        if not re.fullmatch(r"\d{17}", steamid) or not re.fullmatch(r"\d+", appid):
            return fail(400, "Invalid profile or game.")

        profile = load_profile(steamid, max_age=None)
        if not profile:
            return fail(404, "That profile is not cached yet. Load it first.")

        tags = profile.get("tags")
        if not isinstance(tags, dict):
            tags = {}
        current = parse_tags(tags.get(appid, []))

        action = form.get("action", [""])[0]
        incoming = parse_tags(form.get("tag", []))
        if action == "clear":
            current = []
        elif action == "set":
            current = parse_tags(form.get("tags", []))
        elif action == "remove":
            drop = {tag.casefold() for tag in incoming}
            current = [tag for tag in current if tag.casefold() not in drop]
        elif action == "add":
            known = {tag.casefold() for tag in current}
            current.extend(tag for tag in incoming if tag.casefold() not in known)
        elif incoming:
            tag = incoming[0]
            if tag.casefold() in {t.casefold() for t in current}:
                current = [t for t in current if t.casefold() != tag.casefold()]
            else:
                current.append(tag)
        current = current[:MAX_TAGS]

        if current:
            tags[appid] = current
        else:
            tags.pop(appid, None)
        profile["tags"] = tags
        save_profile(profile)

        if wants_json:
            return self.respond_json(200, {"appid": appid, "tags": current})

        params = "" if sort == DEFAULT_ORDER else "?sort=" + urllib.parse.quote(sort, safe="")
        self.send_response(303)
        self.send_header("Location", f"/{steamid}{params}#games")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _guard(self, action):
        try:
            action()
        except CLIENT_GONE:
            self.close_connection = True
        except SteamError as exc:
            self.respond(500, home(str(exc)))
        except Exception as exc:  # never drop the connection on an unexpected error
            self.log_message("unhandled error: %r", exc)
            self.respond(500, home(f"Something broke: {exc}"))

    def do_GET(self):
        self._guard(self.dispatch)

    def do_POST(self):
        self._guard(self.dispatch_post)

    def dispatch_post(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/tags":
            return self.respond(405, layout("Not allowed",
                                            '<div class="err">No such action.</div>'))
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length < 0 or length > 64 * 1024:
            return self.respond(413, layout("Too large",
                                            '<div class="err">That request is too large.</div>'))
        body = self.rfile.read(length).decode("utf-8", "replace")
        self.serve_tags(urllib.parse.parse_qs(body))

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
