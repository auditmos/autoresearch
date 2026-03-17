# Autoquant — autonomous trading strategy optimizer

You modify `strategy.py`, run backtests, keep improvements, discard regressions. Loop forever.

## Rules

**CAN:** modify `strategy.py` — signals, indicators, filters, ML models, everything.

**CANNOT:** modify `prepare.py`, add packages, change backtest/scoring logic.

**Metric:** `score` (higher = better). Extract: `grep "^score:" run.log`

**Assets:** SPY + BTC + ETH daily candles, multi-asset averaging.

**Available columns:** timestamp, open, high, low, close, volume

## Experiment loop

LOOP FOREVER:

1. Read `results.tsv`. Find best score and its commit hash (`best_commit`).
2. If last experiment was `discard`: restore best strategy:
   `git show <best_commit>:strategy.py > strategy.py`
3. Modify `strategy.py` with a new idea.
4. `git add strategy.py && git commit -m "<short description>"`
5. Run: `uv run strategy.py > run.log 2>&1`
6. Check: `grep "^score:\|^sharpe:\|^max_drawdown:" run.log`
   Empty output = crash → `tail -n 50 run.log`, attempt fix.
7. Append to `results.tsv` (tab-separated):
   `<commit_hash>\t<score>\t<sharpe>\t<max_dd>\t<status>\t<description>`
8. If score > best → status=`keep`
   If score ≤ best → status=`discard` (**NO git reset** — all commits stay)
9. Push: `git push origin HEAD 2>/dev/null || echo "push failed, continuing"`
10. Notify: `./notify.sh "<b>Autoquant #N</b>
Status: keep ✅ / discard ❌
Score: X.XXX (best: X.XXX)
Sharpe: X.XX | MaxDD: -XX%
Desc: <description>"`
11. GOTO 1

**Timeout:** each backtest ~30-60s. Kill if >2 min.

**Crash handling:** `tail -n 50 run.log`, notify error, attempt fix, move on after 2-3 tries.

**NEVER STOP.** Run indefinitely until manually interrupted.

## Ideas to explore

- RSI overbought/oversold filters
- MACD signal line crossover
- Bollinger Band breakout / mean reversion
- ATR-based stop losses and position sizing
- Volume-weighted signals
- Momentum (ROC, Williams %R)
- Multi-timeframe (weekly + daily)
- Regime detection (volatility-based switching)
- Ensemble voting (combine multiple signals)
- Neural signals (torch GPU — small MLP on features)
- Trend strength filters (ADX)
- Seasonal / day-of-week patterns
- Mean reversion vs momentum regime switching
