"""Weekday post-market scheduler for the daily recap engine."""

from __future__ import annotations

import logging
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

# 任务函数第一步必须校验交易日(方案 8.3)。cron 每天触发(覆盖调休工作日);
# 任务体内再次校验,非交易日正常退出并记录 SKIPPED_NON_TRADING_DAY。
from trading_calendar import is_trading_day

logger = logging.getLogger("recap_scheduler")
RECAP_SCRIPT = Path(__file__).with_name("recap_engine.py")

SKIPPED_NON_TRADING_DAY = "SKIPPED_NON_TRADING_DAY"


def should_run() -> bool:
    """盘后任务是否应执行:仅交易日执行。

    返回 False 时调用方应记录 SKIPPED_NON_TRADING_DAY 而非告警为故障。
    """
    return is_trading_day()


def run_recap_job() -> None:
    """Run one recap process and surface failures to the container supervisor.

    非交易日正常退出并记录 SKIPPED_NON_TRADING_DAY,不视为故障(方案 8.3)。
    """
    if not should_run():
        logger.info("non-trading day; %s", SKIPPED_NON_TRADING_DAY)
        return
    logger.info("starting daily recap")
    subprocess.run([sys.executable, str(RECAP_SCRIPT)], check=True)


def build_scheduler(job: Callable[[], None] = run_recap_job) -> BlockingScheduler:
    scheduler = BlockingScheduler(timezone="Asia/Shanghai")
    scheduler.add_job(
        job,
        CronTrigger(hour=15, minute=10, timezone="Asia/Shanghai"),
        id="daily-recap",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=1800,
    )
    return scheduler


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    scheduler = build_scheduler()
    logger.info("daily recap scheduler started")
    scheduler.start()


if __name__ == "__main__":
    main()
