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
import math
import random
import sys
from bisect import bisect_right
from datetime import date, timedelta
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from github_api import compute_streaks, fetch_user_data
from content import COOP_LINE, DAILY_PAIRS, INVENTORY, QUESTS

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
        # The cycle starts with the first line already typed, so a still
        # frame (or a client that never advances the clock) shows text
        # instead of an empty card with a lone caret.
        "phase": f"{phases[0][1]:.2f}",
        "lines": lines_ctx,
        "caret": {
            "x_init": round(merged[0][0], 2),
            "x_values": x_values,
            "x_key": x_key,
        },
    }


# ---------------------------------------------------------------------------
# Contribution parkour — the calendar as a landscape.
#
# The heatmap is gone: every week becomes a column of ground, and that week's
# real contribution total lifts the ground into a hill (busy) or lets it fall
# into a valley (quiet). One pixel runner crosses the whole year in a single
# lap, hops the boulders that stand in for busy patches, collects the amber
# gems planted on active weeks and stops at the checkpoint flag on the last
# week; then the lap starts over. Geometry, the runner's timetable and every
# CSS keyframe are precomputed here — templates/activity.svg.j2 only paints.
# ---------------------------------------------------------------------------

SCENE_W, SCENE_H = 760, 210
GROUND_Y = 176.0     # ground line of a week with no contributions at all
EARTH_BOTTOM = 209.0 # soil runs to the card edge; month row sits inside it
HILL_MAX = 54.0      # how far the busiest week lifts the ground
X0, PITCH = 26.0, 13.0

RUN_X0, RUN_X1 = 34.0, 712.0
RUN_SPEED = 70.0     # px/s — constant, so the lap line is genuinely linear
HOLD_SEC = 2.2       # checkpoint celebration before the lap restarts
SAMPLE_DT = 0.02     # timetable sampling resolution
SURF_STEP = 3        # ground polyline resolution
JUMP_PAD = 15.0      # take-off/landing distance either side of a boulder

PALETTE = {
    "dark": {
        "sky_top": "#070A10", "sky_bottom": "#161D28", "glow": "#F59E0B",
        "far": "#131C28", "mid": "#1D2836",
        "earth_top": "#33240E", "earth_bottom": "#0D0904",
        "ridge": "#F59E0B", "ridge_soft": "#B45309",
        "soil": "#C08E3F", "tuft": "#8A4A0E", "soil_label": "#C08E3F",
        "rock": "#5C4423", "rock_hi": "#C08E3F",
        "gem": "#FBBF24", "gem_core": "#FEF9C3",
        "body": "#2DD4BF", "body_dark": "#0F766E", "pants": "#CBD5E1",
        "face": "#FDE68A", "scarf": "#FB7185",
        "text": "#FDE68A", "muted": "#8FA0B5", "bright": "#FBBF24",
        "moon": "#FDE68A", "star": "#FDE68A",
        "track": "#1E2733", "marker": "#F59E0B",
        "banner": "#0B0F16", "banner_edge": "#F59E0B",
        # inventory / quest slots
        "slot_bg": "#111823", "pip_off": "#2A3442",
        "r_legendary": "#FBBF24", "r_epic": "#A78BFA",
        "r_rare": "#2DD4BF", "r_common": "#8FA0B5",
    },
    "light": {
        "sky_top": "#FFFDF7", "sky_bottom": "#FCEFD0", "glow": "#F59E0B",
        "far": "#F7E7BE", "mid": "#EFD9A6",
        "earth_top": "#ECD4A2", "earth_bottom": "#D6B77C",
        "ridge": "#B45309", "ridge_soft": "#D97706",
        "soil": "#B08A4B", "tuft": "#8A4A0E", "soil_label": "#7C5A2A",
        "rock": "#C9A96B", "rock_hi": "#F7ECD2",
        "gem": "#D97706", "gem_core": "#FFFBEB",
        "body": "#0D9488", "body_dark": "#115E59", "pants": "#334155",
        "face": "#FDE68A", "scarf": "#E11D48",
        "text": "#92400E", "muted": "#7C6A4E", "bright": "#B45309",
        "moon": "#F59E0B", "star": "#D97706",
        "track": "#E7CFA0", "marker": "#B45309",
        "banner": "#FFF8E7", "banner_edge": "#B45309",
        "slot_bg": "#FFF8E7", "pip_off": "#E7CFA0",
        "r_legendary": "#B45309", "r_epic": "#7C3AED",
        "r_rare": "#0D9488", "r_common": "#7C6A4E",
    },
}


def _weekly_totals(days: list[dict]) -> list[float]:
    """Contribution count per calendar week column."""
    totals = [0.0] * ((len(days) + 6) // 7)
    for idx, day in enumerate(days):
        totals[idx // 7] += day["contributionCount"]
    return totals


def _surface_pts(days: list[dict], *, sigma: float = 5.5,
                 scale: float = 1.0, lift: float = 0.0) -> tuple[list[float], list[float]]:
    """Sample the ground line left to right.

    Each week is a control point whose height is its contribution total; a
    Gaussian blend turns the columns into landforms. A convex blend never
    overshoots, so a quiet week is a valley and never a hole below the
    baseline. `scale`/`lift` build the dimmer depth layers behind the ground.
    """
    totals = _weekly_totals(days)
    peak = max(totals) if totals else 0.0
    hs = [((t / peak) ** 0.72 * HILL_MAX * scale) if peak else 0.0 for t in totals]
    # A light 1-2-1 pass rounds the shoulders the columns would otherwise show.
    hs = [0.25 * hs[max(i - 1, 0)] + 0.5 * hs[i] + 0.25 * hs[min(i + 1, len(hs) - 1)]
          for i in range(len(hs))]
    # Anchor the quietest week to the baseline: an unusually busy year must
    # still read as land rather than a plateau floating above the card.
    floor = min(hs) if hs else 0.0
    hs = [h - floor for h in hs]

    centers = [X0 + i * PITCH + 5.5 for i in range(len(hs))]
    xs = [float(x) for x in range(0, SCENE_W + 1, SURF_STEP)]
    ys: list[float] = []
    inv = 1.0 / (2.0 * sigma * sigma)
    for x in xs:
        acc = wsum = 0.0
        for center, h in zip(centers, hs):
            d = x - center
            w = math.exp(-d * d * inv)
            acc += w * h
            wsum += w
        ys.append(round(GROUND_Y - lift - (acc / wsum if wsum else 0.0), 1))
    return xs, ys


def _at(xs: list[float], ys: list[float], x: float) -> float:
    """Ground height at x, linearly interpolated between samples."""
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    i = bisect_right(xs, x) - 1
    span = xs[i + 1] - xs[i]
    return ys[i] + (ys[i + 1] - ys[i]) * ((x - xs[i]) / span if span else 0.0)


def _line_path(xs: list[float], ys: list[float]) -> str:
    return "M" + " L".join(f"{x:.1f} {y:.1f}" for x, y in zip(xs, ys))


def _fill_path(xs: list[float], ys: list[float]) -> str:
    return (_line_path(xs, ys)
            + f" L{xs[-1]:.1f} {EARTH_BOTTOM:.1f} L{xs[0]:.1f} {EARTH_BOTTOM:.1f} Z")


def _rocks(xs: list[float], ys: list[float]) -> list[dict]:
    """Boulders on the trail. Fixed seed: the course never moves under the data."""
    rng = random.Random(7)
    rocks: list[dict] = []
    x = 92.0
    while x < RUN_X1 - 110:
        w = rng.choice((9, 10, 11))
        h = rng.choice((9, 11, 13))
        rocks.append({"x": round(x, 1), "w": w, "h": h,
                      "y": round(_at(xs, ys, x + w / 2), 1)})
        x += rng.choice((60, 68, 78, 86))
    return rocks


def _gems(days: list[dict], xs: list[float], ys: list[float],
          rocks: list[dict]) -> list[dict]:
    """One gem per active week, parked just above the ground."""
    gems: list[dict] = []
    for week, total in enumerate(_weekly_totals(days)):
        if total <= 0:
            continue
        x = X0 + week * PITCH + 5.5
        if x < RUN_X0 + 14 or x > RUN_X1 - 14:
            continue
        if gems and x - gems[-1]["x"] < 21:  # greedy spacing, no gem fences
            continue
        if any(abs(x - (r["x"] + r["w"] / 2)) < 15 for r in rocks):
            continue
        gems.append({"x": round(x, 1), "y": round(_at(xs, ys, x) - 7.5, 1)})
    return gems


def _tufts(xs: list[float], ys: list[float]) -> list[dict]:
    rng = random.Random(11)
    tufts: list[dict] = []
    x = 12.0
    while x < SCENE_W - 12:
        tufts.append({"x": round(x, 1), "y": round(_at(xs, ys, x), 1),
                      "s": rng.choice((1, 1, 2))})
        x += rng.choice((17, 23, 31, 37, 43))
    return tufts


def _soil(xs: list[float], ys: list[float]) -> list[dict]:
    """Pebbles buried in the earth band."""
    rng = random.Random(13)
    dots: list[dict] = []
    for _ in range(30):
        x = rng.uniform(10, SCENE_W - 10)
        top = _at(xs, ys, x) + 7
        dots.append({"x": round(x, 1),
                     "y": round(rng.uniform(top, EARTH_BOTTOM - 7), 1),
                     "r": rng.choice((0.8, 1.0, 1.3))})
    return dots


def _stars() -> list[dict]:
    rng = random.Random(3)
    stars: list[dict] = []
    for _ in range(38):
        x = rng.uniform(10, SCENE_W - 10)
        y = rng.uniform(12, 106)
        if 636 < x and 30 < y < 104:  # keep the moon's halo clear
            continue
        stars.append({"x": round(x, 1), "y": round(y, 1),
                      "r": rng.choice((0.7, 1.0, 1.3)),
                      "delay": round(rng.uniform(0.0, 4.2), 2)})
    return stars


def _month_labels(days: list[dict], max_x: float = 700.0) -> list[dict]:
    """One label per month where its first week column begins."""
    labels: list[dict] = []
    last_week = -10
    prev_month = None
    for idx, day in enumerate(days):
        week = idx // 7
        month = int(day["date"][5:7])
        if month == prev_month:
            continue
        prev_month = month
        if idx == 0:  # the calendar opens mid-month; skip the partial month
            continue
        if week - last_week < 4:  # avoid crowded consecutive labels
            continue
        x = X0 + week * PITCH
        if x <= max_x:
            labels.append({"x": round(x, 1), "label": f"{month}月"})
            last_week = week
    return labels


def _timetable(xs: list[float], ys: list[float], rocks: list[dict]) -> dict:
    """Runner path: constant ground speed, one parabola per boulder.

    Sampling the ground on a fixed clock and then thinning the frame list
    keeps the sprite glued to the terrain — a straight-line interpolation
    between distant points would cut through every hill.
    """
    dur_run = (RUN_X1 - RUN_X0) / RUN_SPEED
    dur = round(dur_run + HOLD_SEC, 2)
    jumps = [(r["x"] - JUMP_PAD, r["x"] + r["w"] + JUMP_PAD, r["h"] + 12.0)
             for r in rocks]

    frames: list[tuple[float, float, float]] = []
    for i in range(int(round(dur / SAMPLE_DT)) + 1):
        t = i * SAMPLE_DT
        x = RUN_X0 + RUN_SPEED * min(t, dur_run)
        lift = 0.0
        for start, end, apex in jumps:
            if start <= x <= end:
                s = (x - start) / (end - start)
                lift = max(lift, 4.0 * apex * s * (1.0 - s))
        frames.append((x, _at(xs, ys, x) - lift, t))

    kept = [frames[0]]
    for frame in frames[1:-1]:
        if abs(frame[0] - kept[-1][0]) >= 1.6 or abs(frame[1] - kept[-1][1]) >= 0.35:
            kept.append(frame)
    kept.append(frames[-1])

    keys = [f"{t / dur:.5f}" for _, _, t in kept]
    keys[-1] = "1.00000"
    return {
        "dur": dur,
        "run_pct": round(dur_run / dur * 100.0, 2),
        "values": ";".join(f"{x:.1f},{y:.1f}" for x, y, _ in kept),
        "keys": ";".join(keys),
        # The cast shadow walks the same clock but ignores the jump lift, so it
        # stays pinned to the ground while the sprite rises off it.
        "shadow_values": ";".join(
            f"{x:.1f},{_at(xs, ys, x):.1f}" for x, _, _ in kept),
        "jumps": jumps,
    }


def _opacity_frames(spans: list[tuple[float, float]], *, on: str = "1",
                    off: str = "0", total: float = 100.0) -> list[tuple[float, str]]:
    """Discrete opacity stops for the percentage windows in `spans`.

    Consumed with `calcMode="discrete"`, so each stop holds until the next one:
    the sprite is either on the ground or in the air, never half of each.
    """
    frames: list[tuple[float, str]] = [(0.0, off)]
    for start, end in spans:
        frames.append((min(max(start, 0.0), total), on))
        frames.append((min(max(end, 0.0), total), off))
    frames.append((total, frames[-1][1]))

    merged: list[tuple[float, str]] = []
    for pct, val in frames:
        if merged and abs(pct - merged[-1][0]) < 1e-9:
            merged[-1] = (pct, val)  # the later stop wins at a shared instant
        else:
            merged.append((pct, val))
    return merged


def _smil(frames: list[tuple[float, str]]) -> dict:
    """The same frames as SMIL values/keyTimes, for a discrete opacity swap.

    The keys are short on purpose: `values` and `keys` are dict methods, so a
    template reading `.values` would render the bound method instead.
    """
    return {
        "v": ";".join(val for _, val in frames),
        "kt": ";".join(f"{pct / 100.0:.5f}" for pct, _ in frames),
    }


def _parkour_context(days: list[dict], theme: str, total: int,
                     streak: int, max_streak: int) -> dict:
    p = PALETTE[theme]
    xs, ys = _surface_pts(days)
    rocks = _rocks(xs, ys)
    gems = _gems(days, xs, ys, rocks)
    run = _timetable(xs, ys, rocks)
    dur = run["dur"]

    # Airborne windows, and the gem pickups, as percentages of one lap.
    # Everything time-driven is SMIL rather than CSS keyframes: the runner is
    # already an animateTransform, and one mechanism means one thing to reason
    # about (and to verify) when a frame looks wrong.
    air_spans = [((start - RUN_X0) / RUN_SPEED / dur * 100.0,
                  (end - RUN_X0) / RUN_SPEED / dur * 100.0)
                 for start, end, _ in run["jumps"]]
    pose_air = _smil(_opacity_frames(air_spans))
    pose_ground = _smil(_opacity_frames(air_spans, on="0", off="1"))
    shadow = _smil(_opacity_frames(air_spans, on=".18", off=".4"))
    banner = _smil(_opacity_frames([(run["run_pct"], 100.0)]))
    reward = []
    for gem in gems:
        hit = (gem["x"] - RUN_X0) / RUN_SPEED / dur * 100.0
        reward.append({
            **gem,
            "gem": _smil(_opacity_frames([(0.0, hit)])),
            "spark": _smil(_opacity_frames([(hit, hit + 2.2)])),
        })

    far_xs, far_ys = _surface_pts(days, sigma=26.0, scale=0.55, lift=9.0)
    mid_xs, mid_ys = _surface_pts(days, sigma=15.0, scale=0.82, lift=3.0)
    flag_x = 726.0
    track = {"x": 560.0, "w": 174.0, "y": 46.0}

    score = f"{total:,}"
    return {
        "w": SCENE_W, "h": SCENE_H,
        "p": p,
        "total": score,
        "score_w": round(len(score) * 21 * 0.6, 1),
        "streak": streak,
        "max_streak": max_streak,
        "date_from": f"{days[0]['date'][:7].replace('-', '.')}",
        "date_to": f"{days[-1]['date'][:7].replace('-', '.')}",
        "months": _month_labels(days),
        "terrain": _fill_path(xs, ys),
        "ridge": _line_path(xs, ys),
        "far": _fill_path(far_xs, far_ys),
        "far_ridge": _line_path(far_xs, far_ys),
        "mid": _fill_path(mid_xs, mid_ys),
        "mid_ridge": _line_path(mid_xs, mid_ys),
        "soil": _soil(xs, ys),
        "tufts": _tufts(xs, ys),
        "rocks": rocks,
        "gems": reward,
        "pose_air": pose_air,
        "pose_ground": pose_ground,
        "banner": banner,
        "stars": _stars(),
        "flag": {"x": flag_x, "y": round(_at(xs, ys, flag_x), 1)},
        "dur": dur,
        "run_pct": run["run_pct"],
        "runner_values": run["values"],
        "runner_keys": run["keys"],
        "shadow_values": run["shadow_values"],
        "shadow": shadow,
        "run_x0": RUN_X0,
        "run_y0": round(_at(xs, ys, RUN_X0), 1),
        "poster": {
            "x": round(RUN_X0 + (RUN_X1 - RUN_X0) * 0.55, 1),
            "y": round(_at(xs, ys, RUN_X0 + (RUN_X1 - RUN_X0) * 0.55), 1),
        },
        "track": track,
        "progress": {
            "v": f"0,0;{track['w'] - 3:.1f},0;{track['w'] - 3:.1f},0",
            "kt": f"0;{run['run_pct'] / 100.0:.5f};1",
        },
    }


# ---------------------------------------------------------------------------
# Quest log + inventory — the two editorial cards.
#
# Neither of them reads the GitHub API: they render a small hand-written
# config (scripts/content.py) in the same game-UI language as the parkour
# card, so the whole profile reads as one save file. All coordinates below
# are computed here; the templates only paint.
# ---------------------------------------------------------------------------

RARITY_LABEL = {"legendary": "LEGENDARY", "epic": "EPIC",
                "rare": "RARE", "common": "COMMON"}
RARITY_CN = {"legendary": "传说", "epic": "史诗", "rare": "稀有", "common": "普通"}
RARITY_STROKE = {"legendary": 0.95, "epic": 0.7, "rare": 0.5, "common": 0.38}
RARITY_LABEL_OP = {"legendary": 1.0, "epic": 0.85, "rare": 0.8, "common": 0.78}

INV_W, INV_H = 760, 196
SLOT_W, SLOT_H = 92.0, 62.0
SLOT_X0, SLOT_Y0 = 25.0, 44.0
SLOT_GAP_X, SLOT_GAP_Y = 11.0, 10.0
SLOT_COLS = 7
PIP_PITCH, PIP_START = 6.0, 32.0  # 5 pips of 4px + 2px gaps, centred in a slot

QUEST_W, QUEST_H = 760, 208
QUEST_ROW_Y = 44.0
QUEST_ROW_STEP = 44.0
QUEST_BAR_X, QUEST_BAR_W = 418.0, 150.0
QUEST_CHIP_X, QUEST_CHIP_W = 674.0, 60.0
QUEST_FOOTER_RULE, QUEST_FOOTER_Y = 176.0, 194.0

DAILY_W, DAILY_H = 760, 64
DAILY_TITLE_W = 12.5 * 3  # “今日签”, three fullwidth advances at font-size 12.5


def _est_width(text: str, size: float) -> float:
    """Rough advance width: fullwidth CJK, 0.58em for Latin (monospace-ish)."""
    return sum(size if ord(ch) >= 0x2E80 else size * 0.58 for ch in text)


def _inventory_context(theme: str) -> dict:
    p = PALETTE[theme]
    items = []
    for idx, spec in enumerate(INVENTORY):
        col, row = idx % SLOT_COLS, idx // SLOT_COLS
        x = SLOT_X0 + col * (SLOT_W + SLOT_GAP_X)
        y = SLOT_Y0 + row * (SLOT_H + SLOT_GAP_Y)
        cx = x + SLOT_W / 2
        filled = min(5, int(spec["level"] / 20 + 0.5))
        rarity = spec["rarity"]
        items.append({
            "name": spec["name"],
            "rarity": rarity,
            "rarity_label": RARITY_LABEL[rarity],
            "color": p[f"r_{rarity}"],
            "stroke_op": RARITY_STROKE[rarity],
            "label_op": RARITY_LABEL_OP[rarity],
            "pip_on_op": RARITY_STROKE[rarity],
            "x": round(x, 1), "y": round(y, 1), "cx": round(cx, 1),
            "w": SLOT_W, "h": SLOT_H,
            "pips": [{"x": round(x + PIP_START + k * PIP_PITCH, 1), "on": k < filled}
                     for k in range(5)],
        })

    counts = {r: sum(1 for s in INVENTORY if s["rarity"] == r) for r in RARITY_CN}
    legend: list[dict] = []
    cursor = INV_W - 26.0
    for rarity in ("legendary", "epic", "rare", "common"):
        if not counts[rarity]:
            continue
        count = counts[rarity]
        text_w = _est_width(RARITY_CN[rarity], 7.5) + 3 + _est_width(str(count), 7.5)
        cursor -= 6 + 4 + text_w  # swatch + gutter + label
        legend.insert(0, {"x": round(cursor, 1), "color": p[f"r_{rarity}"],
                          "label": RARITY_CN[rarity], "count": count})
        cursor -= 14

    return {
        "w": INV_W, "h": INV_H, "p": p,
        "items": items, "count": len(INVENTORY), "legend": legend,
    }


def _quest_context(theme: str) -> dict:
    p = PALETTE[theme]
    quests = []
    for idx, spec in enumerate(QUESTS):
        y = QUEST_ROW_Y + idx * QUEST_ROW_STEP
        accent = p["bright"] if spec["kind"] == "MAIN" else p["r_rare"]
        quests.append({
            **spec,
            "y": round(y, 1),
            "accent": accent,
            "fill_w": round(QUEST_BAR_W * spec["progress"] / 100.0, 1),
        })
    return {
        "w": QUEST_W, "h": QUEST_H, "p": p,
        "quests": quests,
        "main_count": sum(1 for q in QUESTS if q["kind"] == "MAIN"),
        "bar_x": QUEST_BAR_X, "bar_w": QUEST_BAR_W,
        "chip_x": QUEST_CHIP_X, "chip_w": QUEST_CHIP_W,
        "footer_rule": QUEST_FOOTER_RULE, "footer_y": QUEST_FOOTER_Y,
        "coop": COOP_LINE,
    }


def _daily_context(theme: str, today: date) -> dict:
    """The daily strip: one (宜, 忌) pair picked from the date itself."""
    p = PALETTE[theme]
    good, bad = DAILY_PAIRS[today.toordinal() % len(DAILY_PAIRS)]
    return {
        "w": DAILY_W, "h": DAILY_H, "p": p,
        "good": good, "bad": bad,
        "date_label": today.strftime("%Y.%m.%d"),
        "weekday": "周" + "一二三四五六日"[today.weekday()],
        "seed": f"{today.toordinal():03X}",
        "title_w": DAILY_TITLE_W,
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
    typing_ctx = _typing_context(TYPING_LINES)
    today = date.today()

    for theme in ("dark", "light"):
        suffix = "" if theme == "dark" else "-light"
        cards = (
            ("typing-card", env.get_template("typing.svg.j2").render(**typing_ctx, theme=theme)),
            ("daily-card", env.get_template("daily.svg.j2").render(**_daily_context(theme, today), theme=theme)),
            ("quest-card", env.get_template("quest.svg.j2").render(**_quest_context(theme), theme=theme)),
            ("inventory-card", env.get_template("inventory.svg.j2").render(**_inventory_context(theme), theme=theme)),
            ("activity-card", env.get_template("activity.svg.j2").render(
                **_parkour_context(
                    data["contribution_days"], theme,
                    data["total_contribs"], data["streak"], data["max_streak"],
                ),
                theme=theme,
            )),
        )
        for name, svg in cards:
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
