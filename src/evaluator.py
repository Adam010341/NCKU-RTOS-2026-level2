#!/usr/bin/env python3
# evaluator.py
# Level 1 Evaluation Program for NCKU-RTOS-2026 VPP scheduling assignment.

import argparse
import json
import sys
from pathlib import Path
from collections import defaultdict
from typing import Optional

H = 72
ALPHA = 10000.0
EPS = 1e-9


def project_root():
    return Path(__file__).resolve().parents[1]


def resolve_path(path_str):
    p = Path(path_str)
    if p.is_absolute():
        return p
    cwd_path = Path.cwd() / p
    if cwd_path.exists():
        return cwd_path
    return project_root() / p


def load_json(path):
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def unwrap_schedule(schedule_data):
    if isinstance(schedule_data, dict):
        if "trajectory" in schedule_data:
            return schedule_data["trajectory"]
        if "schedule_result" in schedule_data:
            return schedule_data["schedule_result"]
        if "schedule" in schedule_data:
            return schedule_data["schedule"]
    if isinstance(schedule_data, list):
        return schedule_data
    raise ValueError("Invalid schedule format. Expected list or dict with schedule_result.")


def extract_level2_metrics_from_schedule(schedule_data) -> dict:
    if isinstance(schedule_data, dict) and isinstance(schedule_data.get("level2_metrics"), dict):
        return schedule_data["level2_metrics"]
    return {}


def is_charging_pseudo_job(job_id: str) -> bool:
    return str(job_id).endswith("_chg")


def detect_time_base(schedule):
    if not schedule:
        return 1
    times = [int(rec.get("t", 0)) for rec in schedule]
    return 0 if min(times) == 0 else 1


def normalize_schedule(schedule):
    normalized = []
    for rec in schedule:
        normalized.append({
            "t": int(rec.get("t", 0)),
            "P": rec.get("P", {}) or {},
            "k": rec.get("k", {}) or {},
            "sell": float(rec.get("sell", 0.0) or 0.0),
            "soc": rec.get("soc", {}) or {},
            "missed_aperiodic": rec.get("missed_aperiodic", []) or [],
            "rejected_sporadic": rec.get("rejected_sporadic", []) or [],
        })
    return sorted(normalized, key=lambda x: x["t"])


def task_release_to_schedule_time(r, time_base):
    # task_set.json generally uses 1..72. Convert to 0..71 if schedule is 0-based.
    return r - 1 if time_base == 0 else r


def scenario_release_to_schedule_time(r, time_base):
    # Current repo scenario generator uses 0..71. Convert to 1..72 if schedule is 1-based.
    return r + 1 if time_base == 1 else r


def slot_end_time(t, time_base):
    # For 0-based slot labels, slot 0 ends at time 1.
    # For 1-based output labels, use the label itself as completion time.
    return t + 1 if time_base == 0 else t


def last_schedulable_time_before_deadline(deadline_abs, time_base):
    return deadline_abs - 1 if time_base == 0 else deadline_abs


def expand_periodic_jobs(periodic_tasks, time_base):
    jobs = []
    max_time_label = 71 if time_base == 0 else 72

    for task_id, task in periodic_tasks.items():
        r_raw = int(task["r"])
        p = int(task["p"])
        e = int(task["e"])
        d = int(task["d"])
        w = float(task["w"])
        preempt = int(task.get("preempt", 1))
        first_release = task_release_to_schedule_time(r_raw, time_base)

        idx = 1
        release = first_release
        while release <= max_time_label:
            jobs.append({
                "id": f"{task_id}_{idx}",
                "task_id": task_id,
                "type": "periodic",
                "r": release,
                "d_abs": release + d,
                "e": e,
                "w": w,
                "preempt": preempt,
                "slots": [],
                "energy_by_slot": {},
            })
            idx += 1
            release = first_release + (idx - 1) * p
    return jobs


def load_scenario_jobs(scenario_path, time_base):
    if scenario_path is None:
        return [], []
    if not scenario_path.exists():
        raise FileNotFoundError(f"Scenario file not found: {scenario_path}")

    data = load_json(scenario_path)

    def convert(item, job_type):
        r = scenario_release_to_schedule_time(int(item["r"]), time_base)
        d = int(item["d"])
        return {
            "id": str(item["id"]),
            "task_id": str(item["id"]),
            "type": job_type,
            "r": r,
            "d_abs": r + d,
            "e": int(item["e"]),
            "w": float(item["w"]),
            "preempt": int(item.get("preempt", 1)),
            "slots": [],
            "energy_by_slot": {},
        }

    sporadic = [convert(x, "sporadic") for x in data.get("sporadic", [])]
    aperiodic = [convert(x, "aperiodic") for x in data.get("aperiodic", [])]
    return sporadic, aperiodic


def energy_assigned_to_job(record, job_id):
    if is_charging_pseudo_job(job_id):
        return 0.0
    k = record.get("k", {}) or {}
    entry = k.get(job_id)
    if entry is None:
        return 0.0
    if isinstance(entry, dict):
        return sum(float(v or 0.0) for v in entry.values())
    if isinstance(entry, (int, float)):
        return float(entry)
    return 0.0


def assign_periodic_slots(periodic_jobs, schedule, time_base):
    jobs_by_task = defaultdict(list)
    for job in periodic_jobs:
        jobs_by_task[job["task_id"]].append(job)
    for task_id in jobs_by_task:
        jobs_by_task[task_id].sort(key=lambda j: (j["r"], j["d_abs"]))

    for rec in schedule:
        t = int(rec["t"])
        for task_id, jobs in jobs_by_task.items():
            assigned_energy = energy_assigned_to_job(rec, task_id)

            # Also support expanded id such as p1_1 if scheduler outputs it.
            if assigned_energy <= EPS:
                for job in jobs:
                    val = energy_assigned_to_job(rec, job["id"])
                    if val > EPS and len(job["slots"]) < job["e"]:
                        job["slots"].append(t)
                        job["energy_by_slot"][t] = val
                        break
                continue

            for job in jobs:
                last_ok = last_schedulable_time_before_deadline(job["d_abs"], time_base)
                if job["r"] <= t <= last_ok and len(job["slots"]) < job["e"]:
                    job["slots"].append(t)
                    job["energy_by_slot"][t] = assigned_energy
                    break


def assign_direct_slots(jobs, schedule):
    job_map = {job["id"]: job for job in jobs}
    for rec in schedule:
        t = int(rec["t"])
        for job_id, job in job_map.items():
            val = energy_assigned_to_job(rec, job_id)
            if val > EPS:
                job["slots"].append(t)
                job["energy_by_slot"][t] = val


def is_completed(job):
    return len(job["slots"]) >= int(job["e"])


def completion_time(job, time_base):
    if not is_completed(job):
        return None
    return slot_end_time(max(job["slots"]), time_base)


def deadline_miss(job, time_base):
    c = completion_time(job, time_base)
    return c is None or c > job["d_abs"]


def response_time(job, time_base):
    c = completion_time(job, time_base)
    if c is None:
        return None
    return c - job["r"]


def tardiness(job, time_base):
    c = completion_time(job, time_base)
    if c is None:
        return max(0, H + 1 - job["d_abs"])
    return max(0, c - job["d_abs"])


def compute_completion_jitter(periodic_jobs, time_base):
    responses_by_task = defaultdict(list)
    for job in periodic_jobs:
        rt = response_time(job, time_base)
        if rt is not None:
            responses_by_task[job["task_id"]].append(rt)

    jitter_by_task = {}
    for task_id, resps in responses_by_task.items():
        jitter_by_task[task_id] = float(max(resps) - min(resps)) if len(resps) > 1 else 0.0

    if not jitter_by_task:
        return 0.0, {}
    return sum(jitter_by_task.values()) / len(jitter_by_task), jitter_by_task


def generator_cost(schedule, processor_data):
    generators = {g["generator_id"]: g for g in processor_data.get("generator", [])}
    total = 0.0
    for rec in schedule:
        P = rec.get("P", {}) or {}
        for gid, g in generators.items():
            out = float(P.get(gid, 0.0) or 0.0)
            if out > EPS:
                total += float(g.get("cost_fixed", 0.0))
                total += float(g.get("cost_variable", 0.0)) * out
    return total


def price_map(price_data, time_base):
    raw = price_data.get("price", price_data)
    result = {}
    if isinstance(raw, list):
        for item in raw:
            hour = int(item.get("hour", item.get("t", 0)))
            value = float(item.get("market_price", item.get("price", 0.0)) or 0.0)
            if time_base == 0 and hour >= 1:
                hour -= 1
            elif time_base == 1 and hour == 0:
                hour += 1
            result[hour] = value
    return result


def market_revenue(schedule, price_data, time_base):
    prices = price_map(price_data, time_base)
    total = 0.0
    for rec in schedule:
        t = int(rec["t"])
        sell = float(rec.get("sell", 0.0) or 0.0)
        total += prices.get(t, 0.0) * sell
    return total


def summarize_job(job, time_base):
    c = completion_time(job, time_base)
    return {
        "id": job["id"],
        "task_id": job["task_id"],
        "type": job["type"],
        "release_time": job["r"],
        "absolute_deadline": job["d_abs"],
        "execution_time": job["e"],
        "energy_demand": job["w"],
        "preempt": job["preempt"],
        "scheduled_slots": sorted(job["slots"]),
        "completed": is_completed(job),
        "completion_time": c,
        "response_time": response_time(job, time_base),
        "tardiness": tardiness(job, time_base),
        "deadline_miss": deadline_miss(job, time_base),
    }


def compute_all_metrics(periodic_jobs, sporadic_jobs, aperiodic_jobs, schedule, processor_data, price_data, time_base):
    accepted_sporadic = [j for j in sporadic_jobs if len(j["slots"]) > 0]
    hard_jobs = periodic_jobs + accepted_sporadic
    hard_missed = [j for j in hard_jobs if deadline_miss(j, time_base)]
    hard_deadline_miss_rate = len(hard_missed) / len(hard_jobs) if hard_jobs else 0.0

    soft_missed = [j for j in aperiodic_jobs if deadline_miss(j, time_base)]
    soft_deadline_miss_rate = len(soft_missed) / len(aperiodic_jobs) if aperiodic_jobs else 0.0

    all_jobs = periodic_jobs + sporadic_jobs + aperiodic_jobs
    tardiness_values = [tardiness(j, time_base) for j in all_jobs]
    response_values = [response_time(j, time_base) for j in all_jobs if response_time(j, time_base) is not None]

    avg_tardiness = sum(tardiness_values) / len(tardiness_values) if tardiness_values else 0.0
    max_tardiness = max(tardiness_values) if tardiness_values else 0.0
    avg_response = sum(response_values) / len(response_values) if response_values else 0.0
    max_response = max(response_values) if response_values else 0.0

    avg_jitter, jitter_by_task = compute_completion_jitter(periodic_jobs, time_base)

    total_sporadic_execution = sum(int(j["e"]) for j in sporadic_jobs)
    completed_sporadic_execution = sum(int(j["e"]) for j in sporadic_jobs if not deadline_miss(j, time_base))
    sporadic_value_rate = completed_sporadic_execution / total_sporadic_execution if total_sporadic_execution > 0 else 0.0

    gen_cost = generator_cost(schedule, processor_data)
    revenue = market_revenue(schedule, price_data, time_base)
    objective_value = ALPHA * len(soft_missed) + gen_cost - revenue

    return {
        "hard_deadline_miss_rate": hard_deadline_miss_rate,
        "soft_deadline_miss_rate": soft_deadline_miss_rate,
        "average_tardiness": avg_tardiness,
        "max_tardiness": max_tardiness,
        "average_response_time": avg_response,
        "max_response_time": max_response,
        "completion_time_jitter": avg_jitter,
        "acceptance_test": {
            "sporadic_total_jobs": len(sporadic_jobs),
            "sporadic_accepted_jobs": len(accepted_sporadic),
            "sporadic_completed_before_deadline": sum(1 for j in sporadic_jobs if not deadline_miss(j, time_base)),
            "completed_sporadic_execution_time": completed_sporadic_execution,
            "total_sporadic_execution_time": total_sporadic_execution,
            "sporadic_value_rate": sporadic_value_rate,
        },
        "sporadic_value_rate": sporadic_value_rate,
        "post_acceptance_violation_rate": (
            len([j for j in accepted_sporadic if deadline_miss(j, time_base)]) / len(accepted_sporadic)
            if accepted_sporadic else 0.0
        ),
        "generator_cost": gen_cost,
        "market_revenue": revenue,
        "objective_value": objective_value,
        "details": {
            "time_base": time_base,
            "periodic_job_count": len(periodic_jobs),
            "sporadic_job_count": len(sporadic_jobs),
            "aperiodic_job_count": len(aperiodic_jobs),
            "hard_deadline_missed_jobs": [j["id"] for j in hard_missed],
            "soft_deadline_missed_jobs": [j["id"] for j in soft_missed],
            "completion_time_jitter_by_periodic_task": jitter_by_task,
            "periodic_jobs": [summarize_job(j, time_base) for j in periodic_jobs],
            "sporadic_jobs": [summarize_job(j, time_base) for j in sporadic_jobs],
            "aperiodic_jobs": [summarize_job(j, time_base) for j in aperiodic_jobs],
        },
    }


def find_matching_scenario(schedule_path):
    name = schedule_path.name
    # Support both level1 and level2 prefixed names
    for prefix in ("schedule_result_level2_", "schedule_result_"):
        if name.startswith(prefix):
            scenario_name = name[len(prefix):]
            scenario_path = schedule_path.parent / "sporadic_aperiodic_task" / scenario_name
            if scenario_path.exists():
                return scenario_path
    return None


def extract_level2_metrics_from_log(log_path: Optional[Path]) -> dict:
    """從 acceptance_test_log JSON 中抽取 Level 2 Summary 行。"""
    if log_path is None or not log_path.exists():
        return {}
    try:
        with open(log_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        entries = data.get("acceptance_test_log", [])
        for entry in reversed(entries):
            if isinstance(entry, str) and entry.startswith("[Level 2 Summary]"):
                raw = entry[len("[Level 2 Summary]"):].strip()
                # raw is a Python dict repr; use json with single-quote fix
                try:
                    import ast
                    return ast.literal_eval(raw)
                except Exception:
                    return {}
    except Exception:
        return {}
    return {}


def evaluate_one(task_set_path, schedule_path, processor_path, price_path, scenario_path, output_path, log_path=None):
    task_set_data = load_json(task_set_path)
    schedule_data = load_json(schedule_path)
    processor_data = load_json(processor_path)
    price_data = load_json(price_path)

    schedule = normalize_schedule(unwrap_schedule(schedule_data))
    time_base = detect_time_base(schedule)

    periodic_jobs = expand_periodic_jobs(task_set_data.get("periodic", {}), time_base)
    sporadic_jobs, aperiodic_jobs = load_scenario_jobs(scenario_path, time_base)

    assign_periodic_slots(periodic_jobs, schedule, time_base)
    assign_direct_slots(sporadic_jobs, schedule)
    assign_direct_slots(aperiodic_jobs, schedule)

    results = compute_all_metrics(
        periodic_jobs=periodic_jobs,
        sporadic_jobs=sporadic_jobs,
        aperiodic_jobs=aperiodic_jobs,
        schedule=schedule,
        processor_data=processor_data,
        price_data=price_data,
        time_base=time_base,
    )

    # Attach Level 2 metrics if available. Prefer first-class schedule metadata;
    # fall back to older acceptance-log summary parsing.
    l2_raw = extract_level2_metrics_from_schedule(schedule_data) or extract_level2_metrics_from_log(log_path)
    if l2_raw:
        gen_cost = results["generator_cost"]
        revenue  = results["market_revenue"]
        bat_deg  = float(l2_raw.get("battery_degradation_cost", 0.0))
        penalty  = float(l2_raw.get("market_penalty", 0.0))
        rt_extra = float(l2_raw.get("realtime_extra_revenue", 0.0))
        level2_adj_obj = gen_cost + bat_deg + penalty - revenue - rt_extra
        results["level2_metrics"] = {
            "forecast_error_ratio": l2_raw.get("forecast_error_ratio", "N/A"),
            "advanced_reschedule_count": l2_raw.get("advanced_reschedule_count", 0),
            "renewable_shortfall_events": l2_raw.get("renewable_shortfall_events", 0),
            "renewable_surplus_events": l2_raw.get("renewable_surplus_events", 0),
            "total_forecast_renewable": l2_raw.get("total_forecast_renewable", 0.0),
            "total_actual_renewable": l2_raw.get("total_actual_renewable", 0.0),
            "total_renewable_shortfall": l2_raw.get("total_renewable_shortfall", 0.0),
            "total_renewable_surplus": l2_raw.get("total_renewable_surplus", 0.0),
            "battery_rescue_energy": l2_raw.get("battery_rescue_energy", 0.0),
            "thermal_rescue_energy": l2_raw.get("thermal_rescue_energy", 0.0),
            "deferred_aperiodic_jobs": l2_raw.get("deferred_aperiodic_jobs", 0),
            "total_deferred_aperiodic_energy": l2_raw.get("total_deferred_aperiodic_energy", 0.0),
            "protected_hard_jobs": l2_raw.get("protected_hard_jobs", 0),
            "battery_degradation_cost": bat_deg,
            "market_commitment_shortfall": l2_raw.get("market_commitment_shortfall", 0.0),
            "market_penalty": penalty,
            "realtime_extra_revenue": rt_extra,
            "level2_adjusted_objective_value": round(level2_adj_obj, 4),
        }

    save_json(output_path, results)
    return results


def main():
    root = project_root()

    parser = argparse.ArgumentParser(description="Level 1/2 evaluator for VPP real-time scheduling assignment.")
    parser.add_argument("--task-set", default="output/task_set.json")
    parser.add_argument("--schedule", default="output/schedule_result.json")
    parser.add_argument("--processor", default="input/processor_settings.json")
    parser.add_argument("--price", default="input/price_72hr.json")
    parser.add_argument("--scenario", default=None)
    parser.add_argument("--output", default="output/evaluation_results.json")
    parser.add_argument("--batch-scenarios", action="store_true",
                        help="Evaluate all output/schedule_result_scenario_*.json files.")
    parser.add_argument("--batch-level2", action="store_true",
                        help="Evaluate all output/schedule_result_level2_scenario_*.json files.")

    args = parser.parse_args()

    task_set_path = resolve_path(args.task_set)
    processor_path = resolve_path(args.processor)
    price_path = resolve_path(args.price)

    def _run_batch(glob_pattern: str, eval_prefix: str, summary_filename: str):
        output_dir = root / "output"
        schedule_files = sorted(output_dir.glob(glob_pattern))
        if not schedule_files:
            print(f"No schedule files matched: {glob_pattern}")
            return
        summary = []
        for schedule_path in schedule_files:
            scenario_path = find_matching_scenario(schedule_path)
            # Strip 'schedule_result_' prefix (and any 'level2_' sub-prefix) then apply eval_prefix
            base_name = schedule_path.name
            for strip_prefix in ("schedule_result_level2_", "schedule_result_"):
                if base_name.startswith(strip_prefix):
                    base_name = base_name[len(strip_prefix):]
                    break
            out_name = eval_prefix + base_name
            output_path = output_dir / out_name
            # Try to find matching log file
            log_name = schedule_path.name.replace("schedule_result_", "acceptance_test_log_")
            log_path = output_dir / log_name
            results = evaluate_one(
                task_set_path, schedule_path, processor_path,
                price_path, scenario_path, output_path,
                log_path=log_path if log_path.exists() else None
            )
            entry = {
                "schedule_file": str(schedule_path.relative_to(root)),
                "scenario_file": str(scenario_path.relative_to(root)) if scenario_path else None,
                "evaluation_file": str(output_path.relative_to(root)),
                "hard_deadline_miss_rate": results["hard_deadline_miss_rate"],
                "soft_deadline_miss_rate": results["soft_deadline_miss_rate"],
                "sporadic_value_rate": results["sporadic_value_rate"],
                "generator_cost": results["generator_cost"],
                "market_revenue": results["market_revenue"],
                "objective_value": results["objective_value"],
            }
            if "level2_metrics" in results:
                entry["level2_adjusted_objective_value"] = (
                    results["level2_metrics"].get("level2_adjusted_objective_value", None)
                )
            summary.append(entry)
            print(f"Evaluated {schedule_path.name} -> {output_path.name}")
        summary_path = output_dir / summary_filename
        save_json(summary_path, {"summary": summary})
        print(f"Summary saved to {summary_path}")

    if args.batch_level2:
        _run_batch(
            glob_pattern="schedule_result_level2_scenario_*.json",
            eval_prefix="evaluation_results_level2_",
            summary_filename="evaluation_results_level2_summary.json",
        )
        return

    if args.batch_scenarios:
        _run_batch(
            glob_pattern="schedule_result_scenario_*.json",
            eval_prefix="evaluation_results_",
            summary_filename="evaluation_results_summary.json",
        )
        return

    schedule_path = resolve_path(args.schedule)
    scenario_path = resolve_path(args.scenario) if args.scenario else None
    output_path = resolve_path(args.output)
    log_path_guess = output_path.parent / output_path.name.replace("evaluation_results", "acceptance_test_log")

    results = evaluate_one(
        task_set_path, schedule_path, processor_path, price_path,
        scenario_path, output_path,
        log_path=log_path_guess if log_path_guess.exists() else None
    )

    print(f"evaluation_results saved to {output_path}")
    print(json.dumps({
        "hard_deadline_miss_rate": results["hard_deadline_miss_rate"],
        "soft_deadline_miss_rate": results["soft_deadline_miss_rate"],
        "average_tardiness": results["average_tardiness"],
        "max_tardiness": results["max_tardiness"],
        "average_response_time": results["average_response_time"],
        "max_response_time": results["max_response_time"],
        "completion_time_jitter": results["completion_time_jitter"],
        "sporadic_value_rate": results["sporadic_value_rate"],
        "generator_cost": results["generator_cost"],
        "market_revenue": results["market_revenue"],
        "objective_value": results["objective_value"],
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"[evaluator.py error] {exc}", file=sys.stderr)
        sys.exit(1)
