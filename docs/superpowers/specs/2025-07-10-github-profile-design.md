# GitHub Profile README Design Spec

**Date:** 2025-07-10
**Target Repository:** `jieefeng/jieefeng` (public)

## Overview

Create a professional GitHub Profile README with dynamic stats, contribution tracking, and visual polish. All data updates automatically via GitHub Actions daily.

## Layout Structure (top to bottom)

```
1. Header (avatar + name + tagline + tech direction + contact)
2. Tech Stack (shields.io badges for languages/frameworks)
3. GitHub Stats (4 cards: Stars, Commits, PRs, Issues)
4. Contribution Streak (consecutive days)
5. Top Languages + Activity Graph
6. Profile Views Counter
```

## Components

### 1. Header Section

- GitHub avatar (auto-fetched)
- Display name: `jieefeng`
- Tagline: AI/RAG/Full-stack Developer
- Brief intro paragraph
- Social/contact links (using shields.io badges)

### 2. Tech Stack Badges

Using shields.io + simple-icons:

| Category | Items |
|----------|-------|
| Languages | Python, Java |
| Frontend | Vue.js |
| Backend | Spring Boot |
| Databases | MySQL, Redis |

### 3. GitHub Stats Cards

Four cards arranged horizontally using `github-readme-stats`:

```markdown
![Stars](https://github-readme-stats.vercel.app/api?username=jieefeng&show_icons=true&theme=radical)
![Commits](https://github-readme-stats.vercel.app/api?username=jieefeng&show_icons=true&count_private=true&theme=radical)
![PRs](https://github-readme-stats.vercel.app/api?username=jieefeng&show_icons=true&theme=radical)
![Issues](https://github-readme-stats.vercel.app/api?username=jieefeng&show_icons=true&theme=radical)
```

Configuration:
- Theme: `radical` (dark, techy)
- Show icons: true
- Count private commits: true
- Include all-time stats

### 4. Contribution Streak

Using `github-readme-streak-stats`:

```markdown
![Streak](https://github-readme-streak-stats.vercel.app?user=jieefeng&theme=radical)
```

Shows:
- Current streak days
- Longest streak days
- Total contributions

### 5. Top Languages & Activity Graph

```markdown
![Top Langs](https://github-readme-stats.vercel.app/api/top-langs/?username=jieefeng&layout=compact&theme=radical)
![Activity Graph](https://github-readme-stats.vercel.app/api/activity-graph?username=jieefeng&theme=radical)
```

- Compact layout for languages
- Activity graph shows contribution history

### 6. Profile Views Counter

```markdown
![Views](https://hits.seeyoufarm.com/api/count/incr/badge.svg?url=https%3A%2F%2Fgithub.com%2Fjieefeng&count_bg=%2379C83D&title_bg=%23555555&icon=&icon_color=%23E7E7E7&title=Profile+Views&edge_flat=false)
```

- Badge style with progress bar
- Incremental counter

## GitHub Actions Automation

### Workflow File: `.github/workflows/update-stats.yml`

```yaml
name: Update GitHub Stats

on:
  schedule:
    - cron: '0 1 * * *'  # 9:00 AM Beijing Time (UTC+8)
  workflow_dispatch:      # Allow manual trigger

jobs:
  update-readme:
    runs-on: ubuntu-latest
    permissions:
      contents: write
    steps:
      - uses: actions/checkout@v4
      - name: Update README
        uses: anuraghazra/github-readme-stats@master
        with:
          github_token: ${{ secrets.GITHUB_TOKEN }}
      - name: Commit changes
        run: |
          git config --local user.email "action@github.com"
          git config --local user.name "GitHub Action"
          git diff --quiet || (git add README.md && git commit -m "chore: update stats [skip ci]" && git push)
```

### Stats APIs Used

| Service | Purpose |
|---------|---------|
| `github-readme-stats` | Stars, Commits, PRs, Issues, Languages, Activity Graph |
| `github-readme-streak-stats` | Contribution streak |
| `hits.seeyoufarm` | Profile views counter |
| `shields.io` | Tech stack badges, social badges |

## Theme

- Primary theme: `radical` (dark purple/green)
- All cards use same theme for consistency
- Customization possible: `blue`, `gradient`, `tokyonight`, `dracula`

## Success Criteria

1. Profile displays stats correctly on page load
2. Stats update automatically daily (visible via git commit history)
3. Profile views counter increments on each visit
4. All cards load without errors
5. Mobile-responsive layout

## Out of Scope

- Custom website (github.io)
- GitHub Pages deployment
- Real-time WebSocket updates
- Custom widgets beyond standard libraries
