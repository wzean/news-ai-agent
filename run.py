"""命令行入口。

用法：
    python run.py                    # 执行一次（GitHub Actions / 手动）
    python run.py --dry-run          # 不发邮件，仅生成 output/preview.html
    python run.py --no-gemini        # 跳过 Gemini，使用原文摘要（便于本地调试）
    python run.py --limit 6          # 仅处理前 6 条（省 API 额度的真实测试）
    python run.py --schedule         # 常驻，按 config 里的计划每日定时执行（Docker 用）
    python run.py --respect-schedule # 仅当当前时刻匹配计划窗口才执行（GitHub Actions 守卫）
"""
from __future__ import annotations

import argparse
import logging
import os

from news_agent.config import load_config
from news_agent.logging_conf import setup_logging
from news_agent.main import run_once
from news_agent.scheduler import matches_schedule_now, run_scheduler, should_run_cron


def _safe_run(args) -> None:
    try:
        run_once(args.config, dry_run=args.dry_run,
                 use_gemini=not args.no_gemini, limit=args.limit)
    except Exception as exc:  # noqa: BLE001
        logging.getLogger("news_agent").error("本次运行失败: %s", exc)


def main() -> None:
    parser = argparse.ArgumentParser(description="每日外媒新闻 AI 简报 Agent")
    parser.add_argument("--config", default=os.getenv("CONFIG_PATH", "config.yaml"))
    parser.add_argument("--dry-run", action="store_true",
                        help="不发送邮件，仅生成 output/preview.html")
    parser.add_argument("--no-gemini", action="store_true",
                        help="跳过 Gemini，使用原文摘要")
    parser.add_argument("--limit", type=int, default=0,
                        help="仅处理前 N 条（本地省额度测试用，0=不限制）")
    parser.add_argument("--schedule", action="store_true",
                        help="常驻按 config.yaml 的 settings.schedules 定时执行")
    parser.add_argument("--respect-schedule", action="store_true",
                        help="仅当当前时刻匹配某个计划时间窗才执行（供 GitHub Actions 守卫用）")
    args = parser.parse_args()

    setup_logging(os.getenv("LOG_LEVEL", "INFO"))
    log = logging.getLogger("news_agent")

    run_mode = os.getenv("RUN_MODE", "once").lower()

    # 1) 常驻定时模式（Docker）
    if args.schedule or run_mode == "schedule":
        cfg = load_config(args.config)
        run_on_start = str(os.getenv("RUN_ON_START", "false")).lower() in ("1", "true", "yes")
        run_scheduler(cfg, lambda: _safe_run(args), run_on_start=run_on_start)
        return

    # 2) 守卫模式（GitHub Actions 多条 UTC cron，只在正确窗口执行）
    if args.respect_schedule:
        cfg = load_config(args.config)
        # 优先用 GitHub 传入的「计划 cron 标识」判定——抗定时延迟，不会因迟到被误跳过。
        scheduled_cron = os.getenv("SCHEDULED_CRON", "").strip()
        if scheduled_cron:
            ok, label = should_run_cron(scheduled_cron)
            if not ok:
                log.info("[respect-schedule] cron '%s' 当前 DST 下不执行（另一条负责），跳过。", scheduled_cron)
                return
            log.info("[respect-schedule] 命中计划 cron '%s' → %s，开始执行。", scheduled_cron, label)
        else:
            # 本地/无 cron 标识时回退到「实时时间窗」判断（Docker 手动模拟用）。
            ok, label = matches_schedule_now(cfg)
            if not ok:
                log.info("[respect-schedule] 当前不在任何计划时间窗内，跳过本次执行。")
                return
            log.info("[respect-schedule] 命中计划窗口：%s，开始执行。", label)
        _safe_run(args)
        return

    # 3) 执行一次（默认）
    _safe_run(args)


if __name__ == "__main__":
    main()
