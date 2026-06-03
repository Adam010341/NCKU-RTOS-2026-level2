# NCKU-RTOS-2026 Virtual Power Plant (VPP) Dynamic Scheduling System

## 🚀 快速執行指南 (Quick Start & Execution Guide)

本專案同時支援 **「自動批次分析 10 種情境」** 以及 **「單一檔案 Demo 測試」**，並且可以隨時在 Level 1 (基礎要求) 與 Level 2 (進階動態排程) 之間無縫切換。

### 1. Level 1 / Level 2 模式切換
專案預設開啟 **Level 2 進階動態排程模式**。
若須測試level 1，請至 `src/scheduler.py` 大約第 40 行處，將 `LEVEL2_ENABLED` 變數修改為 `False`：
```python
# src/scheduler.py
LEVEL2_ENABLED = False  # 設為 False 執行 Level 1，設為 True 執行 Level 2
```
切換後重新執行程式，所有的資源限制與排程邏輯都會退回到符合 Level 1 的要求。

### 2. 重現 10 種情境分析 (Batch Analysis)
在平常開發或撰寫報告階段，系統預設會自動載入 `output/sporadic_aperiodic_task/` 底下的 10 組 `scenario_*.json`。
請確認 `input/` 資料夾內 **沒有** 名為 `aperiodic_n_sporadic.json` 的檔案，然後執行：
```bash
python src/scheduler.py
```
**執行結果**：
- 系統會依序跑完 10 種情境，並在 `output/` 目錄下產生帶有情境後綴的檔案（例如 `schedule_result_level2_scenario_01_uniform.json`）。
- 為了相容批改系統，程式會自動將第一組 (`scenario_01`) 的結果複製成標準繳交檔名 (`schedule_result.json` 等)。
- 同時會呼叫 evaluator 進行總評估，產生包含所有情境的 `evaluation_results.json`。

### 3. Demo 測試
在 Demo 時：
1. 將測試用的突發任務檔案命名為 `aperiodic_n_sporadic.json`。
2. 將該檔案放入專案的 `input/` 目錄中 (`input/aperiodic_n_sporadic.json`)。
3. 執行程式：
```bash
python src/scheduler.py
```
**執行結果**：
程式會印出 `[*] 偵測到 Demo 專用測資` 的提示，並 **直接跳過批次情境**，單獨針對該 Demo 檔案進行模擬。產生的輸出檔案會 **直接覆蓋** 標準檔名：
- `output/schedule_result.json`
- `output/acceptance_test_log.json`
- `output/evaluation_results.json`

---

## 📂 檔案結構

```text
NCKU-RTOS-2026-level2/
├── README.md                  # 本說明文件
├── report.pdf                 # 系統設計報告
├── src/
│   ├── scheduler.py           # 系統進入點 (包含 Offline / Online 排程與切換邏輯)
│   ├── evaluator.py           # 評估與計分模組
│   ├── engine/                # 核心排程引擎 (Planner, Tester, Tracer 等)
│   ├── advanced_scheduler.py  # Level 2 專用：處理市場違約與綠電預測誤差
│   └── task_generator.py      # Task Set 生成器
├── input/                     # 輸入資料與 Demo 專用測資放置區
├── output/                    # 模擬結果與 Evaluator 輸出
└── runtime_config.json        # Level 2 額外設定檔
```

---

## 📦 Periodic Task Set 生成策略與額外設計說明

本模組在滿足作業基礎規範外，額外引入以下工程設計，以確保產出的 Task Set 兼具「數學可排程性」與 `Demo` 穩定性。組員與評分時可參考此邏輯理解輸入資料特性：

| 額外設計 / 限制 | 設計動機與對排程器的影響 |
|:---|:---|
| **Non-preemptive 綁定於 `e=2` 而非 `e=3`** | 原規劃將最長執行時間設為不可中斷，但 `e=3, d=3` 會產生零鬆弛的連續區塊，極易造成排程碎片化與 MILP 求解震盪。改為 `e=2` 可在滿足 `e≠1` 規範的前提下，顯著降低連續時段分配難度，提升 Scheduler 收斂速度與 Acceptance Test 的插入成功率。 |
| **固定比例 `p=6` 短週期任務** | 用於精確錨定 Workload Density (DW) 於 `0.75~0.95` 區間。避免 DW 過低導致排程無挑戰性，或 DW > 1.0 造成理論過載。短週期提供穩定的基底負載，便於計算跨 Frame 的 Slack 餘裕，並降低儲能 SOC 劇烈波動的風險。 |
| **混合週期設計 (`6`, `11/12`, `15~24`) 與防禦性 Deadline 下限** | 未強制所有 period 為 3 的倍數，保留 `11/12` 以貼近真實非對齊週期情境。為確保 `f=3` 的 Frame 可視性 (`2f−gcd(f,p)≤d`)，對前 `N-2` 個 task 自動設定 `d≥6` 下限。此設計在數學上恆滿足限制式（例：`p=11` 時 `2×3−gcd(3,11)=5 ≤ 6`），避免寫死參數，同時測試排程器處理非對齊釋放點的能力。 |
| **Deadline 分層策略：前段寬鬆(≥6) / 末段緊迫(d=3)** | 末段固定 `d=3` 是為了穩定滿足 1-6 (`≥20% d=e`) 與 `f=3` 的邊界條件；前段保留寬鬆 Deadline 則提供排程器進行能量平移（儲能充放）與機組 Ramp 調整的彈性空間，避免所有 Job 競爭同一時間窗，利於優化 `f2` (發電成本) 與 `f3` (售電收益)。 |
| **確定性種子 + 自動回退驗證機制** | 固定 `RANDOM_SEED=2026` 並內建 `validate()` 斷言。若隨機組合觸發 DW 超標、Job 展開數不足或 Frame 可視性失敗，將自動重抽。確保每次執行輸出皆為「合法且可排程」的確定性輸入，方便組員除錯、CI 驗證與 Demo 重現。 |

---

## ⚙️ 核心調度引擎設計 (Scheduling Engine Architecture)

本虛擬電廠 (VPP) 的排程核心採用「雙層調度架構 (Two-Tier Scheduling Architecture)」，以確保在硬即時 (Hard Real-Time) 約束下達成系統存活與經濟效益最大化。在 Level 2 版本更導入了進階動態重排程來應對市場與氣候的不確定性。整體引擎分為四大階段：

### 1. 日前離線排程 (Offline Pre-scheduling)
* **負責模組：** `src/engine/offline_planner.py`
* **處理對象：** 週期性任務 (Periodic Tasks)，發布時間與週期提前已知。
* **演算法 (Greedy DFS)：** 
  採用以 **3 小時為一個尋找窗口 (Frame)** 的深度優先搜尋 (DFS)。
  1. 系統針對當下 3 小時內待執行的任務，產生所有可能的排程排列組合。
  2. 優先嘗試「把時間排滿」的激進貪婪策略 (Aggressive Greedy)，以確保任務盡早執行完畢。
  3. 驗證組合是否符合傳統火力機組的升降載速率 (Ramp Rate)、起停限制與電池容量極限。若驗證通過則推進至下一 Frame；若預見未來會 Deadline Miss 則啟動 **隱性回溯 (Backtrack)**。
* **產出：** 一份穩定的 72 小時基載排程表，與每小時的「全域剩餘算力 (Slack Capacity)」，作為後續防禦的基底。

### 2. 線上准入控制 (Online Admission Control)
* **負責模組：** `src/engine/acceptance_tester.py`
* **處理對象：** 突發任務 (Sporadic Tasks) 與 非週期任務 (Aperiodic Tasks)。
* **運作邏輯：**
  這是一個動態發生的過程。當系統運行到第 `t` 小時，新任務抵達時：
  1. **Sporadic 任務 (硬限制)：** 系統檢查 Offline Planner 留下的 `slack_capacity`，評估在該任務的 Deadline 之前是否能消化其能量需求。若算力不足，為了避免拖垮全系統，會執行嚴格的 **直接拒絕 (Reject)**。
  2. **Aperiodic 任務 (軟限制)：** 將其放入等候佇列 (Queue) 中。系統會在空閒時依序消化佇列；若任務等待過久導致物理上絕對無法完成，才會將其超時丟棄 (Timeout Drop)，解決隊頭阻塞 (Head-of-Line Blocking)。

### 3. 線上即時分派與能量溯源 (Real-time Dispatch & Tracing)
* **負責模組：** `src/engine/main_scheduler.py` 與 `src/engine/power_tracer.py`
* **運作邏輯：**
  每小時盤點當下所有應執行的任務（包含 Offline 與 Online 准入的任務），計算「總用電需求」。
  1. **Must-take 優先：** 優先全額吸收邊際成本為 0 的再生能源，算出「淨負載 (Net Load)」。
  2. **保命防禦：** 依照機組變動成本 (`cost_variable`) 升冪啟動發電機以補足淨負載。若火力極限仍不足，則以電池放電作為最後防線。
  3. **高價套利：** 若當下市場電價高於已開機火力的成本，系統主動推升該機組出力至極限，將剩餘算力倒賣給電網以極大化售電收益。
  4. **注水溯源：** `power_tracer.py` 透過注水演算法，精準對應「發電機/電池」與「個別任務」的供需流向，產出 $k_{j,i,t}$ 矩陣，確保能量絕對守恆。

### 4. Level 2 進階動態重排程 (Advanced Dynamic Rescheduling)
* **負責模組：** `src/advanced_scheduler.py` (僅在 `LEVEL2_ENABLED = True` 時啟動)
* **運作邏輯：**
  打破理想狀態，引入真實電力市場機制與氣候隨機性：
  1. **綠電不確定性：** 實際綠電發電量會與日前預測有 ±20% 的隨機波動 (`forecast_error_ratio`)。
  2. **市場違約機制：** 系統須預先向電網進行日前承諾售電 (Day-Ahead Commitment)。若因即時綠電不足導致無法履約，將面臨嚴厲的違約罰金 (`penalty_rate`)。
  3. **動態救援策略：** 在緊急缺電時刻，系統會打破原定排程，強行拉高昂貴火力機組的發電量，將電池放電納入老化成本考量，甚至將可延遲的 Aperiodic 任務「踢回」等候佇列 (Defer)，優先保證系統硬限制任務與市場承諾不違約。
