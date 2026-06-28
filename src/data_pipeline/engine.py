import asyncio
import logging
import os
from datetime import datetime

import pandas as pd
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from scorer import compute_relay_score

# 盘中与盘后必须消费同一套交易日判断(AGENTS.md 不可破坏约束)。
# 旧实现用 weekday()<5 回退,会把节假日当成交易日;改用 XSHG 主日历。
from trading_calendar import is_trading_day as _calendar_is_trading_day

from .collector import AshareCollector, NewsCollector, ZTPoolCollector
from .merger import merge
from .normalizer import normalize
from .push import push_alert
from .rules import check_rules
from .store import Store

logger = logging.getLogger("data_pipeline.engine")

DB_PATH = os.getenv(
    "RECAP_DB_PATH",
    os.path.join(os.path.dirname(__file__), "..", "..", "data", "recap.db"),
)


def is_trading_day(dt: datetime | None = None) -> bool:
    """交易日判断统一委托 trading_calendar(XSHG 主日历)。

    非交易日(含节假日)返回 False,盘中轮询应跳过并记录 SKIPPED_NON_TRADING_DAY,
    而非退化为周一至周五(方案 8.3)。
    """
    return _calendar_is_trading_day(dt or datetime.now())


def score_snapshot(snapshot: pd.DataFrame) -> pd.DataFrame:
    """Attach complete-snapshot sector counts and intraday relay scores."""
    result = snapshot.copy()
    if result.empty:
        return result

    previous = result.get("score_intraday", pd.Series(0, index=result.index))
    result["score_intraday_prev"] = pd.to_numeric(previous, errors="coerce").fillna(0).astype(int)

    limit_up_rows = result["seal_funds"].notna() & result["sector"].notna()
    sector_counts = result.loc[limit_up_rows].groupby("sector").size()
    result["sector_limit_ups"] = result["sector"].map(sector_counts).fillna(0).astype(int)

    result["score_intraday"] = result.apply(
        lambda row: compute_relay_score(row.to_dict(), row["sector_limit_ups"]),
        axis=1,
    )
    return result


class Pipeline:
    """Manages collector lifecycle and polling loop."""

    def __init__(self, db_path: str = ""):
        self.store = Store(db_path or DB_PATH)
        self.ashare = AshareCollector()
        self.zt_pool = ZTPoolCollector()
        self.news = NewsCollector()

    def get_watchlist(self) -> list[str]:
        """Build dynamic watchlist from zt_pool snapshot + yesterday's candidates."""
        snapshot = self.store.get_snapshot()
        codes = list(snapshot.keys())
        try:
            from db import connect

            conn = connect(self.store.db_path, read_only=True)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT DISTINCT code FROM candidates WHERE date = (SELECT MAX(date) FROM candidates)"
            )
            codes.extend([r[0] for r in cursor.fetchall()])
            conn.close()
        except Exception as e:
            logger.warning("failed to read yesterday candidates: %s", e)

        return list(set(codes))

    async def run_polling_loop(self):
        if not is_trading_day():
            logger.info("非交易日，跳过")
            return

        logger.info("Polling loop started")

        while True:
            now = datetime.now()
            if now.hour > 15 or (now.hour == 15 and now.minute > 0):
                logger.info("收盘，停止轮询")
                break

            self.ashare.update_watchlist(self.get_watchlist())

            for collector in [self.zt_pool, self.ashare, self.news]:
                if not collector.due():
                    continue
                try:
                    data = await asyncio.wait_for(
                        collector.poll(), timeout=collector.interval
                    )
                except (TimeoutError, ConnectionError):
                    await asyncio.sleep(collector.retry_delay)
                    continue

                df = normalize(collector.source, data)
                if df.empty:
                    continue

                merged = merge(collector.source, df, self.store.get_snapshot())
                if merged.empty:
                    continue

                merged = score_snapshot(merged)

                self.store.write_snapshot(merged)

                for _, row in merged.iterrows():
                    matched = check_rules(row)
                    for rule in matched:
                        msg = rule.format(row)
                        logger.info("rule matched: %s", msg)
                        asyncio.create_task(push_alert(rule.name, msg))

            await asyncio.sleep(0.1)

    async def run(self):
        scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")

        scheduler.add_job(
            self.run_polling_loop,
            CronTrigger(hour="9-14", minute="15-59"),
        )
        scheduler.add_job(
            self.run_polling_loop,
            CronTrigger(hour="15", minute="0"),
        )
        scheduler.add_job(
            self.store.cleanup,
            CronTrigger(hour="15", minute="5"),
        )

        scheduler.start()
        logger.info("Pipeline scheduler started")

        try:
            while True:
                await asyncio.sleep(3600)
        except asyncio.CancelledError:
            scheduler.shutdown(wait=False)
            self.store.close()
