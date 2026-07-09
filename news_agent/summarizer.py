"""调用 Google Gemini 生成英文精简摘要 + 核心关键词 + 关键段落中文翻译。

使用官方新版 SDK `google-genai`（import 方式为 `from google import genai`）。
内置 API 限流/异常重试与 JSON 解析兜底，保证单条失败不影响整体流程。
"""
from __future__ import annotations

import json
import logging
import re
import time

from google import genai
from google.genai import types

from .models import Article

logger = logging.getLogger(__name__)

SYSTEM_INSTRUCTION = (
    "You are a senior news editor specializing in technology, finance, macro-economics, "
    "semiconductors, US equities and geopolitics. You write tight, factual, jargon-free "
    "briefings for a busy professional reader. Always respond with STRICT JSON only, "
    "no markdown, no commentary."
)

PROMPT_TEMPLATE = """Analyse the following news item and return STRICT JSON with these keys:
- "english_summary": a concise 2-3 sentence English summary of the ORIGINAL article (max ~60 words).
- "summary_zh": a faithful Simplified Chinese translation of your english_summary (中英对照用).
- "keywords": an array of 4-8 core English keywords / named entities.
- "title_zh": a faithful Simplified Chinese translation of the headline.
- "key_points_zh": an array of 2-4 Simplified Chinese bullet strings that translate the
  most important points / paragraphs (each <= 40 Chinese characters).

Source: {source}
Section: {section}
Headline: {title}
Body/excerpt: {body}

Return ONLY the JSON object."""

DIGEST_PROMPT = """You are writing the opening overview of a daily news brief.
Below are today's {n} selected headlines across technology, finance, economics,
semiconductors, US equities and geopolitics.

Return STRICT JSON with two keys:
- "digest_en": 2-4 sentences in English summarising the day's most important themes/trends.
- "digest_zh": a faithful Simplified Chinese translation of digest_en.

Headlines:
{headlines}

Return ONLY the JSON object."""


def _parse_json(text: str) -> dict:
    if not text:
        return {}
    t = text.strip()
    t = re.sub(r"^```(?:json)?", "", t).strip()
    t = re.sub(r"```$", "", t).strip()
    try:
        return json.loads(t)
    except Exception:  # noqa: BLE001
        m = re.search(r"\{.*\}", t, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:  # noqa: BLE001
                return {}
    return {}


class GeminiSummarizer:
    def __init__(self, api_key: str, model: str = "gemini-2.0-flash",
                 temperature: float = 0.3, interval: float = 1.5,
                 max_retries: int = 4, verify_ssl: bool | str = True,
                 timeout_ms: int = 60000):
        # verify_ssl: True / False / CA 证书路径；timeout_ms: 单次请求超时(毫秒)。
        # 用于兼容公司网络 SSL 拦截 / 代理，避免请求无限期挂起。
        opt_kwargs: dict = {"timeout": timeout_ms}
        if verify_ssl is not True:
            opt_kwargs["client_args"] = {"verify": verify_ssl}
            opt_kwargs["async_client_args"] = {"verify": verify_ssl}
        try:
            http_options = types.HttpOptions(**opt_kwargs)
        except Exception as exc:  # noqa: BLE001
            logger.warning("HttpOptions 构造失败，改用默认: %s", exc)
            http_options = None
        self.client = genai.Client(api_key=api_key, http_options=http_options)
        self.model = model
        self.temperature = temperature
        self.interval = interval
        self.max_retries = max_retries

    def _generate(self, prompt: str) -> str:
        last_err: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = self.client.models.generate_content(
                    model=self.model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_INSTRUCTION,
                        temperature=self.temperature,
                        response_mime_type="application/json",
                    ),
                )
                return resp.text or ""
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                msg = str(exc).lower()
                is_rate = any(k in msg for k in ("429", "rate", "quota", "resource_exhausted", "503", "overloaded"))
                wait = min(90, 5 * attempt + 5) if is_rate else min(30, 2 ** attempt)
                logger.warning(
                    "Gemini 调用失败(%s)%s，第 %d/%d 次，%ds 后重试 ...",
                    type(exc).__name__,
                    " [限流]" if is_rate else "",
                    attempt, self.max_retries, wait,
                )
                if attempt < self.max_retries:
                    time.sleep(wait)
        raise last_err if last_err else RuntimeError("Gemini 调用失败")

    def summarize(self, article: Article) -> Article:
        body = (article.raw_summary or article.title)[:4000]
        prompt = PROMPT_TEMPLATE.format(
            source=article.source,
            section=article.section,
            title=article.title,
            body=body,
        )
        try:
            raw = self._generate(prompt)
            data = _parse_json(raw)
        except Exception as exc:  # noqa: BLE001
            logger.error("摘要生成失败，使用兜底内容: %s", exc)
            data = {}

        article.english_summary = (data.get("english_summary") or article.raw_summary[:280]).strip()
        article.summary_zh = str(data.get("summary_zh") or "").strip()
        kws = data.get("keywords") or article.matched_keywords
        article.keywords = [str(k) for k in kws][:8] if isinstance(kws, list) else article.matched_keywords
        pts = data.get("key_points_zh") or []
        article.key_points_zh = [str(p) for p in pts] if isinstance(pts, list) else []
        article.title_zh = str(data.get("title_zh") or "").strip()

        if self.interval > 0:
            time.sleep(self.interval)
        return article

    def daily_digest(self, articles: list[Article]) -> dict:
        """根据全部入选新闻生成开篇「今日总结」（中英双语）。失败返回空串。"""
        if not articles:
            return {"digest_en": "", "digest_zh": ""}
        headlines = "\n".join(
            f"- [{a.source}/{a.section}] {a.title}" for a in articles[:60]
        )
        prompt = DIGEST_PROMPT.format(n=len(articles), headlines=headlines)
        try:
            data = _parse_json(self._generate(prompt))
        except Exception as exc:  # noqa: BLE001
            logger.error("今日总结生成失败: %s", exc)
            data = {}
        if self.interval > 0:
            time.sleep(self.interval)
        return {
            "digest_en": str(data.get("digest_en") or "").strip(),
            "digest_zh": str(data.get("digest_zh") or "").strip(),
        }
