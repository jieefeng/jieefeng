"""Generate all SVG cards from Jinja2 templates and GitHub data."""

import sys
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from github_api import fetch_user_data

# Project root (scripts/ -> project root)
ROOT = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = ROOT / "templates"
ASSETS_DIR = ROOT / "assets"

# Skills configuration (static)
SKILLS = [
    {"name": "Python", "color": "#3572A5"},
    {"name": "Java", "color": "#B07219"},
    {"name": "TypeScript", "color": "#3178C6"},
    {"name": "Vue", "color": "#41B883"},
    {"name": "Spring", "color": "#6DB33F"},
    {"name": "MySQL", "color": "#4479A1"},
    {"name": "Redis", "color": "#DC382D"},
    {"name": "RabbitMQ", "color": "#FF6600"},
    {"name": "Kafka", "color": "#231F20"},
    {"name": "Docker", "color": "#2496ED"},
    {"name": "Linux", "color": "#FCC624"},
    {"name": "Git", "color": "#F05032"},
    {"name": "LangChain", "color": "#1C3C3C"},
    {"name": "MinIO", "color": "#C72E49"},
]

# Blog links (static)
BLOG_LINKS = [
    {"name": "掘金", "url": "https://juejin.cn/user/jieefeng", "color": "#1E80FF"},
    {"name": "CSDN", "url": "https://blog.csdn.net/jieefeng", "color": "#FC5531"},
]

# Learning goals (static)
LEARNING_GOALS = [
    {"name": "RAG 深入实践", "progress": 65, "color": "#F59E0B"},
    {"name": "系统设计", "progress": 40, "color": "#D97706"},
    {"name": "云原生架构", "progress": 30, "color": "#92400E"},
]

# Typing animation lines
TYPING_LINES = [
    "AI 工程师 | RAG 探索者",
    "全栈开发 | 后端架构师",
    "Always building, always learning",
]


def _build_activity_cells(contribution_days: list[dict], theme: str) -> list[dict]:
    """Pre-compute activity heatmap cell positions and colors for a theme."""
    cell_size = 11
    gap = 2
    start_x = 20
    start_y = 42

    cells = []
    week = 0
    day_in_week = 0

    for day in contribution_days:
        count = day.get("contributionCount", 0)
        if count == 0:
            fill = "#161B22" if theme == "dark" else "#E5E7EB"
        elif count <= 3:
            fill = "#FEF3C7"
        elif count <= 6:
            fill = "#FDE68A"
        elif count <= 9:
            fill = "#F59E0B"
        else:
            fill = "#92400E"

        x = start_x + week * (cell_size + gap)
        y = start_y + day_in_week * (cell_size + gap)
        cells.append({"x": x, "y": y, "fill": fill})

        day_in_week += 1
        if day_in_week >= 7:
            day_in_week = 0
            week += 1

    return cells


def generate_all():
    """Generate all SVG cards."""
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )

    # Fetch data
    print("Fetching GitHub data...")
    data = fetch_user_data()
    print(f"  Repos: {data['repos']}, Stars: {data['stars']}, Commits: {data['commits']}")

    # Card definitions: name -> template context
    cards = {
        "stats": {
            **data,
        },
        "langs": {
            "languages": data["languages"],
        },
        "achievements": {
            **data,
        },
        "views": {
            "views": data["views"],
        },
        "typing": {
            "lines": TYPING_LINES,
        },
        "skills": {
            "skills": SKILLS,
            "card_height": 20 + ((len(SKILLS) + 6) // 7) * 38 + 10,
        },
        "activity": {
            "cells": [],  # will be filled per-theme below
        },
        "pinned": {
            "repos": data["pinned_repos"],
            "card_height": max(60, 20 + ((len(data["pinned_repos"]) + 1) // 2) * 100 + 10),
        },
        "blog": {
            "links": BLOG_LINKS,
            "goals": LEARNING_GOALS,
            "card_height": 20 + len(BLOG_LINKS) * 32 + len(LEARNING_GOALS) * 36 + 50,
        },
    }

    for card_name, context in cards.items():
        template_path = f"{card_name}.svg.j2"
        template_file = TEMPLATES_DIR / template_path
        if not template_file.exists():
            print(f"  SKIP {card_name}: template not found")
            continue

        template = env.get_template(template_path)
        for theme in ["dark", "light"]:
            try:
                render_ctx = dict(context)
                # Pre-compute activity cells per theme
                if card_name == "activity":
                    render_ctx["cells"] = _build_activity_cells(
                        data["contribution_days"], theme
                    )
                svg = template.render(**render_ctx, theme=theme)
                suffix = "" if theme == "dark" else "-light"
                output_path = ASSETS_DIR / f"{card_name}-card{suffix}.svg"
                output_path.write_text(svg, encoding="utf-8")
                print(f"  OK {card_name}-card{suffix}.svg")
            except Exception as e:
                print(f"  ERROR {card_name}-card{'-light' if theme == 'light' else ''}.svg: {e}")

    print("All cards generated.")


if __name__ == "__main__":
    generate_all()
