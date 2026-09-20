"""Fetch GitHub contribution data via the gh CLI (GraphQL).

The script only needs what the cards actually render: the contribution
calendar. Everything is fetched in one GraphQL call per token attempt —
no per-repo follow-up requests.

Token resolution: PAT_TOKEN first (a classic PAT with repo scope also
counts private contributions); if it is rejected we retry with
GH_TOKEN/GITHUB_TOKEN (public contributions only) instead of failing.
"""

from __future__ import annotations

import json
import os
import shutil
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


def _parse_calendar(payload: dict) -> dict:
    user = (payload.get("data") or {}).get("user")
    if not user:
        raise ValueError(f"unexpected GraphQL response: {payload}")

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


def _try_graphql(token: str) -> dict:
    """One authenticated GraphQL attempt. Raises on any failure."""
    env = dict(os.environ)
    env["GH_TOKEN"] = token  # override any ambient GH_TOKEN (incl. the other candidate)

    result = subprocess.run(
        ["gh", "api", "graphql", "-f", f"query={USER_QUERY}"],
        capture_output=True, text=True, timeout=60,
        encoding="utf-8", errors="replace",
        env=env,
    )
    if result.returncode != 0:
        raise RuntimeError(f"gh api graphql failed: {result.stderr.strip()}")

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"invalid JSON from gh api: {exc}") from exc

    return _parse_calendar(payload)


def fetch_user_data() -> dict | None:
    """Fetch the contribution calendar; return None when every token fails.

    Returning None (instead of zeroed fallback data) lets generate_cards.py
    fail closed and keep the last good SVGs on disk.
    """
    if shutil.which("gh") is None:
        print("ERROR: gh CLI not found on PATH; install it or run `gh auth login`.")
        return None

    # PAT first (private contributions), then the workflow's GITHUB_TOKEN.
    candidates: list[tuple[str, str]] = []
    pat = os.environ.get("PAT_TOKEN", "").strip()
    gh_token = os.environ.get("GH_TOKEN", "").strip()
    if pat:
        candidates.append(("PAT_TOKEN", pat))
    if gh_token and gh_token != pat:
        candidates.append(("GH_TOKEN", gh_token))
    if not candidates:
        print("ERROR: no token available (set PAT_TOKEN or GH_TOKEN, or `gh auth login`).")
        return None

    data: dict | None = None
    for label, token in candidates:
        try:
            data = _try_graphql(token)
        except Exception as exc:
            print(f"WARNING: {label} attempt failed: {exc}")
            data = None
        if data is not None:
            if len(candidates) > 1:
                print(f"  using {label} for this run")
            return data

    print("ERROR: all token candidates failed; keeping existing SVGs untouched.")
    return None
