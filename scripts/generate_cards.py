"""Generate all SVG cards from Jinja2 templates.

Usage:
    python scripts/generate_cards.py              # real data -> assets/
    python scripts/generate_cards.py --mock       # deterministic sample data
    python scripts/generate_cards.py --out DIR    # write cards to DIR instead

The script fails closed: if GitHub data cannot be fetched it exits non-zero
and leaves the previously generated SVGs untouched, so the workflow never
overwrites good cards with empty ones.
"""

from __future__ import annotations

import argparse
import random
import sys
from datetime import date, timedelta
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from github_api import compute_streaks, fetch_user_data

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = ROOT / "templates"
DEFAULT_OUT = ROOT / "assets"

# ---------------------------------------------------------------------------
# Typing animation — presentation lives in templates/typing.svg.j2, all
# timing/geometry math is precomputed here into SMIL keyframes.
# ---------------------------------------------------------------------------

TYPING_LINES = [
    "AI 工程师 | RAG 探索者",
    "全栈开发 | 后端架构师",
    "Always building, always learning",
]

TYPE_SEC_PER_CHAR = 0.10    # reveal one character
HOLD_SEC = 1.6              # pause with the full line visible
DELETE_SEC_PER_CHAR = 0.04  # erase one character
MIN_TYPE_SEC = 0.8
MIN_DELETE_SEC = 0.35

FONT_SIZE = 14
LATIN_W = FONT_SIZE * 0.60  # monospace advance (Consolas/most coding fonts)
CJK_W = FONT_SIZE * 1.00    # fullwidth advance (Sans CJK: YaHei/PingFang)
CARD_W = 500


def _is_cjk(ch: str) -> bool:
    return ord(ch) >= 0x2E80  # CJK blocks & fullwidth forms


def _text_width(text: str) -> int:
    return round(sum(CJK_W if _is_cjk(ch) else LATIN_W for ch in text))


def _keyframes(frames: list[tuple[float, float]], total: float) -> tuple[str, str]:
    """Convert absolute (value, time) frames to SMIL values/keyTimes strings.

    Times are normalized to [0, 1] and rounded to 4 decimals; rounding
    collisions are broken by nudging (sub-2 ms, invisible), and the final
    frame is pinned to exactly 1.0 so every SMIL renderer treats the cycle
    deterministically.
    """
    out: list[tuple[float, float]] = []
    for value, t in frames:
        k = round(min(t / total, 1.0), 4)
        if out and k <= out[-1][1]:
            k = out[-1][1] + 0.0001
        out.append((value, min(k, 1.0)))
    out[-1] = (out[-1][0], 1.0)
    if len(out) > 1 and out[-1][1] <= out[-2][1]:
        out.pop(-2)  # a shadowed predecessor right at the cycle end
    values = ";".join(f"{v:.2f}" for v, _ in out)
    keys = ";".join(f"{k:.4f}" for _, k in out)
    return values, keys


def _typing_context(lines: list[str]) -> dict:
    """Precompute SMIL keyframes for one full typewriter cycle over `lines`."""
    phases = []
    cursor = 0.0
    for text in lines:
        n = max(len(text), 1)
        t_type = max(MIN_TYPE_SEC, TYPE_SEC_PER_CHAR * n)
        t_del = max(MIN_DELETE_SEC, DELETE_SEC_PER_CHAR * n)
        phases.append((cursor, t_type, HOLD_SEC, t_del))
        cursor += t_type + HOLD_SEC + t_del
    total = cursor

    lines_ctx = []
    caret: list[tuple[float, float]] = []

    for i, (text, (start, t_type, t_hold, t_del)) in enumerate(zip(lines, phases)):
        n = max(len(text), 1)
        w = max(_text_width(text), 1)
        x0 = (CARD_W - w) / 2

        # Reveal width: 0 -> w char by char, hold, then w -> 0.
        # Every line's timeline starts with an explicit 0-width frame at
        # t=0: SMIL requires keyTimes[0] == 0 (violating it makes strict
        # renderers drop the animation, leaving the rect at full static
        # width), and a static width of 0 keeps hidden lines invisible in
        # renderers with no SMIL at all. Visibility is clip-only, so two
        # lines can never overlap.
        width_frames = [(0.0, 0.0)]
        width_frames += [(w * k / n, start + t_type * k / n) for k in range(n + 1)]
        width_frames += [(w * (n - k) / n, start + t_type + t_hold + t_del * k / n)
                         for k in range(1, n + 1)]
        w_values, w_key = _keyframes(width_frames, total)

        # Discrete opacity: a line is opaque only inside its own
        # type/hold/delete window, so no two lines ever share the stage.
        # The trailing (0.0, total) frame matters: _keyframes pins the last
        # frame to the end of the cycle, and without it the "hidden" frame
        # would be stretched from the window's end to t=1, leaving the line
        # visible on top of every later line.
        # The static opacity attribute stays as the no-SMIL fallback
        # (line 1 only), which clipping alone cannot provide: a clip of
        # width 0 hides a line, but a line left at opacity 0 stays
        # invisible even while its clip opens — the bug this animation
        # fixes (lines 2 and 3 never appeared before).
        visible_end = start + t_type + t_hold + t_del
        op_values, op_key = _keyframes(
            [(0.0, 0.0), (1.0, start), (0.0, visible_end), (0.0, total)],
            total,
        )

        lines_ctx.append({
            "text": text,
            "width": w,
            "x0": x0,
            "w_values": w_values,
            "w_key": w_key,
            "op_values": op_values,
            "op_key": op_key,
        })

        # Caret positions contributed by this line.
        caret.append((x0, start))
        caret += [(x0 + w * k / n, start + t_type * k / n) for k in range(1, n + 1)]
        caret += [(x0 + w * (n - k) / n, start + t_type + t_hold + t_del * k / n)
                  for k in range(1, n + 1)]

    # Merge caret keyframes (entries are (x, time)); at phase boundaries keep
    # the later value so the caret jumps to the next line's start on time.
    caret.sort(key=lambda p: p[1])
    merged = [caret[0]]
    for x, t in caret[1:]:
        if abs(t - merged[-1][1]) < 1e-6:
            merged[-1] = (x, t)
        else:
            merged.append((x, t))
    merged.insert(0, (merged[0][0], 0.0))  # caret at line 1 start when t=0
    x_values, x_key = _keyframes(merged, total)

    return {
        "duration": round(total, 2),
        "lines": lines_ctx,
        "caret": {
            "x_init": round(merged[0][0], 2),
            "x_values": x_values,
            "x_key": x_key,
        },
    }


# ---------------------------------------------------------------------------
# Contribution heatmap — geometry mirrored in templates/activity.svg.j2.
# ---------------------------------------------------------------------------

GRID_X, GRID_Y, CELL, GAP = 36, 52, 11, 2
PITCH = CELL + GAP

# Amber ramps; index = activity level 0..4 (GitHub-style: dark theme
# brightens with activity, light theme deepens).
LEVEL_COLORS = {
    "dark": ["#21262D", "#4A3007", "#8A5806", "#D9930B", "#FBBF24"],
    "light": ["#EBEDF0", "#FEF3C7", "#FDE68A", "#F59E0B", "#92400E"],
}


def _level(count: int) -> int:
    if count <= 0:
        return 0
    if count <= 3:
        return 1
    if count <= 6:
        return 2
    if count <= 9:
        return 3
    return 4


def _activity_cells(days: list[dict], theme: str, crawl: list[float] | None = None) -> list[dict]:
    """One rect per calendar day.

    `crawl` is indexed like `days`: each value is the delay (seconds) at which
    the snake's head reaches that cell. The template paints the cell in the
    snake colour for the length of the body, then hands it back to the
    heatmap, so the snake reads as a moving chain of cells.
    """
    return [
        {
            "x": GRID_X + (idx // 7) * PITCH,
            "y": GRID_Y + (idx % 7) * PITCH,
            "fill": LEVEL_COLORS[theme][_level(d["contributionCount"])],
            "delay": None if crawl is None else crawl[idx],
        }
        for idx, d in enumerate(days)
    ]


def _month_labels(days: list[dict], max_x: float = 700.0) -> list[dict]:
    """One label per month where its first column begins (GitHub style)."""
    labels: list[dict] = []
    last_week = -10
    prev_month = None
    for idx, d in enumerate(days):
        week = idx // 7
        month = int(d["date"][5:7])
        if month == prev_month:
            continue
        prev_month = month
        if idx == 0:  # the calendar opens mid-month; skip the partial month
            continue
        if week - last_week < 4:  # avoid crowded consecutive labels
            continue
        x = GRID_X + week * PITCH
        if x <= max_x:
            labels.append({"x": x, "label": f"{month}月"})
            last_week = week
    return labels


# ---------------------------------------------------------------------------
# Snake overlay — a pixel snake crawls the calendar in serpentine order (down
# the first week column, up the next, and so on) one cell per step. The body
# is the chain of cells the head has just crossed: every grid cell paints
# itself in the snake colour during its own pass and then returns to its
# contribution colour, so the snake reads as a moving reptile rather than a
# line drawn over the chart. Geometry is shared with the heatmap block above.
# ---------------------------------------------------------------------------

SNAKE_STEP_SEC = 0.10      # seconds the head takes per cell
SNAKE_BODY_CELLS = 10      # cells the body trails behind the head

SNAKE_COLORS = {
    "dark": {"body": "#34D399", "head": "#6EE7B7", "eye": "#04231A", "tongue": "#FB7185"},
    "light": {"body": "#059669", "head": "#10B981", "eye": "#022C22", "tongue": "#BE123C"},
}


def _snake_route(days: list[dict]) -> list[tuple[int, int]]:
    """Cell coordinates (week column, weekday row) in serpentine order."""
    rows_by_col: dict[int, list[int]] = {}
    for idx in range(len(days)):
        rows_by_col.setdefault(idx // 7, []).append(idx % 7)

    route: list[tuple[int, int]] = []
    for week in sorted(rows_by_col):
        rows = sorted(rows_by_col[week], reverse=bool(week % 2))
        route.extend((week, row) for row in rows)
    return route


def _snake_context(days: list[dict], theme: str) -> dict:
    """Precompute the head path plus the per-cell delay of the body crawl.

    The head moves cell to cell with `calcMode="discrete"`; the delay of a
    cell is simply the time the head reaches it, and the CSS crawl window is
    the body length, so head and body cannot drift apart.
    """
    route = _snake_route(days)
    total = len(route)
    dur = round(total * SNAKE_STEP_SEC, 2)

    points = [
        (GRID_X + week * PITCH + CELL / 2, GRID_Y + row * PITCH + CELL / 2)
        for week, row in route
    ]
    path = "M " + " L ".join(f"{x:.1f} {y:.1f}" for x, y in points)

    # Discrete keyPoints: cell i holds from keyTimes[i] to keyTimes[i + 1].
    # The extra final frame (same point, t=1) keeps the last cell on screen
    # until the cycle ends; SMIL requires the last keyTime to be exactly 1.
    key_points = ";".join(f"{i / (total - 1):.5f}" for i in range(total)) + ";1"
    key_times = ";".join(f"{i / total:.5f}" for i in range(total)) + ";1"

    delays = [0.0] * len(days)
    for pos, (week, row) in enumerate(route):
        delays[week * 7 + row] = round(pos * SNAKE_STEP_SEC, 2)

    body_pct = round(SNAKE_BODY_CELLS / total * 100, 3)
    return {
        "dur": dur,
        "path": path,
        "key_points": key_points,
        "key_times": key_times,
        "delays": delays,
        "body_pct": body_pct,
        "colors": SNAKE_COLORS[theme],
    }


def _mock_data() -> dict:
    """Deterministic sample data for local preview (no gh CLI required)."""
    rng = random.Random(42)
    today = date.today()
    days = []
    for back in range(371, 0, -1):
        day = today - timedelta(days=back)
        if back <= 5:  # keep recent days active so the preview shows a streak
            count = rng.randint(1, 14)
        else:
            count = 0 if rng.random() < 0.28 else rng.randint(1, 14)
        days.append({"date": day.isoformat(), "contributionCount": count})
    streak, longest = compute_streaks(days)
    total = sum(d["contributionCount"] for d in days)
    return {
        "total_contribs": total,
        "commits": round(total * 0.85),
        "streak": streak,
        "max_streak": max(longest, streak),
        "contribution_days": days,
    }


def generate_all(out_dir: Path, mock: bool) -> None:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )

    if mock:
        data = _mock_data()
        print("Using deterministic mock data (--mock).")
    else:
        print("Fetching GitHub data...")
        data = fetch_user_data()
        if data is None:
            print("ERROR: could not fetch GitHub data; keeping existing SVGs untouched.")
            sys.exit(1)

    print(
        f"  contributions(1y): {data['total_contribs']:,} | "
        f"streak {data['streak']} | max {data['max_streak']}"
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    weekdays = [
        {"label": label, "y": GRID_Y + dow * PITCH + 9}
        for dow, label in ((1, "一"), (3, "三"), (5, "五"))
    ]
    activity_ctx = {
        "total_contribs": f"{data['total_contribs']:,}",
        "streak": data["streak"],
        "max_streak": data["max_streak"],
        "months": _month_labels(data["contribution_days"]),
        "weekdays": weekdays,
    }

    cards = (
        ("typing-card", "typing.svg.j2", _typing_context(TYPING_LINES)),
        ("activity-card", "activity.svg.j2", activity_ctx),
    )

    for theme in ("dark", "light"):
        suffix = "" if theme == "dark" else "-light"
        for name, template_name, ctx in cards:
            render_ctx = dict(ctx)
            if name == "activity-card":
                # The snake owns the crawl schedule, so the cells are built
                # after it and inherit the delay at which the head arrives.
                snake_ctx = _snake_context(data["contribution_days"], theme)
                render_ctx["cells"] = _activity_cells(
                    data["contribution_days"], theme, snake_ctx["delays"]
                )
                render_ctx["levels"] = LEVEL_COLORS[theme]
                render_ctx["snake"] = snake_ctx
            svg = env.get_template(template_name).render(**render_ctx, theme=theme)
            path = out_dir / f"{name}{suffix}.svg"
            # newline="\n" keeps the bytes identical whether this runs on the
            # Linux runner or a Windows checkout; the default text-mode
            # translation would emit CRLF locally.
            path.write_text(svg, encoding="utf-8", newline="\n")
            try:
                shown = path.resolve().relative_to(ROOT).as_posix()
            except ValueError:
                shown = path.as_posix()
            print(f"  OK {shown}")

    print("All cards generated.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate profile SVG cards.")
    parser.add_argument("--mock", action="store_true",
                        help="use deterministic sample data instead of the GitHub API")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT,
                        help="output directory (default: assets/)")
    args = parser.parse_args()
    generate_all(args.out, args.mock)


if __name__ == "__main__":
    main()
