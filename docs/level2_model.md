# Level 2 Advanced Dynamic Scheduler — Formal Model

## 1. Relaxed Assumptions (放寬假設)

| # | Level 1 假設 | Level 2 放寬 |
|---|---|---|
| A1 | Renewable forecast = actual output | Actual output 帶有隨機誤差 ε |
| A2 | Battery 無效率損失 | 充放電效率 η_chg, η_dis < 1 |
| A3 | Battery 無自放電 | 每小時 self-discharge σ |
| A4 | Battery 無老化成本 | 每 MWh 放電計入 degradation cost |
| A5 | Market: sell 無承諾 | Day-ahead sell commitment Commit_t |

---

## 2. Notation (符號定義)

| 符號 | 說明 | 單位 |
|------|------|------|
| T | 排程週期長度 = 72 | h |
| t | 時間索引，t ∈ {0,…,71} | — |
| R | 再生能源機組集合 | — |
| G | 火力機組集合 | — |
| B | 電池集合 | — |
| J^P | Periodic job 集合（hard-deadline） | — |
| J^S | Sporadic job 集合（hard-deadline） | — |
| J^A | Aperiodic job 集合（soft-deadline） | — |
| R̂_{r,t} | 再生能源 r 在 t 的**預測**出力比例（0~1） | — |
| R_act_{r,t} | 再生能源 r 在 t 的**實際**出力 | MWh |
| ε_{r,t} | 預測誤差 | — |
| ρ | 最大預測誤差比例 (forecast_error_ratio) | — |
| cap_r | 再生能源 r 的裝置容量 | MWh |
| SOC_{b,t} | 電池 b 在時間 t 的荷電狀態 | MWh |
| SOC_min_b | 電池 b 的最低 SOC | MWh |
| SOC_max_b | 電池 b 的最高 SOC | MWh |
| η_chg_b | 電池 b 的充電效率 (0~1) | — |
| η_dis_b | 電池 b 的放電效率 (0~1) | — |
| σ_b | 電池 b 的每小時自放電率 | h⁻¹ |
| C_{b,t} | 電池 b 在 t 的充電輸入量 | MWh |
| D_{b,t} | 電池 b 在 t 的放電輸出量（對負載提供） | MWh |
| D_loss_{b,t} | 放電效率損失 = D_{b,t}/η_dis_b - D_{b,t} | MWh |
| deg_b | 電池 b 每 MWh 放電的老化成本 | $/MWh |
| Commit_t | 時間 t 的日前承諾售電量 | MWh |
| Sell_t | 時間 t 的實際售電量 | MWh |
| λ_rt | 即時市場電價倍率 | — |
| π_t | 市場電價 | $/MWh |
| ρ_pen | 售電缺口罰款率 | $/MWh |
| Penalty_t | 時間 t 的市場罰款 | $ |
| w_j | Job j 每小時的電能需求 | MWh |
| x_{j,t} | 二元決策變數：job j 在 t 是否執行 | {0,1} |

---

## 3. Level 2 限制式（共 12 條）

### C1. Actual Renewable Output Definition（實際再生能源出力定義）

$$R\_act_{r,t} = cap_r \times \hat{R}_{r,t} \times (1 + \varepsilon_{r,t})$$

> 實際出力等於預測值乘上誤差因子。  
> **程式對應**：`RenewableUncertaintyModel.__init__` 中的 `actual = fc * (1.0 + eps)`

---

### C2. Actual Renewable Bounds（實際出力上下界）

$$0 \leq R\_act_{r,t} \leq cap_r, \quad \forall r \in R, t \in T$$

> 實際出力不得為負，也不得超過裝置容量。  
> **程式對應**：`actual = max(0.0, min(1.0, actual))`

---

### C3. Forecast Error Bound（預測誤差上界）

$$|\varepsilon_{r,t}| \leq \rho, \quad \forall r \in R, t \in T$$

> 誤差在 ±ρ 範圍內均勻分布（deterministic seed 確保可重現）。  
> **程式對應**：`eps = rng.uniform(-forecast_error_ratio, forecast_error_ratio)`

---

### C4. Battery SOC Transition with Efficiency（含效率的 SOC 狀態轉移方程式）

$$SOC_{b,t+1} = SOC_{b,t} - \frac{D_{b,t}}{\eta^{dis}_b} + C_{b,t} \times \eta^{chg}_b - \sigma_b \times SOC_{b,t}$$

> 放電時，SOC 實際下降量 = 提供量 / 放電效率；充電時，SOC 增量 = 輸入量 × 充電效率；再減去自放電。  
> **程式對應**：`apply_discharge_with_efficiency` / `apply_charge_with_efficiency` / `apply_self_discharge`

---

### C5. Battery SOC Lower and Upper Bound（SOC 上下界）

$$SOC^{min}_b \leq SOC_{b,t} \leq SOC^{max}_b, \quad \forall b \in B, t \in T$$

> SOC 不可低於 soc_min，也不可超過 soc_max。  
> **程式對應**：`bat.current_soc = max(bat.soc_min, bat.current_soc - soc_decrease)`

---

### C6. Battery Charge Power Limit（充電功率限制）

$$0 \leq C_{b,t} \leq C^{max}_b, \quad \forall b \in B, t \in T$$

> 每小時充電輸入量不超過 charge_max。  
> **程式對應**：`max_charge_input = min(float(battery.charge_max), ...)`

---

### C7. Battery Discharge Power Limit（放電功率限制）

$$0 \leq D_{b,t} \leq D^{max}_b, \quad \forall b \in B, t \in T$$

> 每小時放電量不超過 discharge_max。  
> **程式對應**：`raw_limit = min(float(battery.discharge_max), battery.current_soc - battery.soc_min)`

---

### C8. Battery Self-Discharge（自放電）

$$SOC_{b,t+1} \mathrel{-}= \sigma_b \times SOC_{b,t}$$

> 每小時固定比例的自放電損耗（在 apply_self_discharge 中呼叫）。  
> **程式對應**：`loss = battery.current_soc * sigma; battery.current_soc -= loss`

---

### C9. SOC-Dependent Discharge Limit（SOC 相依的放電上限）

$$D^{eff}_{b,t} = D^{max}_b \times \min\!\left(1,\; \frac{SOC_{b,t} - SOC^{min}_b}{0.2 \times (SOC^{max}_b - SOC^{min}_b)}\right)$$

> 當 SOC 接近下限時，可放電量線性縮減，防止電池過度放電。  
> **程式對應**：`effective_discharge_limit(battery)` 中的 `scale = min(1.0, depth / 0.2)`

---

### C10. Day-Ahead Sell Commitment Shortfall（日前售電承諾缺口）

$$Shortfall_t = \max(0,\; Commit_t - Sell_t), \quad \forall t \in T$$

> 若實際售電低於承諾，計算缺口。  
> **程式對應**：`shortfall = max(0.0, day_ahead_commitment - actual_sell)`

---

### C11. Market Penalty Calculation（市場罰款計算）

$$Penalty_t = Shortfall_t \times \rho^{pen}, \quad \forall t \in T$$

> 每單位缺口乘以罰款率，計入系統成本。  
> **程式對應**：`penalty = shortfall * penalty_rate`

---

### C12. Hard-Deadline Job Protection Rule（硬截止期任務保護規則）

$$x_{j,t} = 1 \text{ (保留)}, \quad \forall j \in J^P \cup J^S,\; \forall t : t \in \text{schedule}(j)$$

$$x_{j,t} \in \{0, 1\} \text{ (可延後)}, \quad \forall j \in J^A$$

> Periodic 和 accepted sporadic jobs 不可被 advanced_reschedule 移除；  
> 只有 aperiodic jobs（id 以 `a_` 開頭）可被 defer，且必須重新進入 waiting queue。  
> **程式對應**：`hard_jobs = [j for j in active_jobs if not is_aperiodic_job(j.id)]` 永遠保留；  
> `deferred_aperiodic_ids` 只記錄本 tick 被移除的 aperiodic id；`main_scheduler.py` 接著呼叫 `AcceptanceTester.defer_aperiodic_execution()`，把原始 `AperiodicTask` 狀態放回 tester queue，確保不消失。

---

### C13. Real-Time Extra Revenue（即時市場額外收益）

$$ExtraRev_t = \max(0,\; Sell_t - Commit_t) \times \pi_t \times (\lambda^{rt} - 1)$$

> 額外收益只能在 `trace_power_flows()` 得到實際 `Sell_t` 之後計算，避免用 renewable surplus 重複計入收入。  
> **程式對應**：`compute_market_metrics()` 中的 `surplus_sell`。

---

### C14. Battery Charging Pseudo Job（電池充電虛擬任務）

$$x_{b\_chg,t} = 1 \Rightarrow C_{b,t} > 0$$

> 當 Level 2 有剩餘供給可為電池充電時，`main_scheduler.py` 會加入如 `battery_1_chg` 的 pseudo job，讓 `TickRecord.k` 保留充電能流。此 pseudo job 不參與 deadline / response time / tardiness / jitter 評估。  
> **程式對應**：`ActiveJob(id=f"{bat.id}_chg", w=charged_input)`；`evaluator.py` 的 `is_charging_pseudo_job()`。

---

### C15. Aperiodic Defer State Restoration（Aperiodic 延後狀態復原）

$$j \in J^A \land j \text{ deferred at } t \Rightarrow j \in Queue^A_{t+1}$$

> 被 Level 2 延後的 aperiodic job 不可遺失，也不可只保留 `id` 與 `w`。系統必須復原原始 `AperiodicTask` 的 `remaining_execution`、slack reservation、queue membership。  
> **程式對應**：`AcceptanceTester.defer_aperiodic_execution(task_id, current_t)`。

---

### C16. Level 2 Adjusted Objective（Level 2 調整後目標值）

$$Obj^{L2} = GenCost + BatteryDegCost + MarketPenalty - MarketRevenue - ExtraRev$$

> Level 2 評估在 Level 1 成本與收入之外，加入電池老化成本、市場罰款與即時額外收益。  
> **程式對應**：`evaluator.py` 的 `level2_adjusted_objective_value`。

---

## 4. Level 2 Advanced Dynamic Scheduling Algorithm（虛擬碼）

```
ALGORITHM Level2-Advanced-Dynamic-Reschedule(t, active_jobs, ...)

INPUT:
  t                       ← current time step (0-based)
  active_jobs             ← set of jobs to execute at t
  actual_renewable_profile← RenewableUncertaintyModel object
  batteries, generators   ← hardware resources
  day_ahead_commitment[t] ← pre-committed sell amount

OUTPUT:
  new_active_jobs         ← adjusted job set
  deferred_aperiodic_ids  ← aperiodic ids deferred at current tick
  actual_ren_outputs      ← actual renewable power dict

BEGIN
  1. forecast_ren ← Σ_r cap_r × R̂_{r,t}               // forecast
     actual_ren   ← Σ_r cap_r × actual_ratio[r][t]      // C1, C2, C3
     gap ← forecast_ren - actual_ren

  2. IF gap > 0 (shortfall):                             // C10, C11
       remaining ← gap
       FOR each battery b:
         D ← min(remaining, D_eff_{b,t})                // C7, C9
         SOC_{b,t} -= D / η_dis_b                       // C4, C5
         remaining -= D
         record battery_rescue_energy += D

       FOR each generator g (sorted by cost):
         headroom ← g.output_max - g.current_output     // ramp-up
         ramp ← min(remaining, headroom)
         remaining -= ramp
         record thermal_rescue_energy += ramp

       IF remaining > 0:                                 // C12
         FOR each aperiodic job j ∈ active_jobs:
           IF remaining > 0:
             remove j from active_jobs
             append j.id to deferred_aperiodic_ids       // restored by AcceptanceTester
             remaining -= w_j
             deferred_aperiodic_jobs += 1

  3. ELIF gap < 0 (surplus):
       FOR each battery b:
         C ← min(|gap|, C_max_b, (SOC_max - SOC_b)/η_chg)  // C6
         record advisory charging capacity
         |gap| -= C

  4. RETURN new_active_jobs, deferred_aperiodic_ids, actual_ren_dict, level2_decision

  [Post power-tracing]
  5. main_scheduler applies:
     - tester.defer_aperiodic_execution(id, t) for deferred ids
     - apply_discharge_with_efficiency() for committed battery rescue
     - battery charge pseudo jobs such as battery_1_chg before tracing

  6. shortfall_t ← max(0, Commit_t - Sell_t)            // C10
     Penalty_t   ← shortfall_t × ρ_pen                  // C11
     level2_metrics.market_penalty += Penalty_t
     realtime_extra_revenue is computed from actual Sell_t only

  7. APPLY apply_self_discharge(b) for each b            // C8

END
```

---

## 5. Evaluation Metrics 說明

| 指標 | 公式 / 來源 | 說明 |
|------|------------|------|
| `hard_deadline_miss_rate` | \|missed hard jobs\| / \|total hard jobs\| | Level 1 指標，應維持 0 |
| `soft_deadline_miss_rate` | \|missed aperiodic\| / \|total aperiodic\| | Level 2 下允許部分缺失 |
| `sporadic_value_rate` | completed_e / total_e | Sporadic 任務完成效益 |
| `renewable_shortfall_events` | 計數 | 實際再生能源低於預測的次數 |
| `total_renewable_shortfall` | Σ_t (forecast - actual) if > 0 | 累積缺口 MWh |
| `battery_rescue_energy` | Σ 電池補救 MWh | Level 2 電池補救總量 |
| `thermal_rescue_energy` | Σ 火力升載 MWh | Level 2 火力補救總量 |
| `battery_degradation_cost` | Σ D_{b,t} × deg_b | 電池老化成本 |
| `market_penalty` | Σ_t Penalty_t | 累積市場罰款 |
| `realtime_extra_revenue` | Σ max(0, Sell_t - Commit_t) × π_t × (λ_rt - 1) | 由 power tracing 後的實際售電量計算 |
| `level2_adjusted_objective_value` | gen_cost + bat_deg + penalty - revenue - rt_extra | Level 2 整體目標函數 |

---

## 6. Schedule Result Format

Level 1 keeps the original plain list format:

```json
[
  {"t": 1, "P": {}, "k": {}, "sell": 0.0, "soc": {}}
]
```

Level 2 writes a metadata object:

```json
{
  "trajectory": [
    {"t": 1, "P": {}, "k": {}, "sell": 0.0, "soc": {}}
  ],
  "level2_metrics": {
    "forecast_error_ratio": 0.2,
    "advanced_reschedule_count": 0,
    "battery_degradation_cost": 0.0,
    "market_penalty": 0.0,
    "realtime_extra_revenue": 0.0
  }
}
```

Battery charging pseudo jobs, such as `battery_1_chg`, may appear inside `TickRecord.k` to preserve energy-flow balance. They are not real periodic, sporadic, or aperiodic tasks, so the evaluator ignores `_chg` ids for deadline, response-time, tardiness, jitter, and completion metrics.

---

## 7. 與程式邏輯的對應

| 限制式 | 檔案 | 函式 / 行為 |
|--------|------|------------|
| C1 | `advanced_scheduler.py` | `RenewableUncertaintyModel.__init__` |
| C2 | `advanced_scheduler.py` | `max(0.0, min(1.0, actual))` |
| C3 | `advanced_scheduler.py` | `rng.uniform(-rho, rho)` |
| C4 | `advanced_scheduler.py` | `apply_discharge_with_efficiency` / `apply_charge_with_efficiency` |
| C5 | `advanced_scheduler.py` | `max(bat.soc_min, ...)` |
| C6 | `advanced_scheduler.py` | `apply_charge_with_efficiency` 的 `max_charge_input` |
| C7 | `advanced_scheduler.py` | `effective_discharge_limit` |
| C8 | `advanced_scheduler.py` / `main_scheduler.py` | `apply_self_discharge` |
| C9 | `advanced_scheduler.py` | `effective_discharge_limit` 中的 `scale` |
| C10 | `advanced_scheduler.py` | `compute_market_metrics` shortfall |
| C11 | `advanced_scheduler.py` | `penalty = shortfall * penalty_rate` |
| C12 | `advanced_scheduler.py` / `acceptance_tester.py` | hard jobs 不可移除；aperiodic defer 由 `deferred_aperiodic_ids` + `defer_aperiodic_execution()` 完成 |
| C13 | `advanced_scheduler.py` | `compute_market_metrics` 根據 actual `Sell_t` 計算 `realtime_extra_revenue` |
| C14 | `main_scheduler.py` / `evaluator.py` | `_chg` pseudo job 保留充電能流；evaluator 忽略其任務指標 |
| C15 | `acceptance_tester.py` | `defer_aperiodic_execution()` 復原 queue、slack、remaining execution |
| C16 | `evaluator.py` | `level2_adjusted_objective_value` |
