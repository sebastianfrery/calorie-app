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


@app.websocket("/{path:path}")
async def ws_proxy(websocket: WebSocket, path: str):
    await websocket.accept()
    query = websocket.url.query
    target = f"ws://localhost:{STREAMLIT_PORT}/{path}"
    if query:
        target += f"?{query}"

    try:
        async with websockets.connect(target) as upstream:

            async def to_upstream():
                try:
                    while True:
                        msg = await websocket.receive()
                        if msg.get("bytes") is not None:
                            await upstream.send(msg["bytes"])
                        elif msg.get("text") is not None:
                            await upstream.send(msg["text"])
                        elif msg.get("type") == "websocket.disconnect":
                            break
                except Exception:
                    pass

            async def to_client():
                try:
                    async for msg in upstream:
                        if isinstance(msg, bytes):
                            await websocket.send_bytes(msg)
                        else:
                            await websocket.send_text(msg)
                except Exception:
                    pass

            tasks = [asyncio.create_task(to_upstream()), asyncio.create_task(to_client())]
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for t in pending:
                t.cancel()
    except Exception:
        try:
            await websocket.close(1011)
        except Exception:
            pass


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"])
async def http_proxy(request: Request, path: str):
    url = f"http://localhost:{STREAMLIT_PORT}/{path}"
    query = str(request.url.query)
    if query:
        url += f"?{query}"

    headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in _HOP_BY_HOP
    }
    headers["host"] = f"localhost:{STREAMLIT_PORT}"

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.request(
            method=request.method,
            url=url,
            headers=headers,
            content=await request.body(),
        )

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
