# QUICKSTART —— 給接手 agent 的 5 分鐘上手

thinloop 讓「**你（人/agent）當介面、DeepSeek 做髒活**」：丟 brief 進、`status.json` 出，
你只給訊號、不讀它的 chain-of-thought。引擎是 project-agnostic，**你的 project 只要寫一份
profile 就能用**。

## 用你的 project：5 步

1. **sandbox image**：準備一個含你 project 工具鏈的 docker image（build/測試在裡面跑得動）。
2. **profile**：寫 `profiles/<name>.json`：
   ```jsonc
   {
     "name": "myproj",
     "project_desc": "一句話描述",
     "sandbox_image": "myproj-sandbox:latest",
     "verify_command": "<在 /workspace 內跑的測試指令>",
     "parser": "generic",          // generic(看 exit code，大多夠用) / pytest / jest / cargo
     "rules_file": "README.md",    // 要 DeepSeek 讀的規範檔（workspace 內）
     "preflight": null,            // 選：沙箱啟動前的守門 script
     "baseline_file": null         // 選：已知/環境限定失敗清單
   }
   ```
3. **workspace**：`git clone 你的 repo` + `git checkout -b deepseek/<task>`（git 隔離，DeepSeek 改動落在分支）。
4. **brief**：寫 `/tmp/brief.md` —— 任務 + **明確驗收標準** + 邊界（不要動哪些）。
5. **跑**：
   ```bash
   bash drive.sh profiles/<name>.json /tmp/brief.md /path/to/clone
   # 偷懶 / 沒完成 → 同一 run 續跑，附一句導正：
   bash drive.sh profiles/<name>.json /tmp/brief.md /path/to/clone --continue --nudge "修一下 X"
   ```

## 你只讀 `status.json`

`finished_reason`（finish/stalled/max_iters/error）、`new_failures`（DeepSeek 引入的紅燈，
空 = 乾淨）、`files_changed`、`summary`。**不要讀 transcript**（那是它的廢話）。

## 兩份必讀
- **`DISCIPLINE.md`** —— 哪些靠工具、哪些靠你的紀律（寫好 brief、**只給訊號不給答案**、
  交付前自跑真實路徑、merge 前 review）。這是成敗關鍵。
- **`README.md`** —— 架構、完整 profile schema、parser registry 怎麼擴充。

## 一句話
工具負責「機械正確」，**你負責「判斷正確」**。
