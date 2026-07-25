"""GitHub API data fetching using gh CLI."""

import json
import subprocess
from pathlib import Path


def _gh_api(endpoint: str) -> dict | list | None:
    """Call gh api and return parsed JSON."""
    try:
        result = subprocess.run(
            ["gh", "api", endpoint],
            capture_output=True, text=True, timeout=30,
            encoding="utf-8", errors="replace",
        )
        if result.returncode != 0:
            print(f"WARNING: gh api {endpoint} failed: {result.stderr}")
            return None
        return json.loads(result.stdout)
    except Exception as e:
        print(f"WARNING: gh api {endpoint} error: {e}")
        return None


def _gh_graphql(query: str) -> dict | None:
    """Call gh api graphql and return parsed JSON."""
    try:
        result = subprocess.run(
            ["gh", "api", "graphql", "-f", f"query={query}"],
            capture_output=True, text=True, timeout=30,
            encoding="utf-8", errors="replace",
        )
        if result.returncode != 0:
            print(f"WARNING: graphql failed: {result.stderr}")
            return None
        return json.loads(result.stdout)
    except Exception as e:
        print(f"WARNING: graphql error: {e}")
        return None


USER_QUERY = """
{
  user(login: "jieefeng") {
    repositories(privacy: PUBLIC, first: 1) { totalCount }
    followers(first: 1) { totalCount }
    starredRepositories { totalCount }
    contributionsCollection {
      totalCommitContributions
      totalPullRequestContributions
      totalIssueContributions
      contributionCalendar {
        totalContributions
        weeks {
          contributionDays {
            contributionCount
            date
          }
        }
      }
    }
    pullRequests(first: 1) { totalCount }
    issues(first: 1) { totalCount }
    pinnedItems(first: 6, types: [REPOSITORY]) {
      nodes {
        ... on Repository {
          name
          description
          stargazerCount
          primaryLanguage {
            name
            color
          }
          url
          isFork
        }
      }
    }
  }
}
"""


def fetch_user_data() -> dict:
    """Fetch all user data in a single GraphQL query."""
    result = _gh_graphql(USER_QUERY)
    if not result or "data" not in result:
        return _fallback_data()

    user = result["data"].get("user")
    if not user:
        return _fallback_data()

    # Calculate streak
    weeks = user["contributionsCollection"]["contributionCalendar"]["weeks"]
    days = []
    for week in weeks:
        for day in week["contributionDays"]:
            days.append(day)

    current_streak = 0
    max_streak = 0
    streak = 0
    temp_streak = 0

    # Iterate from most recent to oldest
    for day in reversed(days):
        if day["contributionCount"] > 0:
            temp_streak += 1
            if temp_streak > max_streak:
                max_streak = temp_streak
        else:
            if streak == 0:
                streak = temp_streak
            temp_streak = 0
    if streak == 0:
        streak = temp_streak

    # Fetch languages
    langs = _fetch_languages()

    # Fetch views
    views = _fetch_views()

    return {
        "repos": user.get("repositories", {}).get("totalCount", 0),
        "followers": user.get("followers", {}).get("totalCount", 0),
        "stars": user.get("starredRepositories", {}).get("totalCount", 0),
        "commits": user["contributionsCollection"].get("totalCommitContributions", 0),
        "prs": user["contributionsCollection"].get("totalPullRequestContributions", 0),
        "issues": user["contributionsCollection"].get("totalIssueContributions", 0),
        "total_contribs": user["contributionsCollection"]["contributionCalendar"].get("totalContributions", 0),
        "total_prs": user.get("pullRequests", {}).get("totalCount", 0),
        "total_issues": user.get("issues", {}).get("totalCount", 0),
        "streak": streak,
        "max_streak": max_streak,
        "contribution_days": days,
        "languages": langs,
        "views": views,
        "pinned_repos": [
            {
                "name": repo["name"],
                "description": repo.get("description") or "",
                "stars": repo.get("stargazerCount", 0),
                "language": repo.get("primaryLanguage", {}),
                "url": repo.get("url", ""),
                "fork": repo.get("isFork", False),
            }
            for repo in (user.get("pinnedItems", {}).get("nodes") or [])
            if repo and not repo.get("isFork")
        ],
    }


def _fetch_languages() -> list[dict]:
    """Fetch and aggregate language data from user repos."""
    repos_json = _gh_api("users/jieefeng/repos?per_page=100&sort=updated")
    if not repos_json:
        return []

    lang_totals: dict[str, int] = {}
    for repo in repos_json:
        if repo.get("fork"):
            continue
        repo_langs = _gh_api(f"repos/{repo['full_name']}/languages")
        if repo_langs and isinstance(repo_langs, dict):
            for lang, bytes_count in repo_langs.items():
                lang_totals[lang] = lang_totals.get(lang, 0) + bytes_count

    # Sort by bytes, top 6
    sorted_langs = sorted(lang_totals.items(), key=lambda x: x[1], reverse=True)[:6]
    total_bytes = sum(b for _, b in sorted_langs) or 1

    LANG_COLORS = {
        "Python": "#3572A5", "Java": "#B07219", "JavaScript": "#F1E05A",
        "TypeScript": "#3178C6", "Vue": "#41B883", "HTML": "#E34C26",
        "CSS": "#563D7C", "Shell": "#89E051", "Go": "#00ADD8",
        "C": "#555555", "C++": "#F34B7D", "Rust": "#DEA584",
        "Kotlin": "#A97BFF", "Swift": "#F05138", "Dart": "#00B4AB",
        "Ruby": "#701516", "PHP": "#4F5D95", "Lua": "#000080",
        "Jupyter Notebook": "#DA5B0B", "Makefile": "#427819",
    }

    return [
        {
            "name": name,
            "bytes": bytes_count,
            "percent": round(bytes_count * 100 / total_bytes, 1),
            "color": LANG_COLORS.get(name, "#8B949E"),
        }
        for name, bytes_count in sorted_langs
    ]


def _fetch_views() -> int:
    """Fetch profile view count from komarev API."""
    try:
        result = subprocess.run(
            ["curl", "-sf", "--max-time", "15", "--retry", "3", "--retry-delay", "5",
             "https://komarev.com/ghpvc/?username=jieefeng&color=blue&style=flat"],
            capture_output=True, text=True, timeout=20,
            encoding="utf-8", errors="replace",
        )
        if result.returncode != 0 or not result.stdout:
            return 0
        import re
        match = re.findall(r'(\d+)</text>', result.stdout)
        if match:
            return int(match[-1])
    except Exception as e:
        print(f"WARNING: views fetch error: {e}")
    return 0


def _fallback_data() -> dict:
    """Return fallback data when API fails."""
    return {
        "repos": 0, "followers": 0, "stars": 0,
        "commits": 0, "prs": 0, "issues": 0,
        "total_contribs": 0, "total_prs": 0, "total_issues": 0,
        "streak": 0, "max_streak": 0,
        "contribution_days": [], "languages": [], "views": 0,
        "pinned_repos": [],
    }
