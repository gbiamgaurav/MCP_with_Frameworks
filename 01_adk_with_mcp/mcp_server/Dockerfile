

FROM python:3.12-slim

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Install dependencies first (layer-cache friendly)
COPY requirements.txt .
RUN uv pip install --system --no-cache -r requirements.txt

# Copy server source
COPY server.py .

# Cloud Run injects $PORT; default 8080
ENV PORT=8080
ENV MCP_TRANSPORT=http

EXPOSE 8080

CMD ["python", "server.py", "--http"]
