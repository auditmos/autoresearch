# Autoquant — BTC Daily Swing (LSTM + On-chain + Macro)

BTC-only daily swing trading. LSTM on GPU, on-chain data (bitcoin-data.com Tier 1), FRED macro, FOMC calendar. Optimize for R:R ratio (target 1:3), not win rate.

## Rules

**CAN:** modify `strategy.py` — LSTM architecture, features, training params, risk params.
**CANNOT:** modify `prepare.py`, add packages, change backtest logic.
**MUST use LSTM (PyTorch GPU)** — rule-based-only strategies are forbidden. LSTM is the core signal generator. You may add rule-based filters/confirmations ON TOP of LSTM signals, but LSTM must remain the primary decision maker. If LSTM baseline scores poorly, fix the LSTM (features, architecture, training), don't replace it.
**Metric:** `score` (higher = better). Extract: `grep "^score:" run.log`
**Also track:** `grep "^avg_rr:\|^profit_factor:" run.log` — R:R and PF are 30% of score.
**Asset:** BTC/USDT daily candles — columns: timestamp, open, high, low, close, volume.

## Data available in `context` dict

### On-chain (bitcoin-data.com, Tier 1, daily):
- `onchain_mvrv`, `onchain_mvrv_sth`, `onchain_mvrv_lth` — valuation
- `onchain_sopr_sth` — realized profit/loss
- `onchain_exchange_netflow` — accumulation vs distribution
- `onchain_nupl` — net unrealized P/L
- `onchain_fear_greed` — crowd sentiment
- `onchain_active_addresses` — network health

### Macro (FRED, daily/weekly/monthly, forward-filled):
- `fred_walcl` — Fed balance sheet (liquidity proxy)
- `fred_dff` — Fed funds rate
- `fred_t10y2y` — yield curve spread (recession signal)
- `fred_vixcls` — VIX (risk appetite)
- `fred_dgs10` — 10Y treasury yield
- `fred_hy_spread` — high yield spread (credit stress)
- `fred_usd_index` — USD trade-weighted index

### Other:
- `funding_rate` — Binance futures funding rate (daily avg)
- `_fomc` — FOMC calendar features (fomc_proximity, is_fomc_day, is_fomc_week)

All context DataFrames have `value` column except `_fomc` (multiple columns).
Access: `context["onchain_mvrv"]["value"]`, forward-fill to daily index with `.reindex(df.index, method="ffill")`.

## Scoring formula

```
score = (
    0.25 * sharpe +
    0.15 * sortino +
    0.15 * (1 + max_drawdown) +
    0.10 * total_return +
    0.05 * win_rate +
    0.15 * min(avg_rr / 3.0, 1.0) +     ← R:R component
    0.15 * min(profit_factor / 3.0, 1.0) ← PF component
) * trade_penalty * consistency
```

- trade_penalty: min(num_trades / 15, 1.0) — need ≥15 trades on val
- consistency: penalizes train/val Sharpe divergence
- **R:R 1:3 = max score on R:R component**
- **Profit factor 3.0 = max score on PF component**

## Experiment loop

LOOP FOREVER:

1. Read `results.tsv`. Find best score + last experiment number.
2. If last was `discard`: `cp strategy_best.py strategy.py`
3. Modify `strategy.py` with new idea.
4. Run: `uv run strategy.py > run.log 2>&1` (timeout: 2 min)
5. Check: `grep "^score:\|^avg_rr:\|^profit_factor:\|^sharpe:" run.log`
   Empty = crash → `tail -n 50 run.log`, fix, retry max 2x then move on.
6. Append to `results.tsv`: `<exp>\t<score>\t<sharpe>\t<max_dd>\t<avg_rr>\t<pf>\t<status>\t<desc>`
7. score > best → keep + `cp strategy.py strategy_best.py` | score ≤ best → discard
8. `./notify.sh "<b>BTC Daily #N</b>\nStatus: keep/discard\nScore: X.XXX\nR:R: X.XX\nPF: X.XX\nDesc: <desc>"`
9. GOTO 1

## Strategy signature

```python
def strategy(df, context) -> tuple[pd.Series, list[dict]]:
    # df: BTC daily OHLCV
    # context: dict of DataFrames (on-chain, FRED, funding, FOMC)
    # returns: (signals, attributions)
    #   signals: pd.Series, +1=long, -1=short, 0=flat
    #   attributions: list of {date, signal, top_features: [str]}
```

## Current state

**Best score: TBD** (first run)

Current strategy: LSTM baseline (128 hidden, 2 layers, lookback=60d)
- Features: price TA + on-chain Tier 1 + FRED macro + funding rate + FOMC calendar
- Risk: ATR(14) SL=1.5x, TP=4.5x (R:R 1:3)
- Target: 5-day forward return
- Threshold: |confidence| > 0.30 to enter

### What worked:
- (starts empty — populate after experiments)

### What failed (do NOT repeat):
- (starts empty — populate after experiments)

## Ideas (priority: structurally different approaches)

**Try first:**
1. Tune LSTM confidence threshold (0.20 vs 0.30 vs 0.40) — affects trade count vs quality
2. Multi-horizon targets: 3d + 5d + 10d ensemble — reduces timing sensitivity
3. Asymmetric signals: different thresholds for long vs short (BTC has long bias)
4. On-chain regime filter: only trade when MVRV_STH < 1.0 (undervalued) for longs
5. FOMC-aware: reduce position size 2 days before FOMC, increase after if direction confirmed
6. Funding rate contrarian: extreme negative funding → long setup (leveraged shorts getting squeezed)
7. Fear & Greed extremes: F&G < 20 → accumulation zone, F&G > 80 → distribution
8. Yield curve regime: different strategy when T10Y2Y inverted vs steep
9. ATR SL/TP tuning: test SL 1.0-2.0, TP 3x-5x SL
10. Ensemble: 3-5 seeds, average predictions (like gpu-ta per-asset approach)

**Later (Tier 2/3 data experiments):**
- Add NVT ratio, liquidations, stablecoin supply, hashrate, BTC dominance
- Dual-input LSTM: separate price encoder + macro/onchain encoder
- Attention mechanism over FOMC windows
- Walk-forward validation instead of fixed split

**Do not try:**
- (starts empty)
