#!/bin/bash
# LXP Diagnosis 启动脚本
# 启动 FastAPI 服务 + Cloudflare Tunnel 公网穿透

set -e

APP_DIR="/home/lingjiashu/lxp-diagnosis"
VENV_PYTHON="/home/lingjiashu/.hermes/hermes-agent/venv/bin/python3"
CLOUDFLARED="/tmp/cloudflared"
PORT=8765

# 1. 启动 FastAPI
echo "[LXP Diagnosis] Starting FastAPI on port $PORT..."
cd "$APP_DIR"
nohup "$VENV_PYTHON" -m uvicorn web.main:app --host 0.0.0.0 --port "$PORT" > /tmp/lxp-diagnosis-server.log 2>&1 &
SERVER_PID=$!
echo "[LXP Diagnosis] Server PID: $SERVER_PID"

# 2. 等待服务就绪
sleep 3

# 3. 启动 Cloudflare Tunnel
echo "[LXP Diagnosis] Starting Cloudflare Tunnel..."
nohup "$CLOUDFLARED" tunnel --url "http://localhost:$PORT" > /tmp/cloudflared.log 2>&1 &
TUNNEL_PID=$!
echo "[LXP Diagnosis] Tunnel PID: $TUNNEL_PID"

# 4. 等待 Tunnel URL
sleep 10
TUNNEL_URL=$(grep -oP 'https://[a-z0-9-]+\.trycloudflare\.com' /tmp/cloudflared.log | head -1)
if [ -n "$TUNNEL_URL" ]; then
    echo "[LXP Diagnosis] ✅ Public URL: $TUNNEL_URL"
    echo "$TUNNEL_URL" > /tmp/lxp-diagnosis-url.txt
else
    echo "[LXP Diagnosis] ⚠️  Tunnel URL not found yet, check: tail -f /tmp/cloudflared.log"
fi

echo "[LXP Diagnosis] Started. Local: http://localhost:$PORT"
