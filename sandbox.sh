#!/usr/bin/env bash
# sandbox.sh —— 管理 thin loop 的持久沙箱容器（project-agnostic）。
#
# 由環境變數驅動（drive.sh 從 profile 讀出後 export）：
#   RUNTIME_IMAGE  （必）沙箱用的 docker image。
#   SANDBOX_NAME   （選）容器名，預設 thinloop-sandbox。
#   PREFLIGHT      （選）一個 host script 路徑，沙箱啟動前跑、非 0 就中止
#                  （例如 limn 的依賴鎖守門 check-lock-sync.sh）。
#
# 用法：
#   sandbox.sh up <workspace>      # 起持久沙箱
#   sandbox.sh ensure <workspace>  # 確保沙箱在跑且 /workspace 指向這個 workspace
#   sandbox.sh down                # 停掉移除
#   sandbox.sh exec -- <cmd...>    # 在沙箱 /workspace 內跑
#   sandbox.sh status
set -euo pipefail

NAME="${SANDBOX_NAME:-thinloop-sandbox}"
RUNTIME_IMAGE="${RUNTIME_IMAGE:?需要 RUNTIME_IMAGE（由 profile 提供）}"
PREFLIGHT="${PREFLIGHT:-}"

_preflight() {
  [ -z "$PREFLIGHT" ] && return 0
  RUNTIME_IMAGE="$RUNTIME_IMAGE" bash "$PREFLIGHT" || {
    echo "沙箱啟動中止：preflight（$PREFLIGHT）失敗。" >&2; exit 1; }
}

_up() {
  local WORKSPACE="$1"
  [[ -z "$WORKSPACE" ]] && { echo "用法：sandbox.sh up <workspace>" >&2; exit 1; }
  [[ -d "$WORKSPACE" ]] || { echo "錯誤：workspace 不存在：$WORKSPACE" >&2; exit 1; }
  _preflight
  if docker inspect "$NAME" &>/dev/null; then
    echo "沙箱 '$NAME' 已存在（先 down 再 up 可換 workspace）。"; return 0
  fi
  docker run -d --name "$NAME" \
    -e LANG=C.UTF-8 -e LC_ALL=C.UTF-8 \
    -v "$WORKSPACE:/workspace" \
    --entrypoint bash "$RUNTIME_IMAGE" -lc 'sleep infinity'
  echo "✅ 沙箱 '$NAME' 起好了，workspace=$WORKSPACE → /workspace"
}

cmd="${1:-}"; shift || true
case "$cmd" in
  up)
    _up "${1:-}"
    ;;
  ensure)
    # 確保沙箱在跑、且 /workspace 真的指向「這個」workspace（防 stale mount / 換 workspace）。
    WORKSPACE="${1:-}"
    [[ -z "$WORKSPACE" ]] && { echo "用法：sandbox.sh ensure <workspace>" >&2; exit 1; }
    if docker inspect "$NAME" &>/dev/null; then
      src="$(docker inspect -f '{{range .Mounts}}{{if eq .Destination "/workspace"}}{{.Source}}{{end}}{{end}}' "$NAME" 2>/dev/null)"
      want="$(cd "$WORKSPACE" 2>/dev/null && pwd -P || echo "$WORKSPACE")"
      have="$(cd "$src" 2>/dev/null && pwd -P || echo "$src")"
      # sentinel：clone 都有 .git；mount stale 時讀不到 → 重建。
      if docker exec "$NAME" test -e /workspace/.git 2>/dev/null && [[ "$have" == "$want" ]]; then
        echo "沙箱 '$NAME' 正常，/workspace=$want"; exit 0
      fi
      echo "沙箱 '$NAME' 的 /workspace 失效或換了 workspace → 重建"
      docker rm -f "$NAME" >/dev/null
    fi
    _up "$WORKSPACE"
    ;;
  down)
    docker rm -f "$NAME" &>/dev/null && echo "✅ 沙箱 '$NAME' 已移除" || echo "（沒有 '$NAME' 在跑）"
    ;;
  exec)
    [[ "${1:-}" == "--" ]] && shift
    docker exec -w /workspace "$NAME" bash -lc "$*"
    ;;
  status)
    docker ps --filter "name=$NAME" --format '{{.Names}}\t{{.Image}}\t{{.Status}}' 2>/dev/null || echo "（沒有 '$NAME'）"
    ;;
  *)
    echo "用法：sandbox.sh {up <ws>|ensure <ws>|down|exec -- <cmd>|status}" >&2; exit 1
    ;;
esac
