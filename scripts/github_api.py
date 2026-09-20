"""Fetch GitHub contribution data via the gh CLI (GraphQL).

The script only needs what the cards actually render: the contribution
calendar. Everything is fetched in a single GraphQL call — no per-repo
follow-up requests.
"""

import json
import subprocess

LOGIN = "jieefeng"

USER_QUERY = """
{
  user(login: "%s") {
    contributionsCollection(includePrivateContributions: true) {
      totalCommitContributions
      contributionCalendar {
        totalContributions
        weeks {
          contributionDays {
            date
            contributionCount
          }
        }
      }
    }
  }
}
""" % LOGIN


def compute_streaks(days: list[dict]) -> tuple[int, int]:
    """Return (current_streak, longest_streak) for contribution days (old -> new).

    Grace rule: if *today* has no contribution yet, it must not break an
    otherwise ongoing streak — so today is excluded from the current-streak
    walk (but still counts toward the longest streak).
    """
    counts = [d["contributionCount"] for d in days]

    longest = run = 0
    for c in counts:
        run = run + 1 if c > 0 else 0
        longest = max(longest, run)

    seq = counts[:-1] if counts and counts[-1] == 0 else counts
    current = 0
    for c in reversed(seq):
        if c > 0:
            current += 1
        else:
            break
    return current, longest


def fetch_user_data() -> dict | None:
    """Fetch the contribution calendar; return None when anything fails.

    Returning None (instead of zeroed fallback data) lets generate_cards.py
    fail closed and keep the last good SVGs on disk.
    """
    try:
        result = subprocess.run(
            ["gh", "api", "graphql", "-f", f"query={USER_QUERY}"],
            capture_output=True, text=True, timeout=60,
            encoding="utf-8", errors="replace",
        )
    except Exception as exc:
        print(f"WARNING: gh api graphql error: {exc}")
        return None
    if result.returncode != 0:
        print(f"WARNING: gh api graphql failed: {result.stderr.strip()}")
        return None

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        print(f"WARNING: invalid JSON from gh api: {exc}")
        return None

    user = (payload.get("data") or {}).get("user")
    if not user:
        print(f"WARNING: unexpected GraphQL response: {payload}")
        return None

    coll = user["contributionsCollection"]
    calendar = coll["contributionCalendar"]
    days = [d for w in calendar["weeks"] for d in w["contributionDays"]]
    current, longest = compute_streaks(days)

    return {
        "total_contribs": calendar.get(
            "totalContributions", sum(d["contributionCount"] for d in days)
        ),
        "commits": coll.get("totalCommitContributions", 0),
        "streak": current,
        "max_streak": longest,
        "contribution_days": days,
    }
