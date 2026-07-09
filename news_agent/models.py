"""数据模型。"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


@dataclass
class Article:
    """一条新闻及其 AI 加工结果。"""

    source: str                 # 媒体名，例如 "CNBC"
    section: str                # 板块名，例如 "Technology"
    title: str                  # 标题（原文）
    url: str                    # 原文链接
    published: Optional[datetime] = None  # 发布时间（UTC）
    raw_summary: str = ""       # RSS/网页摘要（已清洗 HTML）
    content: str = ""           # 可选：正文全文

    # —— Gemini 加工产物 ——
    english_summary: str = ""           # 英文精简摘要
    summary_zh: str = ""                # 英文摘要对应的中文翻译（中英对照）
    keywords: List[str] = field(default_factory=list)        # 核心关键词
    key_points_zh: List[str] = field(default_factory=list)   # 关键段落中文翻译
    title_zh: str = ""                                       # 标题中文翻译
    matched_keywords: List[str] = field(default_factory=list)  # 命中的过滤关键词

    @property
    def uid(self) -> str:
        """稳定唯一 ID（用于跨天去重）。"""
        base = (self.url or self.title).strip().lower()
        return hashlib.sha1(base.encode("utf-8")).hexdigest()

    @property
    def published_display(self) -> str:
        if self.published:
            return self.published.strftime("%Y-%m-%d %H:%M UTC")
        return ""
