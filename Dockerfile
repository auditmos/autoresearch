FROM nvidia/cuda:12.8.1-devel-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl ca-certificates bash tmux \
    && rm -rf /var/lib/apt/lists/*

# Non-root user (required by claude --dangerously-skip-permissions)
RUN useradd -m -s /bin/bash researcher

# uv for researcher
RUN su - researcher -c 'curl -LsSf https://astral.sh/uv/install.sh | sh'

WORKDIR /app
RUN chown researcher:researcher /app

USER researcher
ENV PATH="/home/researcher/.local/bin:$PATH"

# Project files + install deps as researcher (symlinks point to researcher's Python)
COPY --chown=researcher:researcher pyproject.toml .python-version ./
RUN uv sync

# Application code (changes more often → separate layer)
COPY --chown=researcher:researcher prepare.py strategy.py program.md notify.sh ./
COPY --chown=researcher:researcher hooks/ ./hooks/
RUN chmod +x notify.sh

# Claude Code CLI
RUN curl -fsSL https://claude.ai/install.sh | bash 2>/dev/null || true

# Entrypoint (needs root for chmod)
USER root
COPY entrypoint.sh ./
RUN chmod +x entrypoint.sh && chown researcher:researcher entrypoint.sh
RUN mkdir -p /home/researcher/.cache/autoquant \
    && chown -R researcher:researcher /home/researcher/.cache/autoquant

VOLUME /home/researcher/.cache/autoquant

ENTRYPOINT ["./entrypoint.sh"]
CMD ["strategy.py"]
