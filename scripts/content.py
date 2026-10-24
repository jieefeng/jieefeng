"""Static content for the hand-authored cards (quest log, inventory).

Only the parkour card is data-driven; these two are editorial: the numbers
below are *levels and progress the profile owner chose to publish*, not
anything fetched from the GitHub API. Keeping them here — instead of inside
the Jinja templates — means the "what I'm working on" copy can be edited
without touching layout code.
"""

from __future__ import annotations

# --- 任务日志 ---------------------------------------------------------------
#
# kind: MAIN = 当前主线, SIDE = 支线/学习; status rides along as a chip.
# progress is 0-100 and is drawn as a bar, so keep it honest-ish, not exact.

QUESTS: list[dict] = [
    {
        "kind": "MAIN",
        "title": "RAG 检索链路优化",
        "detail": "召回 · 重排 · 评估闭环",
        "progress": 72,
        "status": "进行中",
    },
    {
        "kind": "MAIN",
        "title": "后端服务工程化",
        "detail": "可观测 · 稳定性 · 部署流水线",
        "progress": 58,
        "status": "进行中",
    },
    {
        "kind": "SIDE",
        "title": "Embedding 调优 · 系统设计 · 云原生",
        "detail": "每天攒一点技能点",
        "progress": 41,
        "status": "学习中",
    },
]

# Footer line of the quest card: what the owner is happy to be pinged about.
COOP_LINE = "开放组队：Python / Java 后端 · RAG 落地 · 全栈开发"

# --- 装备栏 ---------------------------------------------------------------
#
# rarity drives the slot colour and the label under the name:
#   legendary / epic / rare / common
# level (0-100) drives the five pips, so 90 -> five pips, 45 -> two.
# Order matters: the grid is filled left to right, strongest first.

INVENTORY: list[dict] = [
    {"name": "Python", "rarity": "legendary", "level": 90},
    {"name": "Java", "rarity": "epic", "level": 82},
    {"name": "Git", "rarity": "epic", "level": 80},
    {"name": "TypeScript", "rarity": "epic", "level": 76},
    {"name": "Spring", "rarity": "rare", "level": 74},
    {"name": "MySQL", "rarity": "rare", "level": 70},
    {"name": "Vue", "rarity": "rare", "level": 68},
    {"name": "Redis", "rarity": "rare", "level": 66},
    {"name": "Docker", "rarity": "rare", "level": 64},
    {"name": "LangChain", "rarity": "common", "level": 62},
    {"name": "Linux", "rarity": "common", "level": 60},
    {"name": "RabbitMQ", "rarity": "common", "level": 58},
    {"name": "Kafka", "rarity": "common", "level": 55},
    {"name": "MinIO", "rarity": "common", "level": 45},
]

# --- 今日签 ---------------------------------------------------------------
#
# One (宜, 忌) pair per day, picked deterministically from the date, so the
# strip is different every morning without any randomness at render time.
# Keep both halves short: the card is one line tall.

DAILY_PAIRS: list[tuple[str, str]] = [
    ("重构旧代码", "周五晚上线"),
    ("补一个测试", "直接 push 到 main"),
    ("读源码", "凭感觉调参"),
    ("写清注释", "相信昨天的自己"),
    ("拆小 PR", "一次改 40 个文件"),
    ("备份数据库", "手滑 rm -rf"),
    ("提前画时序图", "边写边想架构"),
    ("清理死代码", "注释掉就当删了"),
    ("量化评估", "拍脑袋调 prompt"),
    ("早睡", "凌晨改线上配置"),
    ("给同事点个赞", "在群里口头报 bug"),
    ("关掉通知专注两小时", "会议里偷偷改代码"),
]
