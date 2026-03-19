#!/bin/bash
set -e

# PATTERN: Start as root, fix bind-mount permissions, re-exec as researcher
# Bind mounts are created as root:root by Docker — fix before switching user
if [ "$(id -u)" = "0" ]; then
    mkdir -p /home/researcher/.cache/yourapp
    chown -R researcher:researcher /home/researcher/.cache/yourapp /app
    exec runuser -u researcher -- "$0" "$@"
fi

# Everything below runs as researcher

# PATTERN: Separate login mode — run outside tmux for readable auth URL
# Usage: docker compose run your-service login
if [ "$1" = "login" ]; then
    exec claude login
fi

# PATTERN: Autonomous agent mode
if [ "$1" = "agent" ]; then
    echo "=== Agent mode ==="

    # PATTERN: git safe.directory — required when /app was owned by root
    git config --global --add safe.directory /app
    git config --global user.email "agent@yourapp"
    git config --global user.name "agent"

    # PATTERN: Persist git state across container restarts via remote clone
    # /app is not a volume — state is lost on container stop without this
    if [ ! -d .git ]; then
        if [ -n "$GIT_REMOTE_URL" ] && git clone "$GIT_REMOTE_URL" /tmp/repo 2>/dev/null; then
            cp -a /tmp/repo/.git /app/.git
            git checkout HEAD -- important_file.txt 2>/dev/null || true
            rm -rf /tmp/repo
            echo "=== Resumed from remote ==="
        else
            git init && git add -A && git commit -m "baseline"
        fi
    fi

    # Set remote if provided
    if [ -n "$GIT_REMOTE_URL" ]; then
        git remote remove origin 2>/dev/null || true
        git remote add origin "$GIT_REMOTE_URL"
    fi

    # PATTERN: Background sync — periodic git add/commit/push
    [ -d .git ] && ./sync.sh &

    # PATTERN: Claude -p with while loop
    # -p (non-interactive) exits after prompt — wrap in loop to auto-restart
    # Never use interactive mode: theme picker + TTY issues break in containers
    MODEL_FLAG=""
    [ -n "$CLAUDE_MODEL" ] && MODEL_FLAG="--model $CLAUDE_MODEL"
    while true; do
        claude -p --dangerously-skip-permissions $MODEL_FLAG \
            "Read program.md and continue your autonomous task. NEVER STOP."
        echo "=== Claude exited, restarting in 5s ==="
        sleep 5
    done
fi

# Default: run arbitrary command
exec uv run "$@"
