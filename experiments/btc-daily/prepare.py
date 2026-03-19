"""
prepare.py — BTC daily: data pipeline + backtest engine + scoring
READ-ONLY for agent. Only human modifies.

Data sources:
  - BTC/USDT daily     → ccxt/Binance (1H resampled to daily)
  - On-chain Tier 1    → bitcoin-data.com API (MVRV, SOPR, exchange flow, NUPL, F&G, active addr)
  - Macro (FRED)       → WALCL, DFF, T10Y2Y, VIXCLS, DGS10, BAMLH0A0HYM2, DTWEXBGS
  - Funding rate       → Binance Futures (8H → daily avg)
  - FOMC calendar      → hardcoded dates 2022-2026
"""

import os
import time
import json
import numpy as np
import pandas as pd
import ccxt
import requests
import matplotlib.pyplot as plt
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

# ─── Config ──────────────────────────────────────────────────────

CACHE_DIR = Path.home() / ".cache" / "autoquant" / "data"

# Periods
TRAIN_START = "2022-01-01"
TRAIN_END   = "2025-06-30"
VAL_START   = "2025-07-01"
VAL_END     = "2026-03-19"

# Costs (Binance spot)
COMMISSION = 0.001   # 0.1% taker
SLIPPAGE   = 0.0003  # 0.03%

# API keys
AV_API_KEY = os.getenv("ALPHA_VANTAGE_API_KEY", "")
FRED_API_KEY = os.getenv("FRED_API_KEY", "")
BITCOIN_DATA_API_KEY = os.getenv("BITCOIN_DATA_API_KEY", "")

FRED_BASE_URL = "https://api.stlouisfed.org/fred/series/observations"
BITCOIN_DATA_BASE_URL = "https://bitcoin-data.com/v1"

# ─── FOMC calendar (announcement dates, 2022-2026) ──────────────

FOMC_DATES = [
    # 2022
    "2022-01-26", "2022-03-16", "2022-05-04", "2022-06-15",
    "2022-07-27", "2022-09-21", "2022-11-02", "2022-12-14",
    # 2023
    "2023-02-01", "2023-03-22", "2023-05-03", "2023-06-14",
    "2023-07-26", "2023-09-20", "2023-11-01", "2023-12-13",
    # 2024
    "2024-01-31", "2024-03-20", "2024-05-01", "2024-06-12",
    "2024-07-31", "2024-09-18", "2024-11-07", "2024-12-18",
    # 2025
    "2025-01-29", "2025-03-19", "2025-05-07", "2025-06-18",
    "2025-07-30", "2025-09-17", "2025-11-05", "2025-12-17",
    # 2026
    "2026-01-28", "2026-03-18", "2026-05-06", "2026-06-17",
    "2026-07-29", "2026-09-16", "2026-11-04", "2026-12-16",
]
FOMC_DATES_SET = set(pd.to_datetime(FOMC_DATES).date)


def build_fomc_features(index: pd.DatetimeIndex) -> pd.DataFrame:
    """FOMC calendar features: days_to_fomc, is_fomc_day, is_fomc_week."""
    fomc_ts = pd.to_datetime(FOMC_DATES)
    dates = index.normalize()

    days_to = pd.Series(np.nan, index=index)
    is_day = pd.Series(0, index=index)
    is_week = pd.Series(0, index=index)

    for i, d in enumerate(dates):
        future = fomc_ts[fomc_ts >= d]
        if len(future) > 0:
            delta = (future[0] - d).days
            days_to.iloc[i] = delta
            if delta == 0:
                is_day.iloc[i] = 1
            if delta <= 7:
                is_week.iloc[i] = 1
        past = fomc_ts[fomc_ts <= d]
        if len(past) > 0:
            days_since = (d - past[-1]).days
            if days_since <= 2:
                is_week.iloc[i] = 1  # post-FOMC reaction window

    # Normalize days_to to [-1, 1] range (0-45 days typical between meetings)
    days_to = days_to.fillna(45).clip(0, 45) / 45.0

    return pd.DataFrame({
        "fomc_proximity": 1.0 - days_to,  # higher = closer to FOMC
        "is_fomc_day": is_day,
        "is_fomc_week": is_week,
    }, index=index)


# ─── BTC daily data (ccxt → resample) ───────────────────────────

def _fetch_btc_1h(since: str = "2021-06-01") -> pd.DataFrame:
    exchange = ccxt.binance({"enableRateLimit": True})
    since_ts = exchange.parse8601(f"{since}T00:00:00Z")
    limit = 1000
    all_candles = []

    print(f"  Downloading BTC/USDT 1H from Binance (since {since})...")
    while True:
        try:
            candles = exchange.fetch_ohlcv("BTC/USDT", "1h", since=since_ts, limit=limit)
        except Exception as e:
            if "ratelimit" in str(e).lower():
                print(f"    Rate limit, waiting 60s...")
                time.sleep(60)
                continue
            raise
        if not candles:
            break
        all_candles.extend(candles)
        since_ts = candles[-1][0] + 1
        if len(candles) < limit:
            break
        if len(all_candles) % 10000 < limit:
            dt = pd.Timestamp(candles[-1][0], unit="ms")
            print(f"    ... {len(all_candles)} candles, last: {dt}")
        time.sleep(0.5)

    df = pd.DataFrame(all_candles, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    df = df.set_index("timestamp").sort_index()
    df = df[~df.index.duplicated(keep="first")]
    return df


def download_btc_daily(force: bool = False) -> pd.DataFrame:
    """BTC daily candles via Binance 1H → resample."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = CACHE_DIR / "BTC_USDT_daily.parquet"

    if cache_path.exists() and not force:
        print(f"  BTC daily: loaded from cache ({cache_path})")
        return pd.read_parquet(cache_path)

    df_1h = _fetch_btc_1h(since="2021-06-01")
    df_daily = df_1h.resample("1D").agg({
        "open": "first", "high": "max", "low": "min",
        "close": "last", "volume": "sum",
    }).dropna()

    df_daily.to_parquet(cache_path)
    print(f"  BTC daily: saved {len(df_daily)} days -> {cache_path}")
    return df_daily


# ─── On-chain data (bitcoin-data.com) ───────────────────────────

ONCHAIN_ENDPOINTS = {
    "mvrv":             "mvrv",
    "mvrv_sth":         "sth-mvrv",
    "mvrv_lth":         "lth-mvrv",
    "sopr_sth":         "sth-sopr",
    "exchange_netflow":  "exchange-netflow-btc",
    "nupl":             "nupl",
    "fear_greed":       "fear-greed",
    "active_addresses": "active-addresses",
}


def _fetch_onchain(endpoint: str, start: str = "2021-01-01") -> pd.DataFrame:
    """Fetch single on-chain metric from bitcoin-data.com."""
    if not BITCOIN_DATA_API_KEY:
        print(f"    No BITCOIN_DATA_API_KEY, skipping {endpoint}")
        return pd.DataFrame()

    url = f"{BITCOIN_DATA_BASE_URL}/{endpoint}"
    headers = {"Authorization": f"Bearer {BITCOIN_DATA_API_KEY}"}
    params = {"from": start}

    try:
        resp = requests.get(url, headers=headers, params=params, timeout=30)
        if resp.status_code != 200:
            print(f"    {endpoint}: HTTP {resp.status_code}")
            return pd.DataFrame()

        data = resp.json()
        if isinstance(data, list):
            df = pd.DataFrame(data)
        elif isinstance(data, dict) and "data" in data:
            df = pd.DataFrame(data["data"])
        else:
            print(f"    {endpoint}: unexpected response format")
            return pd.DataFrame()

        # Try common column patterns
        date_col = next((c for c in df.columns if c in ("date", "timestamp", "t", "d")), None)
        value_col = next((c for c in df.columns if c in ("value", "v", "close", "price")), None)

        if date_col is None or value_col is None:
            # Fallback: assume first col is date, second is value
            if len(df.columns) >= 2:
                date_col, value_col = df.columns[0], df.columns[1]
            else:
                print(f"    {endpoint}: can't identify columns: {list(df.columns)}")
                return pd.DataFrame()

        result = pd.DataFrame({
            "timestamp": pd.to_datetime(df[date_col]),
            "value": pd.to_numeric(df[value_col], errors="coerce"),
        }).dropna()
        result = result.set_index("timestamp").sort_index()
        result = result[~result.index.duplicated(keep="first")]
        return result

    except Exception as e:
        print(f"    {endpoint}: error — {e}")
        return pd.DataFrame()


def download_onchain(force: bool = False) -> dict[str, pd.DataFrame]:
    """Download all Tier 1 on-chain metrics, cache as parquet."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    result = {}

    for name, endpoint in ONCHAIN_ENDPOINTS.items():
        cache_path = CACHE_DIR / f"onchain_{name}.parquet"

        if cache_path.exists() and not force:
            print(f"  {name}: loaded from cache")
            result[name] = pd.read_parquet(cache_path)
            continue

        print(f"  {name}: downloading from bitcoin-data.com...")
        df = _fetch_onchain(endpoint)
        if not df.empty:
            df.to_parquet(cache_path)
            print(f"  {name}: saved {len(df)} points")
            result[name] = df
        else:
            print(f"  {name}: no data")

        time.sleep(1.5)  # respect rate limits

    return result


# ─── FRED macro data ────────────────────────────────────────────

FRED_SERIES = {
    "walcl":     "WALCL",       # Fed balance sheet (weekly)
    "dff":       "DFF",         # Fed funds rate (daily)
    "t10y2y":    "T10Y2Y",      # 10Y-2Y yield spread (daily)
    "vixcls":    "VIXCLS",      # VIX (daily)
    "dgs10":     "DGS10",       # 10Y treasury yield (daily)
    "hy_spread": "BAMLH0A0HYM2",  # High yield spread (daily)
    "usd_index": "DTWEXBGS",    # USD trade-weighted index (daily)
}


def _fetch_fred(series_id: str, start: str = "2021-01-01") -> pd.DataFrame:
    """Fetch a FRED series."""
    if not FRED_API_KEY:
        print(f"    No FRED_API_KEY, skipping {series_id}")
        return pd.DataFrame()

    params = {
        "series_id": series_id,
        "api_key": FRED_API_KEY,
        "file_type": "json",
        "observation_start": start,
    }

    try:
        resp = requests.get(FRED_BASE_URL, params=params, timeout=30)
        data = resp.json()
        observations = data.get("observations", [])

        rows = []
        for obs in observations:
            val = obs.get("value", ".")
            if val == "." or val is None:
                continue
            rows.append({
                "timestamp": pd.Timestamp(obs["date"]),
                "value": float(val),
            })

        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows).set_index("timestamp").sort_index()
        return df

    except Exception as e:
        print(f"    FRED {series_id}: error — {e}")
        return pd.DataFrame()


def download_fred(force: bool = False) -> dict[str, pd.DataFrame]:
    """Download all FRED series, cache as parquet."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    result = {}

    for name, series_id in FRED_SERIES.items():
        cache_path = CACHE_DIR / f"fred_{name}.parquet"

        if cache_path.exists() and not force:
            print(f"  {name}: loaded from cache")
            result[name] = pd.read_parquet(cache_path)
            continue

        print(f"  {name}: downloading from FRED ({series_id})...")
        df = _fetch_fred(series_id)
        if not df.empty:
            df.to_parquet(cache_path)
            print(f"  {name}: saved {len(df)} points")
            result[name] = df
        else:
            print(f"  {name}: no data")

        time.sleep(0.5)

    return result


# ─── Funding rate (Binance Futures, daily avg) ──────────────────

def _fetch_funding_rate(since: str = "2021-01-01") -> pd.DataFrame:
    exchange = ccxt.binance({
        "options": {"defaultType": "future"},
        "enableRateLimit": True,
    })
    since_ts = exchange.parse8601(f"{since}T00:00:00Z")
    all_rates = []

    print(f"  Downloading BTC/USDT funding rate...")
    while True:
        try:
            rates = exchange.fetch_funding_rate_history("BTC/USDT", since=since_ts, limit=1000)
        except Exception as e:
            if "ratelimit" in str(e).lower():
                time.sleep(10)
                continue
            raise
        if not rates:
            break
        for r in rates:
            all_rates.append({
                "timestamp": pd.Timestamp(r["datetime"]),
                "funding_rate": r["fundingRate"],
            })
        since_ts = rates[-1]["timestamp"] + 1
        if len(rates) < 1000:
            break
        time.sleep(0.3)

    if not all_rates:
        return pd.DataFrame()

    df = pd.DataFrame(all_rates).set_index("timestamp").sort_index()
    df = df[~df.index.duplicated(keep="first")]
    # Resample 8H → daily average
    daily = df.resample("1D").mean().dropna()
    return daily


def download_funding_rate(force: bool = False) -> pd.DataFrame:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = CACHE_DIR / "BTC_funding_rate_daily.parquet"

    if cache_path.exists() and not force:
        print(f"  Funding rate: loaded from cache")
        return pd.read_parquet(cache_path)

    df = _fetch_funding_rate()
    if not df.empty:
        df.to_parquet(cache_path)
        print(f"  Funding rate: saved {len(df)} days")
    return df


# ─── Load all data ──────────────────────────────────────────────

def load_all_data(force: bool = False) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    """
    Load BTC daily + all context data.

    Returns:
        (btc_daily, context) where context is dict of DataFrames with 'value' column
        All context data forward-filled to daily frequency.
    """
    print("Loading data...")
    btc = download_btc_daily(force=force)

    context = {}

    # On-chain
    onchain = download_onchain(force=force)
    for name, df in onchain.items():
        context[f"onchain_{name}"] = df

    # FRED
    fred = download_fred(force=force)
    for name, df in fred.items():
        context[f"fred_{name}"] = df

    # Funding rate
    fr = download_funding_rate(force=force)
    if not fr.empty:
        context["funding_rate"] = pd.DataFrame({"value": fr["funding_rate"]})

    # FOMC
    fomc = build_fomc_features(btc.index)
    context["_fomc"] = fomc  # special: multiple columns, not single 'value'

    n_onchain = sum(1 for k in context if k.startswith("onchain_"))
    n_fred = sum(1 for k in context if k.startswith("fred_"))
    print(f"\nLoaded: BTC {len(btc)} days, {n_onchain} on-chain, "
          f"{n_fred} FRED, funding_rate={'yes' if 'funding_rate' in context else 'no'}, FOMC calendar\n")
    return btc, context


def split_periods(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    train = df.loc[TRAIN_START:TRAIN_END].copy()
    val = df.loc[VAL_START:VAL_END].copy()
    return train, val


# ─── Backtest engine ────────────────────────────────────────────

def backtest(df: pd.DataFrame, signals: pd.Series) -> dict:
    """
    Vectorized backtest with per-trade tracking for R:R metrics.

    Args:
        df: BTC daily OHLCV
        signals: +1 long, -1 short, 0 flat (fractional allowed)

    Returns:
        dict with all metrics including avg_rr and profit_factor
    """
    signals = signals.reindex(df.index).fillna(0).shift(1).fillna(0).clip(-1, 1)
    returns = df["close"].pct_change().fillna(0)
    position_changes = signals.diff().abs().fillna(0)
    costs = position_changes * (COMMISSION + SLIPPAGE)
    strategy_returns = signals * returns - costs
    equity = (1 + strategy_returns).cumprod()

    # ─── Per-trade tracking for R:R ───
    trades_pnl = []
    in_trade = False
    trade_return = 0.0

    for i in range(1, len(signals)):
        prev_pos = signals.iloc[i - 1]
        curr_pos = signals.iloc[i]
        ret = strategy_returns.iloc[i]

        if prev_pos != 0:
            trade_return += ret
            in_trade = True

        # Position changed or closed
        if curr_pos != prev_pos and in_trade:
            trades_pnl.append(trade_return)
            trade_return = 0.0
            in_trade = False

    if in_trade and trade_return != 0:
        trades_pnl.append(trade_return)

    # ─── Metrics ───
    periods_per_year = 365  # daily, BTC trades 365d/y
    mean_ret = strategy_returns.mean()
    std_ret = strategy_returns.std()

    sharpe = (mean_ret / std_ret * np.sqrt(periods_per_year)) if std_ret > 0 else 0.0

    downside = strategy_returns[strategy_returns < 0]
    downside_std = downside.std() if len(downside) > 0 else 1e-9
    sortino = (mean_ret / downside_std * np.sqrt(periods_per_year)) if downside_std > 0 else 0.0

    peak = equity.cummax()
    drawdown = (equity - peak) / peak
    max_drawdown = drawdown.min()

    total_return = equity.iloc[-1] / equity.iloc[0] - 1 if len(equity) > 0 else 0.0

    # Trade stats
    num_trades = len(trades_pnl)
    wins = [t for t in trades_pnl if t > 0]
    losses = [t for t in trades_pnl if t < 0]

    win_rate = len(wins) / num_trades if num_trades > 0 else 0.0
    avg_win = np.mean(wins) if wins else 0.0
    avg_loss = abs(np.mean(losses)) if losses else 1e-9
    avg_rr = avg_win / avg_loss if avg_loss > 1e-9 else 0.0

    gross_profit = sum(wins) if wins else 0.0
    gross_loss = abs(sum(losses)) if losses else 1e-9
    profit_factor = gross_profit / gross_loss if gross_loss > 1e-9 else 0.0

    bh_return = df["close"].iloc[-1] / df["close"].iloc[0] - 1 if len(df) > 0 else 0.0

    long_pct = (signals > 0).sum() / len(signals) if len(signals) > 0 else 0
    short_pct = (signals < 0).sum() / len(signals) if len(signals) > 0 else 0
    flat_pct = (signals == 0).sum() / len(signals) if len(signals) > 0 else 0

    return {
        "sharpe": round(sharpe, 3),
        "sortino": round(sortino, 3),
        "max_drawdown": round(max_drawdown, 4),
        "total_return": round(total_return, 4),
        "win_rate": round(win_rate, 4),
        "avg_rr": round(avg_rr, 3),
        "profit_factor": round(profit_factor, 3),
        "num_trades": num_trades,
        "avg_win": round(avg_win, 4),
        "avg_loss": round(avg_loss, 4),
        "buy_hold_return": round(bh_return, 4),
        "long_pct": round(long_pct, 3),
        "short_pct": round(short_pct, 3),
        "flat_pct": round(flat_pct, 3),
        "equity_curve": equity,
    }


# ─── Scoring ────────────────────────────────────────────────────

def compute_score(train_metrics: dict, val_metrics: dict) -> float:
    """
    Composite score — higher = better.
    R:R focused: avg_rr and profit_factor together = 30% weight.

    Components:
    - 25% Sharpe (val)
    - 15% Sortino (val)
    - 15% (1 + max_drawdown)
    - 10% total return (val)
    - 05% win rate (val)
    - 15% avg R:R normalized (R:R 3.0 = max)
    - 15% profit factor normalized (PF 3.0 = max)
    x trade_penalty (min 15 trades on val)
    x consistency (train/val Sharpe similarity)
    """
    v = val_metrics

    avg_rr_norm = min(v["avg_rr"] / 3.0, 1.0)
    pf_norm = min(v["profit_factor"] / 3.0, 1.0)

    raw = (
        0.25 * v["sharpe"]
        + 0.15 * v["sortino"]
        + 0.15 * (1 + v["max_drawdown"])
        + 0.10 * v["total_return"]
        + 0.05 * v["win_rate"]
        + 0.15 * avg_rr_norm
        + 0.15 * pf_norm
    )

    trade_penalty = min(v["num_trades"] / 15.0, 1.0)

    t_sharpe = train_metrics["sharpe"]
    v_sharpe = v["sharpe"]
    if abs(t_sharpe) > 0.01:
        ratio = v_sharpe / t_sharpe
        consistency = max(0.0, min(1.0, 1.0 - abs(1.0 - ratio) * 0.5))
    else:
        consistency = 0.5

    score = raw * trade_penalty * consistency
    return round(score, 4)


# ─── Evaluation ─────────────────────────────────────────────────

def evaluate(strategy_fn) -> dict:
    """
    Run strategy on BTC daily with full context.

    strategy_fn signature:
        strategy(df, context) -> (pd.Series, list[dict])
        - df: BTC daily OHLCV
        - context: dict of DataFrames (on-chain, FRED, funding, FOMC)
        - returns: (signals Series, attributions list)
          signals: +1 long, -1 short, 0 flat
          attributions: [{date, signal, top_features: [...]}] for report
    """
    btc, context = load_all_data()
    train_df, val_df = split_periods(btc)

    if len(train_df) < 100 or len(val_df) < 50:
        print(f"  Not enough data: {len(train_df)} train, {len(val_df)} val")
        return {"score": 0.0}

    # Split context
    train_ctx, val_ctx = {}, {}
    for name, ctx_df in context.items():
        if name == "_fomc":
            t, v = split_periods(ctx_df)
            train_ctx[name] = t
            val_ctx[name] = v
        else:
            t, v = split_periods(ctx_df)
            train_ctx[name] = t
            val_ctx[name] = v

    # Generate signals
    train_result = strategy_fn(train_df, train_ctx)
    val_result = strategy_fn(val_df, val_ctx)

    # Unpack: strategy can return (signals,) or (signals, attributions)
    if isinstance(train_result, tuple):
        train_signals, _ = train_result
    else:
        train_signals = train_result

    if isinstance(val_result, tuple):
        val_signals, val_attributions = val_result
    else:
        val_signals, val_attributions = val_result, []

    # Backtest
    train_metrics = backtest(train_df, train_signals)
    val_metrics = backtest(val_df, val_signals)
    score = compute_score(train_metrics, val_metrics)

    print(f"  BTC Daily:")
    print(f"    Train — Sharpe: {train_metrics['sharpe']:>7.3f}  "
          f"Return: {train_metrics['total_return']:>8.2%}  "
          f"MaxDD: {train_metrics['max_drawdown']:>7.2%}  "
          f"Trades: {train_metrics['num_trades']}  "
          f"R:R: {train_metrics['avg_rr']:.2f}  "
          f"PF: {train_metrics['profit_factor']:.2f}")
    print(f"    Val   — Sharpe: {val_metrics['sharpe']:>7.3f}  "
          f"Return: {val_metrics['total_return']:>8.2%}  "
          f"MaxDD: {val_metrics['max_drawdown']:>7.2%}  "
          f"Trades: {val_metrics['num_trades']}  "
          f"R:R: {val_metrics['avg_rr']:.2f}  "
          f"PF: {val_metrics['profit_factor']:.2f}")
    print(f"    WinRate: {val_metrics['win_rate']:.1%}  "
          f"Long/Short/Flat: {val_metrics['long_pct']:.0%}/"
          f"{val_metrics['short_pct']:.0%}/{val_metrics['flat_pct']:.0%}")
    print(f"    B&H: Train {train_metrics['buy_hold_return']:>8.2%}  "
          f"Val {val_metrics['buy_hold_return']:>8.2%}")
    print(f"    Score: {score}")
    print()

    # Grep-parseable output
    print(f"score:          {score}")
    print(f"sharpe:         {val_metrics['sharpe']}")
    print(f"sortino:        {val_metrics['sortino']}")
    print(f"max_drawdown:   {val_metrics['max_drawdown']}")
    print(f"total_return:   {val_metrics['total_return']}")
    print(f"win_rate:       {val_metrics['win_rate']}")
    print(f"avg_rr:         {val_metrics['avg_rr']}")
    print(f"profit_factor:  {val_metrics['profit_factor']}")
    print(f"num_trades:     {val_metrics['num_trades']}")

    # Write signal report
    if val_attributions:
        _write_signal_report(val_attributions, val_signals, val_df)

    return {
        "train": train_metrics,
        "val": val_metrics,
        "score": score,
        "attributions": val_attributions,
    }


# ─── Signal report ──────────────────────────────────────────────

def _write_signal_report(attributions: list[dict], signals: pd.Series, df: pd.DataFrame):
    """Write signal_report.md with daily signals + explanations."""
    report_path = Path(__file__).parent / "signal_report.md"
    lines = [
        f"# BTC Daily Signal Report",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"",
        f"| Date | Signal | BTC Close | Top Features |",
        f"|------|--------|-----------|--------------|",
    ]

    # Last 30 days of signals
    recent = sorted(attributions, key=lambda x: x.get("date", ""))[-30:]
    for attr in recent:
        date = attr.get("date", "?")
        sig = attr.get("signal", 0)
        sig_label = "LONG" if sig > 0 else "SHORT" if sig < 0 else "FLAT"
        top = attr.get("top_features", [])
        top_str = ", ".join(top[:3]) if top else "-"

        close = ""
        try:
            if date in df.index:
                close = f"${df.loc[date, 'close']:,.0f}"
        except Exception:
            pass

        lines.append(f"| {date} | **{sig_label}** ({sig:+.2f}) | {close} | {top_str} |")

    # Previous day verification
    if len(recent) >= 2:
        prev = recent[-2]
        curr = recent[-1]
        prev_date = prev.get("date", "")
        curr_date = curr.get("date", "")
        prev_sig = prev.get("signal", 0)

        try:
            if prev_date in df.index and curr_date in df.index:
                prev_close = df.loc[prev_date, "close"]
                curr_close = df.loc[curr_date, "close"]
                pnl = (curr_close - prev_close) / prev_close
                correct = (prev_sig > 0 and pnl > 0) or (prev_sig < 0 and pnl < 0)
                lines.extend([
                    "",
                    f"## Previous Day Verification",
                    f"- Date: {prev_date} → {curr_date}",
                    f"- Signal: {'LONG' if prev_sig > 0 else 'SHORT' if prev_sig < 0 else 'FLAT'}",
                    f"- BTC move: {pnl:+.2%}",
                    f"- Result: {'CORRECT' if correct else 'INCORRECT'}",
                ])
        except Exception:
            pass

    with open(report_path, "w") as f:
        f.write("\n".join(lines) + "\n")
    print(f"\nSignal report -> {report_path}")


# ─── Equity plot ────────────────────────────────────────────────

def plot_equity(results: dict, save_path: str = "equity.png"):
    if "train" not in results:
        return

    fig, ax = plt.subplots(1, 1, figsize=(14, 6))
    for period, label, color in [("train", "Train", "#2196F3"), ("val", "Val", "#FF9800")]:
        eq = results[period]["equity_curve"]
        ax.plot(eq.index, eq.values, label=f"Strategy ({label})", color=color)
    ax.axhline(y=1.0, color="gray", linestyle="--", alpha=0.5)
    ax.set_title(f"BTC Daily — Score: {results['score']}")
    ax.set_ylabel("Equity")
    ax.legend()
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(save_path, dpi=100)
    print(f"\nEquity chart -> {save_path}")
    plt.close()


# ─── Standalone mode ────────────────────────────────────────────

if __name__ == "__main__":
    btc, context = load_all_data()
    train, val = split_periods(btc)
    print(f"\nBTC daily: {len(btc)} total, {len(train)} train, {len(val)} val")
    print(f"  Range: {btc.index[0]} -> {btc.index[-1]}")
    print(f"  Price: ${btc['close'].iloc[0]:,.0f} -> ${btc['close'].iloc[-1]:,.0f}")

    print(f"\nContext data:")
    for name, df in context.items():
        if name.startswith("_"):
            continue
        print(f"  {name}: {len(df)} points")

    fomc = context.get("_fomc")
    if fomc is not None:
        upcoming = fomc[fomc["is_fomc_day"] == 1]
        print(f"\n  FOMC days in data: {len(upcoming)}")
