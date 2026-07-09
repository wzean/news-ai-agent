"""配置加载：读取 .env 环境变量与 config.yaml。"""
from __future__ import annotations

from pathlib import Path

import yaml
from dotenv import load_dotenv

_ENV_LOADED = False


def ensure_env() -> None:
    """加载 .env 到环境变量（仅执行一次；不覆盖已存在的系统变量）。"""
    global _ENV_LOADED
    if not _ENV_LOADED:
        load_dotenv(override=False)
        _ENV_LOADED = True


def load_config(path: str = "config.yaml") -> dict:
    """读取 YAML 配置文件并返回字典。"""
    ensure_env()
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"未找到配置文件: {p.resolve()}")
    with p.open("r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    return cfg
