# Autoquant — autonomous trading strategy optimizer

Claude Code autonomously modifies `strategy.py`, backtests on SPY+BTC+ETH daily data, keeps improvements, discards regressions. All commits pushed for transparency. Telegram notifications after each experiment.

Same agent pattern as [karpathy/autoresearch](https://github.com/karpathy/autoresearch), applied to trading strategies instead of ML training.

## Repository structure

```
autoresearch/
├── containers/
│   └── autoquant/          # single Docker image (CPU + GPU)
│       ├── Dockerfile
│       ├── docker-compose.yml
│       ├── entrypoint.sh
│       ├── notify.sh
│       └── hooks/          # pre/post-commit git hooks
│
├── experiments/            # experiment configs — one folder per variant
│   ├── .env.example        # template — copy to each experiment folder
│   ├── cpu-ta/             # CPU strategies (SMA, indicators, pandas/numpy)
│   │   ├── strategy.py
│   │   ├── prepare.py
│   │   ├── live_signals.py # daily signal monitor (see Live signals section)
│   │   ├── program.md
│   │   ├── pyproject.toml
│   │   ├── .python-version
│   │   └── .env            # gitignored — keys + GIT_REMOTE_URL for this experiment
│   ├── gpu-ta/             # GPU strategies (LSTM, PyTorch, CUDA)
│   │   ├── strategy.py
│   │   ├── prepare.py
│   │   ├── program.md
│   │   ├── pyproject.toml
│   │   ├── .python-version
│   │   └── .env            # gitignored — keys + GIT_REMOTE_URL for this experiment
│   └── btc-daily/          # BTC-only daily swing (LSTM + on-chain + FRED macro + FOMC)
│       ├── strategy.py
│       ├── prepare.py
│       ├── program.md
│       ├── pyproject.toml
│       ├── .python-version
│       ├── EXPERIMENT_NOTES.md  # v1 results: 80 experiments, best score 1.4155
│       └── .env            # gitignored — keys (AV + FRED + bitcoin-data.com)
│
├── data/                   # shared market data — gitignored
│                           # downloaded once, reused by all experiments
└── README.md
```

**One image, swappable experiments.** The `EXPERIMENT` env var tells the container which folder to load. Experiment files are mounted read-only at `/experiment` — the container copies them to `/app` at startup and runs `uv sync` (fast: uv cache is a named Docker volume).

## Who edits what

| File | Who | Role |
|------|-----|------|
| `experiments/*/program.md` | **user** | defines the task — goal, constraints, what to try, what to avoid |
| `experiments/*/strategy.py` | **agent** | trading logic — modified every experiment iteration |
| `experiments/*/prepare.py` | **user** | read-only for agent — data loading, backtest engine, scoring |
| `experiments/*/pyproject.toml` | **user** | Python dependencies |
| `experiments/*/.env` | **user** | secrets + config per experiment |
| `containers/autoquant/` | **user** | Docker infrastructure — rarely changes |

**Metric:** `score` (higher=better) — composite of Sharpe, Sortino, drawdown, return, win rate, with overfitting prevention (train/val/holdout splits, consistency penalty).

## Requirements

- NVIDIA GPU + `nvidia-container-toolkit` (required for gpu-ta, optional for cpu-ta)
- Docker
- Claude subscription
- Alpha Vantage API key (premium recommended)
- FRED API key (free, for btc-daily macro data)
- bitcoin-data.com API key (for btc-daily on-chain data)

## Secrets setup

### Alpha Vantage API key

Get one at https://www.alphavantage.co/support/#api-key (premium recommended for no rate limits).

### Telegram bot + chat ID

1. Message `@BotFather` on Telegram → `/newbot` → pick name/username → copy the token
2. Add your bot to the channel/group as admin
3. Send a message in the channel
4. Open `https://api.telegram.org/bot<TOKEN>/getUpdates` — find `"chat":{"id":-100xxxxxxxxxx}`
5. That negative number is your `TELEGRAM_CHAT_ID`

### GitHub personal access token

1. https://github.com/settings/tokens → "Generate new token" → **Fine-grained token**
2. Resource owner: your org/account
3. Repository access: select the target repo
4. Permissions: **Contents** → Read and write
5. Generate → copy the `github_pat_...` token

## Upload to VPS via scp

If you prefer scp over git clone (e.g. VPS has no GitHub access):

```bash
# Upload entire repo (excludes data/ and .env files — add locally on VPS)
scp -r autoresearch/ user@vps-host:~/

# Or upload only what changed (experiment files)
scp experiments/cpu-ta/{strategy.py,prepare.py,program.md,pyproject.toml,.python-version} \
    user@vps-host:~/autoresearch/experiments/cpu-ta/

# Upload .env separately (never commit secrets)
scp experiments/cpu-ta/.env user@vps-host:~/autoresearch/experiments/cpu-ta/.env
```

> **Tip:** Use `rsync` for incremental syncs after initial upload:
> ```bash
> rsync -av --exclude='data/' --exclude='**/.env' --exclude='**/__pycache__' \
>     autoresearch/ user@vps-host:~/autoresearch/
> ```

## VPS setup

```bash
# 1. Clone repo
git clone https://github.com/auditmos/autoresearch.git
cd autoresearch

# 2. Create .env per experiment
cp experiments/.env.example experiments/cpu-ta/.env
cp experiments/.env.example experiments/gpu-ta/.env
# edit each .env — fill in keys, set correct EXPERIMENT and GIT_REMOTE_URL

# 3. Build image (once)
cd containers/autoquant
docker compose build

# 4. Authenticate Claude — once per experiment (each has its own claude-config volume)
docker compose -p cpu-ta --env-file ../../experiments/cpu-ta/.env run autoquant login
docker compose -p gpu-ta --env-file ../../experiments/gpu-ta/.env run autoquant login
```

## Running experiments

All commands from `containers/autoquant/`. Use `-p <name>` + `--env-file` to run experiments independently and simultaneously.

```bash
cd containers/autoquant

# Launch agent — cpu-ta
docker compose -p cpu-ta --env-file ../../experiments/cpu-ta/.env run -d autoquant agent

# Launch agent — gpu-ta (simultaneously)
docker compose -p gpu-ta --env-file ../../experiments/gpu-ta/.env run -d autoquant agent

# Single backtest
docker compose -p cpu-ta --env-file ../../experiments/cpu-ta/.env run autoquant strategy.py

# Status per experiment
docker compose -p cpu-ta ps
docker compose -p gpu-ta ps

# Stop specific experiment
docker compose -p gpu-ta down
```

> **Note:** Market data (`data/`) is shared between all experiments and downloaded once on first run. Subsequent runs (even switching experiments) skip the download.

## Live signals

`live_signals.py` (cpu-ta only) loads the current best strategy from git, generates LONG/SHORT/FLAT signals for SPY, BTC, ETH, and sends Telegram notifications. Run it on a cron or manually:

```bash
# Run once — refresh data, emit signals, notify on changes
docker compose -p cpu-ta --env-file ../../experiments/cpu-ta/.env run autoquant live
```

What it does each run:
- Refreshes market data (re-downloads only if stale)
- Loads best `strategy.py` commit from `results.tsv`
- Detects signal changes → Telegram alert
- Sends daily summary (once per day)
- Tracks open signals and verifies them after `VERIFY_DAYS` days (default 7) — reports ✅/❌ vs entry price

State is persisted in `~/.cache/autoquant/live_signals_state.json` inside the container (bind-mount or named volume to persist across runs).

| Env var | Default | Description |
|---------|---------|-------------|
| `VERIFY_DAYS` | `7` | Days after signal to check outcome |
| `REPO_DIR` | auto-detected | Override repo path (useful if running outside container) |

## Monitoring

```bash
# Live agent output (Ctrl+C to detach, container keeps running)
docker compose -p cpu-ta logs -f

# Restart a hung claude without killing the container (loop auto-restarts in 5s)
docker compose -p cpu-ta exec autoquant kill $(cat /tmp/claude.pid)
# Claude also auto-kills itself after 20min if hung

# Results table
docker compose -p gpu-ta exec autoquant cat results.tsv

# Best score so far
docker compose -p gpu-ta exec autoquant sort -t$'\t' -k2 -rn results.tsv | head -3

# Live backtest output
docker compose -p gpu-ta exec autoquant tail -f run.log

# Git log (all experiments)
docker compose -p gpu-ta exec autoquant git log --oneline
```

## Adding a new experiment

1. Copy an existing experiment folder: `cp -r experiments/cpu-ta experiments/my-strategy`
2. Edit `strategy.py`, `prepare.py`, `program.md` as needed
3. Run: `EXPERIMENT=my-strategy docker compose -f containers/autoquant/docker-compose.yml run autoquant agent`

No image rebuild needed — experiment files are mounted at runtime.

## How it works

1. Agent reads `results.tsv`, finds best score + commit
2. If last was discard: restores best `strategy.py` from git
3. Modifies `strategy.py` with new idea
4. Commits, runs backtest (~30-60s)
5. Extracts metrics, appends to `results.tsv`
6. Keeps or discards (no git reset — linear history)
7. Pushes to remote, sends Telegram notification
8. Repeats forever

## License

MIT
