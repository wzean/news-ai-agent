"""编排主流程：抓取 -> 过滤 -> 去重 -> Gemini 摘要 -> 排版 -> 发送。"""
from __future__ import annotations

import logging
import os
import re
from collections import OrderedDict, deque
from datetime import datetime
from pathlib import Path

from . import report
from .config import load_config
from .dedup import DedupStore
from .emailer import send_email
from .fetcher import _verify_setting, fetch_feed
from .filters import filter_article
from .logging_conf import setup_logging
from .summarizer import build_summarizer

logger = logging.getLogger("news_agent")

_MAIL_KEYS = [
    "SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD",
    "MAIL_FROM", "MAIL_TO", "SMTP_USE_SSL",
]
_REQUIRED_MAIL_KEYS = ["SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "MAIL_TO"]


def _normalize_title(t: str) -> str:
    return re.sub(r"\W+", "", t.lower())[:80]


def _balanced_select(articles: list, max_total: int) -> list:
    """按媒体 round-robin 均衡挑选，保证每个媒体都有露出，再截断到 max_total。

    避免「按 max_items_total 顺序截断」导致排在最后的媒体（如联合早报）被整段丢掉。
    """
    if len(articles) <= max_total:
        return articles
    buckets: "OrderedDict[str, deque]" = OrderedDict()
    for a in articles:
        buckets.setdefault(a.source, deque()).append(a)
    result: list = []
    while len(result) < max_total and any(buckets.values()):
        for src in list(buckets.keys()):
            q = buckets[src]
            if q:
                result.append(q.popleft())
                if len(result) >= max_total:
                    break
    return result


def _collect(cfg: dict) -> list:
    settings = cfg.get("settings", {})
    lookback = int(settings.get("lookback_hours", 36))
    per_feed_cap = int(settings.get("max_items_per_feed", 15))

    articles = []
    for source in cfg.get("sources", []):
        if not source.get("enabled", True):
            continue
        name = source["name"]
        for feed in source.get("feeds", []):
            items = fetch_feed(name, feed, lookback)
            logger.info("抓取 %-14s / %-22s : %d 条", name, feed.get("section", ""), len(items))
            articles.extend(items[:per_feed_cap])
    logger.info("抓取合计: %d 条", len(articles))
    return articles


def _filter_and_dedup(cfg: dict, articles: list, store: DedupStore) -> list:
    include = (cfg.get("keywords", {}) or {}).get("include", {}) or {}
    exclude = (cfg.get("keywords", {}) or {}).get("exclude", []) or []

    kept = [a for a in articles if filter_article(a, include, exclude)]
    logger.info("关键词过滤后: %d 条", len(kept))

    seen_titles: set[str] = set()
    deduped = []
    for a in kept:
        if not store.is_new(a.uid):
            continue
        nt = _normalize_title(a.title)
        if nt in seen_titles:
            continue
        seen_titles.add(nt)
        deduped.append(a)
    logger.info("去重后: %d 条", len(deduped))

    max_total = int((cfg.get("settings", {}) or {}).get("max_items_total", 40))
    if len(deduped) > max_total:
        deduped = _balanced_select(deduped, max_total)
        logger.info("按 max_items_total 均衡截断为 %d 条（各媒体轮流保留）", len(deduped))
    return deduped


def _summarize(cfg: dict, articles: list, use_gemini: bool) -> dict:
    # 供应商切换：环境变量 LLM_PROVIDER 优先，其次 config.yaml 的 llm.provider，默认 gemini。
    provider = (
        os.getenv("LLM_PROVIDER")
        or (cfg.get("llm", {}) or {}).get("provider")
        or "gemini"
    ).strip().lower()
    if provider == "deepseek":
        sec = cfg.get("deepseek", {}) or {}
        api_key = os.getenv("DEEPSEEK_API_KEY")
        key_name = "DEEPSEEK_API_KEY"
        default_model = "deepseek-chat"
        default_interval = 1.0
        base_url = str(sec.get("base_url", "https://api.deepseek.com"))
    else:
        provider = "gemini"
        sec = cfg.get("gemini", {}) or {}
        api_key = os.getenv("GEMINI_API_KEY")
        key_name = "GEMINI_API_KEY"
        default_model = "gemini-2.5-flash"
        default_interval = 1.5
        base_url = ""

    summarizer = None
    if use_gemini and api_key and articles:
        summarizer = build_summarizer(
            provider=provider,
            api_key=api_key,
            model=str(sec.get("model", default_model)),
            temperature=float(sec.get("temperature", 0.3)),
            interval=float(sec.get("request_interval_seconds", default_interval)),
            max_retries=int(sec.get("max_retries", 4)),
            verify_ssl=_verify_setting(),
            base_url=base_url,
        )
        logger.info("使用 %s 模型: %s", provider, summarizer.model)
    elif use_gemini and not api_key:
        logger.warning("未配置 %s，跳过 AI 摘要，使用原文摘要兜底。", key_name)

    for idx, a in enumerate(articles, 1):
        if summarizer:
            logger.info("Gemini 处理 %d/%d: %s", idx, len(articles), a.title[:60])
            summarizer.summarize(a)
        else:
            a.english_summary = a.raw_summary[:280]
            a.keywords = a.matched_keywords

    digest = {"digest_en": "", "digest_zh": ""}
    if summarizer and articles:
        logger.info("生成今日总结（开篇导语）...")
        digest = summarizer.daily_digest(articles)
    elif articles:
        # 无 Gemini 时的兜底导语：统计各媒体条数
        counts = OrderedDict()
        for a in articles:
            counts[a.source] = counts.get(a.source, 0) + 1
        parts = "，".join(f"{k} {v} 条" for k, v in counts.items())
        digest = {
            "digest_en": "",
            "digest_zh": f"今日共筛选 {len(articles)} 条新闻：{parts}。",
        }
    return digest


def _send(cfg: dict, articles: list, dry_run: bool, digest: dict | None = None) -> None:
    settings = cfg.get("settings", {}) or {}
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    subject_prefix = os.getenv("MAIL_SUBJECT_PREFIX", "每日外媒新闻简报")
    digest = digest or {}
    meta = {
        "title": f"{subject_prefix} · {now_str}",
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "total": len(articles),
        "empty": len(articles) == 0,
        "digest_en": digest.get("digest_en", ""),
        "digest_zh": digest.get("digest_zh", ""),
    }
    html = report.render_html(articles, meta, report.default_template_dir())
    text = report.render_text(articles, meta)

    if dry_run:
        out = Path("output")
        out.mkdir(exist_ok=True)
        (out / "preview.html").write_text(html, encoding="utf-8")
        (out / "preview.txt").write_text(text, encoding="utf-8")
        logger.info("[dry-run] 已写入 output/preview.html（%d 条），未发送邮件。", len(articles))
        return

    if len(articles) == 0 and not settings.get("send_empty_notification", True):
        logger.info("无匹配新闻且未开启空白通知，跳过发送。")
        return

    env = {k: os.getenv(k) for k in _MAIL_KEYS}
    missing = [k for k in _REQUIRED_MAIL_KEYS if not env.get(k)]
    if missing:
        logger.error("缺少邮件配置 %s，跳过发送。请在 .env 或 GitHub Secrets 中设置。", missing)
        return
    send_email(html, text, meta["title"], env)


def run_once(config_path: str = "config.yaml", dry_run: bool = False,
             use_gemini: bool = True, limit: int = 0) -> int:
    """执行一次完整流程，返回本次处理的新闻条数。

    limit>0 时仅处理前 N 条（本地省额度测试用）。
    """
    cfg = load_config(config_path)
    setup_logging(os.getenv("LOG_LEVEL", "INFO"))
    logger.info("=============== 新闻 Agent 启动 ===============")

    settings = cfg.get("settings", {}) or {}
    store = DedupStore(
        settings.get("dedup_store", "data/seen.json"),
        int(settings.get("dedup_retention_days", 7)),
    )

    try:
        articles = _collect(cfg)
        deduped = _filter_and_dedup(cfg, articles, store)
        if limit and limit > 0 and len(deduped) > limit:
            deduped = deduped[:limit]
            logger.info("按 --limit 仅保留前 %d 条（测试模式）", limit)
        digest = _summarize(cfg, deduped, use_gemini)
        _send(cfg, deduped, dry_run, digest)

        if not dry_run:
            for a in deduped:
                store.mark(a.uid)
            store.prune()
            store.save()
        logger.info("=============== 完成，本次 %d 条 ===============", len(deduped))
        return len(deduped)
    except Exception:
        logger.exception("流程异常终止")
        if not dry_run:
            try:
                store.prune()
                store.save()
            except Exception:  # noqa: BLE001
                pass
        raise
