FROM python:3.12-slim

WORKDIR /app

# uv for fast, locked installs
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Install deps first for layer caching
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Then the app
COPY src ./src
RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8080

CMD ["uvicorn", "travel_planner.main:app", "--host", "0.0.0.0", "--port", "8080"]
