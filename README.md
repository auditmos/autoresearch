# autoresearch — Docker fork for consumer GPUs

Docker-based fork of [karpathy/autoresearch](https://github.com/karpathy/autoresearch) optimized for consumer NVIDIA GPUs (RTX 5070, 12GB VRAM).

The original autoresearch requires an H100 (80GB) and runs bare-metal. This fork packages everything in Docker with configuration tuned for 12GB VRAM GPUs.

## Changes from upstream

| Parameter | Upstream (H100) | This fork (RTX 5070) |
|-----------|-----------------|----------------------|
| `MAX_SEQ_LEN` | 2048 | 1024 |
| `TIME_BUDGET` | 300s (5 min) | 600s (10 min) |
| `EVAL_TOKENS` | 40 × 524K | 10 × 524K |
| `DEPTH` | 8 | 8 |
| `HEAD_DIM` | 128 | 64 |
| `DEVICE_BATCH_SIZE` | 128 | 32 |
| `TOTAL_BATCH_SIZE` | 2^19 | 2^18 |
| `WINDOW_PATTERN` | SSSL | L |
| Attention | Flash Attention 3 | PyTorch SDPA (FA3 fallback) |

**Why 10 min instead of 5?** On RTX 5070, the 50M param model needs ~540 steps to converge. At 5 min it only gets ~275 steps (undertrained). 10 min gives ~540 steps and 141M tokens — matching the tokens/params ratio of the H100 baseline.

**Why SDPA?** Flash Attention 3 compiled kernels don't support Blackwell (sm_120). PyTorch's `scaled_dot_product_attention` uses efficient backends automatically. GQA is supported via `repeat_interleave`.

## Baseline results

| DEPTH | params | TIME | steps | tokens | val_bpb | VRAM |
|-------|--------|------|-------|--------|---------|------|
| 6 | 26M | 5 min | 987 | 129M | 1.146 | 3.7GB |
| 8 | 50M | 5 min | 275 | 72M | 1.184 | 6.2GB |
| 7 | 39M | 5 min | 350 | 92M | 1.170 | 4.9GB |
| **8** | **50M** | **10 min** | **539** | **141M** | **1.104** | **6.2GB** |

## Requirements

- NVIDIA GPU with 12GB+ VRAM (tested: RTX 5070)
- Docker with NVIDIA runtime (`nvidia-container-toolkit`)
- ~5GB disk for data shards + tokenizer

### Docker + NVIDIA runtime setup

```bash
# If using Docker 29+ with containerd v2, downgrade (nvidia-ctk incompatibility):
sudo apt install -y --allow-downgrades \
  docker-ce=5:27.5.1-1~ubuntu.24.04~noble \
  docker-ce-cli=5:27.5.1-1~ubuntu.24.04~noble \
  containerd.io=1.7.29-1~ubuntu.24.04~noble

sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker

# Verify
docker run --rm --gpus all nvidia/cuda:12.6.0-base-ubuntu24.04 nvidia-smi
```

## Quick start

```bash
# Build (first time ~15 min: PyTorch 2.5GB + Rust compiler)
docker compose build

# Run (first time: downloads ~5GB data + trains tokenizer, then 10 min training)
docker compose up

# Output: val_bpb score (lower = better)
```

## Running the autonomous agent

```bash
# Enter container interactively
docker compose run --entrypoint bash autoresearch

# Inside container:
git init && git add -A && git commit -m "baseline"
git checkout -b autoresearch/experiment1

# Init results tracking
printf 'commit\tval_bpb\tmemory_gb\tstatus\tdescription\n' > results.tsv

# Install and run Claude Code (or any AI coding agent)
curl -fsSL https://claude.ai/install.sh | sh
claude --dangerously-skip-permissions "Read program.md and start experimenting"
```

The agent will autonomously modify `train.py`, run 10-min experiments, evaluate results, and keep/discard changes. ~50 experiments overnight.

## Adapting for other GPUs

Adjust these parameters in `train.py` based on available VRAM:

- **24GB (RTX 4090):** `DEVICE_BATCH_SIZE=64`, `DEPTH=10`
- **16GB (RTX 4080):** `DEVICE_BATCH_SIZE=48`, `DEPTH=8`
- **12GB (RTX 5070/4070):** current defaults
- **8GB (RTX 4060):** `DEVICE_BATCH_SIZE=16`, `DEPTH=4`

If OOM: lower `DEVICE_BATCH_SIZE` first, then `DEPTH`.

## License

MIT (same as upstream)
