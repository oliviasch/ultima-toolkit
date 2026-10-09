import json
import os
import tempfile
import time

CACHE_DIR = os.environ.get(
    "STEAM_CACHE_DIR", os.path.abspath(os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "cache")))
PROFILE_TTL = int(os.environ.get("PROFILE_TTL", 60 * 60))  # reuse window
CACHE_VERSION = 6


def profile_path(steamid):
    return os.path.join(CACHE_DIR, f"{steamid}.json")


def load_profile(steamid):
    try:
        with open(profile_path(steamid), encoding="utf-8") as handle:
            saved = json.load(handle)
    except (OSError, ValueError):
        return None
    if not isinstance(saved, dict) or not saved.get("games"):
        return None
    if saved.get("cache_version") != CACHE_VERSION:
        return None
    if time.time() - saved.get("cached_at", 0) > PROFILE_TTL:
        return None
    return saved


def list_profiles():
    try:
        names = os.listdir(CACHE_DIR)
    except OSError:
        return []

    pins = []
    for name in names:
        if not name.endswith(".json") or name.startswith("."):
            continue
        try:
            with open(os.path.join(CACHE_DIR, name), encoding="utf-8") as handle:
                saved = json.load(handle)
        except (OSError, ValueError):
            continue
        if not isinstance(saved, dict) or not saved.get("steamid"):
            continue
        pins.append({
            "steamid": saved["steamid"],
            "name": saved.get("name") or saved["steamid"],
            "avatar": saved.get("avatar", ""),
            "level": saved.get("level", 1),
            "platinum": saved.get("platinum", 0),
            "cached_at": saved.get("cached_at", 0),
        })
    pins.sort(key=lambda pin: pin["cached_at"], reverse=True)
    return pins


def save_profile(profile):
    os.makedirs(CACHE_DIR, exist_ok=True)
    payload = dict(profile, cache_version=CACHE_VERSION)
    handle, tmp = tempfile.mkstemp(dir=CACHE_DIR, prefix=".profile-", suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as out:
            json.dump(payload, out)
        os.replace(tmp, profile_path(profile["steamid"]))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
