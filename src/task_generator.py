import random, math, json
from pathlib import Path

RANDOM_SEED = 2026
random.seed(RANDOM_SEED)
PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = PROJECT_ROOT / "output" / "task_set.json"

def generate_your_task_set():
    N = random.randint(6, 10)
    tasks = {}
    
    # 1. Period 分配 (遞增)
    half = (N - 2) // 2
    periods = [6]*half + [random.choice([11,12])]*((N-2)-half) + random.sample([15,18,21,24], 2)
    
    # 2. Execution time (遞增)
    exec_times = [1]*(N-4) + [2,2,3,3]
    
    # 3. Deadline (不強制全局排序，依 index 綁定)
    deadlines = []
    for i in range(N):
        if i < N-2:
            deadlines.append(random.randint(6, periods[i]))  # 前半 ≥6
        else:
            deadlines.append(3)  # 末尾強制 = maxe
            
    # 4. Release time & Energy demand
    r = [random.randint(1, p) for p in periods]
    w = [random.randint(6, 13) for _ in range(N-2)] + [random.randint(14, 18) for _ in range(2)]
    
    # 5. Preemptive (將中後段兩個任務設為 non-preemptive)
    preempt = [1]*N
    preempt[N-3] = 0
    preempt[N-4] = 0
    
    # 6. 包裝
    for i in range(N):
        tasks[f"p{i+1}"] = {
            "r": r[i], "p": periods[i], "e": exec_times[i],
            "d": deadlines[i], "w": w[i], "preempt": preempt[i]
        }
    return tasks

# ✅ 驗證區塊 (必加)
def validate(tasks):
    import math
    t_list = list(tasks.values())
    f = 3
    
    # 1-8 Frame size 檢查
    if not all(2*f - math.gcd(f, t["p"]) <= t["d"] for t in t_list):
        return False, "Frame size f=3 failed constraint 2f-gcd(f,p)≤d"
    
    # 1-5 DW 檢查（加上下限與上限）
    dw = sum(t["e"]/t["p"] for t in t_list)
    if not (0.7 <= dw <= 1.0):
        return False, f"DW={dw:.3f} not in [0.7, 1.0]"
    
    # 1-3 Jobs 數量計算（修正公式）
    jobs = sum(math.floor((72 - t["r"]) / t["p"]) + 1 for t in t_list)
    if jobs <= 30:
        return False, f"Jobs={jobs} <= 30"
    
    # 額外檢查：period 種類
    if len(set(t["p"] for t in t_list)) < 3:
        return False, "Less than 3 distinct periods"
    
    # 額外檢查：non-preemptive 任務的 d≥e
    for name, t in tasks.items():
        if t["preempt"] == 0 and t["d"] < t["e"]:
            return False, f"{name}: non-preemptive but d={t['d']}<e={t['e']}"
    
    return True, "OK"

def main():
    tasks = generate_your_task_set()
    ok, msg = validate(tasks)
    print(msg)
    if ok:
        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
            json.dump({"periodic": tasks}, f, indent=2, ensure_ascii=False)
        print(f"Saved task set to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
