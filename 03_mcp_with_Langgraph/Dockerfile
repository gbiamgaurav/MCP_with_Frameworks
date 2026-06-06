FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

COPY requirements.txt .
RUN uv pip install --system --no-cache -r requirements.txt

COPY server.py .
COPY graphs/ graphs/

ENV PORT=8080
ENV MCP_TRANSPORT=http

EXPOSE 8080

CMD ["python", "server.py", "--http"]
