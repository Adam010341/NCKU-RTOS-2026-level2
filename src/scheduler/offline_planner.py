import copy
import itertools
from typing import List, Dict, Tuple
from src.scheduler.models import PeriodicTask, ThermalGenerator, Battery, RenewableGenerator
from src.scheduler.state_machine import validate_thermal_transition, validate_battery_transition

class Job:
    def __init__(self, task_id: str, job_id: str, r: int, d: int, e: int, w: int, preempt: int):
        self.task_id = task_id
        self.job_id = job_id
        self.r = r
        self.d = d
        self.e = e
        self.w = w
        self.preempt = preempt
        self.remaining_e = e

def expand_jobs(tasks: List[PeriodicTask]) -> List[Job]:
    jobs = []
    for t in tasks:
        k = 0
        while True:
            r_abs = t.r + k * t.p
            if r_abs >= 72:
                break
            d_abs = r_abs + t.d
            jobs.append(Job(t.id, f"{t.id}_{k}", r_abs, d_abs, t.e, t.w, t.preempt))
            k += 1
    return jobs

def get_valid_targets(gen: ThermalGenerator) -> List[int]:
    """Find all valid target outputs for the generator at this exact state."""
    valid = []
    try:
        validate_thermal_transition(gen, 0)
        valid.append(0)
    except Exception:
        pass
        
    min_test = gen.output_min
    max_test = gen.output_max
    if gen.current_output > 0:
        min_test = max(min_test, gen.current_output - gen.ramp_down_rate)
        max_test = min(max_test, gen.current_output + gen.ramp_up_rate)
    else:
        max_test = min(max_test, gen.ramp_up_rate)
        
    if min_test <= max_test:
        for target in range(min_test, max_test + 1):
            try:
                validate_thermal_transition(gen, target)
                valid.append(target)
            except Exception:
                pass
                
    return valid

def get_valid_bounds(gen: ThermalGenerator) -> List[int]:
    """O(1) 計算合法出力邊界，回傳格式為 [0 (若可關機)] + [合法下限, 合法上限]"""
    bounds = []
    
    # 測試是否能關機
    try:
        validate_thermal_transition(gen, 0)
        bounds.append(0)
    except Exception:
        pass
        
    # 計算連續出力的上下界
    lb = gen.output_min
    ub = gen.output_max
    if gen.current_output > 0:
        lb = max(lb, gen.current_output - gen.ramp_down_rate)
        ub = min(ub, gen.current_output + gen.ramp_up_rate)
    else:
        ub = min(ub, gen.ramp_up_rate)
        
    if lb <= ub:
        # 只需用 LB 測試啟停時間限制。只要 LB 合法，[LB, UB] 整段都必然合法
        try:
            validate_thermal_transition(gen, lb)
            bounds.extend([lb, ub])
        except Exception:
            pass
            
    return bounds

def allocate_power(demand: int, generators: List[ThermalGenerator], batteries: List[Battery], renewables: List[RenewableGenerator], t_abs: int) -> Tuple[bool, int]:
    
    # 0. 【新增】優先全額吸收再生能源 (Must-take 綠電)
    renewable_power = 0
    for ren in renewables:
        # forecast 是百分比，乘上 capacity 並取整數
        out = int(ren.capacity * ren.forecast[t_abs])
        renewable_power += out
        
    # 扣除綠電後，剩下的才是火力與電池必須扛下的「淨負載 (Net Load)」
    demand = max(0, demand - renewable_power)
    
    gen_targets = {}
    allocated = 0
    gen_bounds_map = {}
    
    # 1. 初始化基載 (取最低合法出力)
    for gen in generators:
        bounds = get_valid_bounds(gen)
        if not bounds:
            return False, 0
            
        gen_bounds_map[gen.id] = bounds
        min_target = bounds[0] # 可能為 0 或 LB
        if len(bounds) > 1 and min_target == 0 and demand > 0:
             # 如果缺電，且機組可以開機(LB)，優先評估以 LB 啟動以滿足需求 (貪婪起點)
             # 若不缺電，則維持 0
             pass 
             
        gen_targets[gen.id] = min_target
        allocated += min_target
        
    needed = demand - allocated
    
    # 2. 貪婪提昇火力 (直接用數學極值，消滅 for-loop)
    if needed > 0:
        for gen in generators:
            bounds = gen_bounds_map[gen.id]
            current_target = gen_targets[gen.id]
            
            # 如果目前是 0，且有 [LB, UB] 區間可以跳轉
            if current_target == 0 and len(bounds) >= 3:
                lb, ub = bounds[1], bounds[2]
                increase = min(needed, ub)
                # 必須卡在 LB 的下限
                final_target = max(lb, increase)
                gen_targets[gen.id] = final_target
                allocated += (final_target - current_target)
                needed -= (final_target - current_target)
            
            # 如果目前已經在 [LB, UB] 區間內
            elif len(bounds) >= 2 and current_target >= bounds[-2]:
                ub = bounds[-1]
                max_increase = ub - current_target
                if max_increase > 0:
                    increase = min(needed, max_increase)
                    gen_targets[gen.id] += increase
                    allocated += increase
                    needed -= increase
                    
            if needed <= 0:
                break

    # --- 3. 電池與 4. 狀態更新 (維持原 Agent 邏輯，但請移除不必要的迴圈) ---
    # ... (接續原本電池分配邏輯)

    # 3. Use batteries if thermal is insufficient
    bat_targets = {}
    if needed > 0:
        for bat in batteries:
            max_discharge = min(bat.discharge_max, bat.current_soc - bat.soc_min)
            if max_discharge > 0:
                discharge = min(needed, max_discharge)
                bat_targets[bat.id] = discharge
                allocated += discharge
                needed -= discharge
            if needed <= 0:
                break
                
    if needed > 0:
        return False, 0
        
    # 4. Commit State & Compute Slack
    thermal_slack = 0
    for gen in generators:
        target = gen_targets[gen.id]
        if target > 0:
            if gen.current_output > 0:
                gen.consecutive_on_time += 1
            else:
                gen.consecutive_on_time = 1
                gen.consecutive_off_time = 0
        else:
            if gen.current_output == 0:
                gen.consecutive_off_time += 1
            else:
                gen.consecutive_off_time = 1
                gen.consecutive_on_time = 0
        gen.current_output = target
        
        max_val = gen_bounds_map[gen.id][-1]
        thermal_slack += (max_val - target)
        
    battery_slack = 0
    for bat in batteries:
        discharge = bat_targets.get(bat.id, 0)
        max_discharge = min(bat.discharge_max, bat.current_soc - bat.soc_min)
        battery_slack += (max_discharge - discharge)
        
        bat.current_soc -= discharge
        
    return True, thermal_slack + battery_slack

def get_valid_job_patterns(job: Job, frame_start: int) -> List[Tuple[int, ...]]:
    patterns = []
    
    if job.preempt == 0:
        if job.e == 1:
            candidates = [(0,), (1,), (2,), ()]
        elif job.e == 2:
            candidates = [(0, 1), (1, 2), ()]
        elif job.e == 3:
            candidates = [(0, 1, 2), ()]
        else:
            candidates = [()]
    else:
        candidates = [()]
        for length in range(1, min(3, job.remaining_e) + 1):
            candidates.extend(itertools.combinations((0, 1, 2), length))
            
    for pat in candidates:
        valid = True
        for h in pat:
            t = frame_start + h
            if not (job.r <= t < job.d):
                valid = False
                break
        if not valid:
            continue
            
        c = len(pat)
        max_future_hours = max(0, job.d - (frame_start + 3))
        if job.remaining_e - c > max_future_hours:
            continue
            
        if job.preempt == 0 and c > 0:
            if c != job.remaining_e:
                continue
                
        patterns.append(pat)
        
    return patterns

def generate_frame_assignments(active_jobs: List[Job], frame_start: int):
    job_patterns = []
    for job in active_jobs:
        pats = get_valid_job_patterns(job, frame_start)
        if not pats:
            return
        job_patterns.append(pats)
        
    def backtrack(idx, s0, s1, s2):
        if idx == len(active_jobs):
            yield (s0, s1, s2)
            return
            
        job = active_jobs[idx]
        for pat in job_patterns[idx]:
            n_s0 = s0 + [job] if 0 in pat else s0
            n_s1 = s1 + [job] if 1 in pat else s1
            n_s2 = s2 + [job] if 2 in pat else s2
            yield from backtrack(idx + 1, n_s0, n_s1, n_s2)
            
    yield from backtrack(0, [], [], [])

def dfs_frame(k: int, jobs: List[Job], generators: List[ThermalGenerator], batteries: List[Battery], renewables: List[RenewableGenerator], current_schedule: Dict[str, List[int]], slack_capacity: List[int]) -> Tuple[bool, Dict[str, List[int]], List[int]]:
    if k == 24:
        return True, current_schedule, slack_capacity
        
    t_start = k * 3
    
    active_jobs = [j for j in jobs if j.remaining_e > 0 and j.r < t_start + 3 and j.d > t_start]
    max_sys_power = sum(g.output_max for g in generators) + sum(b.discharge_max for b in batteries)
    
    for S0, S1, S2 in generate_frame_assignments(active_jobs, t_start):
        W0 = sum(j.w for j in S0)
        W1 = sum(j.w for j in S1)
        W2 = sum(j.w for j in S2)
        
        if W0 > max_sys_power or W1 > max_sys_power or W2 > max_sys_power:
            continue
            
        # --- 建立極速快照 ---
        snapshot_gens = [(g.current_output, g.consecutive_on_time, g.consecutive_off_time) for g in generators]
        snapshot_bats = [b.current_soc for b in batteries]
        
        success = True
        frame_slacks = []
        
        # 1. 嘗試連續分配 3 個小時的算力 (直接修改原始物件)
        for t_offset, W_t in enumerate([W0, W1, W2]):
            t_abs = t_start + t_offset
            # 【修改】傳入 renewables 與 t_abs
            ok, slack = allocate_power(W_t, generators, batteries, renewables, t_abs)
            if not ok:
                success = False
                break
            frame_slacks.append(slack)
            
        # 2. 如果這 3 小時物理驗證都通過，推進 Job 狀態並往下遞迴
        if success:
            jobs_copy = copy.deepcopy(jobs) # jobs 陣列很小，這裡 deepcopy 耗時可忽略
            job_map = {j.job_id: j for j in jobs_copy}
            for S_list in [S0, S1, S2]:
                for j in S_list:
                    job_map[j.job_id].remaining_e -= 1
                    
            next_schedule = {key: val.copy() for key, val in current_schedule.items()}
            for t_offset, S_list in enumerate([S0, S1, S2]):
                t_abs = t_start + t_offset
                for j in S_list:
                    if j.job_id not in next_schedule:
                        next_schedule[j.job_id] = []
                    next_schedule[j.job_id].append(t_abs)
                    
            next_slack = slack_capacity.copy()
            next_slack[t_start:t_start+3] = frame_slacks
            
            # 遞迴進入下一個 Frame
            res, final_sched, final_slack = dfs_frame(k + 1, jobs_copy, generators, batteries, renewables, next_schedule, next_slack)
            if res:
                return True, final_sched, final_slack # 找到一條通往未來的生路，直接成功返回
                
        # 3. --- DFS 回溯 (退回快照狀態) ---
        # 走到這裡代表：要嘛這 3 小時內有算力破表，要嘛是遞迴到未來發現死路退回來
        # 無論如何，必須將硬體狀態還原，準備嘗試下一組 S0, S1, S2 的排列組合
        for i, g in enumerate(generators):
            g.current_output, g.consecutive_on_time, g.consecutive_off_time = snapshot_gens[i]
        for i, b in enumerate(batteries):
            b.current_soc = snapshot_bats[i]
                
    return False, current_schedule, slack_capacity

def generate_offline_schedule(tasks: List[PeriodicTask], generators: List[ThermalGenerator], batteries: List[Battery], renewables: List[RenewableGenerator]) -> Tuple[Dict[str, List[int]], List[int]]:
    jobs = expand_jobs(tasks)
    generators.sort(key=lambda g: g.cost_variable)
    
    slack_capacity = [0] * 72
    current_schedule = {}
    
    # 【修改】傳入 renewables
    success, sched, slack = dfs_frame(0, jobs, generators, batteries, renewables, current_schedule, slack_capacity)
    
    if not success:
        return {}, []
        
    return sched, slack

