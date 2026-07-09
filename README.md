# 📰 News AI Agent · 每日外媒新闻 AI 简报

自动抓取 **CNA / The Economist / SCMP / The Times / CNBC / 联合早报** 指定板块（科技·金融·财经·政治）新闻，
按关键词过滤去重后，调用 **Google Gemini** 生成「**开篇今日总结（中英双语）** + 每条**中英对照**摘要 + 核心关键词 + 关键段落中文翻译」，
统一排版成 HTML 简报邮件推送到你的邮箱。

全流程 **开源、配置驱动、轻量易部署**：GitHub Actions 免服务器**双时区定时**（北京 09:20 + 纽约 09:20）运行，或 Docker 一键自托管。

---

## ✨ 特性一览

| 需求 | 实现方式 |
| --- | --- |
| 定时自动抓取 | GitHub Actions `cron`（**双时区守卫**）/ Docker 常驻 `schedule` |
| 双时区定时 | **北京 09:20 + 纽约 09:20** 各推一次，自动处理夏令时（DST） |
| 多媒体多板块 | `config.yaml` 内配置，支持 **直连 RSS + Google News + HTML 版块页直抓** 三种方式 |
| 联合早报（无 RSS） | **直抓版块页 HTML** 提取中文标题（Google News 无法解析其标题时的方案） |
| 关键词过滤 | 正向关键词池（分组）+ 黑名单；英文单词边界匹配、中文子串匹配 |
| 去重 / 去旧闻 | 跨天指纹库 `data/seen.json` + 同批次标题归一化去重（**两次推送不重复**） |
| 今日总结 | 开篇一段 **中英双语** 概括当天主题趋势 |
| 中英对照 | 每条：🔖中文标题 → `EN`英文摘要 → `中`中文摘要 → 中文要点 → 关键词 |
| AI 文本处理 | Google Gemini：英文摘要 + 中文翻译 + 关键词 + 标题翻译 + 今日总结 |
| 邮件分发 | SMTP（SSL/STARTTLS），HTML **分媒体 / 分板块** 展示 |
| 异常处理 | 抓取重试退避、Gemini 限流重试、邮件重试、无匹配时空白通知 |
| 易扩展 | 新增媒体 / 增减关键词 **只改 `config.yaml`，不动代码** |
| 部署 | GitHub 托管 · Docker 一键 · 无需数据库 |

---

## 🧭 工具选型结论：n8n vs OpenClaw（以及本项目的取舍）

**先给结论：** 你的判断正确 —— 对「每日固定新闻简报」这类**标准化、定时、批量流水线**任务，
**n8n 明显优于 OpenClaw**。OpenClaw 是自主决策型 AI 智能体框架，强在多轮对话、长期记忆、动态任务，
但缺少成熟的 RSS/邮件模板，抓取·筛选·排版都要自研 Skill，定时批处理的稳定性与易用性都不如 n8n。

**但更进一步：** 结合你的核心约束——「**整套代码托管 GitHub、轻量化、Docker 一键、开源可维护、
增减媒体/关键词无需大改**」——本项目采用了**比 n8n 更贴合的方案：一个轻量 Python Agent + GitHub Actions/Docker**。

| 维度 | n8n | OpenClaw | 本项目（Python Agent） |
| --- | --- | --- | --- |
| 定时批量新闻流水线 | ✅ 成熟 | ⚠️ 需自研 | ✅ 成熟 |
| RSS / 邮件 / 定时 | ✅ 现成节点 | ❌ 缺模板 | ✅ 代码内置 |
| Gemini 深度控制（JSON结构化、限流重试） | ⚠️ 靠 Function 节点写 JS | ⚠️ 自研 | ✅ 原生精细控制 |
| GitHub 版本管理 | ⚠️ 导出 JSON（diff 难读） | ⚠️ | ✅ 纯代码，diff 清晰 |
| 免服务器定时 | ❌ 需常驻实例 | ❌ | ✅ GitHub Actions 免费 cron |
| 去重/中文翻译/复杂排版 | ⚠️ 多个 Function 节点拼 | ⚠️ | ✅ 直接实现 |
| 上手可视化 | ✅ 拖拽直观 | ⚠️ | ⚠️ 需读代码 |

> 一句话：**若偏爱可视化拖拽 → 选 n8n**；**若要 GitHub 原生托管、免服务器、精细可控、最易维护 → 用本项目**。
> 两者不冲突：本仓库的 `config.yaml` 逻辑也可以直接映射成一条 n8n 工作流（见文末「迁移到 n8n」）。

---

## 🏗️ 架构与流程

```text
                       ┌────────────── 触发 ──────────────┐
                       │ GitHub Actions cron / Docker 定时 │
                       │  北京 09:20  +  纽约 09:20（DST） │
                       └───────────────┬──────────────────┘
                                       ▼
   config.yaml ──►  ① 抓取 fetcher     RSS + Google News + HTML 版块页（重试/超时/UA）
                    ② 过滤 filters      正向关键词池 + 黑名单（板块归属）
                    ③ 去重 dedup        跨天指纹库 + 同批标题去重 + 时间窗（两次不重复）
                    ④ 摘要 summarizer   Gemini：今日总结 + 中英对照摘要 + 关键词 + 中文要点
                    ⑤ 排版 report       Jinja2 HTML（今日总结 + 分媒体/分板块卡片）
                    ⑥ 发送 emailer      SMTP（SSL/STARTTLS）→ 你的邮箱
```

### 目录结构

```text
.
├── news_agent/
│   ├── config.py          # 读取 .env 与 config.yaml
│   ├── models.py          # Article 数据模型（含 summary_zh 中英对照字段）
│   ├── fetcher.py         # 抓取（RSS / Google News / HTML 版块页，含重试与 SSL 开关）
│   ├── filters.py         # 关键词过滤
│   ├── dedup.py           # 去重指纹库
│   ├── summarizer.py      # Google Gemini 摘要/翻译 + 今日总结
│   ├── report.py          # 分组 + HTML/文本排版（今日总结 + 中英对照）
│   ├── emailer.py         # SMTP 发送
│   ├── scheduler.py       # 双时区定时（北京/纽约 09:20）+ Actions 守卫（DST 感知）
│   ├── main.py            # 主流程编排
│   └── templates/email.html.j2
├── config.yaml            # ★ 媒体 / 板块 / 关键词 / 定时计划（改这里即可）
├── run.py                 # 命令行入口
├── requirements.txt
├── Dockerfile / docker-compose.yml
├── .github/workflows/daily-news.yml   # 免服务器双时区定时
├── .env.example
└── README.md
```

---

## 🚀 快速开始（本地 · Windows PowerShell）

```powershell
# 1) 创建虚拟环境并安装依赖
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 2) 准备配置
Copy-Item .env.example .env
notepad .env          # 填入 GEMINI_API_KEY 与 SMTP 邮件信息

# 3) 先干跑（不发邮件，仅生成 output/preview.html 预览排版）
python run.py --dry-run

# 4) 小样真跑（真实调用 Gemini + 发邮件，只处理前 8 条，省额度）
python run.py --limit 8

# 5) 正式跑一次（全量，发送邮件）
python run.py
```

命令行参数：

| 参数 | 作用 |
| --- | --- |
| `--dry-run` | 不发邮件，仅生成 `output/preview.html` 预览 |
| `--no-gemini` | 跳过 Gemini，用原文摘要兜底（免额度快速验证抓取/排版） |
| `--limit N` | 只处理前 N 条（省 Gemini 额度的真实测试） |
| `--schedule` | 常驻，按 `config.yaml` 的计划每日定时执行（Docker 用） |
| `--respect-schedule` | 仅当当前时刻命中计划窗口才执行（GitHub Actions 守卫用） |

> 想快速验证抓取与排版但不想耗 Gemini 额度？用 `python run.py --dry-run --no-gemini`。

---

## 🔑 获取密钥

### Google Gemini API Key
1. 打开 <https://aistudio.google.com/apikey> → **Create API key**。
2. 复制填入 `.env` 的 `GEMINI_API_KEY`。

> ⚠️ **重要：免费额度限制（RPD = 每日请求数）**
> `gemini-2.5-flash` 免费层约 **20 次/天**。本 Agent 每条新闻调用 1 次 + 今日总结 1 次。
> 因此：
> - **免费玩法**：把 `config.yaml` 的 `max_items_total` 设小（如 **8**），单次约 9 调用，一天两推≈18 次，勉强够用；
> - **推荐（每天两推 + 数十条）**：在 Google Cloud 为该项目 **开启结算（billing）** 走随用随付。
>   `flash` 系列极便宜——40 条 × 2 次/天 × 30 天 ≈ **每月 $1~2**。
> - 也可换更省的模型：`gemini-2.5-flash-lite`（免费 RPD 更高）。
> 额度用尽时 Agent 会自动退避重试，仍失败则**用原文摘要兜底**（不会崩，但那几条无中英对照）。

### DeepSeek API Key（可选，更便宜约 9 倍）

本项目内置 **LLM 供应商开关**，可在 Gemini / DeepSeek 之间随时切换，**无需改代码**。

1. 打开 <https://platform.deepseek.com/api_keys> → 创建 Key（DeepSeek **无免费额度**，需先小额充值，最低约 ¥10）。
2. 在 `.env` 填入：`DEEPSEEK_API_KEY=...` 且 `LLM_PROVIDER=deepseek`（或在 `config.yaml` 设 `llm.provider: deepseek`）。
3. 切回 Gemini 只需把 `LLM_PROVIDER` 改回 `gemini`（或删掉该行）。

**为什么便宜**：本 Agent 是「输出密集型」（英文摘要 + 中文翻译 + 中文要点），
而 `gemini-2.5-flash` 输出 **$2.50/1M**（含思考 token），DeepSeek 输出仅 **$0.28/1M**。

| 供应商 / 模型 | 输入 $/1M | 输出 $/1M | 免费额度 | 全量(约50条/天)月成本 |
| --- | --- | --- | --- | --- |
| `gemini-2.5-flash` | 0.30 | 2.50 | 有(约20次/天) | ≈ $3~8（¥22~58） |
| `gemini-2.5-flash-lite` | 0.10 | 0.40 | 有(RPD更高) | ≈ $0.6（¥5） |
| `deepseek-chat`（V4-Flash） | 0.14 | 0.28 | 无，需充值 | ≈ $0.35（¥3） |

> 结论：无论哪个都是「每月几块钱」级别。追求最便宜选 DeepSeek；想保留免费额度就用 `gemini-2.5-flash-lite`。

### 邮箱 SMTP（以 Gmail 为例）
1. 开启 Google 账号 **两步验证**。
2. 生成 **应用专用密码（App Password）**：<https://myaccount.google.com/apppasswords>。
3. 填入 `.env`：`SMTP_HOST=smtp.gmail.com`、`SMTP_PORT=465`、`SMTP_USE_SSL=true`、
   `SMTP_USER`/`MAIL_FROM` 为你的 Gmail、`SMTP_PASSWORD` 为 16 位应用密码、`MAIL_TO` 为收件邮箱（多个用逗号分隔）。
> Outlook/企业邮箱同理，改成对应 `SMTP_HOST/PORT` 即可（587 端口会自动走 STARTTLS）。

---

## 🐳 方式 A：Docker 一键自托管（常驻定时）

```bash
cp .env.example .env      # 填好密钥
docker compose up -d      # 后台常驻，按 config.yaml 的计划每日执行（北京/纽约 09:20）
docker compose logs -f    # 查看日志
```

- 改 `config.yaml` **即时生效**（已挂载为只读卷），无需重建镜像。
- 去重记录持久化在 `./data`。修改推送时间/时区：改 `config.yaml` 的 `settings.schedules`。
- 想容器启动即先跑一次验证：把 `docker-compose.yml` 的 `RUN_ON_START` 设为 `"true"`。

## ☁️ 方式 B：GitHub Actions 免服务器双时区定时（推荐）

**Step 1 — 推送到 GitHub**（详见下方「📤 推送到 GitHub 完整步骤」）。

**Step 2 — 配置 Secrets**：仓库 **Settings → Secrets and variables → Actions → New repository secret**，逐个添加：

| Secret 名 | 值（示例） |
| --- | --- |
| `GEMINI_API_KEY` | 你的 Gemini Key |
| `SMTP_HOST` | `smtp.gmail.com` |
| `SMTP_PORT` | `465` |
| `SMTP_USER` | 你的 Gmail |
| `SMTP_PASSWORD` | 16 位应用专用密码 |
| `SMTP_USE_SSL` | `true` |
| `MAIL_FROM` | 你的 Gmail |
| `MAIL_TO` | 收件邮箱（多个用逗号分隔） |

（可选 Variable：`MAIL_SUBJECT_PREFIX`。）

> **想用 DeepSeek？** 再加一个 Secret `DEEPSEEK_API_KEY`，并在
> **Settings → Secrets and variables → Actions → Variables** 里新建 Variable
> `LLM_PROVIDER=deepseek` 即可（改回 `gemini` 或删除该 Variable 即切回）。

**Step 3 — 定时如何工作**：工作流 `.github/workflows/daily-news.yml` 配了 3 条 UTC `cron`，
经 `--respect-schedule` 守卫，只有落在 **北京 09:20 / 纽约 09:20**（含夏令时切换）窗口的那条才真正执行：

| cron (UTC) | 对应本地 | 命中场景 |
| --- | --- | --- |
| `20 1 * * *` | 北京 09:20 | 全年 |
| `20 13 * * *` | 纽约 09:20 | 夏令时(EDT) |
| `20 14 * * *` | 纽约 09:20 | 冬令时(EST) |

- 也可在 **Actions** 页手动 `Run workflow` 立即触发（手动触发**无视守卫**，直接执行，方便验证）。
- 两次推送靠 **Actions cache 保存的去重库** 保证**内容不重复**（第二次只发第一次之后的新增新闻）。
- 改时间/时区：编辑 `config.yaml` 的 `settings.schedules`，并让 workflow 的 `cron` 覆盖到对应 UTC 时刻。

> 无需任何服务器，GitHub 免费额度即可稳定跑；注意 Gemini 免费额度（见上文），量大建议开结算。

---

## ⚙️ 配置说明（`config.yaml`）

### 新增 / 删除媒体
在 `sources:` 下追加一个条目即可（**无需改代码**）。支持三种抓取方式：

```yaml
  - name: "Reuters"
    enabled: true
    feeds:
      - section: "Markets"
        type: "rss"                         # ① 直连 RSS
        url: "https://feeds.reuters.com/reuters/marketsNews"
      - section: "Tech"
        type: "google_news"                 # ② 无稳定 RSS 时用 Google News 站内检索兜底
        query: "site:reuters.com (technology OR semiconductor OR AI)"
        lang: "en-US"
        country: "US"
      - section: "财经"
        type: "html"                        # ③ 直抓版块页 HTML（如联合早报，无 RSS 且 GNews 无标题）
        url: "https://www.zaobao.com.sg/realtime/finance"
        # 可选：link_pattern 自定义文章链接正则（默认匹配 /story\d{6,} 或 8位日期串）
```

- `type: rss` 直连 RSS；`type: google_news` 站内检索（适合付费墙/无 RSS）；`type: html` 直抓版块页并按链接正则提取标题（适合无 RSS 且 Google News 无法解析标题的站点，如**联合早报**）。
- 临时停用某媒体：把 `enabled` 改成 `false`。

### 增减关键词
编辑 `keywords.include`（正向池，可分组）与 `keywords.exclude`（黑名单）。

- 英文/数字词自动按**单词边界**匹配（`AI` 不会误命中 `again`）。
- 中文词按**子串**匹配。命中任一正向词即保留；命中任一黑名单词即丢弃。

### 定时计划（`settings.schedules`）
```yaml
settings:
  schedules:
    - tz: "Asia/Shanghai"       # 北京时间 09:20
      time: "09:20"
    - tz: "America/New_York"    # 纽约时间 09:20（自动夏令时）
      time: "09:20"
  schedule_tolerance_minutes: 30   # GitHub cron 可能延迟，±30 分钟内视为命中
```

- 加一个时区推送：在 `schedules` 再追加一项（如 `Europe/London`），并在 workflow 里补一条对应 UTC 的 `cron`。
- `tz` 用 IANA 时区名（`Asia/Shanghai`、`America/New_York`、`Asia/Singapore`…），夏令时自动处理。

### 常用开关（`settings`）

| 项 | 含义 |
| --- | --- |
| `lookback_hours` | 只保留最近 N 小时内的新闻（默认 36） |
| `max_items_per_feed` | 每个板块最多保留条数 |
| `max_items_total` | 全局上限，**直接决定 Gemini 调用量/成本**（免费额度建议设 8） |
| `dedup_retention_days` | 去重记录保留天数 |
| `send_empty_notification` | 无匹配新闻时是否仍发「空白通知」邮件 |
| `schedules` | 每日定时计划（时区 + 时刻），Docker 与 Actions 守卫共用 |

---

## 🛡️ 异常处理设计
- **抓取失败**：`requests` 指数退避重试 3 次；单个 feed 失败仅记录日志、不影响其它源。
- **API 限流**：Gemini 调用识别 `429/quota/resource_exhausted/503` 等，做更长退避重试；单条失败用原文兜底。
- **邮件失败**：SMTP 发送重试 3 次，仍失败则记录并安全保存去重库。
- **无匹配新闻**：发送简洁「今日无匹配新闻」空白通知（可在 `settings` 关闭）。
- **去重库损坏**：自动重建，不中断流程。

---

## 🧪 常见问题
- **Economist/SCMP 某源抓不到？** 可能被风控。把该 feed 的 `type` 改为 `google_news` 并写 `site:域名 (关键词)` 兜底。
- **联合早报没内容？** 它无公开 RSS 且 Google News 无法解析其标题，本项目已用 `type: html` 直抓版块页；若版块 URL 改版，更新 `config.yaml` 里对应 `url` 即可。
- **邮件里很多条没有中英对照？** 多半是 **Gemini 免费额度（约 20 次/天）用尽**，触发兜底。解决：调小 `max_items_total`、或开结算、或换 `gemini-2.5-flash-lite`、或 **切到 DeepSeek**（`LLM_PROVIDER=deepseek`，便宜约 9 倍）。
- **收不到邮件？** 先 `python run.py --dry-run` 看 `output/preview.html` 是否有内容；再检查 SMTP 是否用的是**应用专用密码**、端口与 SSL 是否匹配、垃圾箱是否拦截。
- **公司网络本地测试报证书错误？** 在 `.env` 设 `VERIFY_SSL=false`（仅本地测试）或 `CA_BUNDLE=公司根证书路径`。GitHub Actions / Docker 无此问题。
- **想更省成本？** 调低 `max_items_total`、把 `gemini.model` 换成更轻量的 flash-lite 版本。

---

## 📤 推送到 GitHub 完整步骤

> ⚠️ 先确认 `.gitignore` 已忽略 `.env`（本项目已配置）——**绝不要把 API Key / 邮箱密码提交上去**。

```powershell
# 在项目根目录执行
cd "c:\Users\zeanwang\OneDrive - Advanced Micro Devices Inc\Downloads\person"

git init
git add .
git status                       # 确认列表里没有 .env（只应有 .env.example）
git commit -m "News AI Agent: 双时区定时 + 中英对照 + 今日总结"

# 在 GitHub 网页新建一个空仓库（不要勾选 README），拿到地址后：
git branch -M main
git remote add origin https://github.com/<你的用户名>/<仓库名>.git
git push -u origin main
```

推送后：

1. 按上文 **方式 B · Step 2** 添加 8 个 Secrets。
2. 进 **Actions** 页，若提示启用工作流就点启用。
3. 点 **Daily News Brief → Run workflow** 手动触发一次，验证能收到邮件。
4. 之后每天 **北京 09:20 / 纽约 09:20** 自动推送，无需服务器。

> 如果 `.env` 曾被误加入：`git rm --cached .env` 后重新提交；若已 push，请**立即在对应平台吊销并更换**该 Key/密码。

---

## 🔁 迁移到 n8n（如果你更想要可视化）
本仓库逻辑与 n8n 工作流一一对应，可按此重建：
`Cron 触发` → `RSS Read（每个源一个节点）/HTTP Request` → `Function（关键词过滤+去重）`
→ `Google Gemini（HTTP/社区节点，返回 JSON）` → `Function（分组排版 HTML）` → `Send Email（Gmail/SMTP）`。
把导出的 workflow JSON 一并提交到本仓库做版本管理即可。

---

## 📄 License
MIT © 2026
