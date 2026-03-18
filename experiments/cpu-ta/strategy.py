"""
Trading strategy — agent modifies this file.
Exports: strategy(df) -> pd.Series of signals (+1 long, -1 short, 0 flat)
"""

import pandas as pd


def strategy(df: pd.DataFrame) -> pd.Series:
    """Dual SMA crossover baseline."""
    fast = df["close"].rolling(20).mean()
    slow = df["close"].rolling(50).mean()
    sig = pd.Series(0, index=df.index)
    sig[fast > slow] = 1
    sig[fast < slow] = -1
    return sig


if __name__ == "__main__":
    from prepare import load_all_assets, run_backtest, print_metrics
    print_metrics(run_backtest(strategy, load_all_assets()))
