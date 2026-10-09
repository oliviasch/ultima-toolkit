import time
from concurrent.futures import ThreadPoolExecutor

from steamapi import (
    MAX_WORKERS,
    SteamError,
    api_get,
    get_game_achievements,
    get_rarity,
    get_schema,
    icon_url,
    text_field,
)
from store import load_profile, save_profile

LEVEL_POINTS = lambda pct: 1 + (1 if pct < 10 else 0) + (2 if pct < 1 else 0)
LEVEL_CURVE = lambda n: 12 * max(0, n - 1) ** 1.7  # points required to reach level n
MILESTONE_TARGETS = (1, 10, 25, 50, 100, 250, 500, 1000)

def as_bool(value):
    # steam flags arrive as ints, digit strings, or absent
    if isinstance(value, str):
        return value.strip().lower() not in ("", "0", "false", "no", "none")
    return bool(value)


def level_for(points):
    level = 1
    while LEVEL_CURVE(level + 1) <= points:
        level += 1
    floor, ceiling = LEVEL_CURVE(level), LEVEL_CURVE(level + 1)
    return level, min(1.0, (points - floor) / (ceiling - floor))


def empty_game(game):
    appid = game["appid"]
    return {
        "appid": appid,
        "name": game.get("name", f"App {appid}"),
        "error": None,
        "icon": icon_url(appid, game.get("img_icon_url", "")),
        "playtime": game.get("playtime_forever", 0),
        "achievements": [],
        "total": 0,
        "earned": 0,
        "percent": 0.0,
        "points": 0,
        "average_rarity": None,
    }


def build_game(steamid, game):
    """merge one owned game with its schema, the player's unlocks, and rarity

    a game with no achievements comes back as a zero-row entry (see empty_game),
    and a game we couldn't load carries an `error`
    """
    appid = game["appid"]
    schema = get_schema(appid)
    if schema is None:
        return {"appid": appid, "name": game.get("name", f"App {appid}"),
                "schema_failed": True,
                "error": "achievement list unavailable (Steam rate limit?)"}
    if not schema:
        # owned, but the game has no achievements
        return empty_game(game)

    try:
        response = api_get("ISteamUserStats", "GetPlayerAchievements", "v0001",
                           steamid=steamid, appid=appid)
        unlocked = {a["apiname"]: a for a in
                    response.get("playerstats", {}).get("achievements", [])
                    if a.get("achieved") or a.get("unlocktime")}
    except SteamError as exc:
        unlocked = {}
        unlock_error = str(exc)
    else:
        unlock_error = None

    rarity = get_rarity(appid)

    # GetSchemaForGame blanks the description of hidden achievements, so pull the
    # localized_desc from GetGameAchievements only for games that
    # actually have hidden stuff
    secrets = {}
    if any(as_bool(entry.get("hidden")) for entry in schema):
        secrets = get_game_achievements(appid) or {}

    achievements = []
    for entry in schema:
        name = entry.get("name") or entry.get("apiname")
        if not name:
            continue
        percent = rarity.get(name)
        earned = name in unlocked
        hidden = as_bool(entry.get("hidden"))
        description = text_field(entry.get("description"))
        if hidden:
            description = text_field(secrets.get(name, {}).get("localized_desc")) or description
        achievements.append({
            "name": text_field(entry.get("displayName")) or name,
            "description": description,
            "hidden": hidden,
            "icon": entry.get("icon", ""),
            "locked_icon": entry.get("icongray") or entry.get("lockedicon", ""),
            "unlocked": earned,
            "unlocktime": unlocked.get(name, {}).get("unlocktime", 0),
            "rarity": percent,
            "points": LEVEL_POINTS(percent if percent is not None else 100),
        })

    total = len(achievements)
    earned = sum(1 for a in achievements if a["unlocked"])
    if not total:
        # schema existed but held no usable entries, so treat it as trophy-less
        return empty_game(game)

    rated = [a["rarity"] for a in achievements if a["unlocked"] and a["rarity"] is not None]

    return {
        "appid": appid,
        "name": game.get("name", f"App {appid}"),
        "error": unlock_error,
        "icon": icon_url(appid, game.get("img_icon_url", "")),
        "playtime": game.get("playtime_forever", 0),
        "achievements": achievements,
        "total": total,
        "earned": earned,
        "percent": round(100 * earned / total, 1) if total else 0.0,
        "points": sum(a["points"] for a in achievements if a["unlocked"]),
        "average_rarity": round(sum(rated) / len(rated), 2) if rated else None,
    }
def build_profile(steamid, force=False):
    if not force:
        saved = load_profile(steamid)
        if saved:
            saved["from_cache"] = True
            return saved

    players = api_get("ISteamUser", "GetPlayerSummaries", "v0002",
                      steamids=steamid).get("players", [])
    if not players:
        raise SteamError("That Steam profile does not exist.")
    player = players[0]

    looks_private = player.get("communityvisibilitystate") == 1

    owned = api_get("IPlayerService", "GetOwnedGames", "v0001", steamid=steamid,
                    include_appinfo=1, include_played_free_games=1,
                    skip_unvetted_apps=0).get("games", [])
    if not owned:
        name = player.get("personaname", "This profile")
        if looks_private:
            raise SteamError(
                f"{name}'s profile is private. Ask them to set "
                "My profile > Profile privacy to Public, then reload."
            )
        raise SteamError(
            f"No games returned for {name}. Their profile is public, so the likelier "
            "cause is that Game details are private - they need to set "
            "My profile > Game details to Public."
        )

    owned.sort(key=lambda g: g.get("playtime_forever", 0), reverse=True)
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        built = list(pool.map(lambda g: build_game(steamid, g), owned))

    # games that failed to load are kept as stubs, never silently dropped
    failed = [g for g in built if g and g.get("schema_failed")]
    games = [g for g in built if g and not g.get("schema_failed")]
    if not games and failed:
        raise SteamError(f"Found {len(failed)} games but could not load any achievement lists - "
            "Steam might be rate limiting us. Wait a minute and reload.")

    games.sort(key=lambda g: (-g["percent"], -g["playtime"]))

    total_earned = sum(g["earned"] for g in games)
    total_all = sum(g["total"] for g in games)
    points = sum(g["points"] for g in games)
    level, progress = level_for(points)

    earned_achievements = [a | {"game": g["name"], "appid": g["appid"]}
                           for g in games for a in g["achievements"] if a["unlocked"]]
    earned_achievements.sort(key=lambda a: (a["rarity"] if a["rarity"] is not None else 100))

    completed = [g for g in games if g["percent"] == 100]

    profile = {
        "steamid": steamid,
        "name": player.get("personaname", "Unknown"),
        "realname": player.get("realname", ""),
        "avatar": player.get("avatarfull", ""),
        "country": player.get("loccountrycode", ""),
        "created": player.get("timecreated", 0),
        "level": level,
        "progress": round(progress * 100, 1),
        "points": points,
        "earned": total_earned,
        "total": total_all,
        "platinum": len(completed),
        "game_count": len(games),
        "failed_count": len(failed),
        "owned_count": len(owned),
        "games": games,
        "rarest": earned_achievements[:12],
        "milestones": build_milestones(completed),
        "cached_at": time.time(),
    }
    save_profile(profile)
    return profile


def ordinal(n):
    suffix = ("th" if 10 <= n % 100 <= 20
              else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th"))
    return f"{n}{suffix}"


def build_milestones(completed):
    stamps = []
    for game in completed:
        times = [a["unlocktime"] for a in game["achievements"] if a["unlocktime"]]
        stamps.append((max(times) if times else 0, game))
    stamps.sort(key=lambda stamp: stamp[0])

    marks = []
    for target in MILESTONE_TARGETS:
        if len(completed) < target:
            break
        when, game = stamps[target - 1]
        previous = marks[-1]["when"] if marks else 0
        marks.append({
            "target": target,
            "label": f"{ordinal(target)} 100% game",
            "game": game["name"],
            "appid": game["appid"],
            "icon": game.get("icon", ""),
            "when": when,
            "span": when - previous if previous and when > previous else 0,
        })
    return marks
