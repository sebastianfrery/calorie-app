#!/usr/bin/env bash
set -e

PORT="${PORT:-8000}"
STREAMLIT_PORT=8501

echo "[start.sh] Starting Streamlit on internal port $STREAMLIT_PORT…"
streamlit run app.py \
    --server.port "$STREAMLIT_PORT" \
    --server.address 127.0.0.1 \
    --server.headless true \
    --server.enableCORS false \
    --server.enableXsrfProtection false &

# Give Streamlit time to bind its port before accepting proxied traffic
sleep 4

echo "[start.sh] Starting gateway (FastAPI) on public port $PORT…"
exec uvicorn entrypoint:app --host 0.0.0.0 --port "$PORT"
