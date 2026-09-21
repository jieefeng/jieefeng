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
LATIN_W = FONT_SIZE * 0.62  # monospace advance, latin glyphs
CJK_W = FONT_SIZE * 1.02    # monospace advance, fullwidth glyphs
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

        lines_ctx.append({
            "text": text,
            "width": w,
            "x0": x0,
            "w_values": w_values,
            "w_key": w_key,
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


def _activity_cells(days: list[dict], theme: str) -> list[dict]:
    return [
        {
            "x": GRID_X + (idx // 7) * PITCH,
            "y": GRID_Y + (idx % 7) * PITCH,
            "fill": LEVEL_COLORS[theme][_level(d["contributionCount"])],
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
# Rendering
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Snake overlay — the snake crawls the same grid serpentine-style, "eating"
# each cell (fill flash) as its head passes. Geometry from the block above.
# ---------------------------------------------------------------------------

SNAKE_DURATION = 14.0  # seconds for one full pass over the grid
# (begin offset, radius, opacity) for head + trailing body segments.
SNAKE_TRAIL = ((0.0, 5.0, "1"), (-0.18, 4.2, "0.55"), (-0.36, 3.2, "0.28"))
SNAKE_COLORS = {"dark": "#FBBF24", "light": "#B45309"}


def _snake_context(days: list[dict], theme: str) -> dict:
    cols = -(-len(days) // 7)  # ceil
    x0, y0 = GRID_X + CELL / 2, GRID_Y + CELL / 2

    # Serpentine visit order: even columns top->bottom, odd bottom->top.
    # Every consecutive hop is exactly PITCH long, so speed is uniform.
    points = [
        (x0 + w * PITCH, y0 + (r if w % 2 == 0 else 6 - r) * PITCH)
        for w in range(cols)
        for r in range(7)
    ]
    path = f"M {points[0][0]:.1f} {points[0][1]:.1f} " + " ".join(
        f"L {x:.1f} {y:.1f}" for x, y in points[1:]
    )

    # Flash window as a fraction of the loop, kept inside (0, 1) keyTimes.
    last = len(points) - 1
    flash_span = 0.035

    def flash_at(index: int) -> tuple[str, str]:
        t = 0.02 + (index / last) * 0.90
        return f"{t:.4f}", f"{t + flash_span:.4f}"

    # Per-cell flash times: cells are generated column-major top->bottom in
    # _activity_cells, i.e. idx = w*7 + r — the same serpentine order.
    eaten = [flash_at(idx) for idx in range(len(days))]

    return {
        "dur": SNAKE_DURATION,
        "path": path,
        "color": SNAKE_COLORS[theme],
        "flash_color": LEVEL_COLORS[theme][4],
        "segments": [
            {"begin": b, "r": r, "opacity": o} for b, r, o in SNAKE_TRAIL
        ],
        "eaten": eaten,
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
                render_ctx["cells"] = _activity_cells(data["contribution_days"], theme)
                render_ctx["levels"] = LEVEL_COLORS[theme]
                render_ctx["snake"] = _snake_context(data["contribution_days"], theme)
            svg = env.get_template(template_name).render(**render_ctx, theme=theme)
            path = out_dir / f"{name}{suffix}.svg"
            path.write_text(svg, encoding="utf-8")
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
