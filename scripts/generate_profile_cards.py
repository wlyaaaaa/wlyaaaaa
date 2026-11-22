"""Generate the profile cards from GitHub's public profile and repository data."""

from collections import Counter
from html import escape
import json
import os
from pathlib import Path
import sys
from urllib.request import Request, urlopen

from generate_snake import fetch_calendar, parse_calendar


REPOSITORIES = """query($login: String!, $cursor: String) {
  user(login: $login) {
    repositories(first: 50, after: $cursor, privacy: PUBLIC, isFork: false,
                 ownerAffiliations: [OWNER]) {
      pageInfo { hasNextPage endCursor }
      totalCount
      nodes {
        stargazerCount forkCount
        languages(first: 100) { edges { size node { name color } } }
      }
    }
  }
}"""
GREEN = "#00A650"
THEMES = {"": ("#ffffff", "#24292f", "#d0d7de"),
          "-dark": ("#0d1117", "#e6edf3", "#30363d")}
ICONS = (
    "M2 8h3l2-5 3 10 2-5h2",
    "M8 2l1.9 3.9 4.3.6-3.1 3 .7 4.3-3.8-2-3.8 2 .7-4.3-3.1-3 4.3-.6z",
    "M3 3h10v10H3z M6 3v10",
    "M4 2v3a4 4 0 0 0 8 0V2 M8 9v5 M2 2h4 M10 2h4",
)


def repository_totals(login, token):
    totals, colors = Counter(), {}
    stars = forks = 0
    cursor = None
    while True:
        request = Request(
            "https://api.github.com/graphql",
            data=json.dumps({"query": REPOSITORIES, "variables": {
                "login": login, "cursor": cursor,
            }}).encode(),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                     "User-Agent": "github-profile-cards"},
        )
        with urlopen(request, timeout=45) as response:
            payload = json.load(response)
        if payload.get("errors"):
            raise ValueError("GitHub GraphQL could not read public repositories")
        repositories = payload["data"]["user"]["repositories"]
        for repo in repositories["nodes"]:
            stars += repo["stargazerCount"]
            forks += repo["forkCount"]
            for edge in (repo["languages"] or {}).get("edges") or []:
                name = edge["node"]["name"]
                totals[name] += edge["size"]
                colors[name] = edge["node"]["color"] or "#8b949e"
        page = repositories["pageInfo"]
        if not page["hasNextPage"]:
            return repositories["totalCount"], stars, forks, totals, colors
        cursor = page["endCursor"]


def card(title, theme, body):
    background, foreground, border = theme
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="390" height="155" viewBox="0 0 390 155" role="img" aria-labelledby="title">
<title id="title">{title}</title>
<rect x=".5" y=".5" width="389" height="154" rx="8" fill="{background}" stroke="{border}"/>
<g font-family="-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif" fill="{foreground}" font-size="13">
<text x="22" y="32" fill="{GREEN}" font-size="19" font-weight="700">{title}</text>
{body}
</g>
</svg>
"""


def stats_card(contributions, repositories, stars, forks, theme):
    rows = (("Contributions (Past Year)", contributions), ("Public Stars", stars),
            ("Public Repositories", repositories), ("Public Forks", forks))
    body = []
    for index, ((label, value), icon) in enumerate(zip(rows, ICONS)):
        y = 59 + 24 * index
        body.append(f'<path transform="translate(22 {y - 12})" d="{icon}" fill="none" '
                    f'stroke="{GREEN}" stroke-width="1.5" stroke-linejoin="round"/>'
                    f'<text x="48" y="{y}">{label}</text>'
                    f'<text x="368" y="{y}" text-anchor="end" font-weight="600">{value:,}</text>')
    return card("GitHub Stats", theme, "\n".join(body))


def languages_card(totals, colors, theme):
    total = totals.total()
    if not total:
        return card("Top Languages", theme, '<text x="22" y="64">No public language data</text>')
    languages = [(name, size, colors[name]) for name, size in totals.most_common(6)]
    if len(totals) > 6:
        remaining = total - sum(size for _, size, _ in languages[:5])
        languages[5] = ("Other", remaining, "#8b949e")
    position, body = 22.0, []
    for index, (name, size, color) in enumerate(languages):
        share = size / total
        width = 346 * share
        x, y = 22 + 173 * (index % 2), 84 + 22 * (index // 2)
        body.append(f'<rect x="{position:.4f}" y="47" width="{width:.4f}" height="9" fill="{color}"/>'
                    f'<circle cx="{x + 4}" cy="{y - 4}" r="4" fill="{color}"/>'
                    f'<text x="{x + 15}" y="{y}">{escape(name)} {share:.1%}</text>')
        position += width
    return card("Top Languages", theme, "\n".join(body))


if __name__ == "__main__":
    login, directory = sys.argv[1:]
    token = os.environ["GITHUB_TOKEN"]
    calendar = parse_calendar(fetch_calendar(login, token))
    contributions = sum(day.count for day in calendar.days)
    repositories, stars, forks, totals, colors = repository_totals(login, token)
    output = Path(directory)
    output.mkdir(parents=True, exist_ok=True)
    for suffix, theme in THEMES.items():
        (output / f"profile-stats{suffix}.svg").write_text(
            stats_card(contributions, repositories, stars, forks, theme), encoding="utf-8")
        (output / f"profile-languages{suffix}.svg").write_text(
            languages_card(totals, colors, theme), encoding="utf-8")
