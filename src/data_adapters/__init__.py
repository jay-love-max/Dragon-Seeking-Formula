import os

from .a_stock_adapter import AStockDataAdapter
from .base_adapter import BaseStockAdapter
from .global_stock_adapter import GlobalStockAdapter
from .thsdk_adapter import ThsdkAdapter


def get_adapter() -> BaseStockAdapter:
    """Instantiate appropriate adapter dynamically based on environment configuration."""
    provider = os.getenv("DATA_PROVIDER", "a-stock-data").lower()

    if provider == "thsdk":
        try:
            return ThsdkAdapter()
        except Exception as e:
            print(f"[Warning] Failed to instantiate ThsdkAdapter: {e}. Falling back to AStockDataAdapter.")
            return AStockDataAdapter()
    elif provider == "global":
        return GlobalStockAdapter()
    else:
        return AStockDataAdapter()
