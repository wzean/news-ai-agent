"""定时计划：支持按「时区 + 每日时刻」触发，自动处理夏令时（DST）。

两种用途：
1) Docker 常驻：run_scheduler() 持续运行，到点触发（每日每个时区各一次）。
2) GitHub Actions 守卫：matches_schedule_now() 判断"当前是否落在某计划时间窗内"，
   让多条 UTC cron 只在正确的那一条上真正执行（从而正确处理纽约 DST）。

时区数据依赖标准库 zoneinfo；Windows / slim 容器需安装 tzdata（见 requirements.txt）。
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

logger = logging.getLogger("news_agent")

DEFAULT_SCHEDULES = [
    {"tz": "Asia/Shanghai", "time": "09:20"},     # 北京时间 09:20
    {"tz": "America/New_York", "time": "09:20"},   # 纽约时间 09:20（自动夏令时）
]


def _parse(schedules: list | None) -> list[tuple[ZoneInfo, int, int, str]]:
    parsed: list[tuple[ZoneInfo, int, int, str]] = []
    for item in (schedules or DEFAULT_SCHEDULES):
        try:
            tz = ZoneInfo(item["tz"])
            hh, mm = str(item["time"]).split(":")
            label = f"{item['tz']} {item['time']}"
            parsed.append((tz, int(hh), int(mm), label))
        except Exception as exc:  # noqa: BLE001
            logger.error("计划项解析失败 %s: %s", item, exc)
    return parsed


def get_schedules(cfg: dict) -> list:
    return (cfg.get("settings", {}) or {}).get("schedules") or DEFAULT_SCHEDULES


def matches_schedule_now(cfg: dict, tolerance_minutes: int | None = None,
                         now: datetime | None = None) -> tuple[bool, str]:
    """判断"现在"是否落在任一计划时刻的容差窗口内。用于 GitHub Actions 守卫。

    now 可注入（UTC，便于测试）；默认取当前 UTC 时间。
    """
    settings = cfg.get("settings", {}) or {}
    if tolerance_minutes is None:
        tolerance_minutes = int(settings.get("schedule_tolerance_minutes", 30))
    now_utc = now or datetime.now(timezone.utc)
    for tz, hh, mm, label in _parse(get_schedules(cfg)):
        local = now_utc.astimezone(tz)
        target = local.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if abs((local - target).total_seconds()) <= tolerance_minutes * 60:
            return True, label
    return False, ""


def run_scheduler(cfg: dict, job, run_on_start: bool = False) -> None:
    """常驻循环：到点触发 job（每个时区每天仅一次）。job 为无参可调用对象。"""
    scheds = _parse(get_schedules(cfg))
    if not scheds:
        logger.error("[scheduler] 无有效计划，退出。")
        return
    for _tz, hh, mm, label in scheds:
        logger.info("[scheduler] 已登记：每日 %02d:%02d (%s)", hh, mm, label)

    if run_on_start:
        logger.info("[scheduler] RUN_ON_START=true，立即先执行一次。")
        job()

    last_fired: dict[str, str] = {}
    while True:
        now_utc = datetime.now(timezone.utc)
        for tz, hh, mm, label in scheds:
            local = now_utc.astimezone(tz)
            day_key = local.date().isoformat()
            if local.hour == hh and local.minute == mm and last_fired.get(label) != day_key:
                last_fired[label] = day_key
                logger.info("[scheduler] 触发 %s（本地时间 %s）", label,
                            local.strftime("%Y-%m-%d %H:%M %Z"))
                try:
                    job()
                except Exception:  # noqa: BLE001
                    logger.exception("[scheduler] 任务执行异常")
        time.sleep(20)
