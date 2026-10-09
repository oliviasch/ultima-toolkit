import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

API_KEY = os.environ.get("STEAM_API_KEY", "")
API_ROOT = "https://api.steampowered.com"
CDN = "https://cdn.cloudflare.steamstatic.com"
USER_AGENT = "steamstats-prototype/0.1"
SCHEMA_TTL = 60 * 60 * 24  # game achievement lists and rarity change slowly
MAX_WORKERS = 4  # steam does throttle burst stuff
RETRIES = 3
RETRY_CODES = (429, 500, 502, 503, 504)
BACKOFF = (1, 3, 8)
MAX_BACKOFF = 30

_cache = {}
_cache_lock = threading.Lock()
_slots = threading.Semaphore(MAX_WORKERS)


class SteamError(Exception):
    pass


def unwrap(payload):
    if isinstance(payload, dict) and isinstance(payload.get("response"), dict):
        return payload["response"]
    return payload


def api_get(interface, method, version, **params):
    params = {k: v for k, v in params.items() if v is not None}
    params["key"] = API_KEY
    params["format"] = "json"
    url = f"{API_ROOT}/{interface}/{method}/{version}/?" + urllib.parse.urlencode(params)

    for attempt in range(RETRIES + 1):
        with _slots:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            try:
                with urllib.request.urlopen(request, timeout=20) as response:
                    return unwrap(json.load(response))
            except urllib.error.HTTPError as exc:
                if exc.code in RETRY_CODES and attempt < RETRIES:
                    delay = float(exc.headers.get("Retry-After") or 0) or BACKOFF[attempt]
                    exc.close()
                    time.sleep(min(delay, MAX_BACKOFF))
                    continue
                detail = ""
                try:
                    body = exc.read().decode("utf-8", "replace")
                    # the useful sentence sits after the <h1>; <title> just repeats it
                    tail = body.rsplit("</h1>", 1)[-1] if "</h1>" in body else body
                    detail = " ".join(re.sub(r"<[^>]+>", " ", tail).split())
                except Exception:
                    pass
                hint = ""
                if exc.code == 404 and "not found" in detail.lower():
                    hint = " - that interface/method no longer exists on Steam"
                elif exc.code in (401, 403):
                    hint = " - check STEAM_API_KEY is valid"
                elif exc.code == 429:
                    hint = " - rate limited by Steam; wait a minute and reload"
                raise SteamError(
                    f"{interface}/{method} failed: HTTP {exc.code}"
                    + (f" ({detail})" if detail else "") + hint) from exc
            except (urllib.error.URLError, TimeoutError) as exc:
                if attempt < RETRIES:
                    time.sleep(BACKOFF[attempt])
                    continue
                raise SteamError(f"{interface}/{method} failed: {exc}") from exc

    raise SteamError(f"{interface}/{method} failed after {RETRIES + 1} attempts")


def cached(key, loader):
    now = time.time()
    with _cache_lock:
        hit = _cache.get(key)
        if hit and hit[1] is not None and now - hit[0] < SCHEMA_TTL:
            return hit[1]

    value = loader()
    if value is None:
        with _cache_lock:
            _cache.pop(key, None)
        return None

    with _cache_lock:
        _cache[key] = (now, value)
    return value


def clear_api_cache():
    with _cache_lock:
        _cache.clear()


def text_field(value):
    if isinstance(value, dict):
        value = value.get("#text", "")
    return value or ""


def get_schema(appid):
    def load():
        try:
            response = api_get("ISteamUserStats", "GetSchemaForGame", "v0002", appid=appid)
        except SteamError:
            return None
        return response.get("game", {}).get("availableGameStats", {}).get("achievements", [])

    return cached(f"schema:{appid}", load)


def get_game_achievements(appid, language="english"):
    def load():
        try:
            response = api_get("IPlayerService", "GetGameAchievements", "v1",
                               appid=appid, language=language)
        except SteamError:
            return None
        entries = response.get("achievements", [])
        return {e["internal_name"]: e for e in entries if e.get("internal_name")}

    return cached(f"gameach:{language}:{appid}", load)


def get_rarity(appid):
    def load():
        url = (f"{API_ROOT}/ISteamUserStats/GetGlobalAchievementPercentagesForApp/v2/"
               f"?gameid={appid}")
        try:
            with _slots:
                request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
                with urllib.request.urlopen(request, timeout=20) as response:
                    payload = json.load(response)
        except (urllib.error.URLError, TimeoutError):
            return {}
        entries = payload.get("achievementpercentages", {}).get("achievements", [])
        return {e["name"]: float(e["percent"]) for e in entries}

    return cached(f"rarity:{appid}", load)


def resolve_steamid(user_input):
    user_input = user_input.strip()
    if not user_input:
        raise SteamError("Enter a SteamID, profile URL, or custom URL.")

    if user_input.isdigit():
        return user_input

    # https://steamcommunity.com/profiles/76561197960435530
    match = re.search(r"/profiles/(\d{17})", user_input)
    if match:
        return match.group(1)

    # https://steamcommunity.com/id/somevanity
    match = re.search(r"steamcommunity\.com/id/([^/?#]+)", user_input)
    if match:
        vanity = match.group(1)
    elif re.fullmatch(r"[A-Za-z0-9._-]+", user_input):
        vanity = user_input
    else:
        raise SteamError(f"Could not understand '{user_input}'.")

    response = api_get("ISteamUser", "ResolveVanityURL", "v0001", vanityurl=vanity)
    steamid = response.get("steamid")
    if not steamid:
        raise SteamError(f"No Steam profile found at '{vanity}'.")
    return steamid


def icon_url(appid, icon_hash):
    if not icon_hash:
        return ""
    return f"{CDN}/steamcommunity/public/images/apps/{appid}/{icon_hash}.jpg"
