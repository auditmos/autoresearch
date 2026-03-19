#!/bin/bash
# Background git sync — periodically commits + pushes all changes
INTERVAL="${SYNC_INTERVAL:-300}"

while true; do
    sleep "$INTERVAL"
    [ ! -d .git ] && continue
    git add -A 2>/dev/null || continue
    git diff --cached --quiet && continue
    git commit -m "sync $(date -u +%Y-%m-%dT%H:%M:%SZ)" 2>/dev/null || true
    git push origin HEAD 2>/dev/null || true
done
