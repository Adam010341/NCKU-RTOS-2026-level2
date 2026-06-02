# gen.py
import numpy as np
import json
from pathlib import Path

# ================= 設定區 =================
BASE_SEED = 2026                  # 固定基礎種子，確保可重現
PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = PROJECT_ROOT / "output" / "sporadic_aperiodic_task"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# 作業規範範圍 (numpy.integers 為 [low, high) 左閉右開)
SPORADIC_E = (1, 4)               # 1~3
SPORADIC_W = (5, 21)              # 5~20
APERIODIC_E = (1, 5)              # 1~4
APERIODIC_W = (5, 16)             # 5~15

# 集中型高峰時段定義 (hour)
PEAK_WINDOWS = [(0, 5), (8, 13), (18, 23)] 
# ==========================================

def generate_scenario(seed, scenario_id, dist_type):
    """依分佈類型生成單一情境的 sporadic 與 aperiodic tasks"""
    rng = np.random.default_rng(seed)
    
    n_sporadic = int(rng.integers(4, 8))   # 4~7
    n_aperiodic = int(rng.integers(7, 14)) # 7~13
    
    scenario = {"scenario_id": scenario_id, "dist_type": dist_type, "sporadic": [], "aperiodic": []}
    
    def make_task(tid, t_type):
        e_range = SPORADIC_E if t_type == "sporadic" else APERIODIC_E
        w_range = SPORADIC_W if t_type == "sporadic" else APERIODIC_W
        
        e = int(rng.integers(*e_range))
        
        # 依分佈抽樣 release time
        if dist_type == "uniform":
            r = int(rng.integers(0, 72 - e))
        elif dist_type == "concentrated":
            if rng.random() < 0.7:  # 70% 落在高峰
                win = rng.choice(PEAK_WINDOWS)
                r = int(rng.integers(win[0], win[1]))
            else:
                r = int(rng.integers(0, 72 - e))
        elif dist_type == "mixed":
            if rng.random() < 0.3:  # 30% 集中，70% 均勻
                win = rng.choice(PEAK_WINDOWS)
                r = int(rng.integers(win[0], win[1]))
            else:
                r = int(rng.integers(0, 72 - e))
                
        r = min(r, 72 - e)  # 安全邊界
        
        # 用電需求 w：集中型或混合型中的集中部分提高需求
        w = int(rng.integers(*w_range))
        if dist_type == "concentrated":
            w = int(rng.integers(w_range[0] + 5, w_range[1]))
        elif dist_type == "mixed" and rng.random() < 0.3:
            w = int(rng.integers(w_range[0] + 4, w_range[1]))
            
        # 相對截止時間 d：必須 >= e，且 r + d <= 72
        max_d = 72 - r
        d_upper = max(e, min(max_d, e + 12))
        d = int(rng.integers(e, d_upper + 1))
        
        preempt = int(rng.choice([0, 1]))
        
        return {
            "id": f"{t_type[0]}_{scenario_id}_{len(scenario[t_type])+1:02d}",
            "r": r, "e": e, "d": d, "w": w, "preempt": preempt
        }

    for _ in range(n_sporadic):
        scenario["sporadic"].append(make_task("s", "sporadic"))
    for _ in range(n_aperiodic):
        scenario["aperiodic"].append(make_task("a", "aperiodic"))
        
    return scenario

def main():
    # 產生 10 筆情境：3 uniform, 3 concentrated, 4 mixed
    config = [
        ("uniform", 3),
        ("concentrated", 3),
        ("mixed", 4)
    ]
    
    idx = 1
    for dist_type, count in config:
        for _ in range(count):
            seed = BASE_SEED + idx
            scenario_data = generate_scenario(seed, idx, dist_type)
            filename = f"scenario_{idx:02d}_{dist_type}.json"
            filepath = OUTPUT_DIR / filename
            
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(scenario_data, f, indent=2, ensure_ascii=False)
            print(f"[OK] generated: {filepath}")
            idx += 1

if __name__ == "__main__":
    main()
