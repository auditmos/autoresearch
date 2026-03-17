FROM nvidia/cuda:12.8.1-devel-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

# System deps: git (kernels pkg downloads repos), curl (uv install)
RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# uv (manages Python + deps)
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"

# Rust (for rustbpe compilation)
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
ENV PATH="/root/.cargo/bin:$PATH"

WORKDIR /app

# Project files
COPY pyproject.toml .python-version ./

# Install Python deps (uv downloads Python 3.10 + all packages)
# torch cu128 wheel is ~2.5GB, cached in Docker layer
RUN uv sync

# Application code (changes more often → separate layer)
COPY prepare.py train.py program.md ./

COPY entrypoint.sh ./
RUN chmod +x entrypoint.sh

VOLUME /root/.cache/autoresearch

ENTRYPOINT ["./entrypoint.sh"]
CMD ["train.py"]
