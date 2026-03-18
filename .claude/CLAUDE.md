# Autoquant — autonomous trading strategy optimizer

## What this is

Autonomous agent loop: modify `strategy.py`, backtest on SPY+BTC+ETH daily data, evaluate `score` (higher=better), keep improvements, discard regressions. All commits kept + pushed for transparency.

## Hardware

- GPU: RTX 5070 12GB VRAM (torch available for neural strategies)
- Backtest runtime: ~30-60s per experiment

## Rules

- **ONLY modify `strategy.py`** — prepare.py is read-only
- **NEVER add packages** — only what's in pyproject.toml
- **Metric: `score`** — extract via `grep "^score:" run.log` (higher=better)
- **Run command:** `uv run strategy.py > run.log 2>&1`
- **Timeout:** kill if >2 min
- **Crash:** `tail -n 50 run.log`, attempt fix, move on after 2-3 tries
- **Keep:** score improved → keep, advance best_commit
- **Discard:** score equal/worse → discard (NO git reset, restore best strategy.py)
- **Log:** append to `results.tsv`: `commit | score | sharpe | max_dd | status | description`
- **Push:** `git push origin HEAD` after every experiment
- **Notify:** `./notify.sh "<html>"` after every experiment
- **NEVER STOP** — run indefinitely until manually interrupted

## Data

- Assets: SPY (stocks), BTC, ETH (crypto) — daily candles
- Columns: timestamp, open, high, low, close, volume
- Train: 2019-01 to 2023-06 | Val: 2023-07 to 2025-06 | Holdout: 2025-07+
- Score = weighted composite of sharpe, sortino, drawdown, return, win_rate × trade_penalty × consistency

## Baseline

SMA crossover (20/50). Score TBD on first run.

## What has been tried (don't repeat)

(starts empty — agent populates via results.tsv)
