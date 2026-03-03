"""每 2 次运行切换信号 1/-1，便于验证交易撮合流程。"""
import pandas as pd
from deltafq.strategy.base import BaseStrategy


class A0_Every2BarFlipStrategy(BaseStrategy):
    """Every 2 strategy runs (each run = new bars) flip signal 1 / -1 for quick verification of matching."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._run_count = 0

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:  # type: ignore[name-defined]
        self._run_count += 1
        sig = 1 if (self._run_count // 2) % 2 == 0 else -1
        n = len(data)
        return pd.Series([sig] * n, index=data.index)
