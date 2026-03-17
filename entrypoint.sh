#!/bin/bash
set -e

# Fix bind mount permissions (starts as root), then re-exec as researcher
if [ "$(id -u)" = "0" ]; then
    mkdir -p /home/researcher/.cache/autoquant/data
    chown researcher:researcher /home/researcher/.cache/autoquant/data
    chown researcher:researcher /app
    exec runuser -u researcher -- "$0" "$@"
fi

# Everything below runs as researcher
CACHE_DIR="/home/researcher/.cache/autoquant"
DATA_DIR="$CACHE_DIR/data"

# Login mode
if [ "$1" = "login" ]; then
    exec claude login
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
    cp /app/hooks/pre-commit /app/.git/hooks/pre-commit 2>/dev/null || true
    cp /app/hooks/post-commit /app/.git/hooks/post-commit 2>/dev/null || true
    chmod +x /app/.git/hooks/pre-commit /app/.git/hooks/post-commit 2>/dev/null || true

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
        claude -p --dangerously-skip-permissions $MODEL_FLAG \
            "Read program.md, check results.tsv for best score and last experiment, continue experimenting. NEVER STOP."
        echo "=== Claude exited, restarting in 5s ==="
        sleep 5
    done
fi

# Default: run script
exec uv run "$@"
