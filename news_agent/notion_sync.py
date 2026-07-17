"""Notion 同步：把每日新闻追加到「当月文档」，每月自动新建一篇。

结构：
  父页面（你在 .env 配 NOTION_PARENT_PAGE_ID）
   └─ 2026-07 每日新闻   ← 每月一个子页面（自动建）
        ## 2026-07-17    ← 每天追加一节
        • 新闻标题（媒体）…
        ## 2026-07-16
        ...

合规：Notion 是你个人知识库，Token 个人所有，从环境变量读，绝不入库/不碰公司环境。
免费：Notion 官方 Integration Token 免费。

环境变量：
  NOTION_TOKEN            —— Integration 的 secret（https://www.notion.so/my-integrations）
  NOTION_PARENT_PAGE_ID   —— 父页面 ID（把 Integration 分享给该页面）
可选：
  NOTION_SYNC_ENABLED=true/false  —— 总开关（默认 true，但缺 token 时自动跳过）
"""
from __future__ import annotations

import logging
import os
from datetime import datetime

import requests

logger = logging.getLogger("news_agent.notion")

API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {os.environ['NOTION_TOKEN']}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def _enabled() -> bool:
    if os.getenv("NOTION_SYNC_ENABLED", "true").lower() != "true":
        return False
    if not os.getenv("NOTION_TOKEN") or not os.getenv("NOTION_PARENT_PAGE_ID"):
        logger.info("未配置 NOTION_TOKEN / NOTION_PARENT_PAGE_ID，跳过 Notion 同步。")
        return False
    return True


def _find_monthly_page(parent_id: str, title: str) -> str | None:
    """在父页面的子块里找已存在的当月页面，返回其 page_id。"""
    url = f"{API}/blocks/{parent_id}/children?page_size=100"
    try:
        r = requests.get(url, headers=_headers(), timeout=30)
        r.raise_for_status()
        for blk in r.json().get("results", []):
            if blk.get("type") == "child_page":
                if blk["child_page"]["title"] == title:
                    return blk["id"]
    except Exception as e:  # noqa: BLE001
        logger.warning("查找当月 Notion 页面失败：%s", e)
    return None


def _create_monthly_page(parent_id: str, title: str) -> str | None:
    """在父页面下新建一个当月子页面，返回 page_id。"""
    payload = {
        "parent": {"page_id": parent_id},
        "properties": {
            "title": [{"type": "text", "text": {"content": title}}]
        },
    }
    try:
        r = requests.post(f"{API}/pages", headers=_headers(),
                          json=payload, timeout=30)
        r.raise_for_status()
        pid = r.json()["id"]
        logger.info("已新建 Notion 当月页面：%s", title)
        return pid
    except Exception as e:  # noqa: BLE001
        logger.warning("新建 Notion 当月页面失败：%s", e)
        return None


def _text(content: str, link: str | None = None) -> dict:
    rt: dict = {"type": "text", "text": {"content": content[:1900]}}
    if link:
        rt["text"]["link"] = {"url": link}
    return rt


def _build_blocks(articles: list, date_str: str, digest_zh: str = "") -> list[dict]:
    """构造当天要追加的块：一个日期二级标题 + 导语 + 每条新闻一个 bullet。"""
    blocks: list[dict] = [
        {"object": "block", "type": "heading_2",
         "heading_2": {"rich_text": [_text(date_str)]}},
    ]
    if digest_zh:
        blocks.append({"object": "block", "type": "quote",
                       "quote": {"rich_text": [_text(digest_zh)]}})

    for a in articles:
        title = getattr(a, "title_zh", "") or a.title
        rich = [_text(f"{title}", a.url)]
        src = getattr(a, "source", "")
        if src:
            rich.append(_text(f"（{src}）"))
        zh = getattr(a, "summary_zh", "")
        children = []
        if zh:
            children.append({"object": "block", "type": "paragraph",
                             "paragraph": {"rich_text": [_text(zh)]}})
        blk = {"object": "block", "type": "bulleted_list_item",
               "bulleted_list_item": {"rich_text": rich}}
        if children:
            blk["bulleted_list_item"]["children"] = children
        blocks.append(blk)
    return blocks


def _append_blocks(page_id: str, blocks: list[dict]) -> bool:
    """往页面末尾追加块（一次最多 100 个）。"""
    ok = True
    for i in range(0, len(blocks), 100):
        chunk = blocks[i:i + 100]
        try:
            r = requests.patch(f"{API}/blocks/{page_id}/children",
                               headers=_headers(),
                               json={"children": chunk}, timeout=30)
            r.raise_for_status()
        except Exception as e:  # noqa: BLE001
            logger.warning("追加 Notion 块失败：%s", e)
            ok = False
    return ok


def sync_daily(articles: list, digest_zh: str = "",
               now: datetime | None = None) -> bool:
    """把当天新闻追加到 Notion 当月文档。返回是否成功。"""
    if not _enabled():
        return False
    if not articles:
        logger.info("无新闻，跳过 Notion 同步。")
        return False

    now = now or datetime.now()
    parent_id = os.environ["NOTION_PARENT_PAGE_ID"]
    month_title = f"{now.strftime('%Y-%m')} 每日新闻"
    date_str = now.strftime("%Y-%m-%d %H:%M")

    page_id = _find_monthly_page(parent_id, month_title) \
        or _create_monthly_page(parent_id, month_title)
    if not page_id:
        return False

    blocks = _build_blocks(articles, date_str, digest_zh)
    ok = _append_blocks(page_id, blocks)
    if ok:
        logger.info("已同步 %d 条新闻到 Notion「%s」。", len(articles), month_title)
    return ok
