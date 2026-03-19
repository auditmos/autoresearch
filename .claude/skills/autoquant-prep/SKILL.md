# autoquant-prep

Prepares a new autoquant experiment: generates `program.md`, `prepare.py`, and initial `strategy.py` for a given experiment slot under `experiments/<name>/`.

## When to use

Invoke when the user wants to:
- Start a new trading strategy experiment
- Reset an experiment to a clean baseline
- Scaffold a new experiment variant (new assets, timeframe, strategy family)
- Update program.md with experiment history

## Workflow

1. **Identify target** — ask for experiment name (default: `cpu-ta`), or infer from context.
2. **Ask strategy intent** — what to try? (momentum, mean-reversion, ML, crypto, daily/hourly, etc.)
3. **Gather history** — if experiment has results, read `results.tsv` + current `strategy.py` to extract: best score, what worked, what failed, per-asset breakdown.
4. **Generate 3 files** in `experiments/<name>/`:
   - `program.md` — rich agent instructions (see template below)
   - `prepare.py` — data download + vectorized backtest engine + scoring
   - `strategy.py` — minimal baseline

## program.md template

The most important file — quality here determines agent behavior. Use this structure:

```markdown
# Autoquant — <experiment name>

<one-line goal>

## Rules

**CAN:** modify `strategy.py` — signals, indicators, filters, ML.
**CANNOT:** modify `prepare.py`, add packages, change backtest logic.
**Metric:** `score` (higher = better). Extract: `grep "^score:" run.log`
**Assets:** <list> — columns: timestamp, open, high, low, close, volume.

## Experiment loop

LOOP FOREVER:

1. Read `results.tsv`. Find best score + last experiment number.
2. If last was `discard`: `cp strategy_best.py strategy.py`
3. Modify `strategy.py` with new idea.
4. Run: `uv run strategy.py > run.log 2>&1` (timeout: 2 min)
5. Check: `grep "^score:\|^sharpe:\|^max_drawdown:" run.log`
   Empty = crash → `tail -n 50 run.log`, fix, retry max 2x then move on.
6. Append to `results.tsv`: `<exp>\t<score>\t<sharpe>\t<max_dd>\t<status>\t<desc>`
7. score > best → keep + `cp strategy.py strategy_best.py` | score ≤ best → discard
8. `./notify.sh "<b>Autoquant #N</b>\nStatus: keep/discard\nScore: X.XXX\nDesc: <desc>"`
9. GOTO 1

## Current state

**Best score: <X.XXX>** (<commit description>)

Current strategy: <describe in 1-2 lines>
Sharpe ~X.XX, MaxDD ~-XX%, val <period>.

### What worked:
- <bullet per key technique that improved score>

### What failed (do NOT repeat):
- <bullet per failed approach, with score if notable>
- Micro-tuning params — space exhausted (add this when stuck)

## Ideas (priority: structurally different approaches)

**Try first:**
- <3-5 concrete ideas not yet tried, structurally different from current>
- Be specific: "RSI(2) < 10 dip-buy" not "try mean reversion"

**Do not try:**
- <exhausted approaches>
```

### Key principles for a good program.md:

- **History section is critical** — without it, agent repeats failed ideas every restart
- **"Do not try" list** is as important as the ideas list
- **Concrete beats vague** — "RSI(2) oversold dip-buy" > "try mean reversion"
- **Update after every ~50 experiments** or when stuck at a plateau
- **Per-asset breakdown** helps when assets behave differently (BTC vs SPY vs ETH)

## prepare.py specs

- Read-only by agent — never modify
- Must export: `load_all_assets()`, `run_backtest(fn, assets)`, `print_metrics(metrics)`
- Output format (grep-parseable): `score:`, `sharpe:`, `sortino:`, `max_drawdown:`, `total_return:`, `win_rate:`, `num_trades:`, `consistency:`
- Splits: train 2019-01→2023-06, val 2023-07→2025-06, holdout 2025-07+
- Score: `(0.4*sharpe + 0.2*sortino + 0.2*(1+max_dd) + 0.1*return + 0.1*win_rate) * trade_penalty * consistency`
- Assets: SPY, BTC, ETH via Alpha Vantage — cache as parquet in `~/.cache/autoquant/data/`

## strategy.py specs

- Exports `strategy(df) -> pd.Series` of signals (+1 long, -1 short, 0 flat)
- Runner block at bottom: `from prepare import load_all_assets, run_backtest, print_metrics`
- Keep minimal — agent evolves it

## Existing experiments

| Name | Best score | Description |
|------|------------|-------------|
| `cpu-ta` | 0.786 | Daily SPY+BTC+ETH, CPU TA, long-only, ADX+BB |
| `gpu-ta`  | 0.408 | 1H multi-crypto, LSTM PyTorch GPU |

## Checklist

- [ ] `pyproject.toml` present (copy from cpu-ta if missing)
- [ ] `.python-version` present (copy from cpu-ta if missing)
- [ ] `results.tsv` absent (entrypoint creates it)
- [ ] `strategy.py` exports `strategy(df) -> pd.Series`
- [ ] `prepare.py` prints `score:` as first metric line
- [ ] `program.md` has history section (worked / failed)
- [ ] `program.md` has concrete "try first" ideas, not vague categories
