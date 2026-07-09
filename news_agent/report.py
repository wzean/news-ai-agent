"""简报排版：按 媒体 -> 板块 分组，渲染 HTML 与纯文本两种版本。"""
from __future__ import annotations

from collections import OrderedDict
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .models import Article


def group_articles(articles: list[Article]) -> "OrderedDict[str, OrderedDict[str, list[Article]]]":
    grouped: "OrderedDict[str, OrderedDict[str, list[Article]]]" = OrderedDict()
    for a in articles:
        grouped.setdefault(a.source, OrderedDict()).setdefault(a.section, []).append(a)
    return grouped


def render_html(articles: list[Article], meta: dict, template_dir: str) -> str:
    env = Environment(
        loader=FileSystemLoader(template_dir),
        autoescape=select_autoescape(["html", "xml", "j2"]),
    )
    tmpl = env.get_template("email.html.j2")
    return tmpl.render(grouped=group_articles(articles), meta=meta)


def render_text(articles: list[Article], meta: dict) -> str:
    lines: list[str] = [meta.get("title", "每日新闻简报"), ""]

    digest_zh = meta.get("digest_zh", "")
    digest_en = meta.get("digest_en", "")
    if digest_zh or digest_en:
        lines.append("【今日总结】")
        if digest_zh:
            lines.append(digest_zh)
        if digest_en:
            lines.append(digest_en)
        lines.append("")

    if meta.get("empty"):
        lines.append("今日暂无匹配关键词的新闻。")
        return "\n".join(lines)

    grouped = group_articles(articles)
    for source, sections in grouped.items():
        lines.append(f"=== {source} ===")
        for section, items in sections.items():
            lines.append(f"-- {section} --")
            for a in items:
                lines.append(f"• {a.title}")
                if a.title_zh:
                    lines.append(f"  {a.title_zh}")
                if a.english_summary:
                    lines.append(f"  EN: {a.english_summary}")
                if a.summary_zh:
                    lines.append(f"  中: {a.summary_zh}")
                for p in a.key_points_zh:
                    lines.append(f"    · {p}")
                if a.keywords:
                    lines.append(f"  Keywords: {', '.join(a.keywords)}")
                lines.append(f"  {a.url}")
                lines.append("")
        lines.append("")
    return "\n".join(lines)


def default_template_dir() -> str:
    return str(Path(__file__).parent / "templates")
