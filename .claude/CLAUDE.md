# Autoresearch — Docker fork for RTX 5070

## What this is

Docker fork of [karpathy/autoresearch](https://github.com/karpathy/autoresearch). You are an autonomous ML researcher. You modify `train.py`, run 10-min training experiments, evaluate `val_bpb` (lower=better), keep improvements, discard regressions. Loop forever.

## Hardware

- GPU: RTX 5070 12GB VRAM, Blackwell sm_120
- Attention: PyTorch SDPA only (FA3 doesn't work on Blackwell)
- Max DEVICE_BATCH_SIZE: 32 (64 OOM'd)
- Peak VRAM so far: 6.2GB — headroom available
- TOTAL_BATCH_SIZE must be divisible by `DEVICE_BATCH_SIZE * 1024`

## Rules

- **ONLY modify `train.py`** — prepare.py is read-only
- **NEVER add packages** — only what's in pyproject.toml
- **Metric: `val_bpb`** — extract via `grep "^val_bpb:" run.log`
- **Run command:** `uv run train.py > run.log 2>&1`
- **Timeout:** kill if >15 min
- **Crash:** `tail -n 50 run.log`, attempt fix, move on after 2-3 tries
- **Keep:** val_bpb improved → keep commit, advance branch
- **Discard:** val_bpb equal/worse → `git reset --hard HEAD~1`
- **Log:** append to `results.tsv` (tab-separated): `commit | val_bpb | memory_gb | status | description`
- **NEVER STOP** — run indefinitely until manually interrupted

## Baseline

```
val_bpb:      1.104
params:       50.3M
VRAM:         6.2GB
steps:        539
tokens:       141M
time_budget:  600s (10 min)
config:       DEPTH=8, HEAD_DIM=64, BATCH=32, TOTAL_BATCH=2^18, WINDOW="L"
```

## What has been tried (don't repeat)

- GQA (n_kv_head=4): val_bpb 1.107, discard — reduced capacity hurt more than throughput gained
- DEPTH=6 + 5min: val_bpb 1.146 — too small model
- DEPTH=7 + 5min: val_bpb 1.170 — still too few steps
- DEPTH=8 + 5min: val_bpb 1.184 — not enough training time

## Ideas worth exploring

- SwiGLU activation (replace ReLU²)
- Warmup (WARMUP_RATIO 0.0 → 0.05-0.1)
- Weight tying (wte = lm_head)
- Different LR schedules / values
- Muon hyperparams (momentum, ns_steps, weight_decay)
- Remove or reduce value embeddings (they're 33% of params)
- Layer scaling strategies (resid_lambdas, x0_lambdas init)
- Smaller HEAD_DIM (32 instead of 64)
- torch.compile options
- Gradient clipping
