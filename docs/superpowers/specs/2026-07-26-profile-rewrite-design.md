# GitHub Profile 全面重写设计文档

**日期：** 2026-07-26
**项目：** jieefeng/jieefeng GitHub Profile README
**方案：** 方案 B — 全面重写（Python + Jinja2）

---

## 1. 目标

将 GitHub Profile 项目全面重写，解决四个核心痛点：
1. **外部依赖不稳定** — 将所有动态内容通过 GitHub Actions 本地生成 SVG
2. **工作流代码难维护** — 用 Python + Jinja2 替代 525 行 shell heredoc
3. **内容不够丰富** — 新增项目展示区、博客链接区、学习路线区
4. **视觉设计待提升** — 统一卡片设计语言，优化排版和动画

## 2. 项目结构

```
jieefeng/
├── README.md                    # 主 profile 页面（重写）
├── assets/                      # 生成的 SVG 卡片（git-tracked）
│   ├── stats-card.svg / stats-card-light.svg
│   ├── langs-card.svg / langs-card-light.svg
│   ├── achievements-card.svg / achievements-card-light.svg
│   ├── views-card.svg / views-card-light.svg
│   ├── typing.svg / typing-light.svg           # 新：本地打字动画
│   ├── skills-card.svg / skills-card-light.svg # 新：本地技术栈
│   ├── activity-card.svg / activity-card-light.svg # 新：本地贡献热力图
│   ├── pinned-card.svg / pinned-card-light.svg # 新：置顶项目
│   └── blog-card.svg / blog-card-light.svg     # 新：博客链接
├── templates/                   # Jinja2 SVG 模板
│   ├── stats.svg.j2
│   ├── langs.svg.j2
│   ├── achievements.svg.j2
│   ├── views.svg.j2
│   ├── typing.svg.j2
│   ├── skills.svg.j2
│   ├── activity.svg.j2
│   ├── pinned.svg.j2
│   └── blog.svg.j2
├── scripts/
│   ├── generate_cards.py        # 主生成脚本
│   ├── github_api.py            # GitHub API 数据获取
│   └── requirements.txt         # jinja2
├── .github/
│   └── workflows/
│       ├── update-stats.yml     # 重写：调用 Python 脚本
│       └── snake.yml            # 保持不变
└── docs/
    └── superpowers/
        └── specs/
```

## 3. GitHub Actions 工作流

重写 `update-stats.yml`，从 525 行 shell heredoc 简化为 ~25 行 YAML + Python 脚本：

```yaml
name: Update GitHub Stats

on:
  schedule:
    - cron: '0 1 * * *'
  workflow_dispatch:
  push:
    branches: [main]
    paths:
      - 'scripts/**'
      - 'templates/**'
      - '.github/workflows/update-stats.yml'

jobs:
  update-stats:
    runs-on: ubuntu-latest
    permissions:
      contents: write
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - run: pip install -r scripts/requirements.txt
      - env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: python scripts/generate_cards.py
      - run: |
          git config --local user.email "action@github.com"
          git config --local user.name "GitHub Action"
          git diff --quiet || (git add assets/ && git commit -m "chore: update stats cards [skip ci]" && git push)
```

`snake.yml` 保持不变。

## 4. 外部依赖本地化

| 当前外部服务 | 本地化方案 |
|---|---|
| readme-typing-svg (demolab.com) | 本地 SVG + CSS `<animate>` 打字效果 |
| skillicons.dev | 本地生成技术栈 SVG badge |
| github-readme-activity-graph (vercel.app) | 本地生成贡献热力图 SVG |
| komarev.com/ghpvc | 已本地化，保持 |
| shields.io (MinIO badge) | 内联 SVG badge |

### 4.1 打字动画

- SVG `<text>` + `<animate>` 实现逐字显示
- 三行循环：`AI 工程师 | RAG 探索者` → `全栈开发 | 后端架构师` → `Always building, always learning`
- 每行显示 3 秒，间隔 1.5 秒
- dark/light 通过 `<picture>` 切换

### 4.2 技术栈

- 圆角矩形 badge + 文字标签，shields.io 风格
- 技术列表：Python, Java, TypeScript, Vue, Spring, MySQL, Redis, RabbitMQ, Kafka, Docker, Linux, Git, LangChain, MinIO
- 排列为多行居中布局

### 4.3 贡献热力图

- GraphQL contributionCalendar 最近 52 周数据
- amber 色系梯度：#FEF3C7 → #FDE68A → #F59E0B → #92400E
- 7 行 × 53 列网格，与 GitHub 贡献图风格一致

## 5. 新增内容模块

### 5.1 置顶项目展示 (Pinned Repos)

- GraphQL 查询 `pinnedItems` 获取置顶仓库
- 每个项目显示：名称、描述、星标数、主要语言、链接
- 卡片式布局，2 列排列

### 5.2 博客/文章链接

- 静态配置（硬编码在模板或脚本中）
- 显示博客名称 + 链接 badge
- 预留扩展性，后续可接入 RSS

### 5.3 学习路线/目标

- 静态配置
- 用进度条 SVG 展示当前学习方向和进度
- 内容：RAG 深入、系统设计、云原生

## 6. 视觉设计系统

### 6.1 配色方案

保持现有 amber 色系，统一为设计 token：

| Token | Dark | Light |
|---|---|---|
| bg-primary | #0D1117 | #FFFBEB |
| bg-secondary | #161B22 | #FEF3C7 |
| bg-card | #1C2128 | #FFFFFF |
| border | #30363d | #E5E7EB |
| text-primary | #FDE68A | #92400E |
| text-secondary | #8B949E | #6B7280 |
| accent | #D97706 | #D97706 |
| accent-light | #F59E0B | #F59E0B |
| accent-dark | #92400E | #92400E |

### 6.2 卡片设计规范

- 圆角：12px
- 边框：1.5px gradient（amber 色系）
- 阴影：feDropShadow amber 0.2 opacity
- 内边距：20px
- 标题：16px font-weight 600，居中
- 数值：28px font-weight 700
- 标签：11px，text-secondary

### 6.3 README 布局顺序

1. 头部（头像 + 名字 + 打字动画 + 简介）
2. 社交链接
3. 数据统计（achievements card）
4. 技术栈（skills card）
5. 正在做什么
6. 置顶项目（pinned card）
7. GitHub 统计（stats + langs）
8. 贡献热力图（activity card）
9. 博客/文章链接（blog card）
10. 学习路线/目标
11. 贡献蛇形动画
12. 访客统计
13. 页脚

## 7. Python 脚本设计

### 7.1 github_api.py

```python
# 使用 subprocess 调用 gh CLI（GitHub Actions 预装）
def fetch_user_data() -> dict:
    # GraphQL 查询：用户信息 + 贡献日历、语言
    # 返回统一数据结构

def fetch_pinned_repos() -> list[dict]:
    # GraphQL 查询 pinnedItems
    # 返回 [{name, description, stargazers_count, primary_language, url}]
```

### 7.2 generate_cards.py

```python
# 伪代码
from jinja2 import Environment, FileSystemLoader
from github_api import fetch_user_data, fetch_pinned_repos

env = Environment(loader=FileSystemLoader('templates'))
data = fetch_user_data()
pinned = fetch_pinned_repos()

cards = {
    'stats': data,
    'langs': data['languages'],
    'achievements': data,
    'views': data['views'],
    'typing': {},
    'skills': {},
    'activity': data['contributions'],
    'pinned': pinned,
    'blog': {},
}

for name, card_data in cards.items():
    template = env.get_template(f'{name}.svg.j2')
    for theme in ['dark', 'light']:
        svg = template.render(**card_data, theme=theme)
        suffix = '' if theme == 'dark' else '-light'
        Path(f'assets/{name}-card{suffix}.svg').write_text(svg)
```

## 8. 实施步骤

1. 创建 `scripts/` 目录和 Python 脚本
2. 创建 `templates/` 目录和 Jinja2 模板
3. 重写 `update-stats.yml` 工作流
4. 重写 `README.md`
5. 本地测试验证
6. 提交并推送

## 9. 风险与缓解

| 风险 | 缓解 |
|---|---|
| SVG `<animate>` 在 GitHub README 中不支持 | 降级为静态文字，保留动画作为可选 |
| Python 脚本在 Actions 中执行失败 | 添加错误处理和 fallback（保留旧 SVG） |
| GraphQL API 限流 | 使用 GITHUB_TOKEN（5000 req/hr），单次运行 < 10 请求 |
| Jinja2 模板渲染异常 | 添加 try/except，失败时跳过该卡片 |
