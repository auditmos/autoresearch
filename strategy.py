"""
Trading strategy — agent modifies this file.
Exports: strategy(df) -> pd.Series of signals (+1 long, -1 short, 0 flat)
"""

import pandas as pd


def strategy(df: pd.DataFrame) -> pd.Series:
    """Dual SMA crossover baseline."""
    fast_ma = df["close"].rolling(20).mean()
    slow_ma = df["close"].rolling(50).mean()
    signals = pd.Series(0, index=df.index)
    signals[fast_ma > slow_ma] = 1
    signals[fast_ma < slow_ma] = -1
    return signals


# ---------------------------------------------------------------------------
# Runner — imports prepare.py, backtests all assets, prints metrics
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from prepare import load_all_assets, run_backtest, print_metrics

    assets = load_all_assets()
    metrics = run_backtest(strategy, assets)
    print_metrics(metrics)
