import html
import os
import re
import string
import time
import urllib.parse

from assets import asset_src

TEMPLATE_DIR = os.path.abspath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "templates"))
_SECTION = re.compile(r"\{\{#\s*(?P<name>[A-Za-z0-9_]+)\s*\}\}")
SECTIONS = (
    ("summary", "Summary"),
    ("milestones", "Milestones"),
    ("games", "Games"),
    ("rarest", "Rarest"),
)
SORTS = (("pct", "Completion"),
    ("hours", "Most played"),)
DEFAULT_ORDER = "hours"
PRESET_TAGS = ("backlog", "playing", "played", "to complete", "completed")
STATIC_DIR = os.path.abspath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "static"))

def _parse_sections(text):
    matches = list(_SECTION.finditer(text))
    sections = {}
    for i, match in enumerate(matches):
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        sections[match.group("name") + ".html"] = text[start:end].strip("\n")
    return sections


def _load_templates():
    loaded = {}
    for name in os.listdir(TEMPLATE_DIR):
        if not name.endswith(".html"):
            continue
        with open(os.path.join(TEMPLATE_DIR, name), encoding="utf-8") as handle:
            for key, text in _parse_sections(handle.read()).items():
                loaded[key] = string.Template(text)
    return loaded


_templates = _load_templates()


def t(tpl, **ctx):
    return _templates[tpl].substitute(ctx)


def sort_games(games, order):
    if order == "hours":
        return sorted(games, key=lambda g: (-g["playtime"], -g["percent"]))
    return sorted(games, key=lambda g: (-g["percent"], -g["playtime"]))


def profile_query(order, tag=""):
    """build a profile query string, leaving out values that are the default"""
    params = []
    if order and order != DEFAULT_ORDER:
        params.append("sort=" + urllib.parse.quote(order, safe=""))
    if tag:
        params.append("tag=" + urllib.parse.quote(tag, safe=""))
    return "?" + "&".join(params) if params else ""


def esc(text):
    return html.escape(str(text or ""))


def rarity_label(percent):
    if percent is None:
        return ""
    if percent < 1:
        return "Ultra Rare"
    if percent < 10:
        return "Very Rare"
    if percent < 30:
        return "Rare"
    return "Common"


def icon_img(src, klass=""):
    if not src:
        return ""
    k = f' class="{klass}"' if klass else ""
    return f'<img src="{esc(src)}"{k} alt="" loading="lazy">'


def game_tags(tags, appid):
    value = tags.get(str(appid)) if isinstance(tags, dict) else None
    if not isinstance(value, list):
        return []
    return [tag for tag in value if isinstance(tag, str) and tag]


def profile_tags(tags):
    """every distinct tag on a profile, in case-insensitive order"""
    found = {}
    if isinstance(tags, dict):
        for value in tags.values():
            if not isinstance(value, list):
                continue
            for tag in value:
                if isinstance(tag, str) and tag:
                    found.setdefault(tag.casefold(), tag)
    return sorted(found.values(), key=str.casefold)


def filter_games(games, tags, query):
    """keep games carrying a tag matching the query, case-insensitively"""
    wanted = query.casefold()
    return [g for g in games
            if any(wanted in tag.casefold() for tag in game_tags(tags, g["appid"]))]


def tag_chips(tags, limit=4):
    """small read-only chips for a game row, collapsed when there are many"""
    shown = tags[:limit]
    more = len(tags) - len(shown)
    chips = "".join(t("tag_chip.html", tag=esc(tag)) for tag in shown)
    if more > 0:
        chips += t("tag_more.html", count=more)
    return chips


def tag_list(tags):
    """editable chips in the tag panel; each one removes its tag when clicked"""
    return "".join(t("tag_remove.html", tag=esc(tag)) for tag in tags)


def tag_editor(steamid, appid, tags, order):
    return t("tag_editor.html", steamid=esc(steamid), appid=esc(appid),
             order=esc(order), tags=tag_list(tags))


def static_url(name):
    try:
        stamp = int(os.path.getmtime(os.path.join(STATIC_DIR, name)))
    except OSError:
        stamp = 0
    return f"/{name}?v={stamp}"


def jump_nav(steamid, order, anchors=True):
    if not anchors or not steamid:
        return ""
    links = "".join(
        t("jump_link.html", key=esc(key), label=esc(label)) for key, label in SECTIONS)
    return t("jump.html", links=links)


def layout(title, body, steamid=""):
    presets = "".join(t("tag_option.html", tag=esc(tag)) for tag in PRESET_TAGS)
    return t("base.html", title=esc(title), steamid=esc(steamid), body=body,
             presets=presets,
             style_url=static_url("style.css"), script_url=static_url("app.js"))


def render_home(error=None, pins=()):
    error_html = t("error.html", message=esc(error)) if error else ""
    pin_html = ""
    if pins:
        cards = []
        for pin in pins:
            cards.append(t("pin.html",
                           steamid=esc(pin["steamid"]),
                           avatar=icon_img(asset_src(pin.get("avatar", ""), "avatars")),
                           name=esc(pin["name"]),
                           level=pin["level"],
                           platinum=pin["platinum"]))
        pin_html = t("pins.html", cards="".join(cards))
    return layout("steamstats", t("home.html", error=error_html, pins=pin_html))


def _render_achievements(achievements, game):
    cells = []
    for a in achievements:
        icon = asset_src(a["icon"] if a["unlocked"] else (a["locked_icon"] or a["icon"]), game)
        detail = (f'{a["rarity"]}% \u00b7 {rarity_label(a["rarity"])}'
                  if a["rarity"] is not None else "")
        when = (f'unlocked {time.strftime("%d %b %Y", time.localtime(a["unlocktime"]))}'
                if a["unlocktime"] else "locked")
        desc = a.get("description") or ""
        ctx = dict(icon=esc(icon), name=esc(a["name"]), detail=esc(detail),
                   when=esc(when))
        if a.get("hidden") and not a["unlocked"] and desc:
            cells.append(t("achievement_secret.html", desc=esc(desc), **ctx))
            continue
        if a.get("hidden") and not desc:
            desc = "Hidden achievement."
        cells.append(t("achievement.html", state="" if a["unlocked"] else " locked",
                       desc=esc(desc), **ctx))
    return "".join(cells)


def render_profile(p, order=DEFAULT_ORDER, tag=""):
    order = order if order in dict(SORTS) else DEFAULT_ORDER
    tag = " ".join(str(tag or "").split())
    tags = p.get("tags") if isinstance(p.get("tags"), dict) else {}

    since = (time.strftime("%B %Y", time.gmtime(p["created"]))
             if p["created"] else "unknown")
    fetched = ""
    if p.get("cached_at"):
        age = max(0, time.time() - p["cached_at"])
        if age < 90:
            when = "just now"
        elif age < 5400:
            when = f"{int(age // 60)}m ago"
        elif age < 172800:
            when = f"{int(age // 3600)}h ago"
        else:
            when = f"{int(age // 86400)}d ago"
        fetched = ("from cache, fetched " + when) if p.get("from_cache") else "fetched " + when
    meta = " &middot; ".join(filter(None, [
        f"SteamID {p['steamid']}",
        esc(p["realname"]),
        f"joined {since}",
        esc(p["country"]),
        fetched,
    ]))
    meta += (f" &middot; {p['earned']:,} of {p['total']:,} achievements "
             f"({p['points']:,} weighted points, {p['progress']}% to level {p['level'] + 1})")

    milestones_html = ""
    if p["milestones"]:
        cards = []
        for m in p["milestones"]:
            when = (time.strftime("%b %Y", time.localtime(m["when"]))
                    if m["when"] else "date unknown")
            span = (f'<span>+{m["span"] // 86400}d</span>' if m.get("span") else "<span></span>")
            cards.append(t("milestone.html",
                           icon=icon_img(asset_src(m.get("icon", ""), m["game"])),
                           num=m["target"],
                           lbl=esc(m["label"]),
                           game=esc(m["game"]),
                           when=esc(when),
                           span=span))
        milestones_html = t("milestones.html", cards="".join(cards))

    games = sort_games(filter_games(p["games"], tags, tag) if tag else p["games"],
                       order)
    pcts = [g["percent"] for g in p["games"]]
    active_pcts = [x for x in pcts if x > 0]
    avg_all = round(sum(pcts) / len(pcts), 1) if pcts else 0.0
    avg_active = round(sum(active_pcts) / len(active_pcts), 1) if active_pcts else 0.0
    tabs = "".join(
        t("tab.html", href=esc(f"/{p['steamid']}{profile_query(key, tag)}"),
          label=esc(label),
          active=' aria-current="true"' if key == order else "")
        for key, label in SORTS)
    tag_filter_html = t(
        "tag_filter.html",
        steamid=esc(p["steamid"]),
        order=esc(order),
        tag=esc(tag),
        active=" active" if tag else "",
        options="".join(t("tag_option.html", tag=esc(value))
                        for value in profile_tags(tags)),
        clear_href=esc(f"/{p['steamid']}{profile_query(order)}"),
        clear_hidden="" if tag else " hidden")

    notice = ""
    if p["failed_count"]:
        notice += t("error.html", message=esc(
            f'{p["failed_count"]} of {p["owned_count"]} owned games '
            "could not be loaded - Steam is rate limiting us. Wait a minute and "
            "reload; the rest of the page is accurate for the games shown."))
    if not games:
        notice += (t("filter_empty.html", tag=esc(tag)) if tag
                   else t("empty.html"))

    rows = []
    for g in games:
        mine = game_tags(tags, g["appid"])
        chips = tag_chips(mine)
        hidden = "" if mine else " hidden"
        editor = tag_editor(p["steamid"], g["appid"], mine, order)
        hours = f"{g['playtime'] // 60:,}h played"
        if not g["total"]:
            rows.append(t("game_flat.html",
                          icon=icon_img(asset_src(g.get("icon", ""), g["name"]), "icon"),
                          name=esc(g["name"]),
                          hours=esc(hours),
                          appid=g["appid"],
                          tags=chips,
                          tags_hidden=hidden,
                          tag_editor=editor))
            continue

        badge = (t("plat_badge.html") if g["percent"] == 100
                 else t("pct_badge.html", percent=g["percent"]))
        rarity = ""
        if g["average_rarity"] is not None:
            rarity += f" &middot; avg {g['average_rarity']}% of players"
        if g.get("error"):
            rarity += " &middot; " + t("unlock_warn.html")

        rows.append(t("game.html",
                      icon=icon_img(asset_src(g.get("icon", ""), g["name"]), "icon"),
                      name=esc(g["name"]),
                      hours=esc(hours),
                      rarity=rarity,
                      appid=g["appid"],
                      tags=chips,
                      tags_hidden=hidden,
                      tag_editor=editor,
                      earned=g["earned"],
                      total=g["total"],
                      badge=badge,
                      achievements=_render_achievements(g["achievements"], g["name"])))

    if p["rarest"]:
        rarest_html = "".join(
            t("rarest_row.html",
              icon=esc(asset_src(a["icon"], a["game"])),
              name=esc(a["name"]),
              game=esc(a["game"]),
              detail=esc(f'{a["rarity"]}% \u00b7 {rarity_label(a["rarity"])}'))
            for a in p["rarest"])
    else:
        rarest_html = t("rarest_empty.html")

    body = t("profile.html",
             jump=jump_nav(p["steamid"], order),
             avatar=esc(asset_src(p["avatar"], "avatars")),
             level=p["level"],
             platinum=f"{p['platinum']:,}",
             earned=f"{p['earned']:,}",
             game_count=f"{p['game_count']:,}",
             avg_all=avg_all,
             avg_active=avg_active,
             points=f"{p['points']:,}",
             progress=p["progress"],
             meta=meta,
             milestones=milestones_html,
             games_len=len(games),
             tabs=tabs,
             filter=tag_filter_html,
             notice=notice,
             games="".join(rows),
             rarest=rarest_html)

    return layout(f"{p['name']}'s Profile - steamstats", body, steamid=p["steamid"])
