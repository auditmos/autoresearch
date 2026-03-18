FROM nvidia/cuda:12.8.1-devel-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl ca-certificates bash \
    && rm -rf /var/lib/apt/lists/*

# Non-root user (required by claude --dangerously-skip-permissions)
RUN useradd -m -s /bin/bash researcher

# uv for researcher — pre-create share/uv so named volume inherits researcher ownership
RUN su - researcher -c 'curl -LsSf https://astral.sh/uv/install.sh | sh && mkdir -p /home/researcher/.local/share/uv'

WORKDIR /app
RUN chown researcher:researcher /app

USER researcher
ENV PATH="/home/researcher/.local/bin:$PATH"

# Support files (same for all experiments — experiment files mounted at /experiment)
COPY --chown=researcher:researcher notify.sh ./
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
