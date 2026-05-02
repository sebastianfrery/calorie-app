import asyncio
import os

import httpx
import stripe
import uvicorn
import websockets
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, WebSocket
from fastapi.responses import Response

from database import set_user_vip

load_dotenv()

PORT = int(os.environ.get("PORT", 8000))
STREAMLIT_PORT = 8501

stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")

_HOP_BY_HOP = frozenset({
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade",
})

app = FastAPI(title="CalorieApp Gateway")


# ── 1. Stripe webhook — definida PRIMERO para evitar capturas por el catch-all ──

@app.post("/stripe-webhook")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")

    try:
        event = stripe.Webhook.construct_event(payload, sig, STRIPE_WEBHOOK_SECRET)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    if event["type"] == "checkout.session.completed":
        session_obj = event["data"]["object"]
        email = session_obj.get("metadata", {}).get("email")
        if email:
            set_user_vip(email)

    return {"received": True}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/_stcore/health")
async def stcore_health():
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(f"http://localhost:{STREAMLIT_PORT}/_stcore/health")
        return Response(content=response.content, status_code=response.status_code, headers=dict(response.headers))
    except Exception as exc:
        print(f"[STCORE ✗] health: {exc}", flush=True)
        return Response(content=b"", status_code=502)


@app.post("/_stcore/stream")
async def stcore_stream(request: Request):
    try:
        async with httpx.AsyncClient(timeout=None) as client:
            response = await client.post(
                f"http://localhost:{STREAMLIT_PORT}/_stcore/stream",
                content=await request.body(),
                headers={k: v for k, v in request.headers.items() if k.lower() not in _HOP_BY_HOP}
            )
        return Response(content=response.content, status_code=response.status_code, headers=dict(response.headers))
    except Exception as exc:
        print(f"[STCORE ✗] stream: {exc}", flush=True)
        return Response(content=b"", status_code=502)


# ── 2. Proxy WebSocket — scope type "websocket" nunca colisiona con HTTP ────────
#    Reenvía TODOS los headers del cliente al servidor upstream.

@app.websocket("/{path:path}")
async def ws_proxy(websocket: WebSocket, path: str):
    query = websocket.url.query
    target = f"ws://localhost:{STREAMLIT_PORT}/{path}"
    if query:
        target += f"?{query}"

    print(f"[WS  ←] /{path}{'?' + query if query else ''}", flush=True)

    try:
        ws_headers = {k: v for k, v in websocket.headers.items() if k.lower() not in _HOP_BY_HOP}
        subprotocols = websocket.headers.get("sec-websocket-protocol", "").split(", ") if "sec-websocket-protocol" in websocket.headers else []
        async with websockets.connect(
            target,
            extra_headers=ws_headers,
            subprotocols=subprotocols,
            open_timeout=10,
            ping_timeout=None,
            close_timeout=None,
        ) as upstream:
            await websocket.accept()
            print(f"[WS  ↔] upstream conectado: {target}", flush=True)

            async def client_to_upstream():
                try:
                    while True:
                        msg = await websocket.receive()
                        if msg["type"] == "websocket.disconnect":
                            print(f"[WS  ✗] cliente desconectado de /{path}", flush=True)
                            break
                        elif msg.get("bytes") is not None:
                            await upstream.send(msg["bytes"])
                        elif msg.get("text") is not None:
                            await upstream.send(msg["text"])
                except Exception as exc:
                    print(f"[WS  !] client→upstream error en /{path}: {type(exc).__name__}: {exc}", flush=True)

            async def upstream_to_client():
                try:
                    async for msg in upstream:
                        if isinstance(msg, bytes):
                            await websocket.send_bytes(msg)
                        else:
                            await websocket.send_text(msg)
                except Exception as exc:
                    print(f"[WS  !] upstream→client error en /{path}: {type(exc).__name__}: {exc}", flush=True)

            tasks = [
                asyncio.create_task(client_to_upstream()),
                asyncio.create_task(upstream_to_client()),
            ]
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

            print(f"[WS  ✓] sesión terminada para /{path}", flush=True)

    except Exception as exc:
        print(f"[WS  ✗] error al conectar upstream /{path}: {type(exc).__name__}: {exc}", flush=True)
        try:
            await websocket.close(1011)
        except Exception:
            pass


# ── 3. Proxy HTTP catch-all — scope type "http", nunca captura WebSockets ───────

@app.api_route(
    "/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"],
)
async def http_proxy(request: Request, path: str):
    url = f"http://localhost:{STREAMLIT_PORT}/{path}"
    query = str(request.url.query)
    if query:
        url += f"?{query}"

    print(f"[HTTP ←] {request.method} /{path}{'?' + query if query else ''}", flush=True)

    headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in _HOP_BY_HOP
    }
    headers["host"] = f"localhost:{STREAMLIT_PORT}"
    headers["x-forwarded-for"] = request.client.host
    headers["x-forwarded-proto"] = request.url.scheme

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.request(
                method=request.method,
                url=url,
                headers=headers,
                content=await request.body(),
            )
        print(f"[HTTP →] {response.status_code} /{path}", flush=True)
    except Exception as exc:
        print(f"[HTTP ✗] {request.method} /{path}: {type(exc).__name__}: {exc}", flush=True)
        return Response(content=b"Gateway error", status_code=502)

    resp_headers = {
        k: v for k, v in response.headers.items()
        if k.lower() not in _HOP_BY_HOP
    }
    return Response(
        content=response.content,
        status_code=response.status_code,
        headers=resp_headers,
    )


if __name__ == "__main__":
    uvicorn.run("entrypoint:app", host="0.0.0.0", port=PORT)
