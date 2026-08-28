#!/usr/bin/env python3
"""Render the Rinnegan-themed stat cards used by the profile README.

Reads live numbers from the GitHub GraphQL API and writes two self-hosted SVGs
into assets/, so the README never depends on a third-party stats service.

Env:
  STATS_TOKEN  token used for the API call (a PAT with read:user + repo also
               counts private repositories; the default GITHUB_TOKEN sees
               public ones only)
  STATS_USER   login to render (default: FayzSa)
"""

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

QUERY = """
query($login: String!, $after: String) {
  user(login: $login) {
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


def graphql(after=None):
    body = json.dumps({"query": QUERY, "variables": {"login": USER, "after": after}})
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


def collect():
    stars = 0
    langs = {}
    colors = {}
    after = None
    user = None
    while True:
        user = graphql(after)
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
    return {
        "stars": stars,
        "repos": user["repositories"]["totalCount"],
        "followers": user["followers"]["totalCount"],
        "commits": c["totalCommitContributions"] + c["restrictedContributionsCount"],
        "prs": c["totalPullRequestContributions"],
        "issues": c["totalIssueContributions"],
        "langs": langs,
        "colors": colors,
    }


def human(n):
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M".replace(".0M", "M")
    if n >= 1_000:
        return f"{n / 1_000:.1f}k".replace(".0k", "k")
    return str(n)


FONT = ("'JetBrains Mono','SFMono-Regular',Consolas,'Noto Sans CJK JP',"
        "'Hiragino Sans','Yu Gothic',Meiryo,monospace")


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


def rinnegan(cx, cy, r):
    parts = [f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{RING}" fill-opacity=".10"/>']
    for i in range(4):
        rr = r - i * (r / 4.6)
        parts.append(
            f'<circle cx="{cx}" cy="{cy}" r="{rr:.1f}" fill="none" stroke="{TITLE}" '
            f'stroke-opacity="{0.85 - i * 0.14:.2f}" stroke-width="1.6"/>'
        )
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
        col = i % 2
        cx = 30 + col * 224
        ty = y + (i // 2) * 20
        out.append(
            f'<circle cx="{cx}" cy="{ty - 4}" r="4.5" fill="{d["colors"].get(name, RING)}"/>'
            f'<text x="{cx + 13}" y="{ty}" font-family={FONT!r} font-size="11.5" fill="{TEXT}">'
            f'{escape(name)}</text>'
            f'<text x="{cx + 196}" y="{ty}" text-anchor="end" font-family={FONT!r} font-size="11.5" '
            f'font-weight="700" fill="{BRIGHT}">{pct:.1f}%</text>'
        )
    return frame(w, h, "忍具 · Arsenal Breakdown", "  " + "\n  ".join(out))


def placeholder(title, w, h, note):
    inner = (
        f'  {rinnegan(w // 2, h // 2 + 16, 34)}\n'
        f'  <text x="{w // 2}" y="{h - 26}" text-anchor="middle" font-family={FONT!r} '
        f'font-size="11.5" fill="{TEXT}">{escape(note)}</text>'
    )
    return frame(w, h, title, inner)


def write(name, svg):
    path = os.path.normpath(os.path.join(OUT, name))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(svg)
    print(f"wrote {path} ({len(svg)} bytes)")


def main():
    note = "gathering chakra — refreshes on the next scheduled run"
    if not TOKEN:
        print("no token available; writing placeholders", file=sys.stderr)
        write("stats.svg", placeholder("輪廻眼 · Rinnegan Vision", 470, 205, note))
        write("langs.svg", placeholder("忍具 · Arsenal Breakdown", 470, 156, note))
        return 0
    try:
        d = collect()
    except (urllib.error.URLError, RuntimeError, KeyError) as exc:
        print(f"stat fetch failed: {exc}", file=sys.stderr)
        write("stats.svg", placeholder("輪廻眼 · Rinnegan Vision", 470, 205, note))
        write("langs.svg", placeholder("忍具 · Arsenal Breakdown", 470, 156, note))
        return 0
    write("stats.svg", stats_card(d))
    write("langs.svg", langs_card(d))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
