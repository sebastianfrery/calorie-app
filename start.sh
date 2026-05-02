#!/usr/bin/env bash
set -e

PORT="${PORT:-8501}"
MODE="${RUN_MODE:-streamlit}"

if [ "$MODE" = "webhook" ]; then
    echo "[start.sh] Starting webhook handler on port $PORT…"
    exec uvicorn webhook_handler:app --host 0.0.0.0 --port "$PORT"
else
    echo "[start.sh] Starting Streamlit on port $PORT…"
    exec streamlit run app.py \
        --server.port "$PORT" \
        --server.address 0.0.0.0 \
        --server.headless true \
        --server.enableCORS false \
        --server.enableXsrfProtection false
fi
