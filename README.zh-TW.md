# deepseek-thinloop

一個**通用、project-agnostic** 的 thin agent loop：讓 **DeepSeek 做髒活**，操作者
（人 / Claude）**當介面** —— 寫清楚的 brief、只讀乾淨的成果（`status.json`）、偷懶就
ping，不讀它的 chain-of-thought。

引擎本身不焊任何 project；所有 project 專屬的東西來自一份 **profile**。

## 為什麼存在

DeepSeek 便宜、能做髒活，但會偷懶、會假完成。這個 loop 把它關進一個沙箱、給它工具
自由探索一個 repo、改檔、跑 build/測試，最後**自動驗證 + 算出它引入的新紅燈**，把一個
混亂的 agent 變成「丟 brief 進、status.json 出」的乾淨管道。

它是從 limn 這個專案磨出來的（見 `git log`），現在抽成通用引擎，**任何 project 只要
寫一份 profile 就能用**。

## 架構

```
操作者寫 brief ──► drive.sh <profile> <brief> <workspace>
                      │  讀 profile：sandbox image / preflight / verify / parser / baseline / rules
                      ▼
              sandbox.sh ensure ──► 持久沙箱容器（profile 的 image，掛 workspace 到 /workspace）
                      ▼
              loop.py（function-calling 迴圈）
                 ├─ 檔案工具（list/read/grep/str_replace/write）→ 直接在 host workspace 上（快、釘樁防逃逸）
                 ├─ run_command → docker exec 進沙箱（拿該 project 的工具鏈）
                 └─ 收尾：跑 profile.verify_command → profile.parser 解析 → 扣 baseline → status.json
                      ▼
操作者只讀 status.json（finished_reason / new_failures / files_changed / summary）
```

**關鍵**：檔案操作走 host（workspace 是沙箱 bind-mount），只有 build/測試走容器。
DeepSeek 全自主探索，但死鎖在 workspace 內（工具釘樁、無 browser）。

## 怎麼用

```bash
# 1) 給 DeepSeek 一個 git 隔離的 workspace（clone + 分支）
git clone <repo> /path/to/clone && cd /path/to/clone && git checkout -b deepseek/<task>

# 2) 寫一份 brief（任務 + 驗收標準），存成 /tmp/brief.md

# 3) 跑（沙箱自動起；首次需該 project 的 sandbox image 已 build）
bash drive.sh profiles/<project>.json /tmp/brief.md /path/to/clone

# 偷懶 / 沒做完 → 同一個 run 續跑，可附導正訊息
bash drive.sh profiles/<project>.json /tmp/brief.md /path/to/clone --continue --nudge "修一下 X"

# read-only / orientation 任務跳過驗證
bash drive.sh profiles/<project>.json /tmp/brief.md /path/to/clone --no-verify

# 收工
SANDBOX_NAME=thinloop-<project> bash sandbox.sh down
```

## profile schema

一份 `profiles/<name>.json`：

```jsonc
{
  "name": "limn",                       // 沙箱名衍生自此（thinloop-<name>）
  "project_desc": "...",                // 給 DeepSeek 的一句話描述
  "sandbox_image": "...:tag",           // 必：沙箱 docker image
  "preflight": "/abs/or/rel/script.sh", // 選：沙箱啟動前跑的守門（相對 profile 解析）
  "verify_command": "...",              // 必：在 /workspace 內跑的驗證指令
  "verify_hint": "...",                 // 選：給 DeepSeek 自驗用（預設 = verify_command）
  "parser": "limn-lisp",                // registry：generic | limn-lisp | pytest | jest | cargo
  "baseline_file": "x-baseline.txt",    // 選：已知/環境限定失敗清單（相對 profile）
  "rules_file": "CLAUDE.md"             // 選：workspace 內要 DeepSeek 讀的規範檔
}
```

## 加一個新 project

1. 準備一個 **sandbox image**（含該 project 的工具鏈）。
2. 寫 `profiles/<name>.json`（上面 schema）。`parser` 選一個：
   - `generic`：只看 verify 指令的 exit code（0 = 過）。大多 project 夠用。
   - `pytest` / `jest` / `cargo` / `limn-lisp`：解析「N passed M failed + 失敗名」，
     支援 baseline 排除。
   - 框架沒列到 → 在 `parsers.py` 加一個 `parse_xxx` + 註冊。
3.（選）一個 `<name>-baseline.txt`：環境限定的已知失敗（一行一個測試名）。
4. 跑 `bash drive.sh profiles/<name>.json <brief> <clone>`。

## 操作紀律

工具負責「機械正確」，**操作者負責「判斷正確」** —— 寫好 brief、介入克制（只給訊號
不給答案）、交付前自跑真實路徑、merge 前 review。詳見 **`DISCIPLINE.md`**（必讀）。

## 檔案

| 檔 | 作用 |
|---|---|
| `loop.py` | 引擎：function-calling 迴圈、工具、驗證、status.json |
| `parsers.py` | 測試輸出 parser registry |
| `sandbox.sh` | 持久沙箱容器（image/preflight 由 profile） |
| `drive.sh` | 入口：讀 profile → ensure 沙箱 → 跑 loop |
| `profiles/*.json` | 各 project 的 profile |
| `DISCIPLINE.md` | 操作者紀律（靠人，不是靠工具） |
| `.runs/` | 每次 run 的 transcript/status/messages（gitignored） |
