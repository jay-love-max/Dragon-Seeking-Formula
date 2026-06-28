import logging
import os

import aiohttp

logger = logging.getLogger("data_pipeline.push")

ALERT_WEBHOOK_URL = os.getenv("ALERT_WEBHOOK_URL", "")


async def push_alert(rule_name: str, message: str):
    if not ALERT_WEBHOOK_URL:
        return
    try:
        async with aiohttp.ClientSession() as session:
            await session.post(
                ALERT_WEBHOOK_URL,
                json={"msgtype": "text", "text": {"content": message}},
                timeout=aiohttp.ClientTimeout(total=5),
            )
        logger.info("alert pushed: %s", message)
    except Exception as e:
        logger.warning("alert push failed: %s", e)
