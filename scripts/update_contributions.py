#!/usr/bin/env python3
"""Publish verified, public, merged pull requests to the profile and archive."""

import argparse
from collections import defaultdict
from datetime import datetime
import html
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib import error, parse, request

ROOT = Path(__file__).resolve().parents[1]
START = "<!-- CONTRIBUTIONS:START -->"
END = "<!-- CONTRIBUTIONS:END -->"
QUERY = """
query($login: String!, $cursor: String) {
  user(login: $login) {
    pullRequests(first: 100, after: $cursor, states: MERGED,
                 orderBy: {field: CREATED_AT, direction: DESC}) {
      nodes {
        number title url mergedAt author { login }
        repository {
          nameWithOwner url isPrivate isFork owner { login } description
        }
      }
      pageInfo { hasNextPage endCursor }
    }
  }
}
"""


def github_graphql(query, variables):
    payload = json.dumps({"query": query, "variables": variables}).encode()
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token:
        req = request.Request(
            "https://api.github.com/graphql",
            data=payload,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "User-Agent": "profile-contributions",
            },
        )
        try:
            with request.urlopen(req, timeout=60) as response:
                result = json.load(response)
        except error.HTTPError as exc:
            raise RuntimeError(f"GitHub returned HTTP {exc.code}; existing files are unchanged.") from exc
    else:
        result = json.loads(subprocess.check_output(
            ["gh", "api", "graphql", "--input", "-"], input=payload,
        ))
    if result.get("errors"):
        raise RuntimeError("GitHub returned GraphQL errors; existing files are unchanged.")
    return result


def public_contribution(node, username):
    repo = node["repository"]
    if (repo["isPrivate"] or repo["isFork"]
            or repo["owner"]["login"].casefold() == username.casefold()
            or (node.get("author") or {}).get("login", "").casefold() != username.casefold()
            or not node.get("mergedAt")):
        return None
    name = repo["nameWithOwner"]
    number = node["number"]
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", name):
        raise ValueError("Unexpected repository name")
    if type(number) is not int or number < 1:
        raise ValueError("Unexpected pull request number")
    expected = f"https://github.com/{name}"
    if repo["url"] != expected or node["url"] != f"{expected}/pull/{number}":
        raise ValueError("Unexpected contribution URL")
    datetime.fromisoformat(node["mergedAt"].replace("Z", "+00:00"))
    # Only this allowlist is ever written. Raw responses may include private data.
    return {
        "repository": name,
        "repository_url": expected,
        "description": repo.get("description") or "",
        "number": number,
        "title": node["title"],
        "url": node["url"],
        "merged_at": node["mergedAt"],
    }


def fetch_contributions(username, api=github_graphql):
    cursor = None
    seen_cursors = set()
    contributions = {}
    while True:
        response = api(QUERY, {"login": username, "cursor": cursor})
        if response.get("errors"):
            raise RuntimeError("Incomplete GitHub response; refusing to publish it.")
        connection = response["data"]["user"]["pullRequests"]
        for node in connection["nodes"]:
            record = public_contribution(node, username)
            if record:
                contributions[record["url"]] = record
        page = connection["pageInfo"]
        if not page["hasNextPage"]:
            break
        cursor = page["endCursor"]
        if not cursor or cursor in seen_cursors:
            raise RuntimeError("Invalid pagination; refusing to publish an incomplete list.")
        seen_cursors.add(cursor)
    return sorted(contributions.values(), key=lambda item: (item["merged_at"], item["url"]), reverse=True)


def escaped(value):
    return html.escape(" ".join(str(value).split()), quote=True)


def date_label(timestamp):
    return datetime.fromisoformat(timestamp.replace("Z", "+00:00")).strftime("%d %b %Y")


def groups(records):
    result = defaultdict(list)
    for item in records:
        result[item["repository"]].append(item)
    for items in result.values():
        items.sort(key=lambda item: (item["merged_at"], item["url"]), reverse=True)
    return sorted(result.items(), key=lambda pair: (pair[1][0]["merged_at"], pair[0]), reverse=True)


def render_profile(records, config):
    if not records:
        return "Public contributions will appear here when a pull request is merged upstream."
    lines = []
    for name, items in groups(records):
        curated = config.get("repositories", {}).get(name, {})
        title = curated.get("name", name.split("/", 1)[1])
        description = curated.get("description", items[0]["description"])
        latest = items[0]
        summary = curated.get("summaries", {}).get(str(latest["number"]), latest["title"])
        count = len(items)
        label = "merged contribution" if count == 1 else "merged contributions"
        lines.extend([
            '<table width="100%">',
            '<tr><td>',
            f'<sub>{escaped(name.split("/", 1)[0])}</sub>',
            f'<h3><a href="{escaped(latest["repository_url"])}">{escaped(title)}</a></h3>',
            f'<p>{escaped(description)}</p>' if description else "",
            f'<p>{escaped(summary)}</p>',
            f'<p><a href="{escaped(latest["url"])}">PR #{latest["number"]}</a>'
            f' &nbsp;·&nbsp; Merged {date_label(latest["merged_at"])}'
            f' &nbsp;·&nbsp; {count} {label}</p>',
            '</td></tr>',
            '</table>',
            '',
        ])
    url = f'https://github.com/{config["username"]}/{config["username"]}/blob/main/CONTRIBUTIONS.md'
    lines.append(f'<p><a href="{url}">View the full contribution log →</a></p>')
    return "\n".join(lines).strip()


def render_archive(records, config):
    lines = [
        "# Open-source contributions", "",
        "Public pull requests authored by Avaivartika and merged into projects maintained by others.",
        "Each entry links to the upstream review and merge record. Dates are shown in UTC.", "",
        f'[← Back to profile](https://github.com/{config["username"]})', "",
    ]
    if not records:
        lines.append("No merged public contributions yet.")
    for name, items in groups(records):
        curated = config.get("repositories", {}).get(name, {})
        lines.extend([f'## [{name}]({items[0]["repository_url"]})', ""])
        for item in items:
            summary = curated.get("summaries", {}).get(str(item["number"]), item["title"])
            lines.extend([
                f'<p><strong><a href="{escaped(item["url"])}">#{item["number"]}'
                f' · {escaped(item["title"])}</a></strong><br>',
                f'<sub>Merged {date_label(item["merged_at"])}</sub></p>',
                f'<p>{escaped(summary)}</p>', "",
            ])
    return "\n".join(lines).rstrip() + "\n"


def replace_section(readme, content):
    if readme.count(START) != 1 or readme.count(END) != 1:
        raise ValueError("README must contain exactly one contribution section.")
    before, remaining = readme.split(START)
    _, after = remaining.split(END)
    return before + START + "\n\n" + content + "\n\n" + END + after


def build_outputs(root, records, config, allow_removals=False):
    snapshot = root / "data/contributions.json"
    if snapshot.exists() and not allow_removals:
        previous = json.loads(snapshot.read_text(encoding="utf-8"))["contributions"]
        missing = {item["url"] for item in previous} - {item["url"] for item in records}
        if missing:
            raise RuntimeError("Previously recorded contributions disappeared. Check access or visibility, then rerun with --allow-removals if intentional.")
    data = {"schema_version": 1, "username": config["username"], "contributions": records}
    return {
        root / "README.md": replace_section((root / "README.md").read_text(encoding="utf-8"), render_profile(records, config)),
        root / "CONTRIBUTIONS.md": render_archive(records, config),
        snapshot: json.dumps(data, ensure_ascii=False, indent=2) + "\n",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Exit with 1 if generated files need updating.")
    parser.add_argument("--offline", action="store_true", help="Render the already verified public snapshot without a network request.")
    parser.add_argument("--allow-removals", action="store_true", help="Accept confirmed upstream removals or visibility changes.")
    args = parser.parse_args()
    config = json.loads((ROOT / "profile.json").read_text(encoding="utf-8"))
    records = (json.loads((ROOT / "data/contributions.json").read_text(encoding="utf-8"))["contributions"]
               if args.offline else fetch_contributions(config["username"]))
    outputs = build_outputs(ROOT, records, config, args.allow_removals)
    changed = []
    for path, content in outputs.items():
        if not path.exists() or path.read_text(encoding="utf-8") != content:
            changed.append(str(path.relative_to(ROOT)))
            if not args.check:
                path.parent.mkdir(parents=True, exist_ok=True)
                temporary = path.with_suffix(path.suffix + ".tmp")
                temporary.write_text(content, encoding="utf-8")
                temporary.replace(path)
    print(f"Verified {len(records)} merged PRs across {len(groups(records))} public projects.")
    print("Updated " + ", ".join(changed) if changed else "Already up to date.")
    return 1 if args.check and changed else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RuntimeError, ValueError, KeyError, OSError, subprocess.CalledProcessError) as exc:
        print(f"Update failed: {exc}", file=sys.stderr)
        sys.exit(1)
