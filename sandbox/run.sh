#!/usr/bin/env bash
# sandbox/run.sh — 一键启动虾蜜沙盒控制台（演示用）。
#
# 自动完成四件最容易出错的事：
#   1) 杀掉所有旧 server 进程（"改了没生效 / 下拉只有一条"的头号根因）
#   2) 复位虚拟时钟到 demo 基线（每次从同一时刻开始体验）
#   3) 后台起 server 并等它就绪
#   4) 自检"跑的是新代码" + 自动开浏览器
#
# 用法：
#   ./sandbox/run.sh            # 默认端口 8765
#   ./sandbox/run.sh 8770       # 指定端口
#   NO_OPEN=1 ./sandbox/run.sh  # 不自动开浏览器（脚本自检/CI 用）
#   停止：pkill -f sandbox/server.py

set -euo pipefail

PORT="${1:-8765}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
URL="http://127.0.0.1:$PORT"
LOG="/tmp/xiami-sandbox-$PORT.log"
cd "$ROOT"

echo "🦞 启动虾蜜沙盒控制台 …"

# 1) 清掉旧 server（无论哪个终端起的）
if pgrep -f "sandbox/server.py" >/dev/null 2>&1; then
  echo "  • 发现旧 server 进程，清理中 …"
  pkill -f "sandbox/server.py" || true
  sleep 1
fi
if lsof -nP -i ":$PORT" >/dev/null 2>&1; then
  echo "  ⚠️ 端口 $PORT 仍被占用，先手动查：lsof -nP -i :$PORT" >&2
  exit 1
fi

# 1.5) 复位「高级调参」覆盖层 —— 每次 demo 从干净状态开始（清掉上次注入的事件 / 改的速度），
#      否则会出现"海底捞莫名多 12 桌"这类穿帮（覆盖层是给评委现场注入用的，不该带进基线）
OVERRIDES="$HOME/.openclaw/sandbox/sandbox_overrides.json"
mkdir -p "$(dirname "$OVERRIDES")"
printf '{}\n' > "$OVERRIDES"
echo "  • 高级调参覆盖层已复位（无注入事件 / 默认速度）"

# 2) 后台起 server
python3 sandbox/server.py --port "$PORT" >"$LOG" 2>&1 &
echo "  • server 启动中（日志 $LOG）…"

# 3) 等就绪（最多 ~6s）
ready=""
for _ in $(seq 1 20); do
  if curl -s "$URL/api/clock" >/dev/null 2>&1; then ready=1; break; fi
  sleep 0.3
done
if [ -z "$ready" ]; then
  echo "  ❌ server 没起来，看日志：cat $LOG" >&2
  exit 1
fi

# 4) 自检"跑的是新代码"（新代码 /api/clock 才有 itineraries 字段）
if ! curl -s "$URL/api/clock" | grep -q '"itineraries"'; then
  echo "  ❌ 起来的是旧代码（/api/clock 无 itineraries）。确认在最新分支后重跑。" >&2
  exit 1
fi

# 5) 复位虚拟时钟到 demo 基线（走 server 自己的接口 → 文件格式一定对）
BASELINE="$(curl -s "$URL/api/clock" | python3 -c 'import sys,json;print(json.load(sys.stdin).get("baseline",""))')"
if [ -n "$BASELINE" ]; then
  curl -s -X POST "$URL/api/clock" -d "{\"mode\":\"fixed\",\"time\":\"$BASELINE\"}" >/dev/null
  echo "  • 虚拟时钟复位到 demo 基线：$BASELINE"
fi

echo "  ✅ 沙盒就绪：$URL"

# 6) 开浏览器
if [ -z "${NO_OPEN:-}" ]; then
  if command -v open >/dev/null 2>&1; then open "$URL"
  elif command -v xdg-open >/dev/null 2>&1; then xdg-open "$URL"
  fi
fi

echo ""
echo "🎬 控制台已就绪。停止：pkill -f sandbox/server.py"
