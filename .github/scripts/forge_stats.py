#!/usr/bin/env python3
"""Render the Rinnegan-themed stat cards used by the profile README.

Reads live numbers from the GitHub GraphQL API and writes four self-hosted SVGs
into assets/, so the README never depends on a third-party stats service (every
popular one either goes dark or gets dropped by GitHub's image proxy).

Env:
  STATS_TOKEN  token used for the API call (a PAT with read:user + repo also
               counts private repositories; the default GITHUB_TOKEN sees
               public ones only)
  STATS_USER   login to render (default: FayzSa)
"""

import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.request
from html import escape

USER = os.environ.get("STATS_USER", "FayzSa")
TOKEN = os.environ.get("STATS_TOKEN") or os.environ.get("GITHUB_TOKEN", "")
OUT = os.path.join(os.path.dirname(__file__), "..", "..", "assets")

BG = "#0B0B10"
BORDER = "#2B1B3D"
TITLE = "#B06CFF"
TEXT = "#A8A8B8"
BRIGHT = "#EDEDF2"
ACCENT = "#E01E37"
RING = "#7B5EA7"
# empty -> busiest, a violet ramp so the heatmap sits in the same palette
HEAT = ["#161320", "#33224D", "#5B3A8F", "#8B5CE0", "#C9A6FF"]

FONT = ("'JetBrains Mono','SFMono-Regular',Consolas,'Noto Sans CJK JP',"
        "'Hiragino Sans','Yu Gothic',Meiryo,monospace")

PROFILE_QUERY = """
query($login: String!, $after: String) {
  user(login: $login) {
    createdAt
    followers { totalCount }
    contributionsCollection {
      totalCommitContributions
      restrictedContributionsCount
      totalPullRequestContributions
      totalIssueContributions
    }
    repositories(first: 100, after: $after, ownerAffiliations: OWNER, isFork: false) {
      totalCount
      pageInfo { hasNextPage endCursor }
      nodes {
        stargazerCount
        languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
          edges { size node { name color } }
        }
      }
    }
  }
}
"""

CALENDAR_QUERY = """
query($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    contributionsCollection(from: $from, to: $to) {
      contributionCalendar {
        weeks { contributionDays { date contributionCount } }
      }
    }
  }
}
"""


def graphql(query, variables):
    body = json.dumps({"query": query, "variables": variables})
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=body.encode(),
        headers={
            "Authorization": f"bearer {TOKEN}",
            "Content-Type": "application/json",
            "User-Agent": f"{USER}-profile-forge",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        payload = json.load(r)
    if payload.get("errors"):
        raise RuntimeError(json.dumps(payload["errors"])[:500])
    return payload["data"]["user"]


def fetch_days(created_at):
    """Every contribution day since signup, as {date: count}.

    contributionsCollection caps at one year per call, so walk year by year.
    """
    days = {}
    start = dt.datetime.strptime(created_at[:10], "%Y-%m-%d").replace(
        tzinfo=dt.timezone.utc
    )
    now = dt.datetime.now(dt.timezone.utc)
    cursor = start
    while cursor < now:
        end = min(cursor.replace(year=cursor.year + 1), now)
        user = graphql(
            CALENDAR_QUERY,
            {
                "login": USER,
                "from": cursor.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "to": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
        )
        weeks = user["contributionsCollection"]["contributionCalendar"]["weeks"]
        for week in weeks:
            for day in week["contributionDays"]:
                days[day["date"]] = day["contributionCount"]
        cursor = end
    return days


def streaks(days):
    """Current streak, longest streak and lifetime total from a day map.

    Today is allowed to be empty without breaking the current streak — the day
    is not over yet, which is how every streak tracker treats it.
    """
    if not days:
        return {"current": 0, "longest": 0, "total": 0,
                "current_from": "", "current_to": "",
                "longest_from": "", "longest_to": ""}

    ordered = sorted(days)
    total = sum(days.values())

    longest = run = 0
    run_start = longest_from = longest_to = ordered[0]
    for date in ordered:
        if days[date] > 0:
            if run == 0:
                run_start = date
            run += 1
            if run > longest:
                longest, longest_from, longest_to = run, run_start, date
        else:
            run = 0

    today = dt.date.today().isoformat()
    tail = [d for d in ordered if d <= today]
    if tail and days[tail[-1]] == 0 and tail[-1] == today:
        tail.pop()  # an empty today doesn't end the streak
    current = 0
    current_from = current_to = ""
    for date in reversed(tail):
        if days[date] > 0:
            current += 1
            current_from = date
            if not current_to:
                current_to = date
        else:
            break

    return {
        "current": current,
        "longest": longest,
        "total": total,
        "current_from": current_from,
        "current_to": current_to,
        "longest_from": longest_from,
        "longest_to": longest_to,
    }


def collect():
    stars = 0
    langs = {}
    colors = {}
    after = None
    user = None
    while True:
        user = graphql(PROFILE_QUERY, {"login": USER, "after": after})
        repos = user["repositories"]
        for node in repos["nodes"]:
            stars += node["stargazerCount"]
            for edge in node["languages"]["edges"]:
                name = edge["node"]["name"]
                langs[name] = langs.get(name, 0) + edge["size"]
                colors[name] = edge["node"]["color"] or RING
        if not repos["pageInfo"]["hasNextPage"]:
            break
        after = repos["pageInfo"]["endCursor"]

    c = user["contributionsCollection"]
    days = fetch_days(user["createdAt"])
    return {
        "stars": stars,
        "repos": user["repositories"]["totalCount"],
        "followers": user["followers"]["totalCount"],
        "commits": c["totalCommitContributions"] + c["restrictedContributionsCount"],
        "prs": c["totalPullRequestContributions"],
        "issues": c["totalIssueContributions"],
        "langs": langs,
        "colors": colors,
        "days": days,
        "streak": streaks(days),
    }


def human(n):
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M".replace(".0M", "M")
    if n >= 1_000:
        return f"{n / 1_000:.1f}k".replace(".0k", "k")
    return str(n)


def pretty(date):
    """Short enough to fit a side column: "Aug 4 '26"."""
    if not date:
        return ""
    d = dt.datetime.strptime(date, "%Y-%m-%d")
    return f"{d.strftime('%b')} {d.day} '{d.strftime('%y')}"


def frame(w, h, title, inner):
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img" aria-label="{escape(title)}">
  <defs>
    <linearGradient id="edge" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="{RING}"/><stop offset="55%" stop-color="{BORDER}"/><stop offset="100%" stop-color="{ACCENT}"/>
    </linearGradient>
    <radialGradient id="halo" cx="50%" cy="50%" r="50%">
      <stop offset="0%" stop-color="{TITLE}" stop-opacity=".22"/><stop offset="100%" stop-color="{TITLE}" stop-opacity="0"/>
    </radialGradient>
  </defs>
  <rect x=".75" y=".75" width="{w - 1.5}" height="{h - 1.5}" rx="10" fill="{BG}" stroke="url(#edge)" stroke-width="1.5"/>
  <circle cx="{w - 42}" cy="34" r="60" fill="url(#halo)"/>
  <text x="24" y="36" font-family={FONT!r} font-size="15" font-weight="700" fill="{TITLE}">{escape(title)}</text>
  <rect x="24" y="46" width="{w - 48}" height="1" fill="{BORDER}"/>
{inner}
</svg>
"""


def rinnegan(cx, cy, r, rings=4, clear=0):
    """Concentric ripple rings. `clear` keeps a radius free for text on top."""
    parts = [f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{RING}" fill-opacity=".10"/>']
    for i in range(rings):
        rr = r - i * (r / (rings + 0.6))
        if rr < clear:
            break
        parts.append(
            f'<circle cx="{cx}" cy="{cy}" r="{rr:.1f}" fill="none" stroke="{TITLE}" '
            f'stroke-opacity="{0.85 - i * 0.14:.2f}" stroke-width="1.6"/>'
        )
    if not clear:
        parts.append(f'<circle cx="{cx}" cy="{cy}" r="{r / 9:.1f}" fill="{BRIGHT}"/>')
    return "\n  ".join(parts)


def stats_card(d):
    w, h = 470, 205
    rows = [
        ("総星", "Total Stars", d["stars"]),
        ("巻物", "Repositories", d["repos"]),
        ("刻印", "Commits (yr)", d["commits"]),
        ("嘆願", "Pull Requests", d["prs"]),
        ("報告", "Issues", d["issues"]),
        ("信徒", "Followers", d["followers"]),
    ]
    out = [rinnegan(w - 74, 128, 46)]
    y = 74
    for kanji, label, value in rows:
        out.append(
            f'<text x="24" y="{y}" font-family={FONT!r} font-size="12" fill="{ACCENT}">{kanji}</text>'
            f'<text x="54" y="{y}" font-family={FONT!r} font-size="12" fill="{TEXT}">{label}</text>'
            f'<text x="300" y="{y}" text-anchor="end" font-family={FONT!r} font-size="13" '
            f'font-weight="700" fill="{BRIGHT}">{human(value)}</text>'
        )
        y += 21
    return frame(w, h, "輪廻眼 · Rinnegan Vision", "  " + "\n  ".join(out))


def streak_card(d):
    w, h = 470, 205
    s = d["streak"]
    ring_cy, ring_r = 112, 42
    out = [rinnegan(w / 2, ring_cy, ring_r, rings=5, clear=25)]

    def side(cx, kanji, label, value, sub):
        return (
            f'<text x="{cx}" y="100" text-anchor="middle" font-family={FONT!r} '
            f'font-size="21" font-weight="700" fill="{TEXT}">{escape(value)}</text>'
            f'<text x="{cx}" y="126" text-anchor="middle" font-family={FONT!r} '
            f'font-size="11.5" font-weight="700" fill="{TITLE}">{escape(kanji)} {escape(label)}</text>'
            f'<text x="{cx}" y="143" text-anchor="middle" font-family={FONT!r} '
            f'font-size="9.5" fill="#6E6E7E">{escape(sub)}</text>'
        )

    span_c = f"since {pretty(s['current_from'])}" if s["current"] else "the drought ends today"
    span_l = f"{pretty(s['longest_from'])} – {pretty(s['longest_to'])}" if s["longest"] else ""

    out.append(side(90, "総計", "Contributions", human(s["total"]), "all time"))
    out.append(side(w - 90, "最長", "Longest", str(s["longest"]), span_l))
    out.append(f'<rect x="180" y="70" width="1" height="96" fill="{BORDER}"/>')
    out.append(f'<rect x="{w - 180}" y="70" width="1" height="96" fill="{BORDER}"/>')

    # centred inside the ring, with its caption clear of the outer circle
    out.append(
        f'<text x="{w / 2}" y="{ring_cy + 11}" text-anchor="middle" font-family={FONT!r} '
        f'font-size="30" font-weight="700" fill="{BRIGHT}">{s["current"]}</text>'
        f'<text x="{w / 2}" y="{ring_cy + ring_r + 30}" text-anchor="middle" font-family={FONT!r} '
        f'font-size="11.5" font-weight="700" fill="{TITLE}">現在 Current Streak</text>'
        f'<text x="{w / 2}" y="{ring_cy + ring_r + 46}" text-anchor="middle" font-family={FONT!r} '
        f'font-size="9.5" fill="#6E6E7E">{escape(span_c)}</text>'
    )
    return frame(w, h, "連撃 · Unbroken Chain", "  " + "\n  ".join(out))


def langs_card(d):
    w = 470
    top = sorted(d["langs"].items(), key=lambda kv: -kv[1])[:6]
    total = sum(v for _, v in top) or 1
    h = 96 + ((len(top) + 1) // 2) * 20
    out = []

    x = 24.0
    bar_w = w - 48
    for name, size in top:
        seg = bar_w * size / total
        out.append(
            f'<rect x="{x:.2f}" y="66" width="{max(seg, 1):.2f}" height="9" rx="4.5" '
            f'fill="{d["colors"].get(name, RING)}"/>'
        )
        x += seg

    y = 104
    for i, (name, size) in enumerate(top):
        pct = 100 * size / total
        cx = 30 + (i % 2) * 224
        ty = y + (i // 2) * 20
        out.append(
            f'<circle cx="{cx}" cy="{ty - 4}" r="4.5" fill="{d["colors"].get(name, RING)}"/>'
            f'<text x="{cx + 13}" y="{ty}" font-family={FONT!r} font-size="11.5" fill="{TEXT}">'
            f'{escape(name)}</text>'
            f'<text x="{cx + 196}" y="{ty}" text-anchor="end" font-family={FONT!r} font-size="11.5" '
            f'font-weight="700" fill="{BRIGHT}">{pct:.1f}%</text>'
        )
    return frame(w, h, "忍具 · Arsenal Breakdown", "  " + "\n  ".join(out))


def calendar_card(d):
    """A 53-week contribution heatmap ending today."""
    cell, gap = 11, 2.6
    step = cell + gap
    weeks = 53
    left, top = 30, 78
    w = int(left * 2 + weeks * step)
    h = int(top + 7 * step + 46)

    today = dt.date.today()
    # start on the Sunday that opens the window
    end = today + dt.timedelta(days=(6 - today.weekday()) % 7)
    start = end - dt.timedelta(weeks=weeks - 1, days=6)

    counts = [d["days"].get((start + dt.timedelta(days=i)).isoformat(), 0)
              for i in range((end - start).days + 1)]
    peak = max(counts) if counts else 0

    def level(n):
        if n <= 0:
            return 0
        if peak <= 1:
            return 4
        return min(4, 1 + int(3 * (n - 1) / max(peak - 1, 1)))

    out = []
    months = []
    for wi in range(weeks):
        for di in range(7):
            day = start + dt.timedelta(weeks=wi, days=di)
            if day > today:
                continue
            n = d["days"].get(day.isoformat(), 0)
            x = left + wi * step
            y = top + di * step
            out.append(
                f'<rect x="{x:.1f}" y="{y:.1f}" width="{cell}" height="{cell}" rx="2.4" '
                f'fill="{HEAT[level(n)]}"><title>{day.isoformat()}: {n}</title></rect>'
            )
            if di == 0 and day.day <= 7:
                months.append((x, day.strftime("%b")))

    for x, label in months:
        out.append(
            f'<text x="{x:.1f}" y="{top - 8}" font-family={FONT!r} font-size="9.5" '
            f'fill="#6E6E7E">{label}</text>'
        )

    legend_x = w - left - 5 * step - 46
    legend_y = h - 24
    out.append(
        f'<text x="{legend_x - 8}" y="{legend_y + 9}" text-anchor="end" font-family={FONT!r} '
        f'font-size="9.5" fill="#6E6E7E">quiet</text>'
    )
    for i, colour in enumerate(HEAT):
        out.append(
            f'<rect x="{legend_x + i * step:.1f}" y="{legend_y}" width="{cell}" height="{cell}" '
            f'rx="2.4" fill="{colour}"/>'
        )
    out.append(
        f'<text x="{legend_x + 5 * step + 4:.1f}" y="{legend_y + 9}" font-family={FONT!r} '
        f'font-size="9.5" fill="#6E6E7E">pain</text>'
    )

    year = sum(counts)
    out.append(
        f'<text x="{w - left}" y="36" text-anchor="end" font-family={FONT!r} font-size="11.5" '
        f'fill="{TEXT}">{human(year)} contributions this year</text>'
    )
    return frame(w, h, "天照 · One Year of Rain", "  " + "\n  ".join(out))


def placeholder(title, w, h, note):
    inner = (
        f'  {rinnegan(w // 2, h // 2 + 16, 34)}\n'
        f'  <text x="{w // 2}" y="{h - 26}" text-anchor="middle" font-family={FONT!r} '
        f'font-size="11.5" fill="{TEXT}">{escape(note)}</text>'
    )
    return frame(w, h, title, inner)


CARDS = [
    ("stats.svg", "輪廻眼 · Rinnegan Vision", 470, 205, stats_card),
    ("streak.svg", "連撃 · Unbroken Chain", 470, 205, streak_card),
    ("langs.svg", "忍具 · Arsenal Breakdown", 470, 156, langs_card),
    ("calendar.svg", "天照 · One Year of Rain", 780, 219, calendar_card),
]


def write(name, svg):
    path = os.path.normpath(os.path.join(OUT, name))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(svg)
    print(f"wrote {path} ({len(svg)} bytes)")


def write_placeholders():
    note = "gathering chakra — refreshes on the next scheduled run"
    for name, title, w, h, _ in CARDS:
        write(name, placeholder(title, w, h, note))


def main():
    if not TOKEN:
        print("no token available; writing placeholders", file=sys.stderr)
        write_placeholders()
        return 0
    try:
        d = collect()
    except (urllib.error.URLError, RuntimeError, KeyError, ValueError) as exc:
        print(f"stat fetch failed: {exc}", file=sys.stderr)
        write_placeholders()
        return 0
    for name, _, _, _, render in CARDS:
        write(name, render(d))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
