from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Tuple

@dataclass
class TickRecord:
    """記錄單一小時 (t) 系統內所有能量流向與任務狀態的快照"""
    t: int
    
    # 每台發電設備 (火力、太陽能、電池放電) 在該時間點的總供電量 (MWh)
    # 格式: {"thermal_1": 25.0, "pv_1": 5.0, "battery_1": 5.0}
    P: Dict[str, float] = field(default_factory=dict)
    
    # 每個任務 (包含充電) 從各設備獲得的電量分配 (MWh)
    # 格式: {"p1": {"thermal_1": 10.0, "pv_1": 5.0}, "battery_1_chg": {"thermal_1": 0.0}}
    k: Dict[str, Dict[str, float]] = field(default_factory=dict)
    
    # 售電量 (MWh)
    sell: float = 0.0
    
    # 儲能設備在該時間點結束後的剩餘電量 (MWh)
    # 格式: {"battery_1": 45.0}
    soc: Dict[str, float] = field(default_factory=dict)
    
    # 逾期的 Aperiodic tasks (Soft deadline miss)
    missed_aperiodic: List[str] = field(default_factory=list)
    
    # 被拒絕的 Sporadic tasks (Acceptance test 未通過)
    rejected_sporadic: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """一鍵轉換為符合評分標準的 JSON，並處理浮點數與時間平移"""
        return {
            # 將 Python 內部的 t=0~71，平移為報表上人類與 evaluator 預期的 t=1~72
            "t": self.t + 1,
            
            # 移除強制四捨五入以保留精確度，避免 Evaluator 判定失敗
            "P": {id_: val for id_, val in self.P.items()},
            
            # 移除 2D 的 k 矩陣裡面的四捨五入
            "k": {j_id: {dev_id: v for dev_id, v in dev_map.items()} 
                  for j_id, dev_map in self.k.items()},
            
            # 售電量保留精確度
            "sell": self.sell,
            
            # SOC 保留精確度
            "soc": {id_: val for id_, val in self.soc.items()},
            
            "missed_aperiodic": self.missed_aperiodic,
            "rejected_sporadic": self.rejected_sporadic
        }

# ==========================================
# 1. 發電與儲能設備模型 (Power System Models)
# ==========================================

@dataclass
class ThermalGenerator:
    """傳統發電機組模型"""
    id: str
    output_min: int
    output_max: int
    ramp_up_rate: int
    ramp_down_rate: int
    min_up_time: int
    min_down_time: int
    cost_fixed: int
    cost_variable: int
    initial_on_time: int
    initial_off_time: int
    initial_energy: int
    
    # 運行時動態狀態 (Runtime States)
    current_output: int = field(init=False)
    consecutive_on_time: int = field(init=False)
    consecutive_off_time: int = field(init=False)

    def __post_init__(self):
        """物件建立後，自動將歷史狀態載入運行時變數"""
        self.current_output = self.initial_energy
        self.consecutive_on_time = self.initial_on_time
        self.consecutive_off_time = self.initial_off_time

@dataclass
class RenewableGenerator:
    """再生能源機組模型"""
    id: str
    capacity: int
    forecast: List[float]  # 長度為 72 的陣列，儲存每小時預測百分比

@dataclass
class Battery:
    """儲能設備模型（Level 2 新增效率與老化欄位）"""
    id: str
    soc_min: int
    soc_max: int
    discharge_max: int
    charge_max: int
    soc_init: int

    # ── Level 2 新增欄位（有預設值，向後相容舊 JSON）──
    charge_efficiency: float = 0.95
    discharge_efficiency: float = 0.95
    self_discharge_rate: float = 0.001
    degradation_cost_per_mwh: float = 1.0
    cycle_limit: int = 999999

    # 運行時動態狀態
    current_soc: float = field(init=False)
    total_charged_energy: float = field(init=False)
    total_discharged_energy: float = field(init=False)
    cycle_used: float = field(init=False)

    def __post_init__(self):
        self.current_soc = float(self.soc_init)
        self.total_charged_energy = 0.0
        self.total_discharged_energy = 0.0
        self.cycle_used = 0.0

# ==========================================
# 2. 用電需求任務模型 (Task Models)
# ==========================================

@dataclass
class BaseTask:
    """所有任務的基礎共用模型"""
    id: str
    r: int        # release time (最早可開始時間)
    e: int        # execution time (所需執行總時間段)
    w: int        # energy demand (每小時需消耗的固定電能量)
    preempt: int  # 1 = preemptable, 0 = non-preemptable
    
    # 運行時動態狀態
    remaining_execution: int = field(init=False)
    is_completed: bool = field(default=False, init=False)

    def __post_init__(self):
        self.remaining_execution = self.e

@dataclass
class PeriodicTask(BaseTask):
    """週期性用電需求 (Hard Deadline)"""
    p: int        # period (執行週期)
    d: int        # relative deadline

@dataclass
class SporadicTask(BaseTask):
    """零星用電需求 (Hard Deadline)"""
    d: int        # relative deadline

@dataclass
class AperiodicTask(BaseTask):
    """非週期性用電需求 (Soft Deadline)"""
    # Aperiodic task 在附錄中可能不強制給定 relative deadline，
    # 若有給定則用於計算 tardiness，預設為 None。
    d: Optional[int] = None