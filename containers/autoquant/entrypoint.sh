#!/bin/bash
set -e

# Fix bind mount permissions (starts as root), then re-exec as researcher
if [ "$(id -u)" = "0" ]; then
    mkdir -p /home/researcher/.cache/autoquant/data
    mkdir -p /home/researcher/.local/share/uv
    chown -R researcher:researcher /home/researcher/.cache/autoquant
    chown -R researcher:researcher /home/researcher/.local
    chown researcher:researcher /app
    exec runuser -u researcher -- "$0" "$@"
fi

# Everything below runs as researcher
CACHE_DIR="/home/researcher/.cache/autoquant"
DATA_DIR="$CACHE_DIR/data"

# Login mode (no experiment setup needed)
if [ "$1" = "login" ]; then
    exec claude login
fi

# Copy experiment files from mounted /experiment and install deps
echo "=== Loading experiment: ${EXPERIMENT:-cpu-ta} ==="
cp /experiment/strategy.py /experiment/prepare.py /experiment/program.md .
cp /experiment/pyproject.toml /experiment/.python-version .
# live_signals.py is optional (only in cpu-ta experiment)
[ -f /experiment/live_signals.py ] && cp /experiment/live_signals.py .
uv sync --quiet

# Live signals mode
if [ "$1" = "live" ]; then
    echo "=== Live signals mode ==="
    git config --global --add safe.directory /app
    # Clone from remote to get results.tsv + full git history
    if [ -n "$GIT_REMOTE_URL" ]; then
        git clone --branch autoquant/experiment --depth=200 "$GIT_REMOTE_URL" /tmp/live-repo 2>/dev/null \
            && export REPO_DIR=/tmp/live-repo \
            && echo "=== Loaded repo from $GIT_REMOTE_URL ===" \
            || echo "Warning: git clone failed, REPO_DIR not set"
    fi
    exec uv run live_signals.py
fi

# Agent mode
if [ "$1" = "agent" ]; then
    echo "=== Autoquant agent mode ==="

    # Download AV data if not cached
    if [ -z "$(ls -A "$DATA_DIR" 2>/dev/null)" ]; then
        if [ -z "$ALPHA_VANTAGE_API_KEY" ]; then
            echo "Error: ALPHA_VANTAGE_API_KEY required for first run (data not cached)"
            exit 1
        fi
        echo "=== Downloading market data ==="
        uv run prepare.py
        echo "=== Data ready ==="
    fi

    # Git setup
    git config --global --add safe.directory /app
    git config --global user.email "researcher@autoquant"
    git config --global user.name "researcher"

    if [ ! -d .git ]; then
        # Try to clone from remote (resume previous experiments)
        if [ -n "$GIT_REMOTE_URL" ] && git clone "$GIT_REMOTE_URL" /tmp/repo 2>/dev/null; then
            cp -a /tmp/repo/.git /app/.git
            git checkout autoquant/experiment 2>/dev/null || true
            # Restore strategy.py + results.tsv from remote
            git checkout HEAD -- strategy.py 2>/dev/null || true
            git checkout HEAD -- results.tsv 2>/dev/null || true
            rm -rf /tmp/repo
            echo "=== Resumed from remote ==="
        else
            git init && git add -A && git commit -m "autoquant baseline"
            git checkout -b autoquant/experiment
        fi
    fi

    # Install hooks AFTER git dir is fully set up (clone overwrites .git/hooks)
    cp /app/hooks/pre-commit /app/.git/hooks/pre-commit 2>/dev/null || true
    cp /app/hooks/post-commit /app/.git/hooks/post-commit 2>/dev/null || true
    chmod +x /app/.git/hooks/pre-commit /app/.git/hooks/post-commit 2>/dev/null || true

    # Set remote if provided
    if [ -n "$GIT_REMOTE_URL" ]; then
        git remote remove origin 2>/dev/null || true
        git remote add origin "$GIT_REMOTE_URL"
    fi

    # Results tracking
    if [ ! -f results.tsv ]; then
        printf 'commit\tscore\tsharpe\tmax_dd\tstatus\tdescription\n' > results.tsv
    fi

    # Launch claude in loop (-p exits when done, shell restarts it)
    MODEL_FLAG=""
    [ -n "$CLAUDE_MODEL" ] && MODEL_FLAG="--model $CLAUDE_MODEL"
    while true; do
        # Detect if stuck: last 5 experiments all discards at same score
        STUCK=""
        if [ -f results.tsv ] && [ "$(tail -n 5 results.tsv | grep -c discard)" = "5" ]; then
            SCORES=$(tail -n 5 results.tsv | awk -F'\t' '{print $2}' | sort -u)
            [ "$(echo "$SCORES" | wc -l)" = "1" ] && STUCK="You are stuck — last 5 experiments all scored the same. STOP fine-tuning parameters. Try a completely different approach: new indicator family, different signal logic, or restructure the strategy entirely."
        fi
        # Run in background so kill $CLAUDE_PID doesn't kill the loop
        # timeout 1200s kills hung claude after 20min
        timeout 1200 claude -p --dangerously-skip-permissions $MODEL_FLAG \
            "Read program.md, check results.tsv for best score and last experiment, run next experiment. $STUCK NEVER STOP." &
        CLAUDE_PID=$!
        echo $CLAUDE_PID > /tmp/claude.pid
        wait $CLAUDE_PID || true
        echo "=== Claude exited, restarting in 5s ==="
        sleep 5
    done
fi

# Default: run script
exec uv run "$@"
