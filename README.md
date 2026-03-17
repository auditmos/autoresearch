# Autoquant — autonomous trading strategy optimizer

Claude Code autonomously modifies `strategy.py`, backtests on SPY+BTC+ETH daily data, keeps improvements, discards regressions. All commits pushed for transparency. Telegram notifications after each experiment.

Same agent pattern as [karpathy/autoresearch](https://github.com/karpathy/autoresearch), applied to trading strategies instead of ML training.

## Architecture

| Component | File | Role |
|-----------|------|------|
| Strategy | `strategy.py` | Agent modifies — trading signals |
| Engine | `prepare.py` | Read-only — data download, backtest, scoring |
| Agent loop | `program.md` | Instructions for Claude |
| Notifications | `notify.sh` | Telegram alerts (optional) |

**Metric:** `score` (higher=better) — composite of Sharpe, Sortino, drawdown, return, win rate, with overfitting prevention (train/val/holdout splits, consistency penalty).

## Requirements

- NVIDIA GPU (torch available for neural strategies, not required for basic strategies)
- Docker with NVIDIA runtime (`nvidia-container-toolkit`)
- Claude subscription (for autonomous agent mode)
- Alpha Vantage API key (premium recommended)

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

## Quick start

```bash
# .env file
ALPHA_VANTAGE_API_KEY=your_key_here
TELEGRAM_BOT_TOKEN=your_bot_token                                  # optional
TELEGRAM_CHAT_ID=your_chat_id                                      # optional
GIT_REMOTE_URL=https://github_pat_xxxxx@github.com/org/repo.git    # optional

# Build
docker compose build

# Single backtest run (downloads data on first run)
docker compose run autoquant strategy.py

# Authenticate Claude (one-time)
docker compose run autoquant login

# Launch agent
docker compose run -d autoquant agent
```

## VPS workflow

```bash
# Start detached
docker compose run -d autoquant agent

# Attach to tmux session
docker exec -it $(docker ps -q -f ancestor=autoresearch-autoquant) tmux attach -t autoquant

# Detach: Ctrl+B D
# Reconnect anytime with the same attach command
```

## Monitoring

```bash
# Results table
docker exec -it <id> cat results.tsv

# Live backtest output
docker exec -it <id> tail -f run.log

# Git log (all experiments)
docker exec -it <id> git log --oneline

# Best score so far
docker exec -it <id> sort -t$'\t' -k2 -rn results.tsv | head -3
```

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
