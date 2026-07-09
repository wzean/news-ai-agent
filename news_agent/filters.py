"""关键词过滤：黑名单优先、正向关键词命中即保留。

- 英文/数字关键词使用单词边界匹配，避免 "AI" 命中 "again" 之类的误伤。
- 中文等非 ASCII 关键词使用子串匹配。
"""
from __future__ import annotations

import logging
import re

from .models import Article

logger = logging.getLogger(__name__)

_ASCII_KW = re.compile(r"^[A-Za-z0-9 &\.\-\+/]+$")


def _matches(keyword: str, text_lower: str, text_raw: str) -> bool:
    kw = (keyword or "").strip()
    if not kw:
        return False
    if _ASCII_KW.match(kw):
        return re.search(r"\b" + re.escape(kw.lower()) + r"\b", text_lower) is not None
    return kw in text_raw


def filter_article(article: Article, include_groups: dict, exclude_list: list) -> bool:
    """返回是否保留该文章；保留时把命中的关键词写入 article.matched_keywords。"""
    text_raw = f"{article.title} {article.raw_summary}"
    text_lower = text_raw.lower()

    # 1) 黑名单命中 -> 直接丢弃
    for kw in exclude_list or []:
        if _matches(kw, text_lower, text_raw):
            return False

    # 2) 未配置正向词池 -> 只做黑名单过滤，全部保留
    if not include_groups:
        return True

    # 3) 正向词池：命中任一即保留
    matched: list[str] = []
    for _group, kws in include_groups.items():
        for kw in kws or []:
            if _matches(kw, text_lower, text_raw):
                matched.append(kw)

    if not matched:
        return False

    seen: set[str] = set()
    uniq: list[str] = []
    for k in matched:
        if k.lower() not in seen:
            seen.add(k.lower())
            uniq.append(k)
    article.matched_keywords = uniq
    return True
