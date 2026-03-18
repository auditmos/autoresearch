---
name: docker-ai-agent
description: >
  Creates production-ready Dockerfiles, entrypoint scripts, and docker-compose files for running
  Claude Code (or similar AI agents) autonomously in containers. Encodes battle-tested patterns for:
  non-root user setup with uv/Python, bind-mount permission fixing, Claude non-interactive (-p) mode
  with while-loop restart, git state persistence via remote clone, git safe.directory config, and
  hooks-based automation (pre/post-commit). Use when building a Docker container to run Claude or
  another AI agent autonomously, or when setting up claude-in-docker infrastructure.
---

# Docker AI Agent

Battle-tested patterns for containerized Claude/AI agent workloads. See `assets/` for ready-to-use templates.

## Critical Patterns

### 1. Non-root user + uv

Always install uv and run `uv sync` as the target user — not root. If uv is installed as root, symlinks point to `/root/.local/` and the user gets permission denied.

```dockerfile
RUN useradd -m -s /bin/bash researcher
RUN su - researcher -c 'curl -LsSf https://astral.sh/uv/install.sh | sh'
WORKDIR /app
RUN chown researcher:researcher /app
USER researcher
ENV PATH="/home/researcher/.local/bin:$PATH"
COPY --chown=researcher:researcher pyproject.toml .python-version ./
RUN uv sync
```

### 2. Entrypoint: root → fix perms → re-exec as user

Bind mounts (`./data:/container/path`) are created by Docker as `root:root`. Fix at entrypoint startup:

```bash
if [ "$(id -u)" = "0" ]; then
    chown -R researcher:researcher /data /app
    exec runuser -u researcher -- "$0" "$@"
fi
# Everything below runs as researcher
```

### 3. git safe.directory

When `/app` is owned by root and you exec as root, git refuses to operate:
```
fatal: detected dubious ownership in repository at '/app'
```
Fix in entrypoint (before any git commands):
```bash
git config --global --add safe.directory /app
```

### 4. Claude non-interactive + restart loop

- Always use `claude -p` (non-interactive). Interactive mode blocks on TTY and theme picker breaks in containers.
- `-p` exits after one prompt → wrap in `while true`:

```bash
while true; do
    claude -p --dangerously-skip-permissions \
        "Your autonomous task prompt here. NEVER STOP."
    echo "=== Claude exited, restarting in 5s ==="
    sleep 5
done
```

### 5. Git state persistence across container restarts

`/app` is not in a volume by default → state lost on container stop. Clone from remote on startup:

```bash
if [ ! -d .git ]; then
    if [ -n "$GIT_REMOTE_URL" ]; then
        git clone "$GIT_REMOTE_URL" /tmp/repo
        cp -a /tmp/repo/.git /app/.git
        git checkout HEAD -- important_file.txt 2>/dev/null || true
        rm -rf /tmp/repo
    else
        git init && git add -A && git commit -m "baseline"
    fi
fi
```

### 6. Automation via git hooks, not agent instructions

Agents reliably ignore file-based instructions for git operations. Use hooks instead:
- **pre-commit**: auto-stage files the agent forgets (`git add results.tsv`)
- **post-commit**: auto-push + notify (`git push origin HEAD && ./notify.sh`)

Copy hooks in entrypoint (not Dockerfile — hooks dir may change):
```bash
cp /app/hooks/pre-commit /app/.git/hooks/pre-commit
cp /app/hooks/post-commit /app/.git/hooks/post-commit
chmod +x /app/.git/hooks/pre-commit /app/.git/hooks/post-commit
```

### 7. Named volume for Claude config

Persist Claude auth across container recreations:
```yaml
volumes:
  - claude-config:/home/researcher/.claude

volumes:
  claude-config:
```

### 8. Claude authentication

Never auth inside tmux — URL wraps and becomes unreadable. Use a separate run:
```bash
docker compose run service login
```
This runs `claude login` in a clean terminal.

### 9. docker exec with correct user

`docker exec` defaults to root → can't see tmux sessions/processes owned by researcher:
```bash
docker exec -u researcher container_name tmux attach
```

## Asset Templates

- `assets/Dockerfile` — complete Dockerfile with all patterns applied
- `assets/entrypoint.sh` — full entrypoint with mode switching (login / agent / default)
- `assets/docker-compose.yml` — compose file with GPU support, volumes, env vars

Adapt these templates to your project. Key substitutions:
- `researcher` → your non-root username
- `/home/researcher/.cache/yourapp` → your cache/data path
- `your-service` → your service name
- Agent prompt → your autonomous task description
