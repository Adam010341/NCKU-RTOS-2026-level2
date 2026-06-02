import json
from typing import List, Tuple, Dict, Any
from src.scheduler.models import (
    ThermalGenerator, RenewableGenerator, Battery,
    PeriodicTask, SporadicTask, AperiodicTask
)

def load_price(filepath: str) -> List[float]:
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)
    # 確保按小時排序，取前 72 小時
    prices = sorted(data['price'], key=lambda x: x['hour'])
    return [float(p['market_price']) for p in prices[:72]]

def load_processor_settings(
    filepath: str,
) -> Tuple[List[ThermalGenerator], List[RenewableGenerator], List[Battery]]:
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)
        
    # 1. 載入火力機組
    generators = []
    for g in data.get('generator', []):
        generators.append(ThermalGenerator(
            id=g['generator_id'],
            output_min=g['output_min'],
            output_max=g['output_max'],
            ramp_up_rate=g['ramp_up_rate'],
            ramp_down_rate=g['ramp_down_rate'],
            min_up_time=g['min_up_time'],
            min_down_time=g['min_down_time'],
            cost_fixed=g['cost_fixed'],
            cost_variable=g['cost_variable'],
            initial_on_time=g['initial_on_time'],
            initial_off_time=g['initial_off_time'],
            initial_energy=g['initial_energy']
        ))
        
    # 2. 載入再生能源 (需合併 capacity 與 forecast)
    renewables = []
    forecast_map = {}
    for item in data.get('renewable_forecast', []):
        for pv_id, forecasts in item.items():
            # 確保照 hour 排序
            sorted_fc = sorted(forecasts, key=lambda x: x['hour'])
            forecast_map[pv_id] = [f['pv_forecast'] for f in sorted_fc]
            
    for r in data.get('renewable_capacity', []):
        r_id = r['renewable_id']
        cap = r['capacity']
        fc = forecast_map.get(r_id, [0.0]*72)
        renewables.append(RenewableGenerator(id=r_id, capacity=cap, forecast=fc))
        
    # 3. 載入儲能設備（Level 2 欄位有預設值，向後相容）
    batteries = []
    for b in data.get('storage', []):
        batteries.append(Battery(
            id=b['storage_id'],
            soc_min=b['soc_min'],
            soc_max=b['soc_max'],
            discharge_max=b['discharge_max'],
            charge_max=b['charge_max'],
            soc_init=b['soc_init'],
            # Level 2 欄位：若 JSON 沒提供則使用 Battery dataclass 預設值
            charge_efficiency=float(b.get('charge_efficiency', 0.95)),
            discharge_efficiency=float(b.get('discharge_efficiency', 0.95)),
            self_discharge_rate=float(b.get('self_discharge_rate', 0.001)),
            degradation_cost_per_mwh=float(b.get('degradation_cost_per_mwh', 1.0)),
            cycle_limit=int(b.get('cycle_limit', 999999)),
        ))
        
    return generators, renewables, batteries


def load_level2_market_settings(filepath: str) -> Dict[str, Any]:
    """
    從 processor_settings.json 讀取 Level 2 市場設定。
    若 JSON 沒有 level2_market 欄位，回傳安全預設值。
    """
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)
    defaults = {
        "penalty_rate": 2.0,
        "realtime_price_multiplier": 1.1,
        "commitment_ratio": 0.8,
    }
    market = data.get('level2_market', {})
    defaults.update(market)
    return defaults


def load_periodic_tasks(filepath: str) -> List[PeriodicTask]:
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)
    tasks = []
    for t_id, t in data.get('periodic', {}).items():
        tasks.append(PeriodicTask(
            id=t_id, r=t['r'] - 1, p=t['p'], e=t['e'], d=t['d'], w=t['w'], preempt=t['preempt']
        ))
    return tasks

def load_online_tasks(filepath: str) -> Tuple[Dict[int, List[SporadicTask]], Dict[int, List[AperiodicTask]]]:
    """
    載入動態突發任務，並以 release_time (r) 作為 Key 進行分組。
    預期 JSON 格式包含 "sporadic" 與 "aperiodic" 陣列。
    """
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)
        
    sporadic_dict = {}
    aperiodic_dict = {}
    
    for st in data.get('sporadic', []):
        task = SporadicTask(id=st['id'], r=st['r'], e=st['e'], w=st['w'], preempt=st['preempt'], d=st['d'])
        sporadic_dict.setdefault(task.r, []).append(task)
        
    for at in data.get('aperiodic', []):
        d_val = at.get('d', None) # aperiodic 可能沒有相對 d
        task = AperiodicTask(id=at['id'], r=at['r'], e=at['e'], w=at['w'], preempt=at['preempt'], d=d_val)
        aperiodic_dict.setdefault(task.r, []).append(task)
        
    return sporadic_dict, aperiodic_dict