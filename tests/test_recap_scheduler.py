import importlib
import importlib.util


def test_recap_scheduler_runs_daily_after_market_close():
    """Cron fires every day at 15:10; trading-day gate is handled by should_run()."""
    assert importlib.util.find_spec("recap_scheduler") is not None
    scheduler_module = importlib.import_module("recap_scheduler")
    scheduler = scheduler_module.build_scheduler(lambda: None)

    jobs = scheduler.get_jobs()

    assert len(jobs) == 1
    assert jobs[0].id == "daily-recap"
    trigger = str(jobs[0].trigger)
    assert "hour='15'" in trigger
    assert "minute='10'" in trigger
