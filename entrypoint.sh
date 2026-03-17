#!/bin/bash
set -e

CACHE_DIR="/home/researcher/.cache/autoresearch"

# Auto-prepare data + tokenizer on first run
if [ ! -d "$CACHE_DIR/tokenizer" ]; then
    echo "=== First run: downloading data shards + training tokenizer ==="
    uv run prepare.py --num-shards 8
    echo "=== Data ready ==="
fi

# Login mode: authenticate claude with subscription
if [ "$1" = "login" ]; then
    exec claude login
fi

# Agent mode: init git, setup results.tsv, launch claude
if [ "$1" = "agent" ]; then
    echo "=== Agent mode ==="

    # Git init if needed
    if [ ! -d .git ]; then
        git config --global user.email "researcher@autoresearch"
        git config --global user.name "researcher"
        git init && git add -A && git commit -m "baseline val_bpb=1.104"
        git checkout -b autoresearch/experiment
    fi

    # Results tracking
    if [ ! -f results.tsv ]; then
        printf 'commit\tval_bpb\tmemory_gb\tstatus\tdescription\n' > results.tsv
        printf 'baseline\t1.104000\t6.2\tkeep\tbaseline DEPTH=8 10min\n' >> results.tsv
    fi

    exec claude --dangerously-skip-permissions \
        "Read program.md and start experimenting. Baseline: val_bpb=1.104"
fi

# Default: run training script
exec uv run "$@"
