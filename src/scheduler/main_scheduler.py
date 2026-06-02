"""
main_scheduler.py — 72-hour VPP Online Simulation Engine

Level 1: 基本動態排程（periodic + sporadic acceptance + aperiodic queue）
Level 2: Advanced Dynamic Rescheduling（renewable uncertainty + realistic battery + market）
"""

import json
from typing import List, Dict, Any, Optional

from src.scheduler.models import (
    SporadicTask, AperiodicTask, TickRecord,
    ThermalGenerator, Battery, RenewableGenerator
)
from src.scheduler.acceptance_tester import AcceptanceTester
from src.scheduler.power_tracer import trace_power_flows
from src.scheduler.offline_planner import get_valid_bounds
from src.scheduler.advanced_scheduler import (
    Level2Metrics,
    RenewableUncertaintyModel,
    advanced_reschedule,
    compute_market_metrics,
    apply_charge_with_efficiency,
    apply_discharge_with_efficiency,
    apply_self_discharge,
    compute_battery_degradation_cost,
)


class ActiveJob:
    """單一時間點內待執行的 job 快照。"""
    def __init__(self, id: str, w: float):
        self.id = id
        self.w = w


class SimulationTrajectory(list):
    """List-compatible trajectory that can carry run-level metadata."""

    def __init__(self):
        super().__init__()
        self.level2_metrics: Dict[str, Any] = {}


def run_72hr_simulation(
    schedule_dict: Dict[str, List[int]],
    tester: AcceptanceTester,
    generators: List[ThermalGenerator],
    batteries: List[Battery],
    renewables: List[RenewableGenerator],
    price_72hr: List[float],
    offline_tasks: List[Any],
    online_sporadic_arrivals: Dict[int, List[SporadicTask]],
    online_aperiodic_arrivals: Dict[int, List[AperiodicTask]],
    log_list: List[str] = None,
    # ── Level 2 parameters ──
    level2_enabled: bool = False,
    level2_config: Optional[Dict] = None,
    actual_renewable_profile: Optional[RenewableUncertaintyModel] = None,
    day_ahead_sell_commitment: Optional[List[float]] = None,
) -> List[TickRecord]:
    """
    Main 72-hour dynamic scheduling simulation loop.

    Parameters
    ----------
    level2_enabled              : True → 啟用 Level 2 advanced scheduler
    level2_config               : Level 2 設定字典（penalty_rate / realtime_price_multiplier / commitment_ratio）
    actual_renewable_profile    : RenewableUncertaintyModel 物件（Level 2 用）
    day_ahead_sell_commitment   : 長度 72 的每小時日前承諾售電量 list（Level 2 用）
    """
    if log_list is None:
        log_list = []

    # ── Level 2 初始化 ──
    level2_metrics = Level2Metrics()
    _l2cfg = level2_config or {}
    level2_metrics.forecast_error_ratio = float(_l2cfg.get("forecast_error_ratio", 0.0))
    penalty_rate             = float(_l2cfg.get("penalty_rate", 2.0))
    realtime_price_mult      = float(_l2cfg.get("realtime_price_multiplier", 1.1))
    commitment_ratio         = float(_l2cfg.get("commitment_ratio", 0.8))
    reserve_margin           = float(_l2cfg.get("reserve_margin", 0.1))

    trajectory = SimulationTrajectory()
    
    # 建立離線任務的 w 對照表
    offline_w_map = {}
    for t_obj in offline_tasks:
        offline_w_map[t_obj.id] = t_obj.w

    # 建立 online task w 對照表（方便快速查詢）
    online_w_map: Dict[str, float] = {}
    for tasks in online_sporadic_arrivals.values():
        for st in tasks:
            online_w_map[st.id] = float(st.w)
    for tasks in online_aperiodic_arrivals.values():
        for at in tasks:
            online_w_map[at.id] = float(at.w)

    for t in range(72):
        price_t = price_72hr[t]
        
        # ─────────────────────────────────────────────────────────
        # Step 1: 突發任務抵達與准入
        # ─────────────────────────────────────────────────────────
        tester.rejected_sporadic_this_tick.clear()
        
        # 推進佇列並取得從 Queue 中丟棄的清單
        missed_aperiodic = tester.process_queue_at_tick(t)
        for missed_id in missed_aperiodic:
            log_list.append(
                f"[時間 t={t+1:02d}] ⚠️ Aperiodic 任務 {missed_id} "
                f"因超時或硬體算力不足，已從佇列中強制丟棄 (Soft Deadline Miss)。"
            )
        
        if t in online_sporadic_arrivals:
            for stask in online_sporadic_arrivals[t]:
                is_admitted = tester.test_sporadic(stask, current_t=t)
                status = "✅ 准入成功 (排入時程)" if is_admitted else "❌ 准入拒絕 (違反硬約束)"
                log_list.append(
                    f"[時間 t={t+1:02d}] 📥 Sporadic 任務抵達: ID={stask.id} "
                    f"(需求={stask.w}MWh, 時長={stask.e}h, D={stask.d}) -> {status}"
                )
                
        if t in online_aperiodic_arrivals:
            for atask in online_aperiodic_arrivals[t]:
                is_admitted = tester.test_aperiodic(atask, current_t=t)
                status = "✅ 准入成功 (進入佇列待命)" if is_admitted else "❌ 准入拒絕 (物理極限不可能完成)"
                log_list.append(
                    f"[時間 t={t+1:02d}] 📥 Aperiodic 任務抵達: ID={atask.id} "
                    f"(需求={atask.w}MWh, 時長={atask.e}h) -> {status}"
                )
                if not is_admitted:
                    missed_aperiodic.append(atask.id)
                
        rejected_sporadic = list(tester.rejected_sporadic_this_tick)
        
        # ─────────────────────────────────────────────────────────
        # Step 2: 任務盤點
        # ─────────────────────────────────────────────────────────
        active_jobs: List[ActiveJob] = []
        
        # 收集離線排定的任務（periodic jobs）
        for job_id, hours in schedule_dict.items():
            if t in hours:
                task_id = job_id.split('_')[0] if '_' in job_id else job_id
                w = offline_w_map.get(task_id, 0)
                active_jobs.append(ActiveJob(id=task_id, w=w))
                
        # 收集線上 Accept 排定的任務（sporadic + aperiodic from acceptance queue）
        for task_id, hours in tester.online_schedule.items():
            if t in hours:
                w = online_w_map.get(task_id, 0)
                active_jobs.append(ActiveJob(id=task_id, w=w))

        # ─────────────────────────────────────────────────────────
        # Step 3 (Level 2 only): Advanced Dynamic Rescheduling
        # ─────────────────────────────────────────────────────────
        actual_renewable_outputs: Dict[str, float] = {}
        level2_decision: Dict[str, Any] = {}
        deferred_aperiodic_ids: List[str] = []

        if level2_enabled and actual_renewable_profile is not None:
            commit_t = (day_ahead_sell_commitment[t]
                        if day_ahead_sell_commitment is not None
                        else 0.0)
            active_jobs, deferred_aperiodic_ids, actual_renewable_outputs, level2_decision = advanced_reschedule(
                t=t,
                active_jobs=active_jobs,
                generators=generators,
                batteries=batteries,
                renewables=renewables,
                actual_renewable_profile=actual_renewable_profile,
                price_t=price_t,
                day_ahead_sell_commitment=commit_t,
                log_list=log_list,
                level2_metrics=level2_metrics,
                reserve_margin=reserve_margin,
                penalty_rate=penalty_rate,
                realtime_price_multiplier=realtime_price_mult,
            )
            for task_id in deferred_aperiodic_ids:
                restored = tester.defer_aperiodic_execution(task_id, current_t=t)
                if restored:
                    log_list.append(
                        f"[Level 2 t={t+1:02d}] Deferred aperiodic {task_id} restored to AcceptanceTester queue."
                    )
                else:
                    log_list.append(
                        f"[Level 2 t={t+1:02d}] Warning: could not restore deferred aperiodic {task_id}."
                    )

        # ─────────────────────────────────────────────────────────
        # Step 4: 淨負載計算
        # ─────────────────────────────────────────────────────────
        W_t = sum(job.w for job in active_jobs)
        
        # ─────────────────────────────────────────────────────────
        # Step 5: 綠電優先與套利決策
        # ─────────────────────────────────────────────────────────
        # Level 2: 使用 actual renewable；Level 1: 使用 forecast
        renewable_outputs: Dict[str, float] = {}
        P_ren = 0.0
        if level2_enabled and actual_renewable_outputs:
            for r in renewables:
                out = actual_renewable_outputs.get(r.id, float(r.capacity * r.forecast[t]))
                P_ren += out
                renewable_outputs[r.id] = out
        else:
            for r in renewables:
                out = r.capacity * r.forecast[t]
                P_ren += out
                renewable_outputs[r.id] = float(out)
            
        W_net = max(0.0, W_t - P_ren)
        
        # 1. 取得所有發電機的合法邊界
        gen_bounds_map = {}
        for gen in generators:
            bounds = get_valid_bounds(gen)
            if not bounds:
                raise Exception(f"Generator {gen.id} locked out at t={t}")
            gen_bounds_map[gen.id] = bounds
            
        # 2. 保命為先：建立「最低合法基載」
        gen_targets = {}
        allocated = 0.0
        for gen in generators:
            min_target = gen_bounds_map[gen.id][0]
            gen_targets[gen.id] = min_target
            allocated += min_target
            
        deficit = W_net - allocated
        
        # 3. 補足淨負載
        sorted_gens = sorted(generators, key=lambda g: g.cost_variable)
        if deficit > 0:
            for gen in sorted_gens:
                bounds = gen_bounds_map[gen.id]
                current = gen_targets[gen.id]
                
                if current == 0 and len(bounds) >= 3:
                    lb, ub = bounds[1], bounds[-1]
                    increase = min(deficit, ub)
                    target = max(lb, increase)
                    gen_targets[gen.id] = target
                    deficit -= target
                elif current > 0 and len(bounds) >= 2:
                    ub = bounds[-1]
                    increase = min(deficit, ub - current)
                    gen_targets[gen.id] += increase
                    deficit -= increase
                    
                if deficit <= 0:
                    break
                
        # 4. 高價套利
        for gen in sorted_gens:
            if price_t > gen.cost_variable:
                bounds = gen_bounds_map[gen.id]
                current = gen_targets[gen.id]
                if current > 0 and len(bounds) >= 2:
                    gen_targets[gen.id] = bounds[-1]
                    
        # 5. 電池放電外援
        battery_discharges: Dict[str, float] = {b.id: 0.0 for b in batteries}
        if deficit > 0:
            for bat in batteries:
                if level2_enabled:
                    dis = apply_discharge_with_efficiency(bat, deficit)
                    if dis > 0:
                        level2_metrics.battery_rescue_energy += dis
                        level2_metrics.battery_degradation_cost += compute_battery_degradation_cost(bat, dis)
                else:
                    max_dis = min(
                        float(bat.discharge_max),
                        bat.current_soc - bat.soc_min
                    )
                    dis = min(deficit, max_dis) if max_dis > 0 else 0.0
                if dis > 0:
                    battery_discharges[bat.id] = float(dis)
                    deficit -= dis
                if deficit <= 0:
                    break
                
        if deficit > 0.5:
            # 允許小數誤差，但真正缺電才報錯
            raise Exception(f"Fatal: Cannot satisfy load at t={t}. Deficit: {deficit}")

        # ─────────────────────────────────────────────────────────
        # Step 6: 狀態結算
        # ─────────────────────────────────────────────────────────
        if level2_enabled and level2_decision:
            for gen in generators:
                recommended = float(
                    level2_decision.get("recommended_thermal_rescue", {}).get(gen.id, 0.0)
                )
                if recommended > 0:
                    committed = min(recommended, max(0.0, gen_targets[gen.id] - gen.current_output))
                    level2_metrics.thermal_rescue_energy += committed

        for gen in generators:
            target = gen_targets[gen.id]
            if target > 0:
                if gen.current_output == 0:
                    gen.consecutive_on_time = 1
                else:
                    gen.consecutive_on_time += 1
                gen.consecutive_off_time = 0
            else:
                if gen.current_output > 0:
                    gen.consecutive_off_time = 1
                else:
                    gen.consecutive_off_time += 1
                gen.consecutive_on_time = 0
            gen.current_output = target
            
        for bat in batteries:
            dis = battery_discharges[bat.id]
            if not level2_enabled:
                bat.current_soc = max(bat.soc_min, bat.current_soc - dis)
                bat.total_discharged_energy += dis

            # Level 2: self-discharge 每小時更新一次
            if level2_enabled:
                apply_self_discharge(bat)

        if level2_enabled:
            remaining_supply = (
                P_ren
                + sum(float(gen.current_output) for gen in generators)
                + sum(battery_discharges.values())
                - W_t
            )
            for bat in batteries:
                if remaining_supply <= 0.01:
                    break
                charged_input = apply_charge_with_efficiency(bat, remaining_supply)
                if charged_input > 0.01:
                    active_jobs.append(ActiveJob(id=f"{bat.id}_chg", w=charged_input))
                    remaining_supply -= charged_input
                    log_list.append(
                        f"[Level 2 t={t+1:02d}] Battery charge committed: "
                        f"{bat.id} input={charged_input:.2f}MWh, SOC={bat.current_soc:.2f}"
                    )
            
        # ─────────────────────────────────────────────────────────
        # Step 7: 能量流溯源
        # ─────────────────────────────────────────────────────────
        k_matrix, total_sell = trace_power_flows(
            active_jobs=active_jobs,
            generators=generators,
            battery_discharges=battery_discharges,
            renewable_outputs=renewable_outputs
        )
        
        # ─────────────────────────────────────────────────────────
        # Step 8 (Level 2 only): Market commitment check
        # ─────────────────────────────────────────────────────────
        if level2_enabled and actual_renewable_profile is not None:
            commit_t = (day_ahead_sell_commitment[t]
                        if day_ahead_sell_commitment is not None
                        else 0.0)
            compute_market_metrics(
                t=t,
                actual_sell=total_sell,
                day_ahead_commitment=commit_t,
                price_t=price_t,
                penalty_rate=penalty_rate,
                realtime_price_multiplier=realtime_price_mult,
                log_list=log_list,
                level2_metrics=level2_metrics,
            )
        
        # ─────────────────────────────────────────────────────────
        # Step 9: 紀錄快照
        # ─────────────────────────────────────────────────────────
        P_dict: Dict[str, float] = {}
        for r_id, out in renewable_outputs.items():
            if out > 0:
                P_dict[r_id] = out
        for gen in generators:
            if gen.current_output > 0:
                P_dict[gen.id] = float(gen.current_output)
        for b_id, dis in battery_discharges.items():
            if dis > 0:
                P_dict[b_id] = dis
                
        soc_dict = {b.id: float(b.current_soc) for b in batteries}
        
        record = TickRecord(
            t=t,
            P=P_dict,
            k=k_matrix,
            sell=total_sell,
            soc=soc_dict,
            missed_aperiodic=missed_aperiodic,
            rejected_sporadic=rejected_sporadic
        )
        trajectory.append(record)

    # ─────────────────────────────────────────────────────────
    # 最終：Level 2 Summary 寫入 log
    # ─────────────────────────────────────────────────────────
    if level2_enabled:
        trajectory.level2_metrics = level2_metrics.to_dict()
        log_list.append(f"[Level 2 Summary] {trajectory.level2_metrics}")

    return trajectory
