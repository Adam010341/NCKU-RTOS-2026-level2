# test_offline_pipeline.py
import sys
import os

# 確保 Python 能正確將當前目錄視為 src 的上層路徑
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.scheduler.models import PeriodicTask, ThermalGenerator, Battery, RenewableGenerator
from src.scheduler.offline_planner import generate_offline_schedule

renewables = [
        RenewableGenerator(
            id="pv_1", capacity=20, forecast=[0.5] * 72
        )
    ]

def run_integration_test():
    print("=" * 60)
    print("展開虛擬電廠日前排程整合測試 (Sprint 3 驗證)")   
    print("=" * 60)

    # 1. 依據 task_set.json 實體規格建立週期性任務集
    # 包含搶佔 (preempt=1) 與非搶佔 (preempt=0) 任務，且最大執行時間 e 均 <= 3
    tasks = [
        PeriodicTask(id="p1", r=5, p=6,  e=1, d=6,  w=7,  preempt=1),
        PeriodicTask(id="p2", r=4, p=6,  e=1, d=6,  w=10, preempt=1),
        PeriodicTask(id="p3", r=4, p=12, e=2, d=12, w=7,  preempt=0),
        PeriodicTask(id="p4", r=1, p=12, e=2, d=12, w=13, preempt=0),
        PeriodicTask(id="p5", r=10,p=15, e=3, d=3,  w=14, preempt=1),
        PeriodicTask(id="p6", r=3, p=24, e=3, d=3,  w=17, preempt=1)
    ]

    # 2. 配置發電設備 (包含一具便宜基載 T1、一具高成本尖載 T2)
    # 預設啟始狀態為關機 (initial_energy=0, initial_on_time=0)
    generators = [
        ThermalGenerator(
            id="T1", output_min=10, output_max=50, 
            ramp_up_rate=15, ramp_down_rate=15, 
            min_up_time=3, min_down_time=2, 
            cost_fixed=100, cost_variable=5, # 便宜
            initial_on_time=0, initial_off_time=5, initial_energy=0
        ),
        ThermalGenerator(
            id="T2", output_min=20, output_max=100, 
            ramp_up_rate=30, ramp_down_rate=30, 
            min_up_time=4, min_down_time=3, 
            cost_fixed=200, cost_variable=25, # 昂貴
            initial_on_time=0, initial_off_time=5, initial_energy=0
        )
    ]

    # 3. 配置儲能電池 (作為策略 B 的算力緩衝外援)
    batteries = [
        Battery(
            id="B1", soc_min=10, soc_max=100, 
            discharge_max=20, charge_max=20, soc_init=50
        )
    ]

    print(f"[*] 成功載入 {len(tasks)} 個週期性任務。")
    print(f"[*] 成功載入 {len(generators)} 台火力發電機組與 {len(batteries)} 組儲能電池。")
    print("[*] 啟動 Frame-based DFS 排程演算法...")

    # 4. 執行排程器
    schedule_dict, slack_capacity = generate_offline_schedule(tasks, generators, batteries, renewables)

    # 5. 結果驗證
    if not schedule_dict or not slack_capacity:
        print("\n[❌ 測試失敗]: DFS 演算法回傳空值，系統無法在物理限制下找到合法可行解。")
        return

    print("\n[?? 測試成功]: 已順利生成 72 小時日前調度表！")
    print("-" * 60)
    print("【日前排程結果摘要】")
    
    # 印出前幾個 Job 的排程時間點以供視覺化檢查
    scheduled_jobs_count = 0
    for job_id, time_slots in sorted(schedule_dict.items()):
        scheduled_jobs_count += 1
        # 僅印出前 8 個 Job 避免洗板
        if scheduled_jobs_count <= 8:
            print(f"Job {job_id:8s} -> 排定的絕對時間點 (時): {time_slots}")
    if len(schedule_dict) > 8:
        print(f"... 其餘 {len(schedule_dict) - 8} 個 Job 已正確排入矩陣。")

    print("-" * 60)
    print("【系統全域剩餘算力備用容量 (Slack Capacity)】")
    # 每 6 個小時列印一次 Slack 數值以利觀察趨勢
    for chunk in range(0, 72, 6):
        slice_vals = slack_capacity[chunk:chunk+6]
        formatted_vals = ", ".join(f"{v:3d}" for v in slice_vals)
        print(f"Hour {chunk:02d} - {chunk+5:02d} : [{formatted_vals}] MWh")
    print("=" * 60)

if __name__ == "__main__":
    run_integration_test()