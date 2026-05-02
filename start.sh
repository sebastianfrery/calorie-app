#!/usr/bin/env bash
set -e

PORT="${PORT:-8000}"
STREAMLIT_PORT=8501

echo "[start.sh] Iniciando Streamlit en puerto interno $STREAMLIT_PORT…"
streamlit run app.py \
    --server.headless=true \
    --server.port=$STREAMLIT_PORT \
    --server.address=127.0.0.1 \
    --server.enableCORS=false \
    --server.enableXsrfProtection=false \
    --server.enableWebsocketCompression=false \
    --browser.gatherUsageStats=false &

# Esperar a que Streamlit esté listo antes de abrir el gateway
sleep 6

echo "[start.sh] Iniciando gateway (FastAPI) en puerto público $PORT…"
exec uvicorn entrypoint:app --host 0.0.0.0 --port "$PORT"
