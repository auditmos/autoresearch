#!/bin/bash
set -e

# Auto-prepare data + tokenizer on first run
if [ ! -d "/root/.cache/autoresearch/tokenizer" ]; then
    echo "=== First run: downloading data shards + training tokenizer ==="
    uv run prepare.py --num-shards 8
    echo "=== Data ready ==="
fi

exec uv run "$@"
