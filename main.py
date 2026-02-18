import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import List

import httpx
from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

import budget_manager as bm
from config import settings

# ── Logging ──────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("ai-firewall")

# ── Lifespan ─────────────────────────────────────────────────────────────────

_http_client: httpx.AsyncClient | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _http_client
    _http_client = httpx.AsyncClient(timeout=httpx.Timeout(connect=10, read=300, write=30, pool=10))
    logger.info("AI Firewall started — upstream: %s", settings.UPSTREAM_BASE_URL)
    yield
    await _http_client.aclose()
    await bm.close()
    logger.info("AI Firewall shut down.")


app = FastAPI(title="AI Firewall", version="1.0.0", lifespan=lifespan)
security = HTTPBearer()

# ── Dependencies ─────────────────────────────────────────────────────────────


async def verify_api_key(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> str:
    """Validate the internal Bearer token. Returns a user identifier."""
    token = credentials.credentials
    if token != settings.INTERNAL_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")
    # In a multi-user setup, resolve token → user_id here.
    return "default"


async def enforce_budget(user: str = Depends(verify_api_key)) -> str:
    """Check daily budget; raise 402 if exceeded."""
    if not await bm.check_budget(user):
        spent = await bm.get_spent(user)
        raise HTTPException(
            status_code=402,
            detail=(
                f"Daily budget exceeded. "
                f"Spent: ${spent:.4f} / Limit: ${settings.DAILY_BUDGET_LIMIT:.2f}"
            ),
        )
    return user


# ── Helpers ──────────────────────────────────────────────────────────────────


def _build_upstream_headers() -> dict:
    """Headers forwarded to the upstream provider."""
    return {
        "Authorization": f"Bearer {settings.UPSTREAM_API_KEY}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }


async def _count_and_bill(
    user: str,
    model: str,
    input_tokens: int,
    sse_chunks: List[str],
) -> None:
    """Background task: extract output text, count tokens, update budget."""
    try:
        output_text = bm.extract_text_from_sse_chunks(sse_chunks)
        output_tokens = bm.count_tokens_text(output_text)
        cost = bm.compute_cost(model, input_tokens, output_tokens)
        await bm.increment_spend(user, cost)
        logger.info(
            "Billing — user=%s model=%s in=%d out=%d cost=$%.6f",
            user, model, input_tokens, output_tokens, cost,
        )
    except Exception:
        logger.exception("Error in background billing task")


# ── Streaming proxy endpoint ─────────────────────────────────────────────────


@app.post("/v1/chat/completions")
async def chat_completions(request: Request, user: str = Depends(enforce_budget)):
    body = await request.body()
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    model: str = payload.get("model", "unknown")
    messages: list = payload.get("messages", [])
    is_stream: bool = payload.get("stream", False)

    # Count input tokens upfront
    input_tokens = bm.count_tokens_for_messages(messages)

    upstream_url = f"{settings.UPSTREAM_BASE_URL}/v1/chat/completions"
    headers = _build_upstream_headers()

    if is_stream:
        return await _handle_streaming(
            upstream_url, headers, body, user, model, input_tokens
        )
    else:
        return await _handle_non_streaming(
            upstream_url, headers, body, user, model, input_tokens
        )


async def _handle_streaming(
    url: str,
    headers: dict,
    body: bytes,
    user: str,
    model: str,
    input_tokens: int,
) -> StreamingResponse:
    """Stream SSE from upstream to client, accumulate chunks for billing."""

    collected_chunks: List[str] = []

    async def event_generator():
        try:
            req = _http_client.build_request("POST", url, headers=headers, content=body)
            resp = await _http_client.send(req, stream=True)

            if resp.status_code != 200:
                error_body = await resp.aread()
                await resp.aclose()
                # Yield a single error event so the client sees the upstream error
                yield f"data: {json.dumps({'error': {'message': error_body.decode(), 'status': resp.status_code}})}\n\n"
                yield "data: [DONE]\n\n"
                return

            async for chunk in resp.aiter_text():
                collected_chunks.append(chunk)
                yield chunk

            await resp.aclose()
        except httpx.HTTPError as exc:
            logger.error("Upstream connection error: %s", exc)
            yield f"data: {json.dumps({'error': {'message': str(exc), 'type': 'proxy_error'}})}\n\n"
            yield "data: [DONE]\n\n"
        finally:
            # Fire-and-forget billing task
            asyncio.create_task(
                _count_and_bill(user, model, input_tokens, collected_chunks)
            )

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


async def _handle_non_streaming(
    url: str,
    headers: dict,
    body: bytes,
    user: str,
    model: str,
    input_tokens: int,
) -> JSONResponse:
    """Proxy a non-streaming request, bill from the usage field."""
    try:
        resp = await _http_client.request("POST", url, headers=headers, content=body)
    except httpx.HTTPError as exc:
        logger.error("Upstream error: %s", exc)
        raise HTTPException(status_code=502, detail=f"Upstream error: {exc}")

    if resp.status_code != 200:
        return JSONResponse(content=resp.json(), status_code=resp.status_code)

    data = resp.json()

    # Use provider-reported usage if available, else estimate
    usage = data.get("usage", {})
    out_tokens = usage.get("completion_tokens", 0)
    in_tokens = usage.get("prompt_tokens", input_tokens)

    cost = bm.compute_cost(model, in_tokens, out_tokens)
    await bm.increment_spend(user, cost)
    logger.info(
        "Billing (sync) — user=%s model=%s in=%d out=%d cost=$%.6f",
        user, model, in_tokens, out_tokens, cost,
    )

    return JSONResponse(content=data, status_code=200)


# ── Health check ─────────────────────────────────────────────────────────────


@app.get("/health")
async def health():
    return {"status": "ok"}
