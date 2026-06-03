"""
main.py — VPP Real-Time Scheduling 主程式

Level 1 baseline  : LEVEL2_ENABLED = False
Level 2 advanced  : LEVEL2_ENABLED = False
"""

import os
import glob
import json
import subprocess
import sys
from pathlib import Path
from typing import List

from src.scheduler.models import TickRecord
from src.scheduler.offline_planner import generate_offline_schedule
from src.scheduler.acceptance_tester import AcceptanceTester
from src.scheduler.main_scheduler import run_72hr_simulation
from src.scheduler.advanced_scheduler import RenewableUncertaintyModel
from src.scheduler.data_loader import (
    load_price,
    load_processor_settings,
    load_periodic_tasks,
    load_online_tasks,
    load_level2_market_settings,
)

PROJECT_ROOT = Path(__file__).resolve().parent

# ═══════════════════════════════════════════════════════════════
# Level 2 開關與設定
# 設為 False → 完全執行 Level 1 baseline（行為與原始版本一致）
# 設為 True  → 啟用 Level 2 Advanced Dynamic Scheduler
# ═══════════════════════════════════════════════════════════════
LEVEL2_ENABLED = True

LEVEL2_CONFIG = {
    "forecast_error_ratio": 0.2,          # 再生能源預測誤差上限 ±20%
    "random_seed": 2026,                   # 確保可重現
    "reserve_margin": 0.1,                 # 系統預留容量比例
    "penalty_rate": 2.0,                   # 售電缺口罰款率 ($/MWh)
    "realtime_price_multiplier": 1.1,      # 即時市場電價倍率
    "commitment_ratio": 0.8,               # 日前承諾比例（相對平均售電量）
}


# ───────────────────────────────────────────────────────────────
def save_schedule_to_json(trajectory: List[TickRecord], output_path: str):
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    records = [record.to_dict() for record in trajectory]
    level2_metrics = getattr(trajectory, "level2_metrics", {})
    if level2_metrics:
        formatted_data = {
            "schedule_result": records,
            "level2_metrics": level2_metrics,
        }
    else:
        formatted_data = records
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(formatted_data, f, indent=4, ensure_ascii=False)
    print(f"   [OK] schedule saved: {output_path}")


def build_day_ahead_commitment(
    price_72hr: List[float],
    commitment_ratio: float,
    typical_sell_per_hour: float = 5.0,
) -> List[float]:
    """
    以簡單的固定比例建立日前承諾售電量（每小時）。
    """
    return [typical_sell_per_hour * commitment_ratio for _ in range(72)]


# ───────────────────────────────────────────────────────────────
def main():
    os.chdir(PROJECT_ROOT)
    print("=" * 60)
    print("VPP Dynamic Scheduling System")
    mode_label = "Level 2 Advanced" if LEVEL2_ENABLED else "Level 1 Baseline"
    print(f"Mode: {mode_label}")
    print("=" * 60)

    # 1. 載入靜態環境參數
    price_72hr    = load_price("input/price_72hr.json")
    periodic_tasks = load_periodic_tasks("output/task_set.json")
    market_cfg    = load_level2_market_settings("input/processor_settings.json")
    
    # 合併 LEVEL2_CONFIG（程式碼設定優先）
    effective_l2cfg = dict(market_cfg)
    effective_l2cfg.update(LEVEL2_CONFIG)

    generators, renewables, batteries = load_processor_settings("input/processor_settings.json")

    # 2. 日前離線排程（Offline DFS）
    print("\n[*] 計算 72 小時日前固定排程 (Offline DFS)...")
    schedule_dict, offline_slack = generate_offline_schedule(
        periodic_tasks, generators, batteries, renewables
    )
    if not schedule_dict:
        print("[ERROR] 日前排程失敗，程式終止。")
        return
    print(f"[OK] 日前排程成功，{len(schedule_dict)} 個擴展 Job。")

    # 3. 建立 Level 2 再生能源不確定性模型（所有情境共用同一個 profile）
    actual_renewable_profile = None
    day_ahead_commitment = None
    if LEVEL2_ENABLED:
        actual_renewable_profile = RenewableUncertaintyModel(
            renewables=renewables,
            seed=effective_l2cfg.get("random_seed", 2026),
            forecast_error_ratio=effective_l2cfg.get("forecast_error_ratio", 0.2),
        )
        day_ahead_commitment = build_day_ahead_commitment(
            price_72hr=price_72hr,
            commitment_ratio=effective_l2cfg.get("commitment_ratio", 0.8),
        )
        print(f"[OK] Level 2 renewable uncertainty model created "
              f"(error_ratio=±{effective_l2cfg['forecast_error_ratio']*100:.0f}%)")

    # 4. 抓取所有情境測資
    scenario_files = sorted(glob.glob("output/sporadic_aperiodic_task/scenario_*.json"))
    if not scenario_files:
        print("[WARN] 找不到任何線上情境測資。")
        return
    print(f"\n[*] 偵測到 {len(scenario_files)} 組情境，開始批次模擬...")

    # 5. 針對每個情境進行模擬
    for filepath in scenario_files:
        scenario_name = os.path.splitext(os.path.basename(filepath))[0]
        print(f"\n  >>> 模擬情境：{scenario_name}")

        gen_sim, ren_sim, bat_sim = load_processor_settings("input/processor_settings.json")
        sporadic_arr, aperiodic_arr = load_online_tasks(filepath)
        tester = AcceptanceTester(offline_slack.copy())
        log_list = []

        try:
            trajectory = run_72hr_simulation(
                schedule_dict=schedule_dict,
                tester=tester,
                generators=gen_sim,
                batteries=bat_sim,
                renewables=ren_sim,
                price_72hr=price_72hr,
                offline_tasks=periodic_tasks,
                online_sporadic_arrivals=sporadic_arr,
                online_aperiodic_arrivals=aperiodic_arr,
                log_list=log_list,
                level2_enabled=LEVEL2_ENABLED,
                level2_config=effective_l2cfg if LEVEL2_ENABLED else None,
                actual_renewable_profile=actual_renewable_profile if LEVEL2_ENABLED else None,
                day_ahead_sell_commitment=day_ahead_commitment if LEVEL2_ENABLED else None,
            )

            # ── 決定輸出檔名前綴 ──
            prefix = "level2_" if LEVEL2_ENABLED else ""

            # schedule_result
            sched_file = f"output/schedule_result_{prefix}{scenario_name}.json"
            save_schedule_to_json(trajectory, sched_file)

            # acceptance_test_log
            log_file = f"output/acceptance_test_log_{prefix}{scenario_name}.json"
            log_data = {
                "scenario": scenario_name,
                "level2_enabled": LEVEL2_ENABLED,
                "acceptance_test_log": log_list if log_list else ["No online tasks."]
            }
            os.makedirs(os.path.dirname(log_file), exist_ok=True)
            with open(log_file, "w", encoding="utf-8") as f:
                json.dump(log_data, f, indent=4, ensure_ascii=False)
            print(f"   [OK] log saved: {log_file}")

        except Exception as e:
            print(f"   [ERROR] {scenario_name}: {str(e)}")
            import traceback
            traceback.print_exc()

    # 6. 評估所有 scenario，產生 evaluation_results_*.json 與 summary
    _run_batch_evaluation(level2_enabled=LEVEL2_ENABLED)

    # 7. 複製第一個情境的結果為標準正式檔名
    _copy_standard_outputs(prefix="level2_" if LEVEL2_ENABLED else "")

    print("\n" + "=" * 60)
    print(f"All scenarios done. Mode: {mode_label}")


def _run_batch_evaluation(level2_enabled: bool):
    """Run evaluator after schedules are generated."""
    evaluator_path = PROJECT_ROOT / "src" / "evaluator.py"
    args = [sys.executable, str(evaluator_path)]
    args.append("--batch-level2" if level2_enabled else "--batch-scenarios")
    print(f"\n[*] Running evaluator: {' '.join(args)}")
    result = subprocess.run(args, cwd=PROJECT_ROOT, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Evaluator failed with exit code {result.returncode}")


def _copy_standard_outputs(prefix: str = ""):
    """將第一個情境結果複製為標準繳交檔名。"""
    mappings = [
        (f"output/schedule_result_{prefix}scenario_01_uniform.json",
         "output/schedule_result.json"),
        (f"output/acceptance_test_log_{prefix}scenario_01_uniform.json",
         "output/acceptance_test_log.json"),
        (f"output/evaluation_results_{prefix}scenario_01_uniform.json",
         "output/evaluation_results.json"),
    ]
    for src, dst in mappings:
        if os.path.exists(src):
            import shutil
            shutil.copy2(src, dst)
            print(f"   [OK] copied {src} -> {dst}")


if __name__ == "__main__":
    main()
