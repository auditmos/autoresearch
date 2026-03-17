# autoresearch — RTX 5070 12GB

Autonomous ML research agent. You modify `train.py`, run experiments, keep improvements, discard regressions.

## Hardware

- GPU: RTX 5070 12GB VRAM (Blackwell, sm_120)
- Attention: PyTorch SDPA (FA3 doesn't work on Blackwell)
- DEVICE_BATCH_SIZE=32 max (64 OOM'd)
- TOTAL_BATCH_SIZE must be divisible by 32*1024=32768
- Peak VRAM so far: 6.2GB — there's headroom

## Setup

1. Branch: `git checkout -b autoresearch/<tag>`
2. Read: `prepare.py` (fixed), `train.py` (you modify)
3. Verify data: `ls ~/.cache/autoresearch/tokenizer/`
4. Init results: create `results.tsv` with header
5. Confirm and go

## Rules

**CAN:** modify `train.py` — architecture, optimizer, hyperparams, batch size, everything.

**CANNOT:** modify `prepare.py`, add packages, change evaluation.

**Metric:** `val_bpb` (lower = better). Extract: `grep "^val_bpb:" run.log`

**VRAM soft limit:** 12GB. Current usage ~6GB, so room to experiment.

## Known results on this hardware

```
commit	val_bpb	memory_gb	status	description
baseline	1.146000	3.7	keep	DEPTH=6, BATCH=32, 5min budget
scale_d8	1.184000	6.2	discard	DEPTH=8, BATCH=32, 5min — too few steps
scale_d7	1.170000	4.9	discard	DEPTH=7, BATCH=32, 5min — still too few steps
time10m	1.104000	6.2	keep	DEPTH=8, BATCH=32, 10min budget — winner
```

Current best: val_bpb=1.104 with DEPTH=8, 50M params, 10min budget.

## Experiment loop

LOOP FOREVER:

1. Review git state
2. Modify `train.py` with an idea
3. `git commit`
4. Run: `uv run train.py > run.log 2>&1`
5. Check: `grep "^val_bpb:\|^peak_vram_mb:" run.log`
6. Empty output = crash → `tail -n 50 run.log`, attempt fix
7. Log to `results.tsv` (tab-separated): `commit | val_bpb | memory_gb | status | description`
8. If val_bpb improved → keep commit
9. If equal/worse → `git reset --hard HEAD~1`

**Timeout:** each run ~12 min total (10 min train + overhead). Kill if >15 min.

**NEVER STOP.** Do not ask for permission. Run indefinitely until manually interrupted.

## Ideas to explore

- GQA (n_kv_head < n_head) — reduce value_embed overhead
- SwiGLU activation instead of ReLU²
- Different LR schedules (warmup, cosine)
- Muon hyperparams (momentum, ns_steps)
- Weight tying (wte = lm_head)
- Layer scaling strategies
- Batch size vs model depth tradeoff
- Remove or reduce value embeddings
