import hashlib
import mimetypes
import os
import re
import shutil
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request

ASSET_DIR = os.environ.get(
    "STEAM_ASSET_DIR",
    os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "cache", "assets")))
USER_AGENT = "steamstats-prototype/0.1"
TIMEOUT = 20
ALLOWED_HOSTS = frozenset({
    "cdn.cloudflare.steamstatic.com",
    "cdn.akamai.steamstatic.com",
    "cdn.steamstatic.com",
    "media.steampowered.com",
    "steamcdn-a.akamaihd.net",
    "avatars.steamstatic.com",
    "avatars.akamai.steamstatic.com",
    "community.cloudflare.steamstatic.com",
})

_lock = threading.Lock()


def is_allowed(url):
    parsed = urllib.parse.urlparse(url)
    return parsed.scheme in ("http", "https") and parsed.hostname in ALLOWED_HOSTS


def asset_src(url, group=""):
    if not url:
        return ""
    if not is_allowed(url):
        return url
    src = "/asset?u=" + urllib.parse.quote(url, safe="")
    if group:
        src += "&g=" + urllib.parse.quote(group, safe="")
    return src


def _key(url):
    return hashlib.sha1(url.encode("utf-8")).hexdigest()


def _slug(name):
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", name or "")
    value = re.sub(r"\s+", " ", value).strip(" .-")
    return value[:80].strip() or "unsorted"


def _path(url, group=""):
    key = _key(url)
    return os.path.join(ASSET_DIR, _slug(group) if group else "misc", key[:2], key)


def _content_type(url):
    return mimetypes.guess_type(url)[0] or "application/octet-stream"


def get(url, group=""):
    if not is_allowed(url):
        return None

    path = _path(url, group)
    try:
        with open(path, "rb") as handle:
            return handle.read(), _content_type(url)
    except OSError:
        pass

    try:
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            if response.status != 200:
                return None
            body = response.read()
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
        return None
    if not body:
        return None

    with _lock:
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            handle, tmp = tempfile.mkstemp(
                dir=os.path.dirname(path), prefix=".asset-", suffix=".tmp")
            with os.fdopen(handle, "wb") as out:
                out.write(body)
            os.replace(tmp, path)
        except OSError:
            # a failed cache write is not worth failing the request over
            try:
                os.unlink(tmp)
            except (OSError, UnboundLocalError):
                pass
    return body, _content_type(url)


def clear():
    shutil.rmtree(ASSET_DIR, ignore_errors=True)
