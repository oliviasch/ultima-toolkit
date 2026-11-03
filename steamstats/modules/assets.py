import hashlib
import mimetypes
import os
import re
import shutil
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

ASSET_DIR = os.environ.get(
    "STEAM_ASSET_DIR",
    os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "cache", "assets")))
USER_AGENT = "steamstats-prototype/0.1"
TIMEOUT = 20
CDN_HOSTS = (
    "cdn.cloudflare.steamstatic.com",
    "cdn.akamai.steamstatic.com",
    "steamcdn-a.akamaihd.net",
)
ALLOWED_HOSTS = frozenset({
    *CDN_HOSTS,
    "cdn.steamstatic.com",
    "media.steampowered.com",
    "avatars.steamstatic.com",
    "avatars.akamai.steamstatic.com",
    "community.cloudflare.steamstatic.com",
})
MISS_TTL = 60 * 60 * 6  # stop re-asking steam about icons it doesn't have

# shown when an image is gone from every steam CDN; the schema does contain a
# few icons whose files return 404 (old app builds, mostly)
PLACEHOLDER = (
    b'<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" '
    b'viewBox="0 0 64 64"><rect width="64" height="64" rx="8" fill="#171a21"/>'
    b'<path d="M32 13l5.8 11.9 13.1 1.9-9.5 9.2 2.3 13-11.7-6.2-11.7 6.2 '
    b'2.3-13-9.5-9.2 13.1-1.9z" fill="#3d444d"/></svg>'
)

_lock = threading.Lock()
_miss_lock = threading.Lock()
_misses = {}


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


def _alternates(url):
    """the same path on the other steam CDNs, in case one host dropped a file"""
    parsed = urllib.parse.urlparse(url)
    if parsed.hostname not in CDN_HOSTS:
        return []
    return [parsed._replace(netloc=host).geturl()
            for host in CDN_HOSTS if host != parsed.hostname]


def _missed(url):
    with _miss_lock:
        stamp = _misses.get(url)
        if stamp is None:
            return False
        if time.time() - stamp < MISS_TTL:
            return True
        del _misses[url]
        return False


def _remember_miss(url):
    with _miss_lock:
        _misses[url] = time.time()


def _fetch(url):
    """returns (body, definitive): definitive means the host said it is gone"""
    try:
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            if response.status != 200:
                return None, False
            return response.read(), False
    except urllib.error.HTTPError as exc:
        return None, exc.code in (403, 404)
    except (urllib.error.URLError, TimeoutError, OSError):
        return None, False


def get(url, group=""):
    if not is_allowed(url):
        return None

    path = _path(url, group)
    try:
        with open(path, "rb") as handle:
            return handle.read(), _content_type(url)
    except OSError:
        pass

    if _missed(url):
        return None

    body = None
    gone = True
    for candidate in (url, *_alternates(url)):
        body, definitive = _fetch(candidate)
        if body:
            break
        gone = gone and definitive
    if not body:
        if gone:
            _remember_miss(url)
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
    with _miss_lock:
        _misses.clear()
