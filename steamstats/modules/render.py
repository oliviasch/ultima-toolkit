import html
import os
import re
import string
import time

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


def jump_nav(steamid, order, anchors=True):
    if not anchors or not steamid:
        return ""
    links = "".join(
        t("jump_link.html", key=esc(key), label=esc(label)) for key, label in SECTIONS)
    return t("jump.html", links=links)


def layout(title, body, steamid=""):
    return t("base.html", title=esc(title), steamid=esc(steamid), body=body)


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
            desc = "Hidden achievement"
        cells.append(t("achievement.html", state="" if a["unlocked"] else " locked",
                       desc=esc(desc), **ctx))
    return "".join(cells)


def render_profile(p, order=DEFAULT_ORDER):
    order = order if order in dict(SORTS) else DEFAULT_ORDER

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

    games = sort_games(p["games"], order)
    tabs = "".join(
        t("tab.html", sort=key, label=esc(label),
          active=' aria-current="true"' if key == order else "")
        for key, label in SORTS)

    notice = ""
    if p["failed_count"]:
        notice += t("error.html", message=esc(
            f'{p["failed_count"]} of {p["owned_count"]} owned games '
            "could not be loaded - Steam is rate limiting us. Wait a minute and "
            "reload; the rest of the page is accurate for the games shown."))
    if not games:
        notice += t("empty.html")

    rows = []
    for g in games:
        hours = f"{g['playtime'] // 60:,}h played"
        if not g["total"]:
            rows.append(t("game_flat.html",
                          icon=icon_img(asset_src(g.get("icon", ""), g["name"]), "icon"),
                          name=esc(g["name"]),
                          hours=esc(hours)))
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
             points=f"{p['points']:,}",
             progress=p["progress"],
             meta=meta,
             milestones=milestones_html,
             games_len=len(games),
             tabs=tabs,
             notice=notice,
             games="".join(rows),
             rarest=rarest_html)

    return layout(f"{p['name']}'s Profile - steamstats", body, steamid=p["steamid"])
