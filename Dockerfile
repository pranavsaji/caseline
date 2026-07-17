# Caseline backend image: FastAPI API + cms_sync event worker (one service,
# both processes — see deploy/railway/start.sh). The voice agent worker is
# NOT in scope here; it runs wherever latency to the SFU is best.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

# Dependency layer (cached until the lock changes)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY . .

ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1

# Voice models (Silero VAD + turn detector) baked in so the agent service
# never downloads at boot; harmless dead weight for the API service.
RUN python -m agent.agent download-files
EXPOSE 8000
CMD ["bash", "deploy/railway/start.sh"]
