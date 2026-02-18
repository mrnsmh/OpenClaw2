# AI Firewall — LLM Reverse Proxy

A high-performance streaming reverse proxy that sits between your client (OpenClaw) and LLM providers (OpenRouter / OpenAI / Anthropic). It enforces authentication, daily per-user budget limits, and transparent SSE streaming.

## Architecture

```
Client ──► AI Firewall (FastAPI :8000) ──► Upstream Provider
                    │
                  Redis (budget state)
```

## Quick Start

```bash
# 1. Configure environment
cp .env.example .env
# Edit .env with your upstream API key

# 2. Launch
docker compose up --build -d

# 3. Test
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer changeme-internal-key" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "openai/gpt-4o-mini",
    "stream": true,
    "messages": [{"role": "user", "content": "Hello!"}]
  }'
```

⚠️ **Sécurité GitHub** : Ne commitez jamais le fichier `.env` (il est exclu via `.gitignore`). Utilisez toujours `.env.example` comme modèle.

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/v1/chat/completions` | Proxied chat completions (streaming & non-streaming) |
| GET | `/health` | Health check |

## How It Works

1. **Auth** — Validates `Authorization: Bearer <INTERNAL_API_KEY>` → 401 if invalid.
2. **Budget gate** — Checks Redis `budget:{user}:{date}` → 402 if daily spend ≥ limit.
3. **Input token count** — Counts prompt tokens with `tiktoken` before forwarding.
4. **Proxy** — Forwards request to upstream; streams SSE chunks back to client in real-time.
5. **Async billing** — After stream ends, a background task counts output tokens and updates the budget in Redis.

## Configuration

All settings via environment variables (or `.env` file):

| Variable | Default | Description |
|----------|---------|-------------|
| `INTERNAL_API_KEY` | `changeme-internal-key` | Bearer token clients must use |
| `UPSTREAM_BASE_URL` | `https://openrouter.ai/api` | Provider base URL |
| `UPSTREAM_API_KEY` | *(empty)* | API key for the upstream provider |
| `REDIS_URL` | `redis://redis:6379/0` | Redis connection string |
| `DAILY_BUDGET_LIMIT` | `5.0` | Max daily spend per user (USD) |

## Local Development (without Docker)

```bash
pip install -r requirements.txt
# Start Redis locally, then:
REDIS_URL=redis://localhost:6379/0 uvicorn main:app --reload --port 8000
```
