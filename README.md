## 檔案結構
```
NCKU-RTOS-2026/
├── README.md
├── report.pdf
├── src/
│ ├── task_generator.*
│ ├── scheduler.*
│ ├── evaluator.*
│ └── advanced_scheduler.* # Only Level 2
├── input/
│ ├── processor_settings.json
│ └── price_72hr.json
├── output/
│ ├── sporadic_aperiodic_task/
│ ├── task_set.json
│ ├── schedule_result.json
│ ├── evaluation_results.json
│ └── acceptance_test_log.json
└── runtime_config.* or crontab.txt # Only Level 2

```

## 📦 Periodic Task Set 生成策略與額外設計說明

本模組在滿足作業基礎規範外，額外引入以下工程設計，以確保產出的 Task Set 兼具「數學可排程性」與 `Demo` 穩定性。組員與評分時可參考此邏輯理解輸入資料特性：

| 額外設計 / 限制 | 設計動機與對排程器的影響 |
|:---|:---|
| **Non-preemptive 綁定於 `e=2` 而非 `e=3`** | 原規劃將最長執行時間設為不可中斷，但 `e=3, d=3` 會產生零鬆弛的連續區塊，極易造成排程碎片化與 MILP 求解震盪。改為 `e=2` 可在滿足 `e≠1` 規範的前提下，顯著降低連續時段分配難度，提升 Scheduler 收斂速度與 Acceptance Test 的插入成功率。 |
| **固定比例 `p=6` 短週期任務** | 用於精確錨定 Workload Density (DW) 於 `0.75~0.95` 區間。避免 DW 過低導致排程無挑戰性，或 DW > 1.0 造成理論過載。短週期提供穩定的基底負載，便於計算跨 Frame 的 Slack 餘裕，並降低儲能 SOC 劇烈波動的風險。 |
| **混合週期設計 (`6`, `11/12`, `15~24`) 與防禦性 Deadline 下限** | 未強制所有 period 為 3 的倍數，保留 `11/12` 以貼近真實非對齊週期情境。為確保 `f=3` 的 Frame 可視性 (`2f−gcd(f,p)≤d`)，對前 `N-2` 個 task 自動設定 `d≥6` 下限。此設計在數學上恆滿足限制式（例：`p=11` 時 `2×3−gcd(3,11)=5 ≤ 6`），避免寫死參數，同時測試排程器處理非對齊釋放點的能力。 |
| **Deadline 分層策略：前段寬鬆(≥6) / 末段緊迫(d=3)** | 末段固定 `d=3` 是為了穩定滿足 1-6 (`≥20% d=e`) 與 `f=3` 的邊界條件；前段保留寬鬆 Deadline 則提供排程器進行能量平移（儲能充放）與機組 Ramp 調整的彈性空間，避免所有 Job 競爭同一時間窗，利於優化 `f2` (發電成本) 與 `f3` (售電收益)。 |
| **確定性種子 + 自動回退驗證機制** | 固定 `RANDOM_SEED=2026` 並內建 `validate()` 斷言。若隨機組合觸發 DW 超標、Job 展開數不足或 Frame 可視性失敗，將自動重抽。確保每次執行輸出皆為「合法且可排程」的確定性輸入，方便組員除錯、CI 驗證與 Demo 重現。 |

## 核心調度引擎設計 (Scheduling Engine Architecture)

本專案的排程核心採用「雙層調度架構 (Two-Tier Scheduling Architecture)」，以確保在硬即時 (Hard Real-Time) 約束下達成系統存活與經濟效益最大化。核心引擎分為四大模組：

### 1. 日前離線排程 (Offline Planner - `offline_planner.py`)
* **演算法：** Frame-based Constraint Satisfaction DFS。
* **設計邏輯：** 為解決 72 小時決策樹的組合爆炸，導入 $f=3$ 的時鐘驅動框架 (Clock-driven Frame)，將排程降維為裝箱問題 (Bin Packing)。
* **防禦機制：** 具備隱性回溯 (State Rollback) 機制，確保週期性任務預排時絕對符合發電機啟停、爬升率與電池 SOC 限制，並輸出每小時的「全域剩餘算力 (Slack Capacity)」作為線上防禦基底。

### 2. 線上准入控制 (Acceptance Tester - `acceptance_tester.py`)
* **演算法：** $O(N)$ 貪婪掃描與動態佇列回填 (Backfilling)。
* **設計邏輯：** 揚棄高運算成本的線上 DFS。對於 Sporadic 任務，直接對 `slack_capacity` 進行線性掃描；對於 Aperiodic 任務，實作嚴格預判 (Strict Admissibility Pre-check) 與佇列管理。
* **防飢餓機制：** 引入「局部執行 (Partial Execution)」與「24 小時超時丟棄 (Timeout Drop)」，徹底解決隊頭阻塞 (Head-of-Line Blocking) 問題。

### 3. 高價套利與大一統迴圈 (Main Scheduler - `main_scheduler.py`)
* **演算法：** 兩階段經濟調度 (Two-Phase Economic Dispatch)。
* **目標函數權衡分析：** 1. **Must-take：** 優先全額吸收邊際成本為 0 的再生能源。
  2. **保命為先：** 計算內部淨負載，若算力不足，強制依照機組變動成本 (`cost_variable`) 升冪啟動發電機。電池鎖死為最後防禦底線，絕不主動放電套利。
  3. **動態套利：** 若當下市場電價 $\lambda_t$ 高於已開機火力機組之發電成本，演算法將主動推升該機組出力至物理極限 (`output_max`)，將剩餘算力倒賣給電網以極大化售電收益 ($f_3$)。

### 4. 能量流溯源 (Power Tracer - `power_tracer.py`)
* **演算法：** 注水分配演算法 (Water-filling Tracing)。
* **設計邏輯：** 將每小時各設備實際發電量建立 Supply Pool，精準配對並分配至各用電任務 ($k_{j,i,t}$ 矩陣)，確保 72 小時內每一度電皆符合能量守恆。
