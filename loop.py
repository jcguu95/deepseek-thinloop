#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
loop.py —— 通用 thin agent loop（Claude 當介面、DeepSeek 做髒活）。

引擎是 project-agnostic：所有 project 專屬的東西（怎麼驗證、怎麼解析測試、
規範檔、baseline）都來自一個 --profile JSON。引擎本身不焊任何 project。

設計：
  - 操作者寫一份 brief（任務 + 驗收標準），呼叫本檔。
  - DeepSeek 用 function-calling 自由探索 /workspace（被開發 repo 的 git clone）、
    讀檔、grep、改檔、跑 build/測試，直到 finish。探索全自主、死鎖在 repo 內。
  - 檔案操作直接在 host workspace 上做（workspace 是沙箱 bind-mount）→ 快、安全。
  - run_command + 驗證走 docker exec 進沙箱（拿該 project 的工具鏈）。
  - transcript 落 jsonl；最後跑 profile.verify_command、用 profile.parser 解析、
    扣 baseline 算「新紅燈」、寫 status.json。操作者只讀 status.json。

只用標準函式庫；host 上任何 python3 可跑。
"""
import argparse, json, os, re, subprocess, sys, urllib.request, urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import parsers  # noqa: E402

MAX_TOOL_OUTPUT = 6000
DEFAULT_CMD_TIMEOUT = 1800   # 冷沙箱第一次跑 unit（FASL 未編譯）可能很慢，給足餘裕

# ─────────────────────────── DeepSeek key ────────────────────────────
def read_deepseek_key():
    p = Path.home() / ".authinfo"
    if not p.exists():
        sys.exit("錯誤：找不到 ~/.authinfo")
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        if "deepseek.api" in line.lower():
            toks = line.split()
            for i, t in enumerate(toks):
                if t == "password" and i + 1 < len(toks):
                    return toks[i + 1]
    sys.exit("錯誤：~/.authinfo 找不到 deepseek.api 的 password 欄位")

# ─────────────────────────── 工具實作 ────────────────────────────────
class Tools:
    def __init__(self, workspace_host: Path, container: str, cmd_timeout: int):
        self.ws = workspace_host.resolve()
        self.container = container
        self.cmd_timeout = cmd_timeout

    def _safe(self, rel: str) -> Path:
        """把路徑釘在 workspace 內，擋住 ../ 逃逸。接受 /workspace/... 或前導 /。"""
        rel = (rel or ".").strip()
        if rel == "/workspace":
            rel = "."
        elif rel.startswith("/workspace/"):
            rel = rel[len("/workspace/"):]
        rel = rel.lstrip("/")
        target = (self.ws / rel).resolve()
        if self.ws != target and self.ws not in target.parents:
            raise ValueError(f"路徑逃出 workspace：{rel}")
        return target

    def list_dir(self, path="."):
        d = self._safe(path)
        if not d.exists():
            return f"(不存在：{path})"
        if d.is_file():
            return f"{path} 是檔案，不是目錄"
        out = [e.name + ("/" if e.is_dir() else "") for e in sorted(d.iterdir())]
        return "\n".join(out) or "(空目錄)"

    def read_file(self, path, start=None, end=None):
        f = self._safe(path)
        if not f.exists() or not f.is_file():
            return f"(不存在或非檔案：{path})"
        lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
        s = max(0, (start or 1) - 1)
        e = min(len(lines), end or len(lines))
        chunk = "\n".join(f"{i+1}\t{lines[i]}" for i in range(s, e))
        return chunk[:MAX_TOOL_OUTPUT] or "(空檔案)"

    def grep(self, pattern, path="."):
        d = self._safe(path)
        try:
            r = subprocess.run(["grep", "-rIn", "--", pattern, str(d)],
                               capture_output=True, text=True, timeout=120)
        except subprocess.TimeoutExpired:
            return "(grep 逾時)"
        out = r.stdout.replace(str(self.ws) + "/", "")
        return out[:MAX_TOOL_OUTPUT] or "(無匹配)"

    def write_file(self, path, content):
        f = self._safe(path)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(content, encoding="utf-8")
        return f"已寫入 {path}（{len(content)} bytes）"

    def str_replace(self, path, old, new):
        f = self._safe(path)
        if not f.exists():
            return f"(不存在：{path})"
        txt = f.read_text(encoding="utf-8", errors="replace")
        n = txt.count(old)
        if n == 0:
            return "錯誤：old 字串在檔案中找不到（要逐字相符，含縮排）"
        if n > 1:
            return f"錯誤：old 字串出現 {n} 次、不唯一，請給更長的上下文"
        f.write_text(txt.replace(old, new), encoding="utf-8")
        return f"已替換 {path}（1 處）"

    def run_command(self, command):
        """在沙箱 /workspace 內跑指令。"""
        try:
            r = subprocess.run(
                ["docker", "exec", "-w", "/workspace", self.container,
                 "bash", "-lc", command],
                capture_output=True, text=True, timeout=self.cmd_timeout)
        except subprocess.TimeoutExpired:
            return f"(指令逾時 {self.cmd_timeout}s)"
        out = (r.stdout or "") + (("\n[stderr]\n" + r.stderr) if r.stderr else "")
        head = f"[exit={r.returncode}]\n"
        if len(out) > MAX_TOOL_OUTPUT:
            out = out[:MAX_TOOL_OUTPUT // 2] + "\n...(截斷)...\n" + out[-MAX_TOOL_OUTPUT // 2:]
        return head + out

TOOL_SCHEMA = [
    {"type": "function", "function": {
        "name": "list_dir", "description": "列出 workspace 內某目錄的內容",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "相對 workspace 的路徑，預設 ."}}}}},
    {"type": "function", "function": {
        "name": "read_file", "description": "讀檔（附行號），可指定行範圍",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"},
            "start": {"type": "integer", "description": "起始行（1-based，選填）"},
            "end": {"type": "integer", "description": "結束行（選填）"}},
            "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "grep", "description": "在 workspace 內遞迴搜尋字串/正則",
        "parameters": {"type": "object", "properties": {
            "pattern": {"type": "string"},
            "path": {"type": "string", "description": "搜尋根，預設 ."}},
            "required": ["pattern"]}}},
    {"type": "function", "function": {
        "name": "str_replace", "description": "把檔案中唯一出現的 old 字串換成 new（逐字相符，含縮排）",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}, "old": {"type": "string"}, "new": {"type": "string"}},
            "required": ["path", "old", "new"]}}},
    {"type": "function", "function": {
        "name": "write_file", "description": "建立或覆寫整個檔案",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["path", "content"]}}},
    {"type": "function", "function": {
        "name": "run_command", "description": "在沙箱 /workspace 內跑 shell 指令（build / 測試）",
        "parameters": {"type": "object", "properties": {
            "command": {"type": "string"}}, "required": ["command"]}}},
    {"type": "function", "function": {
        "name": "finish", "description": "完成任務（build + 測試通過、無新紅燈）時呼叫，附一句話總結",
        "parameters": {"type": "object", "properties": {
            "summary": {"type": "string"}}, "required": ["summary"]}}},
]

def build_system_prompt(profile, baseline_count):
    """從 profile 組 system prompt（project-agnostic template）。"""
    desc = profile.get("project_desc", "這個 repo")
    rules = profile.get("rules_file", "README")
    hint = profile.get("verify_hint", profile.get("verify_command", "（見 brief）"))
    return f"""\
你是在 /workspace（{desc} 的 git clone）裡工作的編碼 agent。

【必讀】先讀 /workspace/{rules} 與任務相關的設計文件，遵守其中所有規則。

【你的工具】list_dir / read_file / grep 探索；str_replace / write_file 改檔；
run_command 跑 build 與測試。自由探索這個 repo，需要看什麼就去看。

【驗證】改完用 run_command 跑：
  {hint}
這個 repo 有 {baseline_count} 個既有 / 環境限定的 baseline 失敗，不是你的鍋。
你的目標是：**完成 brief 的要求，且不引入 baseline 以外的任何新紅燈**。

【完成】確信 brief 達成、測試沒有新紅燈，呼叫 finish 並附一句話總結。
不要做到一半就停下來空轉 —— 要嘛繼續用工具推進，要嘛 finish。"""

# ─────────────────────────── DeepSeek API ────────────────────────────
def call_deepseek(base_url, key, model, messages):
    body = json.dumps({
        "model": model, "messages": messages, "tools": TOOL_SCHEMA,
        "tool_choice": "auto", "temperature": 0.2,
    }).encode("utf-8")
    req = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions", data=body,
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + key})
    with urllib.request.urlopen(req, timeout=300) as resp:
        return json.loads(resp.read().decode("utf-8"))["choices"][0]["message"]

# ─────────────────────────── 驗證 + status ───────────────────────────
def run_verify(tools: Tools, verify_command: str, parser_name: str):
    out = tools.run_command(verify_command)
    passed, failed, names = parsers.get_parser(parser_name)(out)
    return {"passed": passed, "failed": failed, "failure_names": names,
            "raw_tail": out[-2500:]}

def git_diff_stat(ws: Path):
    try:
        stat = subprocess.run(["git", "-C", str(ws), "diff", "--stat"],
                              capture_output=True, text=True, timeout=60).stdout
        porc = subprocess.run(["git", "-C", str(ws), "status", "--porcelain"],
                              capture_output=True, text=True, timeout=60).stdout
        names = [ln[3:].strip() for ln in porc.splitlines() if ln.strip()]
        return stat[-3000:], names
    except Exception as e:
        return f"(git status 失敗：{e})", []

def load_baseline(profile, profile_dir):
    """從 profile.baseline_file 讀已知失敗清單（相對 profile 檔或絕對路徑）。"""
    bf = profile.get("baseline_file")
    if not bf:
        return set()
    p = Path(bf)
    if not p.is_absolute():
        p = (profile_dir / bf).resolve()
    if not p.exists():
        return set()
    out = set()
    for ln in p.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if ln and not ln.startswith("#"):
            out.add(ln)
    return out

# ─────────────────────────────── main ────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", required=True, help="project profile JSON（決定 verify/parser/baseline/rules）")
    ap.add_argument("--brief", required=True, help="任務 brief 檔（markdown）")
    ap.add_argument("--workspace", required=True, help="host 上的 clone 路徑（= 沙箱 /workspace）")
    ap.add_argument("--container", default=os.environ.get("SANDBOX_NAME", "thinloop-sandbox"))
    ap.add_argument("--run-dir", required=True, help="放 transcript / status / messages 的目錄")
    ap.add_argument("--model", default="deepseek-v4-pro")
    ap.add_argument("--base-url", default="https://api.deepseek.com/v1")
    ap.add_argument("--max-iters", type=int, default=60)
    ap.add_argument("--max-nudges", type=int, default=3)
    ap.add_argument("--cmd-timeout", type=int, default=DEFAULT_CMD_TIMEOUT)
    ap.add_argument("--no-verify", action="store_true",
                    help="跳過收尾驗證（read-only / orientation 任務用）")
    ap.add_argument("--continue", dest="cont", action="store_true",
                    help="從 run-dir 既有 messages.json 續跑")
    ap.add_argument("--nudge", default=None,
                    help="續跑時注入的導正訊息（取代預設「繼續」）；操作者導方向的介面")
    args = ap.parse_args()

    profile_path = Path(args.profile).resolve()
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    verify_command = profile["verify_command"]
    parser_name = profile.get("parser", "generic")
    parsers.get_parser(parser_name)  # 早失敗：未知 parser 立刻報

    ws = Path(args.workspace).resolve()
    run_dir = Path(args.run_dir); run_dir.mkdir(parents=True, exist_ok=True)
    key = read_deepseek_key()
    tools = Tools(ws, args.container, args.cmd_timeout)
    baseline = load_baseline(profile, profile_path.parent)

    transcript = (run_dir / "transcript.jsonl").open("a", encoding="utf-8")
    def log(ev): transcript.write(json.dumps(ev, ensure_ascii=False) + "\n"); transcript.flush()

    msgs_path = run_dir / "messages.json"
    brief = Path(args.brief).read_text(encoding="utf-8")
    if args.cont and msgs_path.exists():
        messages = json.loads(msgs_path.read_text(encoding="utf-8"))
        messages.append({"role": "user",
                         "content": args.nudge or "繼續未完成的任務；完成時呼叫 finish。"})
        log({"ev": "resume", "nudge": bool(args.nudge)})
    else:
        messages = [{"role": "system", "content": build_system_prompt(profile, len(baseline))},
                    {"role": "user", "content": "任務 brief：\n\n" + brief}]
        log({"ev": "start", "brief": args.brief, "profile": str(profile_path)})

    DISPATCH = {"list_dir": tools.list_dir, "read_file": tools.read_file,
                "grep": tools.grep, "str_replace": tools.str_replace,
                "write_file": tools.write_file, "run_command": tools.run_command}

    finished_reason, summary, nudges = "max_iters", "", 0
    for it in range(args.max_iters):
        try:
            msg = call_deepseek(args.base_url, key, args.model, messages)
        except urllib.error.HTTPError as e:
            finished_reason = "error"; summary = f"DeepSeek HTTP {e.code}: {e.read().decode('utf-8','replace')[:500]}"
            log({"ev": "api_error", "detail": summary}); break
        except Exception as e:
            finished_reason = "error"; summary = f"DeepSeek 呼叫失敗：{e}"
            log({"ev": "api_error", "detail": summary}); break

        messages.append(msg)
        tool_calls = msg.get("tool_calls") or []
        if msg.get("content"):
            log({"ev": "assistant", "it": it, "text": msg["content"][:1500]})

        if not tool_calls:
            nudges += 1
            log({"ev": "no_tool", "it": it, "nudges": nudges})
            if nudges > args.max_nudges:
                finished_reason = "stalled"; summary = msg.get("content", "")[:500]; break
            messages.append({"role": "user",
                "content": "請用工具繼續推進；完成且測試無新紅燈時呼叫 finish。"})
            msgs_path.write_text(json.dumps(messages, ensure_ascii=False), encoding="utf-8")
            continue
        nudges = 0

        done = False
        for tc in tool_calls:
            name = tc["function"]["name"]
            try:
                a = json.loads(tc["function"].get("arguments") or "{}")
            except Exception:
                a = {}
            if name == "finish":
                finished_reason = "finish"; summary = a.get("summary", ""); done = True
                messages.append({"role": "tool", "tool_call_id": tc["id"], "content": "（已收到 finish）"})
                log({"ev": "finish", "it": it, "summary": summary}); break
            fn = DISPATCH.get(name)
            if fn is None:
                result = f"未知工具：{name}"
            else:
                try:
                    result = fn(**a)
                except Exception as e:
                    result = f"工具 {name} 執行錯誤：{e}"
            log({"ev": "tool", "it": it, "name": name,
                 "args": {k: (v[:200] if isinstance(v, str) else v) for k, v in a.items()},
                 "result_head": result[:400]})
            messages.append({"role": "tool", "tool_call_id": tc["id"], "content": result})
        msgs_path.write_text(json.dumps(messages, ensure_ascii=False), encoding="utf-8")
        if done: break

    # ── 收尾：驗證 + status.json ──
    if args.no_verify:
        verify = {"passed": None, "failed": None, "failure_names": [], "raw_tail": "(skipped: --no-verify)"}
        new_failures = []
        log({"ev": "verify_skipped"})
    else:
        log({"ev": "verify_start"})
        verify = run_verify(tools, verify_command, parser_name)
        new_failures = sorted(set(verify["failure_names"]) - baseline) if verify["failure_names"] else []
    diff_stat, changed = git_diff_stat(ws)
    status = {
        "profile": str(profile_path),
        "brief": args.brief,
        "finished_reason": finished_reason,
        "iterations": it + 1,
        "deepseek_summary": summary,
        "verify": {
            "parser": parser_name,
            "passed": verify["passed"], "failed": verify["failed"],
            "baseline_failed": len(baseline),
            "new_failures": new_failures,
            "clean": (verify["failed"] is not None and not new_failures),
            "raw_tail": verify["raw_tail"],
        },
        "git_diff_stat": diff_stat,
        "files_changed": changed,
        "stalled": finished_reason in ("stalled", "max_iters"),
        "transcript": str(run_dir / "transcript.jsonl"),
    }
    (run_dir / "status.json").write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    log({"ev": "done", "finished_reason": finished_reason})

    print("──────── loop 結束 ────────")
    print(f"finished_reason : {finished_reason}")
    print(f"iterations      : {it + 1}")
    print(f"verify ({parser_name}) : {verify['passed']} passed / {verify['failed']} failed (baseline {len(baseline)})")
    print(f"new_failures    : {new_failures or '無 ✅'}")
    print(f"files_changed   : {len(changed)} 個")
    print(f"summary         : {summary[:300]}")
    print(f"status.json     : {run_dir / 'status.json'}")

if __name__ == "__main__":
    main()
