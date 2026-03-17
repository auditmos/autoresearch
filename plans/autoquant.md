# Plan: Autoquant — trading strategy optimization branch

## Context

Working autoresearch Docker setup on RTX 5070 for GPT training. Adding trading strategy optimization mode using same autonomous agent pattern (modify→run→evaluate→keep/discard). **Alpha Vantage premium** for data (stocks, crypto, forex, commodities, 50+ built-in indicators, news sentiment, economic data).

## Architecture — same 2-file pattern

| | autoresearch (current) | autoquant (new) |
|---|---|---|
| Agent modifies | `train.py` (GPT model) | `strategy.py` (trading signals) |
| Read-only | `prepare.py` (data + BPB eval) | `prepare.py` (AV data + backtest engine + scoring) |
| Metric | `val_bpb` (lower=better) | `score` (higher=better, Sharpe-based composite) |
| Run time | 10 min | ~30-60s |
| Experiments/hour | ~5 | ~30+ |
| Data source | HuggingFace parquet | Alpha Vantage API (premium) |

## Files to create (branch `autoquant`)

### 1. `prepare.py` (read-only by agent)

Three responsibilities:

**a) Data download via Alpha Vantage API:**
- `TIME_SERIES_DAILY_ADJUSTED` for stocks (SPY, AAPL) + `DIGITAL_CURRENCY_DAILY` for crypto (BTC, ETH)
- Full output (20+ years for stocks, all history for crypto)
- Cache as parquet in `~/.cache/autoquant/data/`
- Requires `ALPHA_VANTAGE_API_KEY` env var
- Columns normalized to: `timestamp, open, high, low, close, volume`
- Download on first run, skip if cached

**b) Backtest engine (vectorized numpy, ~150 lines):**
- Input: `strategy(df) → pd.Series` of signals (+1 long, -1 short, 0 flat)
- Simulates equity curve with commission (0.1%) + slippage (0.05%)
- Computes: Sharpe, Sortino, max drawdown, total return, win rate, trade count

**c) Composite scoring:**
```
score = (0.4×sharpe + 0.2×sortino + 0.2×(1+max_dd) + 0.1×return + 0.1×win_rate)
        × trade_penalty(min 20 trades)
        × consistency(train vs val sharpe similarity)
```

**Overfitting prevention (3 periods):**
- Train: 2019-01 to 2023-06 (agent sees metrics, doesn't optimize for)
- Validation: 2023-07 to 2025-06 (**keep/discard metric**)
- Holdout: 2025-07 to 2025-12 (human review only)

**Output format:**
```
score:        1.234
sharpe:       1.85
sortino:      2.41
max_drawdown: -0.18
total_return:  0.45
win_rate:     0.58
num_trades:   47
consistency:  0.92
```

**Assets downloaded by default:**
- `SPY` (S&P 500 ETF — broad market)
- `BTC` (Bitcoin)
- `ETH` (Ethereum)
- Multi-asset averaging: strategy must work on all → resists overfitting

### 2. `strategy.py` (agent modifies)

Baseline: dual SMA crossover. Exports `strategy(df) → pd.Series`.

```python
def strategy(df: pd.DataFrame) -> pd.Series:
    fast_ma = df['close'].rolling(20).mean()
    slow_ma = df['close'].rolling(50).mean()
    signals = pd.Series(0, index=df.index)
    signals[fast_ma > slow_ma] = 1
    signals[fast_ma < slow_ma] = -1
    return signals
```

Bottom: runner boilerplate that imports prepare.py, runs backtest on train+val for each asset, prints metrics.

Agent can add: RSI, MACD, Bollinger, ATR, neural nets (torch GPU), regime detection, multi-timeframe, ensemble voting, etc.

### 3. `pyproject.toml`

```toml
dependencies = [
    "numpy>=2.2.6",
    "pandas>=2.3.3",
    "pyarrow>=21.0.0",
    "matplotlib>=3.10.8",
    "requests>=2.32.0",
    "torch==2.9.1",
]
```
Removed: `rustbpe`, `tiktoken`, `kernels`, `ccxt`
Added: nothing extra (Alpha Vantage = `requests` only, already in deps)

### 4. `Dockerfile`

- Remove Rust toolchain (no rustbpe → saves ~5 min build)
- Keep CUDA base (torch GPU strategies)
- COPY `prepare.py` + `strategy.py` + `program.md`
- Same non-root user + Claude CLI

### 5. `entrypoint.sh`

```bash
# Login mode
if [ "$1" = "login" ]; then exec claude login; fi

# Agent mode
if [ "$1" = "agent" ]; then
    # check ALPHA_VANTAGE_API_KEY
    # git init, results.tsv baseline
    exec claude --dangerously-skip-permissions "Read program.md..."
fi

# Default: run strategy
exec uv run strategy.py
```

### 6. `docker-compose.yml`

```yaml
services:
  autoquant:
    environment:
      - ALPHA_VANTAGE_API_KEY=${ALPHA_VANTAGE_API_KEY}
    volumes:
      - ./data:/home/researcher/.cache/autoquant/data    # host-mounted, survives everything
      - claude-config:/home/researcher/.claude
```

Data persists on host at `~/autoresearch/data/` — visible, backupable, survives `docker system prune`.

### 7. `program.md` — agent instructions

- Metric: `score` (higher=better), `grep "^score:" run.log`
- Data: SPY + BTC + ETH, daily, multi-asset averaging
- Agent modifies only `strategy.py`
- Timeout: 2 min max
- results.tsv: `commit | score | sharpe | max_dd | status | description`
- Ideas: RSI, MACD, Bollinger, ATR stops, momentum, mean reversion, neural signals, regime detection, volume analysis, macro overlay

### 8. `.claude/CLAUDE.md`

- Hardware: RTX 5070 12GB (torch available for neural strategies)
- Rules: modify `strategy.py` only, metric = `score` (higher=better)
- Baseline: SMA crossover (TBD)
- What's been tried: starts empty
- Available data columns: timestamp, open, high, low, close, volume
- Alpha Vantage indicators NOT pre-fetched — agent implements locally in strategy.py using pandas/numpy/torch

### 9. `README.md`

Quick start, setup instructions, monitoring guide (same style as current README).

## Implementation order

1. `prepare.py` — AV data download + backtest engine + scoring
2. `strategy.py` — SMA baseline + runner
3. `pyproject.toml` — trimmed deps
4. `Dockerfile` — no Rust, keep CUDA
5. `entrypoint.sh` — autoquant modes
6. `program.md` + `.claude/CLAUDE.md`
7. `docker-compose.yml`
8. `README.md`
9. Push to `auditmos/autoresearch` branch `autoquant`

## Verification

1. `docker compose build` — builds OK
2. `ALPHA_VANTAGE_API_KEY=... docker compose up` — downloads SPY/BTC/ETH, runs SMA backtest, prints score
3. `docker compose run autoquant agent` — Claude starts experiment loop
4. After 1h: `docker exec <id> cat results.tsv` — experiments logged

## Decisions (confirmed)

- **Branch `autoquant`** in repo `auditmos/autoresearch`
- **Long + short** (signals +1/-1/0)
- **SPY + BTC + ETH** (daily candles, multi-asset averaging)
- **Alpha Vantage premium** for data (not ccxt)
- **No leverage** (max_position_frac=1.0)
- **No bundled CSV** (AV downloads on first run, cached in volume)
