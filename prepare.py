"""
Autoquant data preparation and backtest engine.
Downloads daily data from Alpha Vantage, runs vectorized backtests,
computes composite scores with train/val/holdout splits.

Read-only by agent — only strategy.py is modified.

Usage:
    ALPHA_VANTAGE_API_KEY=... python prepare.py   # download all assets
"""

import os
import sys
import time
import numpy as np
import pandas as pd
import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

CACHE_DIR = os.path.join(os.path.expanduser("~"), ".cache", "autoquant")
DATA_DIR = os.path.join(CACHE_DIR, "data")

ASSETS = {
    "SPY": {
        "function": "TIME_SERIES_DAILY_ADJUSTED",
        "params": {"symbol": "SPY", "outputsize": "full"},
        "series_key": "Time Series (Daily)",
        "is_crypto": False,
    },
    "BTC": {
        "function": "DIGITAL_CURRENCY_DAILY",
        "params": {"symbol": "BTC", "market": "USD"},
        "series_key": "Time Series (Digital Currency Daily)",
        "is_crypto": True,
    },
    "ETH": {
        "function": "DIGITAL_CURRENCY_DAILY",
        "params": {"symbol": "ETH", "market": "USD"},
        "series_key": "Time Series (Digital Currency Daily)",
        "is_crypto": True,
    },
}

# Period splits (overfitting prevention)
TRAIN_START = "2019-01-01"
TRAIN_END = "2023-06-30"
VAL_START = "2023-07-01"
VAL_END = "2025-06-30"
HOLDOUT_START = "2025-07-01"
HOLDOUT_END = "2025-12-31"

# Backtest parameters
COMMISSION = 0.001   # 0.1% per trade
SLIPPAGE = 0.0005    # 0.05% per trade

# ---------------------------------------------------------------------------
# Data download
# ---------------------------------------------------------------------------

def _parse_ohlcv(values, is_crypto):
    """Parse OHLCV from AV response, handles stock vs crypto key formats."""
    def get(keys):
        for k in keys:
            if k in values:
                return float(values[k])
        raise KeyError(f"None of {keys} found in {list(values.keys())}")

    if is_crypto:
        o = get(["1a. open (USD)", "1. open"])
        h = get(["2a. high (USD)", "2. high"])
        lo = get(["3a. low (USD)", "3. low"])
        c = get(["4a. close (USD)", "4. close"])
        v = get(["5. volume"])
    else:
        o = get(["1. open"])
        h = get(["2. high"])
        lo = get(["3. low"])
        c = get(["5. adjusted close", "4. close"])
        v = get(["6. volume", "5. volume"])
    return o, h, lo, c, v


def download_asset(symbol, api_key):
    """Download daily data from Alpha Vantage, cache as parquet."""
    filepath = os.path.join(DATA_DIR, f"{symbol}.parquet")
    if os.path.exists(filepath):
        print(f"  {symbol}: cached at {filepath}")
        return pd.read_parquet(filepath)

    os.makedirs(DATA_DIR, exist_ok=True)
    config = ASSETS[symbol]

    params = {"function": config["function"], "apikey": api_key, "datatype": "json"}
    params.update(config["params"])

    print(f"  {symbol}: downloading from Alpha Vantage...")
    resp = requests.get("https://www.alphavantage.co/query", params=params, timeout=120)
    resp.raise_for_status()
    data = resp.json()

    series_key = config["series_key"]
    if series_key not in data:
        print(f"  Error: key '{series_key}' not in response. Keys: {list(data.keys())}")
        if "Note" in data:
            print(f"  API note: {data['Note']}")
        if "Error Message" in data:
            print(f"  API error: {data['Error Message']}")
        sys.exit(1)

    ts = data[series_key]
    rows = []
    for date_str, values in ts.items():
        o, h, lo, c, v = _parse_ohlcv(values, config["is_crypto"])
        rows.append({
            "timestamp": pd.Timestamp(date_str),
            "open": o, "high": h, "low": lo, "close": c, "volume": v,
        })

    df = pd.DataFrame(rows).sort_values("timestamp").reset_index(drop=True)
    df.to_parquet(filepath)
    print(f"  {symbol}: {len(df)} rows, {df['timestamp'].iloc[0].date()} to {df['timestamp'].iloc[-1].date()}")
    return df


def load_asset(symbol, api_key=None):
    """Load asset from cache or download."""
    filepath = os.path.join(DATA_DIR, f"{symbol}.parquet")
    if os.path.exists(filepath):
        return pd.read_parquet(filepath)
    if api_key is None:
        api_key = os.environ.get("ALPHA_VANTAGE_API_KEY")
    if not api_key:
        print("Error: ALPHA_VANTAGE_API_KEY not set and data not cached")
        sys.exit(1)
    return download_asset(symbol, api_key)


def load_all_assets(api_key=None):
    """Load all configured assets. Returns dict of {symbol: DataFrame}."""
    if api_key is None:
        api_key = os.environ.get("ALPHA_VANTAGE_API_KEY")
    print("Loading assets...")
    assets = {}
    for i, symbol in enumerate(ASSETS):
        assets[symbol] = load_asset(symbol, api_key)
        if i < len(ASSETS) - 1:
            time.sleep(1)  # rate limit courtesy
    return assets


# ---------------------------------------------------------------------------
# Backtest engine
# ---------------------------------------------------------------------------

def split_data(df, start, end):
    """Slice DataFrame by date range."""
    mask = (df["timestamp"] >= pd.Timestamp(start)) & (df["timestamp"] <= pd.Timestamp(end))
    return df[mask].reset_index(drop=True)


def backtest(df, signals, commission=COMMISSION, slippage=SLIPPAGE):
    """
    Vectorized backtest.

    Args:
        df: DataFrame with 'close' column
        signals: Series/array of signals (+1 long, -1 short, 0 flat)
        commission: per-trade commission rate
        slippage: per-trade slippage rate

    Returns dict with: sharpe, sortino, max_drawdown, total_return,
                       win_rate, num_trades, equity_curve
    """
    close = df["close"].values.astype(np.float64)
    sig = np.asarray(signals, dtype=np.float64)

    if len(sig) != len(close):
        sig = sig[:len(close)]

    n = len(close)
    if n < 2:
        return _empty_metrics()

    # daily returns
    returns = np.diff(close) / close[:-1]
    pos = sig[:-1]  # position held during each return period

    # transaction costs on position changes
    pos_with_entry = np.concatenate([[0.0], pos])
    changes = np.abs(np.diff(pos_with_entry))
    costs = changes * (commission + slippage)

    strat_returns = pos * returns - costs

    if len(strat_returns) == 0 or np.std(strat_returns) == 0:
        return _empty_metrics()

    # equity curve
    equity = np.cumprod(1.0 + strat_returns)

    # sharpe (annualized)
    sharpe = np.mean(strat_returns) / np.std(strat_returns) * np.sqrt(252)

    # sortino (downside deviation)
    downside = strat_returns[strat_returns < 0]
    if len(downside) > 1:
        sortino = np.mean(strat_returns) / np.std(downside) * np.sqrt(252)
    else:
        sortino = sharpe * 2

    # max drawdown
    peak = np.maximum.accumulate(equity)
    drawdown = (equity - peak) / peak
    max_drawdown = float(np.min(drawdown))

    # total return
    total_return = float(equity[-1] - 1.0)

    # trades: count contiguous position segments
    trade_returns = []
    cur = 0.0
    in_trade = False
    for i in range(len(pos)):
        if pos[i] != 0:
            cur += strat_returns[i]
            in_trade = True
        elif in_trade:
            trade_returns.append(cur)
            cur = 0.0
            in_trade = False
    if in_trade:
        trade_returns.append(cur)

    num_trades = len(trade_returns)
    win_rate = sum(1 for r in trade_returns if r > 0) / max(num_trades, 1)

    return {
        "sharpe": float(sharpe),
        "sortino": float(sortino),
        "max_drawdown": max_drawdown,
        "total_return": total_return,
        "win_rate": float(win_rate),
        "num_trades": num_trades,
        "equity_curve": equity,
    }


def _empty_metrics():
    return {
        "sharpe": 0.0, "sortino": 0.0, "max_drawdown": -1.0,
        "total_return": 0.0, "win_rate": 0.0, "num_trades": 0,
        "equity_curve": np.array([1.0]),
    }


# ---------------------------------------------------------------------------
# Composite scoring
# ---------------------------------------------------------------------------

def _consistency(train_sharpe, val_sharpe):
    """Ratio-based consistency: 1.0 when train≈val, 0 when divergent."""
    if abs(train_sharpe) < 0.01 and abs(val_sharpe) < 0.01:
        return 1.0
    if abs(train_sharpe) < 0.01:
        return 0.5
    ratio = val_sharpe / train_sharpe
    if ratio <= 0:
        return 0.0
    return min(ratio, 1.0 / ratio)


def compute_score(train_metrics, val_metrics):
    """
    Composite score from validation metrics + train/val consistency.

    score = (0.4*sharpe + 0.2*sortino + 0.2*(1+max_dd) + 0.1*return + 0.1*win_rate)
            * trade_penalty(min 20 trades)
            * consistency(train vs val sharpe)
    """
    v = val_metrics
    raw = (
        0.4 * v["sharpe"]
        + 0.2 * v["sortino"]
        + 0.2 * (1.0 + v["max_drawdown"])
        + 0.1 * v["total_return"]
        + 0.1 * v["win_rate"]
    )

    trade_penalty = min(v["num_trades"] / 20.0, 1.0)
    consistency = _consistency(train_metrics["sharpe"], v["sharpe"])
    return raw * trade_penalty * consistency


# ---------------------------------------------------------------------------
# Full pipeline
# ---------------------------------------------------------------------------

def run_backtest(strategy_fn, assets=None, api_key=None):
    """
    Run backtest across all assets, return aggregate metrics.
    The keep/discard metric is the average composite score across assets.
    """
    if assets is None:
        assets = load_all_assets(api_key)

    scores = []
    all_val = {"sharpe": [], "sortino": [], "max_drawdown": [],
               "total_return": [], "win_rate": [], "num_trades": []}
    consistencies = []

    for symbol, df in assets.items():
        train_df = split_data(df, TRAIN_START, TRAIN_END)
        val_df = split_data(df, VAL_START, VAL_END)

        train_sig = strategy_fn(train_df)
        val_sig = strategy_fn(val_df)

        train_m = backtest(train_df, train_sig)
        val_m = backtest(val_df, val_sig)

        score = compute_score(train_m, val_m)
        scores.append(score)
        consistencies.append(_consistency(train_m["sharpe"], val_m["sharpe"]))

        for k in all_val:
            all_val[k].append(val_m[k])

    return {
        "score": float(np.mean(scores)),
        "sharpe": float(np.mean(all_val["sharpe"])),
        "sortino": float(np.mean(all_val["sortino"])),
        "max_drawdown": float(np.mean(all_val["max_drawdown"])),
        "total_return": float(np.mean(all_val["total_return"])),
        "win_rate": float(np.mean(all_val["win_rate"])),
        "num_trades": int(np.mean(all_val["num_trades"])),
        "consistency": float(np.mean(consistencies)),
    }


def print_metrics(metrics):
    """Print metrics in grep-parseable format."""
    print(f"score:        {metrics['score']:.6f}")
    print(f"sharpe:       {metrics['sharpe']:.4f}")
    print(f"sortino:      {metrics['sortino']:.4f}")
    print(f"max_drawdown: {metrics['max_drawdown']:.4f}")
    print(f"total_return: {metrics['total_return']:.4f}")
    print(f"win_rate:     {metrics['win_rate']:.4f}")
    print(f"num_trades:   {metrics['num_trades']}")
    print(f"consistency:  {metrics['consistency']:.4f}")


# ---------------------------------------------------------------------------
# Main — standalone data download
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    api_key = os.environ.get("ALPHA_VANTAGE_API_KEY")
    if not api_key:
        print("Error: set ALPHA_VANTAGE_API_KEY environment variable")
        sys.exit(1)
    load_all_assets(api_key)
    print("\nData ready.")
