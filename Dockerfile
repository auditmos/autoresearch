FROM nvidia/cuda:12.8.1-devel-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl ca-certificates bash tmux \
    && rm -rf /var/lib/apt/lists/*

# uv (manages Python + deps)
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"

WORKDIR /app

# Project files
COPY pyproject.toml .python-version ./

# Install Python deps (uv downloads Python 3.10 + all packages)
# torch cu128 wheel is ~2.5GB, cached in Docker layer
RUN uv sync

# Application code (changes more often → separate layer)
COPY prepare.py strategy.py program.md ./
COPY notify.sh ./
RUN chmod +x notify.sh

# Non-root user (required by claude --dangerously-skip-permissions)
RUN useradd -m -s /bin/bash researcher \
    && cp -r /root/.local /home/researcher/.local \
    && mkdir -p /home/researcher/.cache/autoquant \
    && chown -R researcher:researcher /app /home/researcher

# Claude Code CLI
RUN su - researcher -c 'curl -fsSL https://claude.ai/install.sh | bash' 2>/dev/null || true

ENV PATH="/home/researcher/.local/bin:$PATH"

COPY entrypoint.sh ./
RUN chmod +x entrypoint.sh

VOLUME /home/researcher/.cache/autoquant

ENTRYPOINT ["./entrypoint.sh"]
CMD ["strategy.py"]
