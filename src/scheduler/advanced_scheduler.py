"""
advanced_scheduler.py — Level 2 Advanced Dynamic Rescheduler

Level 2 三大放寬 Assumptions：
  1. 再生能源不確定性 (Renewable Uncertainty)
  2. 儲能設備真實運作情境 (Realistic Battery Model)
  3. 彈性市場機制 (Flexible Market Mechanism)

Job ID 命名規則：
    - Aperiodic : 以 "a_" 開頭，例如 a_1_03
    - Sporadic  : 以 "s_" 開頭，例如 s_1_03
    - Periodic  : 其餘（例如 p1、p2）
"""

import random
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any


# ══════════════════════════════════════════════════════════════
# 1. Level 2 指標累積器
# ══════════════════════════════════════════════════════════════

@dataclass
class Level2Metrics:
    """記錄 Level 2 Advanced Dynamic Rescheduling 的全部彙整指標。"""

    forecast_error_ratio: float = 0.0

    # 動態重排程觸發次數
    advanced_reschedule_count: int = 0

    # ── 再生能源不確定性 ──
    renewable_shortfall_events: int = 0      # 實際低於預測的次數
    renewable_surplus_events: int = 0        # 實際高於預測的次數
    total_forecast_renewable: float = 0.0   # 預測再生能源總量 (MWh)
    total_actual_renewable: float = 0.0     # 實際再生能源總量 (MWh)
    total_renewable_shortfall: float = 0.0  # 缺口總量 (MWh)
    total_renewable_surplus: float = 0.0    # 盈餘總量 (MWh)

    # ── 補救措施 ──
    battery_rescue_energy: float = 0.0      # 電池補救能量 (MWh)
    thermal_rescue_energy: float = 0.0      # 火力升載補救能量 (MWh)

    # ── Aperiodic defer ──
    deferred_aperiodic_jobs: int = 0
    total_deferred_aperiodic_energy: float = 0.0
    protected_hard_jobs: int = 0

    # ── 電池真實模型 ──
    battery_degradation_cost: float = 0.0

    # ── 市場機制 ──
    market_commitment_shortfall: float = 0.0
    market_penalty: float = 0.0
    realtime_extra_revenue: float = 0.0

    # ── 事件日誌 ──
    level2_event_log: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "advanced_reschedule_count": self.advanced_reschedule_count,
            "forecast_error_ratio": round(self.forecast_error_ratio, 3),
            "renewable_shortfall_events": self.renewable_shortfall_events,
            "renewable_surplus_events": self.renewable_surplus_events,
            "total_forecast_renewable": round(self.total_forecast_renewable, 3),
            "total_actual_renewable": round(self.total_actual_renewable, 3),
            "total_renewable_shortfall": round(self.total_renewable_shortfall, 3),
            "total_renewable_surplus": round(self.total_renewable_surplus, 3),
            "battery_rescue_energy": round(self.battery_rescue_energy, 3),
            "thermal_rescue_energy": round(self.thermal_rescue_energy, 3),
            "deferred_aperiodic_jobs": self.deferred_aperiodic_jobs,
            "total_deferred_aperiodic_energy": round(self.total_deferred_aperiodic_energy, 3),
            "protected_hard_jobs": self.protected_hard_jobs,
            "battery_degradation_cost": round(self.battery_degradation_cost, 3),
            "market_commitment_shortfall": round(self.market_commitment_shortfall, 3),
            "market_penalty": round(self.market_penalty, 3),
            "realtime_extra_revenue": round(self.realtime_extra_revenue, 3),
            "level2_event_log": self.level2_event_log,
        }


# ══════════════════════════════════════════════════════════════
# 2. Job 類型判斷函式
# ══════════════════════════════════════════════════════════════

def is_aperiodic_job(job_id: str) -> bool:
    """Aperiodic job id 以 'a_' 開頭。"""
    return job_id.startswith("a_")


def is_sporadic_job(job_id: str) -> bool:
    """Sporadic job id 以 's_' 開頭。"""
    return job_id.startswith("s_")


# ══════════════════════════════════════════════════════════════
# 3. 再生能源不確定性模型
# ══════════════════════════════════════════════════════════════

class RenewableUncertaintyModel:
    """
    根據 forecast 產生帶有誤差的 actual renewable output profile。

    Constraint C1:
        R_act_{r,t} = capacity_r × actual_ratio_{r,t}
    Constraint C2:
        actual_ratio_{r,t} = forecast_ratio_{r,t} × (1 + ε_{r,t})
    Constraint C3:
        |ε_{r,t}| ≤ ρ   (forecast_error_ratio)
    Constraint C4:
        0 ≤ actual_ratio_{r,t} ≤ 1
    """

    def __init__(
        self,
        renewables: list,
        seed: int = 2026,
        forecast_error_ratio: float = 0.2,
    ):
        self.renewables = renewables
        self.forecast_error_ratio = forecast_error_ratio
        rng = random.Random(seed)

        # actual_ratios[r_id][t] = actual output ratio at hour t
        self.actual_ratios: Dict[str, List[float]] = {}
        for r in renewables:
            ratios = []
            for t in range(72):
                fc = r.forecast[t]
                if fc <= 0.0:
                    ratios.append(0.0)
                else:
                    eps = rng.uniform(-forecast_error_ratio, forecast_error_ratio)
                    actual = fc * (1.0 + eps)
                    actual = max(0.0, min(1.0, actual))   # C4
                    ratios.append(actual)
            self.actual_ratios[r.id] = ratios

    def get_forecast_output(self, r_id: str, t: int) -> float:
        for r in self.renewables:
            if r.id == r_id:
                return float(r.capacity * r.forecast[t])
        return 0.0

    def get_actual_output(self, r_id: str, t: int) -> float:
        for r in self.renewables:
            if r.id == r_id:
                return float(r.capacity * self.actual_ratios[r.id][t])
        return 0.0

    def total_forecast(self, t: int) -> float:
        return sum(r.capacity * r.forecast[t] for r in self.renewables)

    def total_actual(self, t: int) -> float:
        return sum(
            r.capacity * self.actual_ratios[r.id][t]
            for r in self.renewables
        )

    def actual_outputs_dict(self, t: int) -> Dict[str, float]:
        """回傳 {r_id: actual_MWh} 供 power tracer 使用。"""
        return {
            r.id: float(r.capacity * self.actual_ratios[r.id][t])
            for r in self.renewables
        }


# ══════════════════════════════════════════════════════════════
# 4. 電池真實模型 Helper Functions
# ══════════════════════════════════════════════════════════════

def effective_discharge_limit(battery) -> float:
    """
    SOC-dependent discharge limit (Constraint C9)：
    若 SOC 接近 soc_min，可放電量線性縮減至 0。
    回傳：基於 C9 的最大『提供給負載之電量』上限。
    """
    soc_range = battery.soc_max - battery.soc_min
    if soc_range <= 0:
        return 0.0
    depth = (battery.current_soc - battery.soc_min) / soc_range
    scale = min(1.0, depth / 0.2)   # 在 20% depth 以下線性縮減
    return float(battery.discharge_max) * scale


def apply_discharge_with_efficiency(battery, requested_energy: float) -> float:
    """
    以 discharge_efficiency 放電 (Constraint C5)：
    為了提供 D MWh 給負載，SOC 減少 D / eta_dis。
    回傳實際提供給負載的 MWh（= requested_energy 若 SOC 足夠）。
    """
    eta_dis = getattr(battery, "discharge_efficiency", 0.95)
    
    # 物理上限1: C9 規定的放電極限 (以提供給負載的電量計)
    c9_limit = effective_discharge_limit(battery)
    
    # 物理上限2: 電池內剩餘 SOC 實際能轉化為負載電量的極限
    soc_limit = (battery.current_soc - battery.soc_min) * eta_dis
    
    max_deliverable = max(0.0, min(c9_limit, soc_limit))
    actual_deliver = min(requested_energy, max_deliverable)
    
    soc_decrease = actual_deliver / eta_dis   # C5
    battery.current_soc -= soc_decrease
    
    # 累積放電量用於 degradation
    battery.total_discharged_energy = (
        getattr(battery, "total_discharged_energy", 0.0) + actual_deliver
    )
    return actual_deliver


def apply_charge_with_efficiency(battery, charge_input: float) -> float:
    """
    以 charge_efficiency 充電 (Constraint C5)：
    輸入 C MWh，SOC 增加 C × eta_chg。
    回傳實際充入 SOC 的 MWh。
    """
    eta_chg = getattr(battery, "charge_efficiency", 0.95)
    max_charge_input = min(
        float(battery.charge_max),
        (battery.soc_max - battery.current_soc) / eta_chg
    )
    actual_input = min(charge_input, max_charge_input)
    soc_increase = actual_input * eta_chg   # C5
    battery.current_soc = min(battery.soc_max, battery.current_soc + soc_increase)
    battery.total_charged_energy = (
        getattr(battery, "total_charged_energy", 0.0) + actual_input
    )
    return actual_input


def apply_self_discharge(battery):
    """
    每小時 self-discharge (Constraint C7)：
    SOC_{b,t+1} = SOC_{b,t} × (1 - σ_b)
    """
    sigma = getattr(battery, "self_discharge_rate", 0.001)
    loss = battery.current_soc * sigma
    battery.current_soc = max(battery.soc_min, battery.current_soc - loss)

def compute_battery_degradation_cost(battery, discharge_energy: float) -> float:
    """
    每 MWh 放電帶來一個 degradation cost (Constraint C8)。
    """
    cost_per_mwh = getattr(battery, "degradation_cost_per_mwh", 1.0)
    return discharge_energy * cost_per_mwh


# ══════════════════════════════════════════════════════════════
# 5. Advanced Reschedule 核心函式
# ══════════════════════════════════════════════════════════════

def advanced_reschedule(
    t: int,
    active_jobs: list,
    generators: list,
    batteries: list,
    renewables: list,
    actual_renewable_profile: "RenewableUncertaintyModel",
    price_t: float,
    day_ahead_sell_commitment: float,
    log_list: list,
    level2_metrics: "Level2Metrics",
    reserve_margin: float = 0.1,
    penalty_rate: float = 2.0,
    realtime_price_multiplier: float = 1.1,
):
    """
    Level 2 Advanced Dynamic Rescheduling。
    """
    dt = t + 1   # 1-based display time

    # ── Step 1：計算需求 ──
    total_load = sum(job.w for job in active_jobs)

    # ── Step 2：計算 forecast vs actual renewable ──
    forecast_ren = actual_renewable_profile.total_forecast(t)
    actual_ren   = actual_renewable_profile.total_actual(t)
    actual_ren_dict = actual_renewable_profile.actual_outputs_dict(t)

    level2_metrics.total_forecast_renewable += forecast_ren
    level2_metrics.total_actual_renewable   += actual_ren

    renewable_gap = forecast_ren - actual_ren   # >0 = shortfall, <0 = surplus

    new_active_jobs = list(active_jobs)
    deferred_aperiodic_ids = []
    level2_decision = {
        "renewable_forecast": float(forecast_ren),
        "renewable_actual": float(actual_ren),
        "renewable_shortfall": float(max(0.0, renewable_gap)),
        "renewable_surplus": float(max(0.0, -renewable_gap)),
        "recommended_battery_rescue": {},
        "recommended_thermal_rescue": {},
        "deferred_aperiodic_ids": [],
        "actual_renewable_outputs": actual_ren_dict,
    }

    # ── Step 3：分類 shortfall / surplus ──
    if renewable_gap > 0.01:
        level2_metrics.renewable_shortfall_events += 1
        level2_metrics.total_renewable_shortfall  += renewable_gap
        level2_metrics.advanced_reschedule_count  += 1

        event_msg = (
            f"[時間 t={dt:02d}] Level 2 renewable shortfall: "
            f"forecast={forecast_ren:.2f}, actual={actual_ren:.2f}, deficit={renewable_gap:.2f}MWh"
        )
        log_list.append(event_msg)
        level2_metrics.level2_event_log.append(event_msg)

        # ── Step 4A：估計電池可補救量（advisory log only）──
        remaining_shortfall = renewable_gap
        for bat in batteries:
            if remaining_shortfall <= 0.01:
                break
            eta = getattr(bat, "discharge_efficiency", 0.95)
            c9_limit = effective_discharge_limit(bat)
            soc_limit = (bat.current_soc - bat.soc_min) * eta
            can_deliver = max(0.0, min(c9_limit, soc_limit))
            
            rescue = min(remaining_shortfall, can_deliver)
            if rescue > 0.01:
                remaining_shortfall -= rescue
                level2_decision["recommended_battery_rescue"][bat.id] = float(rescue)
                bat_msg = (
                    f"[時間 t={dt:02d}] Level 2 battery rescue (advisory): "
                    f"{bat.id} can supply up to {rescue:.2f}MWh"
                )
                log_list.append(bat_msg)
                level2_metrics.level2_event_log.append(bat_msg)

        # ── Step 4B：估計火力可補救量（advisory log only）──
        if remaining_shortfall > 0.01:
            from src.scheduler.offline_planner import get_valid_bounds
            for gen in sorted(generators, key=lambda g: g.cost_variable):
                if remaining_shortfall <= 0.01:
                    break
                bounds = get_valid_bounds(gen)
                if len(bounds) >= 2:
                    headroom = bounds[-1] - gen.current_output
                    ramp_up = min(remaining_shortfall, headroom)
                    if ramp_up > 0:
                        remaining_shortfall -= ramp_up
                        level2_decision["recommended_thermal_rescue"][gen.id] = float(ramp_up)
                        th_msg = (
                            f"[時間 t={dt:02d}] Level 2 thermal rescue (advisory): "
                            f"{gen.id} headroom {ramp_up:.2f}MWh"
                        )
                        log_list.append(th_msg)
                        level2_metrics.level2_event_log.append(th_msg)

        # ── Step 4C：若仍有缺口，延後 aperiodic jobs ──
        if remaining_shortfall > 0.01:
            aperiodic_in_active = [j for j in new_active_jobs if is_aperiodic_job(j.id)]
            for job in aperiodic_in_active:
                if remaining_shortfall <= 0.01:
                    break
                new_active_jobs.remove(job)
                level2_metrics.deferred_aperiodic_jobs        += 1
                level2_metrics.total_deferred_aperiodic_energy += job.w
                level2_decision["deferred_aperiodic_ids"].append(job.id)
                deferred_aperiodic_ids.append(job.id)
                remaining_shortfall -= job.w
                defer_msg = (
                    f"[時間 t={dt:02d}] Level 2 defer aperiodic job {job.id}, "
                    f"energy={job.w}MWh (restore through AcceptanceTester queue)"
                )
                log_list.append(defer_msg)
                level2_metrics.level2_event_log.append(defer_msg)

        # ── Step 4D：統計保護的 hard-deadline jobs ──
        protected = sum(1 for j in new_active_jobs if not is_aperiodic_job(j.id))
        level2_metrics.protected_hard_jobs += protected

    elif renewable_gap < -0.01:
        # ── Step 5：renewable surplus ──
        surplus = abs(renewable_gap)
        level2_metrics.renewable_surplus_events += 1
        level2_metrics.total_renewable_surplus  += surplus

        surplus_msg = (
            f"[時間 t={dt:02d}] Level 2 renewable surplus: "
            f"forecast={forecast_ren:.2f}, actual={actual_ren:.2f}, surplus={surplus:.2f}MWh"
        )
        log_list.append(surplus_msg)
        level2_metrics.level2_event_log.append(surplus_msg)
        # 5A：估計充電容量（advisory）
        remaining_surplus = surplus
        for bat in batteries:
            if remaining_surplus <= 0.01:
                break
            eta_chg = getattr(bat, "charge_efficiency", 0.95)
            max_chg_input = min(
                float(bat.charge_max),
                (bat.soc_max - bat.current_soc) / eta_chg if eta_chg > 0 else 0
            )
            charged = min(remaining_surplus, max_chg_input)
            if charged > 0.01:
                remaining_surplus -= charged
                chg_msg = (
                    f"[時間 t={dt:02d}] Level 2 battery charge: {bat.id} "
                    f"charged {charged:.2f}MWh → SOC={bat.current_soc:.1f}"
                )
                log_list.append(chg_msg)
                level2_metrics.level2_event_log.append(chg_msg)

        new_active_jobs = list(active_jobs)

    else:
        new_active_jobs = list(active_jobs)

    # ── Step 6：Market commitment ──
    # day_ahead_sell_commitment 是當前小時的承諾售電量
    # 實際 sell 量未知（由 power tracer 計算），此處先記錄 commitment
    # 市場罰款在 main_scheduler 取得 actual_sell 後計算

    return new_active_jobs, deferred_aperiodic_ids, actual_ren_dict, level2_decision


def compute_market_metrics(
    t: int,
    actual_sell: float,
    day_ahead_commitment: float,
    price_t: float,
    penalty_rate: float,
    realtime_price_multiplier: float,
    log_list: list,
    level2_metrics: "Level2Metrics",
):
    """
    Step 6 (post power-tracing)：
    用真實 sell 量計算市場罰款 / 額外收益。
    """
    dt = t + 1
    shortfall = max(0.0, day_ahead_commitment - actual_sell)
    if shortfall > 0.01:
        penalty = shortfall * penalty_rate
        level2_metrics.market_commitment_shortfall += shortfall
        level2_metrics.market_penalty              += penalty
        pen_msg = (
            f"[時間 t={dt:02d}] Level 2 market penalty: "
            f"commitment={day_ahead_commitment:.2f}, actual_sell={actual_sell:.2f}, "
            f"shortfall={shortfall:.2f}MWh, penalty={penalty:.2f}"
        )
        log_list.append(pen_msg)
        level2_metrics.level2_event_log.append(pen_msg)

    surplus_sell = max(0.0, actual_sell - day_ahead_commitment)
    if surplus_sell > 0.01:
        extra = surplus_sell * price_t * (realtime_price_multiplier - 1.0)
        level2_metrics.realtime_extra_revenue += extra
        ext_msg = (
            f"[時間 t={dt:02d}] Level 2 realtime extra revenue (sell surplus): "
            f"{surplus_sell:.2f}MWh × {price_t:.2f} × factor = {extra:.2f}"
        )
        log_list.append(ext_msg)
        level2_metrics.level2_event_log.append(ext_msg)
