# 用 DeepSeek dev loop 的紀律（靠你，不是靠工具）

這份是給**操作者**（用 `meta/loop/` 派 DeepSeek 做事的人，包含未來其他 project）的
建議。harness 會自動扛一部分事，但有些東西**本質要靠你的紀律** —— 工具幫不上、或
不該全自動。這份就是後者的清單，全部從真實踩坑中累積。

## 工具已經幫你扛的（你不用操心）

- **依賴一致性**：`check-lock-sync` 守門，沙箱 image 的 lock ≠ repo 就拒絕啟動。
- **沙箱 mount 防呆**：`sandbox.sh ensure` 偵測 stale mount（re-clone 過）就重建。
- **驗證解析 + 新紅燈偵測**：parser 認 grand-total 行，扣掉 baseline 算「你引入的」紅燈。
- **不會傻等**：watchdog 在主 loop 完成或超時時叫醒監督者（即使 loop hang）。

## 本質要靠你紀律的（工具幫不上）

### 1. 寫好 brief —— 成敗最關鍵的一步
DeepSeek 探索靠它自己，但**範圍與驗收靠你的 brief**。一份好 brief：
- 指向對的 design doc + 其「現況盤點 / headless 可測」段。
- 明確列**驗收標準**（哪些測試要綠、哪個探針回什麼、build 要過）。
- 圈出**邊界**（不要動哪些子系統）。
- 提醒它遵守該 repo 的規範檔（limn 是 CLAUDE.md）。

brief 模糊 → DeepSeek 亂跑或假完成。工具寫不出好 brief，這是你的活。

### 2. 介入只給訊號，不給診斷答案
發現問題（例如紅燈）時，**只給最少訊號**（「有這些新紅燈、本來是綠的，自己查自己修」），
**不要**把你診斷出的根因塞給它。診斷是 DeepSeek 的活；你替它做 = 過度介入。漸進式：
先給最少，它真卡住多輪才加提示。`--nudge` 是這個介面，內容要克制。

### 3. 交付前自己跑通「真實使用路徑」
**unit 全綠 ≠ 真的能用。** 這次 limn-client 的 unit 2987 全綠，但真正的 CLI 一跑就
reader error —— 是手動 walkthrough 才抓到。所以：碰到對外介面（CLI / API / wire），
**自己親跑一次真實路徑**（walkthrough / smoke），別只看 unit。
（這條可半自動化成 verify 的一步，但「設計出涵蓋真實路徑的 smoke」仍靠你。）

### 4. 要求每個對外介面有 exec-level 測試
DeepSeek 容易只測內部 helper（好測），漏掉真正的入口（CLI script、wire endpoint）。
在 brief 就要求：**對外介面要有「實際 exec / 連線」的測試**，不是只 call 內部函式。
否則覆蓋洞會讓 unit 綠但實際壞。

### 5. workspace 用 clone 隔離，別讓它動 main
給 DeepSeek 的 WORKSPACE 一律是專用 git clone（自己的分支），不是 main 工作樹。
就算它亂改，也落在分支上，由你 review 後 merge。

### 6. 換 model / 改 flake.lock 後，重 build runtime image
依賴鐵律靠守門 + 你的操作紀律：動了 `flake.lock`（含升依賴）要
`build-runtime.sh` 重 build，否則容器與 host 版本漂掉。

### 7. merge 前 review，別盲信綠燈
三重綠（unit + 真實路徑 + walkthrough）通過再 merge。綠燈是必要不是充分 ——
這次若只看 unit 就 merge，會把壞的 CLI 併進去。

## 一句話
**工具負責「機械正確」，你負責「判斷正確」**：brief 寫得準不準、介入收不收斂、
真實路徑驗沒驗、該不該 merge —— 這些是紀律，不是按鈕。
