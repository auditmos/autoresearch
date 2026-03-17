FROM nvidia/cuda:12.8.1-devel-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl ca-certificates bash \
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

# Non-root user (required by claude --dangerously-skip-permissions)
RUN useradd -m -s /bin/bash researcher \
    && cp -r /root/.local /home/researcher/.local \
    && cp -r /root/.cargo /home/researcher/.cargo \
    && mkdir -p /home/researcher/.cache/autoresearch \
    && chown -R researcher:researcher /app /home/researcher

# Claude Code CLI
RUN su - researcher -c 'curl -fsSL https://claude.ai/install.sh | bash' 2>/dev/null || true

ENV PATH="/home/researcher/.local/bin:/home/researcher/.cargo/bin:$PATH"

COPY entrypoint.sh ./
RUN chmod +x entrypoint.sh

VOLUME /home/researcher/.cache/autoresearch

ENTRYPOINT ["./entrypoint.sh"]
CMD ["train.py"]
