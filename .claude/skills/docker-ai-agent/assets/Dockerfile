# Template Dockerfile for Claude AI agent container
# Substitute: researcher, /home/researcher/.cache/yourapp, your app files
FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl ca-certificates bash tmux \
    && rm -rf /var/lib/apt/lists/*

# Non-root user (required by claude --dangerously-skip-permissions)
RUN useradd -m -s /bin/bash researcher

# Install uv AS researcher — if installed as root, symlinks → /root/.local/ → permission denied
RUN su - researcher -c 'curl -LsSf https://astral.sh/uv/install.sh | sh'

WORKDIR /app
RUN chown researcher:researcher /app

USER researcher
ENV PATH="/home/researcher/.local/bin:$PATH"

# Install deps as researcher (symlinks point to researcher's Python)
COPY --chown=researcher:researcher pyproject.toml .python-version ./
RUN uv sync

# Application code (changes more often → separate layer)
COPY --chown=researcher:researcher . ./
RUN chmod +x notify.sh 2>/dev/null || true

# Claude Code CLI
RUN curl -fsSL https://claude.ai/install.sh | bash 2>/dev/null || true

# Entrypoint needs to start as root to fix bind-mount permissions
USER root
COPY entrypoint.sh ./
RUN chmod +x entrypoint.sh && chown researcher:researcher entrypoint.sh

# Pre-create cache dir with correct ownership
RUN mkdir -p /home/researcher/.cache/yourapp \
    && chown -R researcher:researcher /home/researcher/.cache/yourapp

VOLUME /home/researcher/.cache/yourapp

ENTRYPOINT ["./entrypoint.sh"]
CMD ["main.py"]
