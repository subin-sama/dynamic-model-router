"""Deterministic, provider-free graders for a small routing benefit experiment.

Only prompt text from cases.json should be forwarded to a model. This module
contains oracle answers and is for the harness, not the selector or execution.
"""
import argparse
from functools import lru_cache
import json
import re
from pathlib import Path

ROWS = [
    {"row": 1, "id": "RX-004", "status": "ready"},
    {"row": 2, "id": "RX-002", "status": "hold"},
    {"row": 3, "id": "RX-012", "status": "ready"},
    {"row": 4, "id": "RX004", "status": "ready"},
    {"row": 5, "id": " RX-021 ", "status": "ready"},
    {"row": 6, "id": "RX-001", "status": "ready"},
    {"row": 7, "id": "RX-004", "status": "ready"},
    {"row": 8, "id": "RX-000", "status": "ready"},
    {"row": 9, "id": "RX-101", "status": "Ready"},
    {"row": 10, "id": "RX-008", "status": "ready"},
    {"row": 11, "id": "RX-003", "status": "ready"},
    {"row": 12, "id": "RX-12", "status": "ready"},
    {"row": 13, "id": "rx-009", "status": "ready"},
    {"row": 14, "id": "RX-001", "status": "ready"},
    {"row": 15, "id": "RX-007", "status": "ready "},
    {"row": 16, "id": "RX-005", "status": "blocked"},
    {"row": 17, "id": "RX-1000", "status": "ready"},
    {"row": 18, "id": "RX-021", "status": "ready"},
]

# ID, exclusive resource, duration, value, prerequisites.
JOBS = [
    ("A", "CPU", 2, 0, ()),
    ("B", "GPU", 1, 0, ()),
    ("C", "CPU", 2, 7, ("A",)),
    ("D", "GPU", 2, 8, ("A", "B")),
    ("E", "CPU", 1, 5, ("B",)),
    ("F", "GPU", 2, 9, ("C",)),
    ("G", "CPU", 2, 10, ("D",)),
    ("H", "GPU", 1, 6, ("E",)),
    ("I", "CPU", 1, 4, ("H",)),
    ("J", "GPU", 1, 12, ("I",)),
    ("K", "CPU", 1, 6, ("D",)),
    ("L", "GPU", 1, 5, ("C",)),
]
HORIZON = 6


def extraction_oracle():
    accepted = [row for row in ROWS if row["status"] == "ready"
                and re.fullmatch(r"RX-[0-9]{3}", row["id"].strip())]
    ids = sorted({row["id"].strip() for row in accepted}, key=lambda s: int(s[3:]))
    return {"ids": ids, "valid_rows": len(accepted),
            "rejected_rows": [row["row"] for row in ROWS if row not in accepted]}


def scheduling_oracle():
    """Explore all integer-boundary CPU/GPU scheduling decisions, with memoization."""
    index = {job[0]: i for i, job in enumerate(JOBS)}
    dependencies = [sum(1 << index[x] for x in job[4]) for job in JOBS]
    mandatory = (1 << index["A"]) | (1 << index["B"])

    @lru_cache(maxsize=None)
    def solve(t, done, cpu, cpu_left, gpu, gpu_left):
        if cpu >= 0 and cpu_left == 0:
            done |= 1 << cpu
            cpu = -1
        if gpu >= 0 and gpu_left == 0:
            done |= 1 << gpu
            gpu = -1
        if t == HORIZON:
            if done & mandatory != mandatory or cpu >= 0 or gpu >= 0:
                return -1, ()
            return sum(job[3] for i, job in enumerate(JOBS) if done & (1 << i)), ()
        occupied = done | ((1 << cpu) if cpu >= 0 else 0) | ((1 << gpu) if gpu >= 0 else 0)
        available = [i for i, job in enumerate(JOBS) if not occupied & (1 << i)
                     and dependencies[i] & done == dependencies[i]
                     and t + job[2] <= HORIZON]
        cpus = [None] if cpu >= 0 else [None] + [i for i in available if JOBS[i][1] == "CPU"]
        gpus = [None] if gpu >= 0 else [None] + [i for i in available if JOBS[i][1] == "GPU"]
        best = (-1, ())
        for c in cpus:
            for g in gpus:
                next_cpu, next_cl = cpu, cpu_left
                next_gpu, next_gl = gpu, gpu_left
                starts = []
                if c is not None:
                    next_cpu, next_cl = c, JOBS[c][2]
                    starts.append((JOBS[c][0], t))
                if g is not None:
                    next_gpu, next_gl = g, JOBS[g][2]
                    starts.append((JOBS[g][0], t))
                value, suffix = solve(t + 1, done, next_cpu,
                                      max(next_cl - 1, 0), next_gpu,
                                      max(next_gl - 1, 0))
                if value > best[0]:
                    best = value, tuple(starts) + suffix
        return best

    value, suffix = solve(0, 0, index["A"], 2, index["B"], 1)
    schedule = [{"job": job, "start": start} for job, start in (("A", 0), ("B", 0)) + suffix]
    return {"optimal_value": value, "witness": schedule,
            "states_explored": solve.cache_info().currsize}


@lru_cache(maxsize=1)
def _schedule_answer():
    return scheduling_oracle()


def _parse(text):
    raw = text.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", raw, re.S | re.I)
    payload = fenced.group(1) if fenced else raw
    try:
        value = json.loads(payload)
    except (ValueError, TypeError):
        return None, not bool(fenced)
    return value, not bool(fenced)


def _int(value):
    return type(value) is int


def _shape(value, required):
    return isinstance(value, dict) and set(value) == set(required)


def _grade_extraction(answer):
    expected = extraction_oracle()
    shape = _shape(answer, expected)
    checks = {"shape": shape}
    for key in expected:
        checks[key] = shape and answer.get(key) == expected[key]
    return checks, {"expected": expected}


def _grade_inventory(answer):
    keys = ("interleaving", "final_stock", "successful_reservations", "oversell_amount", "safe_fix", "atomic_sequential")
    shape = _shape(answer, keys)
    checks = {"shape": shape}
    expected_events = {who + "." + event for who in ("A", "B") for event in ("read", "check", "write")}
    events = answer.get("interleaving") if shape else None
    event_set = isinstance(events, list) and len(events) == 6 and all(isinstance(x, str) for x in events) and set(events) == expected_events
    checks["all_events_once"] = event_set
    stock = 6
    stage = {"A": 0, "B": 0}
    local = {}
    allowed = {}
    success = 0
    trace_valid = event_set
    if event_set:
        for event in events:
            who, action = event.split(".")
            required_stage = {"read": 0, "check": 1, "write": 2}[action]
            if stage[who] != required_stage:
                trace_valid = False
                break
            if action == "read":
                local[who] = stock
            elif action == "check":
                allowed[who] = local[who] >= 4
            elif not allowed[who]:
                trace_valid = False
                break
            else:
                stock = local[who] - 4
                success += 1
            stage[who] += 1
    checks["program_order_and_legal_writes"] = trace_valid
    checks["demonstrates_oversell"] = trace_valid and success == 2 and success * 4 > 6
    checks["final_stock"] = shape and _int(answer.get("final_stock")) and answer["final_stock"] == stock == 2
    checks["successful_reservations"] = shape and _int(answer.get("successful_reservations")) and answer["successful_reservations"] == success == 2
    checks["oversell_amount"] = shape and _int(answer.get("oversell_amount")) and answer["oversell_amount"] == 2
    checks["safe_fix"] = shape and answer.get("safe_fix") == "whole-function-lock"
    sequential = answer.get("atomic_sequential") if shape else None
    checks["atomic_sequential"] = _shape(sequential, ("results", "final_stock")) and sequential == {"results": [True, False, True], "final_stock": 3} and all(type(x) is bool for x in sequential["results"])
    return checks, {"simulated_final_stock": stock, "simulated_successes": success,
                    "correct_fix": "whole-function-lock"}


def _grade_schedule(answer):
    oracle = _schedule_answer()
    keys = ("schedule", "total_value", "makespan")
    shape = _shape(answer, keys)
    checks = {"shape": shape}
    entries = answer.get("schedule") if shape else None
    jobs = {row[0]: row for row in JOBS}
    row_shape = isinstance(entries, list) and bool(entries) and all(_shape(row, ("job", "start")) and isinstance(row["job"], str) and row["job"] in jobs and _int(row["start"]) for row in entries)
    checks["schedule_rows"] = row_shape
    unique = row_shape and len({row["job"] for row in entries}) == len(entries)
    checks["no_duplicate_jobs"] = unique
    starts = {row["job"]: row["start"] for row in entries} if unique else {}
    checks["fixed_roots"] = unique and starts.get("A") == starts.get("B") == 0
    checks["horizon"] = unique and all(0 <= start and start + jobs[name][2] <= HORIZON for name, start in starts.items())
    checks["dependencies"] = unique and all(all(dep in starts and starts[dep] + jobs[dep][2] <= start for dep in jobs[name][4]) for name, start in starts.items())
    no_overlap = unique
    for resource in ("CPU", "GPU"):
        ordered = sorted((start, start + jobs[name][2]) for name, start in starts.items() if jobs[name][1] == resource)
        no_overlap = no_overlap and all(left[1] <= right[0] for left, right in zip(ordered, ordered[1:]))
    checks["exclusive_resources"] = no_overlap
    total = sum(jobs[name][3] for name in starts)
    makespan = max((start + jobs[name][2] for name, start in starts.items()), default=0)
    checks["reported_value"] = shape and _int(answer.get("total_value")) and answer["total_value"] == total
    checks["reported_makespan"] = shape and _int(answer.get("makespan")) and answer["makespan"] == makespan
    feasible = all(checks[key] for key in ("shape", "schedule_rows", "no_duplicate_jobs", "fixed_roots", "horizon", "dependencies", "exclusive_resources"))
    checks["globally_optimal"] = feasible and total == oracle["optimal_value"]
    return checks, {"feasible": feasible, "actual_value": total, "optimal_value": oracle["optimal_value"], "oracle_states_explored": oracle["states_explored"]}


def grade(case, answerText):
    case_id = case["id"] if isinstance(case, dict) else case
    answer, json_only = _parse(answerText)
    graders = {"extract_ids": _grade_extraction, "inventory_race": _grade_inventory, "constrained_schedule": _grade_schedule}
    if case_id not in graders:
        raise ValueError("Unknown benchmark case")
    if answer is None:
        return {"passed": False, "checks": {"parseable_json": False}, "details": {"reason": "Response must be a JSON object, optionally in one JSON fence."}, "json_only": json_only}
    checks, details = graders[case_id](answer)
    # A lone JSON fence is recorded but does not turn a correct substantive answer into failure.
    return {"passed": all(checks.values()), "checks": checks, "details": details, "json_only": json_only}


def self_test():
    extract = extraction_oracle()
    inventory = {"interleaving": ["A.read", "B.read", "A.check", "B.check", "A.write", "B.write"], "final_stock": 2, "successful_reservations": 2, "oversell_amount": 2, "safe_fix": "whole-function-lock", "atomic_sequential": {"results": [True, False, True], "final_stock": 3}}
    oracle = _schedule_answer()
    makespan = max(row["start"] + dict((job[0], job[2]) for job in JOBS)[row["job"]] for row in oracle["witness"])
    schedule = {"schedule": oracle["witness"], "total_value": oracle["optimal_value"], "makespan": makespan}
    for case, answer in (("extract_ids", extract), ("inventory_race", inventory), ("constrained_schedule", schedule)):
        assert grade(case, json.dumps(answer))["passed"], (case, grade(case, json.dumps(answer)))
    bad_inventory = dict(inventory, interleaving=["A.read", "A.check", "A.write", "B.read", "B.check", "B.write"])
    assert not grade("inventory_race", json.dumps(bad_inventory))["passed"]
    bad_schedule = dict(schedule, schedule=[{"job": "A", "start": 0}, {"job": "B", "start": 0}], total_value=0, makespan=2)
    assert not grade("constrained_schedule", json.dumps(bad_schedule))["passed"]
    assert not grade("extract_ids", json.dumps(dict(extract, valid_rows=0)))["passed"]
    return {"self_test": "passed", "extraction": extract, "schedule_oracle": oracle}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--case")
    parser.add_argument("--answer")
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), indent=2))
    elif args.case and args.answer:
        print(json.dumps(grade(args.case, Path(args.answer).read_text()), indent=2))
    else:
        parser.error("Use --self-test or --case ID --answer PATH")
