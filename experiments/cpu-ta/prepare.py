"""
Autoquant prepare.py — data + backtest + scoring. READ-ONLY by agent.

Exports: load_all_assets(), run_backtest(fn, assets), print_metrics(metrics)
"""

import os, sys, time
import numpy as np
import pandas as pd
import requests

CACHE_DIR = os.path.expanduser("~/.cache/autoquant/data")
ASSETS = {
    "SPY": {"function": "TIME_SERIES_DAILY_ADJUSTED", "params": {"symbol": "SPY", "outputsize": "full"},
            "series_key": "Time Series (Daily)", "is_crypto": False},
    "BTC": {"function": "DIGITAL_CURRENCY_DAILY", "params": {"symbol": "BTC", "market": "USD"},
            "series_key": "Time Series (Digital Currency Daily)", "is_crypto": True},
    "ETH": {"function": "DIGITAL_CURRENCY_DAILY", "params": {"symbol": "ETH", "market": "USD"},
            "series_key": "Time Series (Digital Currency Daily)", "is_crypto": True},
}
TRAIN = ("2019-01-01", "2023-06-30")
VAL   = ("2023-07-01", "2025-06-30")
COMMISSION, SLIPPAGE = 0.001, 0.0005


# ── Data ──────────────────────────────────────────────────────────

def _parse(vals, is_crypto):
    def g(*keys):
        for k in keys:
            if k in vals: return float(vals[k])
        raise KeyError(keys)
    if is_crypto:
        return (g("1a. open (USD)", "1. open"), g("2a. high (USD)", "2. high"),
                g("3a. low (USD)", "3. low"), g("4a. close (USD)", "4. close"), g("5. volume"))
    return (g("1. open"), g("2. high"), g("3. low"),
            g("5. adjusted close", "4. close"), g("6. volume", "5. volume"))


def load_asset(symbol, api_key=None):
    path = os.path.join(CACHE_DIR, f"{symbol}.parquet")
    if os.path.exists(path):
        return pd.read_parquet(path)
    api_key = api_key or os.environ.get("ALPHA_VANTAGE_API_KEY")
    if not api_key:
        print(f"Error: ALPHA_VANTAGE_API_KEY not set, {symbol} not cached"); sys.exit(1)
    cfg = ASSETS[symbol]
    p = {"function": cfg["function"], "apikey": api_key, "datatype": "json", **cfg["params"]}
    print(f"  Downloading {symbol}...")
    r = requests.get("https://www.alphavantage.co/query", params=p, timeout=120)
    r.raise_for_status()
    data = r.json()
    if cfg["series_key"] not in data:
        print(f"  Error: {list(data.keys())}"); sys.exit(1)
    rows = [{"timestamp": pd.Timestamp(d), **dict(zip(
        ["open","high","low","close","volume"], _parse(v, cfg["is_crypto"])))}
        for d, v in data[cfg["series_key"]].items()]
    df = pd.DataFrame(rows).sort_values("timestamp").reset_index(drop=True)
    os.makedirs(CACHE_DIR, exist_ok=True)
    df.to_parquet(path)
    print(f"  {symbol}: {len(df)} rows")
    return df


def refresh_asset(symbol, api_key=None):
    """Re-download if last candle is stale (< yesterday). Returns df."""
    from datetime import date, timedelta
    path = os.path.join(CACHE_DIR, f"{symbol}.parquet")
    if os.path.exists(path):
        df = pd.read_parquet(path)
        if df["timestamp"].max().date() >= date.today() - timedelta(days=1):
            return df
        os.remove(path)
        print(f"  {symbol} stale, re-downloading...")
    return load_asset(symbol, api_key)


def load_all_assets(api_key=None):
    api_key = api_key or os.environ.get("ALPHA_VANTAGE_API_KEY")
    assets = {}
    for i, sym in enumerate(ASSETS):
        assets[sym] = load_asset(sym, api_key)
        if i < len(ASSETS) - 1: time.sleep(1)
    return assets


# ── Backtest ──────────────────────────────────────────────────────

def _slice(df, start, end):
    m = (df["timestamp"] >= pd.Timestamp(start)) & (df["timestamp"] <= pd.Timestamp(end))
    return df[m].reset_index(drop=True)


def backtest(df, signals):
    close = df["close"].values.astype(np.float64)
    sig = np.asarray(signals, dtype=np.float64)[:len(close)]
    if len(close) < 2: return _empty()
    ret = np.diff(close) / close[:-1]
    pos = sig[:-1]
    costs = np.abs(np.diff(np.concatenate([[0.0], pos]))) * (COMMISSION + SLIPPAGE)
    sr = pos * ret - costs
    if np.std(sr) == 0: return _empty()
    eq = np.cumprod(1.0 + sr)
    sharpe = np.mean(sr) / np.std(sr) * np.sqrt(252)
    down = sr[sr < 0]
    sortino = np.mean(sr) / np.std(down) * np.sqrt(252) if len(down) > 1 else sharpe * 2
    peak = np.maximum.accumulate(eq)
    max_dd = float(np.min((eq - peak) / peak))
    # trade-level win rate
    trades, cur, in_t = [], 0.0, False
    for i in range(len(pos)):
        if pos[i] != 0: cur += sr[i]; in_t = True
        elif in_t: trades.append(cur); cur = 0.0; in_t = False
    if in_t: trades.append(cur)
    n = len(trades)
    return {"sharpe": float(sharpe), "sortino": float(sortino), "max_drawdown": max_dd,
            "total_return": float(eq[-1] - 1), "win_rate": sum(1 for t in trades if t > 0) / max(n, 1),
            "num_trades": n}


def _empty():
    return {"sharpe": 0.0, "sortino": 0.0, "max_drawdown": -1.0,
            "total_return": 0.0, "win_rate": 0.0, "num_trades": 0}


# ── Scoring ───────────────────────────────────────────────────────

def _consistency(ts, vs):
    if abs(ts) < 0.01 and abs(vs) < 0.01: return 1.0
    if abs(ts) < 0.01: return 0.5
    r = vs / ts
    return 0.0 if r <= 0 else min(r, 1.0 / r)


def compute_score(train_m, val_m):
    v = val_m
    raw = (0.4*v["sharpe"] + 0.2*v["sortino"] + 0.2*(1+v["max_drawdown"])
           + 0.1*v["total_return"] + 0.1*v["win_rate"])
    return raw * min(v["num_trades"] / 20.0, 1.0) * _consistency(train_m["sharpe"], v["sharpe"])


# ── Pipeline ──────────────────────────────────────────────────────

def run_backtest(strategy_fn, assets=None, api_key=None):
    if assets is None: assets = load_all_assets(api_key)
    scores, val_acc, cons = [], {k: [] for k in ["sharpe","sortino","max_drawdown","total_return","win_rate","num_trades"]}, []
    for sym, df in assets.items():
        tm = backtest(_slice(df, *TRAIN), strategy_fn(_slice(df, *TRAIN)))
        vm = backtest(_slice(df, *VAL),   strategy_fn(_slice(df, *VAL)))
        scores.append(compute_score(tm, vm))
        cons.append(_consistency(tm["sharpe"], vm["sharpe"]))
        for k in val_acc: val_acc[k].append(vm[k])
    return {"score": float(np.mean(scores)), **{k: float(np.mean(v)) for k, v in val_acc.items()},
            "consistency": float(np.mean(cons))}


def print_metrics(m):
    print(f"score:        {m['score']:.6f}")
    print(f"sharpe:       {m['sharpe']:.4f}")
    print(f"sortino:      {m['sortino']:.4f}")
    print(f"max_drawdown: {m['max_drawdown']:.4f}")
    print(f"total_return: {m['total_return']:.4f}")
    print(f"win_rate:     {m['win_rate']:.4f}")
    print(f"num_trades:   {m['num_trades']:.0f}")
    print(f"consistency:  {m['consistency']:.4f}")


if __name__ == "__main__":
    key = os.environ.get("ALPHA_VANTAGE_API_KEY")
    if not key: print("Error: set ALPHA_VANTAGE_API_KEY"); sys.exit(1)
    load_all_assets(key)
    print("Data ready.")
