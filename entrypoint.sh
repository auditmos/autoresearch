#!/bin/bash
set -e

CACHE_DIR="/home/researcher/.cache/autoquant"
DATA_DIR="$CACHE_DIR/data"

# Login mode
if [ "$1" = "login" ]; then
    exec claude login
fi

# Agent mode: prepare data, init git, launch claude in tmux
if [ "$1" = "agent" ]; then
    echo "=== Autoquant agent mode ==="

    # Download AV data if not cached
    if [ ! -d "$DATA_DIR" ] || [ -z "$(ls -A "$DATA_DIR" 2>/dev/null)" ]; then
        if [ -z "$ALPHA_VANTAGE_API_KEY" ]; then
            echo "Error: ALPHA_VANTAGE_API_KEY required for first run (data not cached)"
            exit 1
        fi
        echo "=== Downloading market data ==="
        uv run prepare.py
        echo "=== Data ready ==="
    fi

    # Git init if needed
    if [ ! -d .git ]; then
        git config --global user.email "researcher@autoquant"
        git config --global user.name "researcher"
        git init && git add -A && git commit -m "autoquant baseline"
        git checkout -b autoquant/experiment
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

    # Launch claude in tmux session
    exec tmux new-session -s autoquant \
        "claude --dangerously-skip-permissions 'Read program.md and start experimenting.'"
fi

# Default: run script
exec uv run "$@"
