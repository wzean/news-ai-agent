"""去重存储：以 JSON 文件持久化已推送过的文章指纹，支持按天清理。"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


class DedupStore:
    def __init__(self, path: str = "data/seen.json", retention_days: int = 7):
        self.path = Path(path)
        self.retention_days = retention_days
        self._seen: dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            try:
                self._seen = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception as exc:  # noqa: BLE001
                logger.warning("去重库读取失败，将重建: %s", exc)
                self._seen = {}

    def is_new(self, uid: str) -> bool:
        return uid not in self._seen

    def mark(self, uid: str) -> None:
        self._seen[uid] = datetime.now(timezone.utc).isoformat()

    def prune(self) -> None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.retention_days)
        for uid in list(self._seen.keys()):
            try:
                ts = datetime.fromisoformat(self._seen[uid])
                if ts < cutoff:
                    del self._seen[uid]
            except Exception:  # noqa: BLE001
                del self._seen[uid]

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self._seen, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def __len__(self) -> int:
        return len(self._seen)
