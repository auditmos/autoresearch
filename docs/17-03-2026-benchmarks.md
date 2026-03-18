# 17-03-2026 — RTX 5070 benchmarki + odkrycia techniczne

## Benchmarki — szukanie optymalnego configa

| Run | DEPTH | params | TIME | steps | tokens | val_bpb | VRAM | Status |
|-----|-------|--------|------|-------|--------|---------|------|--------|
| 1 | 6 | 26M | 5 min | 987 | 129M | 1.146 | 3.7GB | discard |
| 2 | 8 | 50M | 5 min | 275 | 72M | 1.184 | 6.2GB | discard |
| 3 | 7 | 39M | 5 min | 350 | 92M | 1.170 | 4.9GB | discard |
| **4** | **8** | **50M** | **10 min** | **539** | **141M** | **1.104** | **6.2GB** | **keep** |

**Wniosek:** DEPTH=8 + 10 min = optymalny. W 5 min budżecie throughput > model size.

## Test API (one-shot) vs Agent (autonomous)

| # | Kto | Zmiana | val_bpb | vs baseline | Status |
|---|-----|--------|---------|-------------|--------|
| 1 | Claude (API one-shot) | GQA n_kv_head=4 | 1.107 | +0.003 (gorzej) | discard |
| 2+ | Agent (autonomous) | nie uruchomiony | — | — | pending |

## Odkrycia techniczne

### Flash Attention 3 vs Blackwell (sm_120)
- FA3 Python module ładuje się OK (`kernels-community/flash-attn3`)
- CUDA kernel crashuje na sm_120: `no kernel image is available for execution on the device`
- **Import success ≠ runtime success** — fallback musi sprawdzać compute capability PRZED użyciem
- Fix: `if cap == (9, 0)` — FA3 tylko na Hopper, reszta → PyTorch SDPA

### SDPA + GQA (Grouped Query Attention)
- PyTorch `F.scaled_dot_product_attention` nie obsługuje różnych n_head vs n_kv_head
- Q: (B, 8, T, D), K/V: (B, 4, T, D) → broadcast error
- Fix: `kt = kt.repeat_interleave(n_rep, dim=1)` przed SDPA

### Fixed time budget tradeoff
- Na mniejszym GPU: throughput > model size
- DEPTH=8 przy 5 min: 275 steps (undertrained) → val_bpb 1.184
- DEPTH=8 przy 10 min: 539 steps (converged) → val_bpb 1.104
- DEPTH=6 przy 5 min: 987 steps → val_bpb 1.146 (mały model, dużo stepów)

### Docker nvidia-ctk
- Docker 29 + containerd v2 wymaga downgrade do Docker 27 / containerd 1.7
- Rootless Docker pułapka: `docker` CLI łączy się z rootless zamiast systemowego
- `--dangerously-skip-permissions` blokuje root → wymaga non-root usera

## TODO autoresearch
- [ ] Uruchomić agenta autonomicznego (auth w kontenerze)
- [ ] tmux na serwerze do utrzymania sesji
- [ ] host-mount results aby nie stracić przy `docker compose down`
- [ ] .gitignore: dodać `data/`
- [ ] .env.example z listą zmiennych
