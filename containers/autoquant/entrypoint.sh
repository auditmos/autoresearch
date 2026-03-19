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
        git clone --depth=200 "$GIT_REMOTE_URL" /tmp/live-repo 2>/dev/null \
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
        BRANCH_FLAG=""
        [ -n "$GIT_BRANCH" ] && BRANCH_FLAG="-b $GIT_BRANCH"
        CLONED=false
        # Try to clone from remote (resume previous experiments)
        if [ -n "$GIT_REMOTE_URL" ] && git clone $BRANCH_FLAG "$GIT_REMOTE_URL" /tmp/repo 2>/dev/null; then
            # Check if repo has commits (not empty)
            if git -C /tmp/repo rev-parse HEAD >/dev/null 2>&1; then
                cp -a /tmp/repo/.git /app/.git
                [ -n "$GIT_BRANCH" ] && git checkout "$GIT_BRANCH" 2>/dev/null || true
                git checkout HEAD -- strategy.py 2>/dev/null || true
                git checkout HEAD -- strategy_best.py 2>/dev/null || true
                git checkout HEAD -- results.tsv 2>/dev/null || true
                CLONED=true
                echo "=== Resumed from remote (branch: ${GIT_BRANCH:-default}) ==="
            fi
            rm -rf /tmp/repo
        fi
        if [ "$CLONED" = "false" ]; then
            git init
            [ -n "$GIT_BRANCH" ] && git checkout -b "$GIT_BRANCH"
            git add -A && git commit -m "autoquant baseline"
            # Push initial commit to empty remote
            if [ -n "$GIT_REMOTE_URL" ]; then
                git remote add origin "$GIT_REMOTE_URL" 2>/dev/null || true
                git push -u origin HEAD 2>/dev/null && echo "=== Pushed initial commit ===" || true
            fi
        fi
    fi

    # Ensure strategy_best.py exists
    [ ! -f strategy_best.py ] && cp strategy.py strategy_best.py

    # Set remote if provided
    if [ -n "$GIT_REMOTE_URL" ]; then
        git remote remove origin 2>/dev/null || true
        git remote add origin "$GIT_REMOTE_URL"
    fi

    # Results tracking
    if [ ! -f results.tsv ]; then
        printf 'exp\tscore\tsharpe\tmax_dd\tstatus\tdescription\n' > results.tsv
    fi

    # Background git sync
    [ -d .git ] && ./sync.sh &

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
