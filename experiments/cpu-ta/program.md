# Autoquant — autonomous trading strategy optimizer

Modify `strategy.py` to maximize `score`. Loop forever.

## Rules

**CAN:** modify `strategy.py` — signals, indicators, filters, ML, everything.

**CANNOT:** modify `prepare.py`, add packages, change backtest logic.

**Metric:** `score` (higher = better). Extract: `grep "^score:" run.log`

**Assets:** SPY + BTC + ETH, daily candles. Columns: timestamp, open, high, low, close, volume.

## Experiment loop

LOOP FOREVER:

1. Read `results.tsv`. Find best score + commit hash (`best_commit`).
2. If last was `discard`: restore best: `git show <best_commit>:strategy.py > strategy.py`
3. Modify `strategy.py` with a new idea.
4. `git add strategy.py results.tsv && git commit -m "<short desc>"`
5. Run: `uv run strategy.py > run.log 2>&1` (timeout: 2 min)
6. Check: `grep "^score:\|^sharpe:\|^max_drawdown:" run.log`
   Empty = crash → `tail -n 50 run.log`, fix, retry max 2x then move on.
7. Append to `results.tsv`: `<commit>\t<score>\t<sharpe>\t<max_dd>\t<status>\t<desc>`
8. score > best → keep | score ≤ best → discard (no git reset)
9. `git push origin HEAD 2>/dev/null || echo "push failed, continuing"`
10. `./notify.sh "<b>Autoquant #N</b>\nStatus: keep ✅ / discard ❌\nScore: X.XXX (best: X.XXX)\nSharpe: X.XX | MaxDD: -XX%\nDesc: <desc>"`
11. GOTO 1

## Current state (177+ experiments)

**Best score: 0.786364** (commit: "BB breakout DI 8.5")

Current strategy: long-only, SMA50 filter, EMA-smoothed ADX>20, DI+>11.5 entry,
BB dip-buy secondary entry, vol regime filter, volume>median, secondary ADX>39/DI>6 breakout.
Sharpe ~0.84, MaxDD ~-15%, val 2023-07→2025-06.

### What worked:
- **Long-only** — breakthrough (#14: 0.546). Short signals hurt on SPY.
- **EMA-smoothed ADX** (#115: 0.758) — raw ADX worse
- **DI+ entry filter** (11.5) — eliminates weak trends
- **BB dip-buy** — secondary entry on pullbacks within trend
- **Vol regime filter** — avoids high-volatility periods
- **Volume > median** — confirms signal

### What failed (do NOT repeat):
- Short signals on SPY
- BB breakout + MACD histogram confirmation (#171: 0.779)
- BB dip-buy + ROC(10) momentum filter (#172: 0.587)
- BB breakout 1% above upper band (#173: 0.738)
- BB breakout requires BB expansion (#174: 0.785)
- Volume confirmation on secondary entry (#175: 0.669)
- Micro-tuning ADX/DI/BB params — space exhausted, stuck at 0.786

## Ideas (priority: structurally different approaches)

**Try these first:**
- Mean reversion overlay: RSI(2) oversold dip-buy within SMA200 uptrend
- Seasonality filter: day-of-week / month-of-year pattern
- Multi-timeframe: weekly SMA as regime filter, daily for entries
- Volatility-adjusted sizing: ATR-based position scale (0.5/1.0) instead of binary
- ATR trailing stop: exit when price drops X×ATR from peak
- Skip-month momentum: 12-1 month cross-asset momentum signal
- Regime switching: trend-following vs mean-reversion based on vol ratio
- Neural MLP: small feature set (rsi, macd, atr, vol_ratio) → torch CPU

**Do not try:**
- Fine-tuning ADX/DI/BB parameters — exhausted
- Short signals on SPY
- Adding more indicators to existing structure without changing logic
