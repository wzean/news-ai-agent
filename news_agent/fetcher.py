"""新闻抓取：支持直接 RSS 与 Google News 站内检索兜底，内置重试/超时/UA。"""
from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import quote_plus, urlparse

import feedparser
import requests
import urllib3
from bs4 import BeautifulSoup
from dateutil import parser as dateparser
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .models import Article

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 NewsAgent/1.0"
)


def _verify_setting():
    """requests 的 verify 参数：
    - 指定 CA_BUNDLE（企业根证书路径）-> 返回该路径（推荐，安全）
    - VERIFY_SSL=false -> 返回 False（仅供公司 SSL 拦截网络下本地测试，会关闭校验）
    - 默认 -> True
    """
    ca = os.getenv("CA_BUNDLE") or os.getenv("REQUESTS_CA_BUNDLE")
    if ca:
        return ca
    if str(os.getenv("VERIFY_SSL", "true")).lower() in ("0", "false", "no"):
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        return False
    return True


def build_google_news_url(query: str, lang: str = "en-US", country: str = "US",
                          when: str = "2d") -> str:
    """构造 Google News RSS 站内检索地址。"""
    q = f"{query} when:{when}"
    base_lang = lang.split("-")[0]
    ceid = f"{country}:{base_lang}"
    return (
        "https://news.google.com/rss/search?"
        f"q={quote_plus(q)}&hl={lang}&gl={country}&ceid={ceid}"
    )


@retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=12),
    retry=retry_if_exception_type((requests.RequestException,)),
)
def _download(url: str, timeout: int = 25) -> bytes:
    """带重试的下载（抓取失败自动退避重试）。"""
    resp = requests.get(
        url,
        headers={"User-Agent": USER_AGENT},
        timeout=timeout,
        verify=_verify_setting(),
    )
    resp.raise_for_status()
    return resp.content


def _clean_html(text: str) -> str:
    if not text:
        return ""
    soup = BeautifulSoup(text, "html.parser")
    return " ".join(soup.get_text(" ").split())


def _clean_gn_title(title: str) -> str:
    """Google News 标题常带 ' - 媒体名' 后缀，去掉它。"""
    if " - " in title:
        return title.rsplit(" - ", 1)[0].strip()
    return title


def _parse_date(entry) -> datetime | None:
    for key in ("published_parsed", "updated_parsed"):
        val = entry.get(key)
        if val:
            try:
                return datetime(*val[:6], tzinfo=timezone.utc)
            except Exception:  # noqa: BLE001
                pass
    for key in ("published", "updated"):
        val = entry.get(key)
        if val:
            try:
                dt = dateparser.parse(val)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.astimezone(timezone.utc)
            except Exception:  # noqa: BLE001
                pass
    return None


def fetch_feed(source_name: str, feed_cfg: dict, lookback_hours: int) -> list[Article]:
    """抓取单个 feed，返回时间窗口内的文章列表。失败不抛异常，返回空列表。"""
    ftype = feed_cfg.get("type", "rss")
    section = feed_cfg.get("section", "General")

    # HTML 版块页直抓（适合无 RSS / Google News 无法解析标题的站点，如联合早报）
    if ftype == "html":
        return _fetch_html(source_name, feed_cfg, lookback_hours)

    if ftype == "google_news":
        when = feed_cfg.get("when", f"{max(1, lookback_hours // 24)}d")
        url = build_google_news_url(
            feed_cfg["query"],
            feed_cfg.get("lang", "en-US"),
            feed_cfg.get("country", "US"),
            when,
        )
    else:
        url = feed_cfg["url"]

    try:
        content = _download(url)
    except Exception as exc:  # noqa: BLE001
        logger.error("抓取失败 [%s / %s]: %s", source_name, section, exc)
        return []

    parsed = feedparser.parse(content)
    if parsed.bozo and not parsed.entries:
        logger.warning("Feed 解析异常 [%s / %s]: %s", source_name, section,
                       getattr(parsed, "bozo_exception", ""))
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
    articles: list[Article] = []
    for entry in parsed.entries:
        title = str(entry.get("title") or "").strip()
        link = str(entry.get("link") or "").strip()
        if not title or not link:
            continue
        if ftype == "google_news":
            title = _clean_gn_title(title)
        published = _parse_date(entry)
        if published and published < cutoff:
            continue
        summary = _clean_html(str(entry.get("summary") or entry.get("description") or ""))
        articles.append(
            Article(
                source=source_name,
                section=section,
                title=title,
                url=link,
                published=published,
                raw_summary=summary,
            )
        )

    # 最新在前，方便 max_items_per_feed 截断时保留最新内容
    articles.sort(
        key=lambda a: a.published or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    return articles


def _origin(url: str) -> str:
    p = urlparse(url)
    return f"{p.scheme}://{p.netloc}"


def _date_from_url(href: str) -> datetime | None:
    """从形如 .../story20260707-9325605 的链接中解析日期。"""
    m = re.search(r"(20\d{2})(\d{2})(\d{2})", href)
    if m:
        try:
            y, mo, d = (int(x) for x in m.groups())
            return datetime(y, mo, d, tzinfo=timezone.utc)
        except Exception:  # noqa: BLE001
            return None
    return None


def _fetch_html(source_name: str, feed_cfg: dict, lookback_hours: int) -> list[Article]:
    """抓取版块 HTML 页，按链接正则提取文章标题/链接（适合联合早报等无 RSS 站点）。"""
    section = feed_cfg.get("section", "General")
    url = feed_cfg["url"]
    base = feed_cfg.get("base") or _origin(url)
    link_pat = re.compile(feed_cfg.get("link_pattern", r"/story\d{6,}|/\d{8}-\d+"))
    min_len = int(feed_cfg.get("min_title_len", 8))

    try:
        html = _download(url).decode("utf-8", "ignore")
    except Exception as exc:  # noqa: BLE001
        logger.error("抓取失败 [%s / %s]: %s", source_name, section, exc)
        return []

    soup = BeautifulSoup(html, "html.parser")
    cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
    seen: set[str] = set()
    articles: list[Article] = []
    for a in soup.find_all("a", href=True):
        href = str(a["href"]).strip()
        if not link_pat.search(href):
            continue
        title = " ".join(a.get_text(" ").split())
        if len(title) < min_len:
            continue
        full = href if href.startswith("http") else base + href
        if full in seen:
            continue
        seen.add(full)
        published = _date_from_url(href)
        # HTML 列表页多数当天/近几天更新；无法解析日期时保留（不误杀）
        if published and published < cutoff:
            continue
        articles.append(
            Article(
                source=source_name,
                section=section,
                title=title,
                url=full,
                published=published,
                raw_summary="",
            )
        )

    articles.sort(
        key=lambda a: a.published or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    return articles
