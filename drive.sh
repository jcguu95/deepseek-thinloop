#!/usr/bin/env bash
# drive.sh —— thin loop 入口（讀 profile，project-agnostic）。
#
# 用法：
#   bash drive.sh <profile.json> <brief.md> <workspace 絕對路徑> [loop 額外參數...]
#
# 範例：
#   bash drive.sh profiles/limn.json /tmp/brief.md /Users/jin/.../limn-deepseek
#   bash drive.sh profiles/limn.json /tmp/brief.md <ws> --continue --nudge "修一下 X"
#   bash drive.sh profiles/limn.json /tmp/brief.md <ws> --no-verify --max-iters 80
#
# profile 提供：name / sandbox_image / preflight / verify_command / parser /
#              baseline_file / rules_file。引擎本身不焊任何 project。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROFILE="${1:-}"; BRIEF="${2:-}"; WORKSPACE="${3:-}"
shift 3 2>/dev/null || true
EXTRA=("$@")

[[ -z "$PROFILE" || -z "$BRIEF" || -z "$WORKSPACE" ]] && {
  echo "用法：bash drive.sh <profile.json> <brief.md> <workspace> [額外參數...]" >&2; exit 1; }
[[ -f "$PROFILE" ]]   || { echo "錯誤：profile 不存在：$PROFILE" >&2; exit 1; }
[[ -f "$BRIEF" ]]     || { echo "錯誤：brief 不存在：$BRIEF" >&2; exit 1; }
[[ -d "$WORKSPACE" ]] || { echo "錯誤：workspace 不存在：$WORKSPACE" >&2; exit 1; }
command -v python3 >/dev/null || { echo "錯誤：host 上沒有 python3" >&2; exit 1; }

PROFILE="$(cd "$(dirname "$PROFILE")" && pwd)/$(basename "$PROFILE")"   # 絕對化

# 從 profile 讀 sandbox 相關欄位（preflight 相對 profile dir 解析成絕對）。
read -r NAME IMAGE PREFLIGHT < <(python3 - "$PROFILE" <<'PY'
import json, sys, os
p = sys.argv[1]
d = json.load(open(p))
name = d.get("name", "default")
image = d["sandbox_image"]
pf = d.get("preflight", "")
if pf and not os.path.isabs(pf):
    pf = os.path.normpath(os.path.join(os.path.dirname(p), pf))
print(name, image, pf)
PY
)

export RUNTIME_IMAGE="$IMAGE"
export PREFLIGHT="$PREFLIGHT"
export SANDBOX_NAME="thinloop-${NAME}"

echo ">>> profile  : $PROFILE"
echo ">>> image    : $IMAGE"
echo ">>> sandbox  : $SANDBOX_NAME"
echo ">>> workspace: $WORKSPACE"

# 確保沙箱在跑且 /workspace 指對（含 preflight 守門）。
bash "$SCRIPT_DIR/sandbox.sh" ensure "$WORKSPACE"

# --continue 接「最近一次」run-dir；否則新建。
CONTINUE=0
for a in "${EXTRA[@]}"; do [[ "$a" == "--continue" ]] && CONTINUE=1; done
if [[ $CONTINUE -eq 1 ]]; then
  RUN_DIR="$(ls -dt "$SCRIPT_DIR"/.runs/*/ 2>/dev/null | head -1)"; RUN_DIR="${RUN_DIR%/}"
  [[ -z "$RUN_DIR" ]] && { echo "錯誤：沒有可續的 run（.runs/ 是空的）" >&2; exit 1; }
  echo ">>> 續跑最近的 run：$RUN_DIR"
else
  RUN_DIR="$SCRIPT_DIR/.runs/$(date +%Y%m%d-%H%M%S)"
  mkdir -p "$RUN_DIR"
  echo ">>> run dir  : $RUN_DIR"
fi
echo ""

python3 "$SCRIPT_DIR/loop.py" \
  --profile "$PROFILE" \
  --brief "$BRIEF" \
  --workspace "$WORKSPACE" \
  --run-dir "$RUN_DIR" \
  --container "$SANDBOX_NAME" \
  "${EXTRA[@]}"
