#!/usr/bin/env python3
"""Portable discovery, onboarding, planning and bounded text delegation.

The calling agent assesses the task. This controller validates and executes a
separate CLI run; it never changes the model of an existing desktop chat.
"""

import argparse
import concurrent.futures
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone

import provider_adapters as adapters


PROVIDERS = ("claude", "agy", "codex", "gemini")
EXTRA_EXECUTABLES = ("ollama", "lms", "opencode", "aider")
COMPLEXITIES = ("light", "standard", "deep", "intensive")
NATIVE_TARGETS = {"light": "low", "standard": "medium", "deep": "high", "intensive": "max"}
EFFORT_ORDER = ("minimal", "low", "medium", "high", "xhigh", "max", "ultra")
ROLE_HINTS = {
    "light": ("fast", "lightweight", "low latency", "simple", "small"),
    "standard": ("general", "balanced", "versatile", "everyday", "workhorse"),
    "deep": ("complex", "reasoning", "demanding", "advanced", "frontier"),
    "intensive": ("most capable", "strongest", "most demanding", "frontier"),
}


class RouterError(ValueError):
    pass


def now():
    return datetime.now(timezone.utc).isoformat()


def state_path():
    base = os.environ.get("XDG_STATE_HOME")
    if base:
        return Path(base) / "dynamic-model-router" / "state.json"
    if os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"]) / "dynamic-model-router" / "state.json"
    return Path.home() / ".local" / "state" / "dynamic-model-router" / "state.json"


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RouterError("Cannot read valid JSON: " + str(path)) from exc


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Atomic replacement; state may contain preferences but never credentials.
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=str(path.parent), delete=False) as stream:
        temp = Path(stream.name)
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    try:
        os.chmod(temp, 0o600)
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def machine_key():
    identity = "|".join((platform.system(), platform.node(), str(Path.home())))
    return hashlib.sha256(identity.encode()).hexdigest()[:20]


def load_state(path):
    if not Path(path).exists():
        return {"schema_version": 1, "machines": {}, "preferences": {}}
    value = read_json(path)
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise RouterError("Unsupported state schema")
    if not isinstance(value.get("machines", {}), dict) or not isinstance(value.get("preferences", {}), dict):
        raise RouterError("Invalid state")
    return value


def onboarding_status(inventory, state):
    key = inventory["machine_key"]
    previous = state.get("machines", {}).get(key, {})
    present = sorted(p["id"] for p in inventory["providers"] if p.get("available"))
    # Tool upgrades do not make us ask the same optional question again.
    new_providers = sorted(set(present) - set(previous.get("providers", [])))
    needs_question = not previous.get("asked_at") or bool(new_providers)
    return {
        "question_required": needs_question,
        "reason": "first_use" if not previous.get("asked_at") else "providers_changed" if new_providers else "already_asked",
        "answer": previous.get("answer", "not_asked"),
        "additional_providers": previous.get("additional_providers", []),
        "question_en": "I found these providers on this machine. Do you have other models or services you want help setting up and using? Name them; do not paste API keys.",
        "question_th": "ตรวจพบ provider เหล่านี้ในเครื่องแล้วค่ะ มีโมเดลหรือบริการอื่นที่อยากให้ช่วยตั้งค่าและเพิ่มให้เรียกใช้ไหมคะ? ระบุชื่อได้เลย โดยไม่ต้องส่ง API key ในแชตค่ะ",
        "blocks_already_authorized_providers": False,
    }


def discover(*, include_models=False, state=None):
    def one(name):
        try:
            value = adapters.discover_provider(name, include_models=include_models)
            value.setdefault("id", name)
            return value
        except Exception as exc:
            return {"id": name, "available": False, "models": [], "discovery_status": "error", "error_type": type(exc).__name__}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        records = list(pool.map(one, PROVIDERS))
    result = {
        "schema_version": 1,
        "created_at": now(),
        "machine_key": machine_key(),
        "platform": platform.system(),
        "providers": records,
        "other_cli_hints": [{"executable": name, "path": path, "adapter_ready": False}
                            for name in EXTRA_EXECUTABLES if (path := shutil.which(name))],
        "limits": "CLI presence is not authentication or model access. No secrets are read. Extra CLI hints are not registered adapters.",
    }
    result["onboarding"] = onboarding_status(result, state or {})
    return result


def record_onboarding(state, inventory, answer, extras=()):
    if answer not in ("pending", "no-additional", "additional"):
        raise RouterError("Unknown onboarding answer")
    if answer == "additional" and not extras:
        raise RouterError("Name the additional provider(s); do not store credentials")
    if any(not isinstance(name, str) or len(name) > 100 or "\n" in name for name in extras):
        raise RouterError("Additional provider names must be short plain text")
    result = json.loads(json.dumps(state))
    result.setdefault("machines", {})[inventory["machine_key"]] = {
        "asked_at": now(), "answer": answer,
        "providers": sorted(p["id"] for p in inventory["providers"] if p.get("available")),
        "additional_providers": list(extras),
        "setup_authorized": False,
    }
    return result


def model_id(model):
    return model.get("id", model.get("model"))


def effort_for(record, model, complexity, lock=None):
    if model_id(model) is None:
        if lock is not None:
            raise RouterError("An explicit effort requires an identified model")
        return None, "default_unexposed"
    levels = model.get("supported_efforts", [])
    scope = model.get("effort_support_scope", record.get("effort_support_scope", "unknown"))
    if not levels and scope not in ("catalog_variant", "model_catalog", "none"):
        levels = record.get("native_efforts", [])
    if lock is not None:
        if lock not in levels:
            raise RouterError("Requested effort is not advertised for this candidate")
        return lock, scope
    target = NATIVE_TARGETS[complexity]
    exact_target = next((level for level in levels if level.lower() == target), None)
    if exact_target is not None:
        return exact_target, scope
    known = [level for level in levels if level.lower() in EFFORT_ORDER]
    if known:
        target_index = EFFORT_ORDER.index(target)
        return min(known, key=lambda value: (abs(EFFORT_ORDER.index(value.lower()) - target_index), EFFORT_ORDER.index(value.lower()))), scope
    # Omit unsupported reasoning controls. Never invent --effort for Gemini.
    return None, "default_unexposed"


def select_plan(inventory, *, complexity="standard", task_kind="general", provider=None,
                model=None, effort=None, preferences=None, current_provider=None):
    if complexity not in COMPLEXITIES:
        raise RouterError("Unsupported task complexity")
    if provider is not None and provider not in PROVIDERS:
        raise RouterError("Provider has no installed adapter; discover and set it up first")
    if model is not None and provider is None:
        raise RouterError("A model lock requires its provider; model IDs are not universal")
    preferences = preferences or {}
    preferred = preferences.get("task_provider_order", {}).get(task_kind, [])
    if not isinstance(preferred, list) or any(p not in PROVIDERS for p in preferred):
        raise RouterError("Invalid task provider preference")
    candidates = []
    for record in inventory.get("providers", []):
        pid = record.get("id")
        if pid not in PROVIDERS or not record.get("available") or record.get("dispatch_ready") is False or (provider and pid != provider):
            continue
        if record.get("authentication", {}).get("status") == "missing":
            continue
        models = record.get("models", [])
        if not models:
            # An existing CLI may only expose its configured default. Do not
            # pretend we discovered account-specific IDs or effort support.
            models = [{"id": None, "description": "Configured CLI default", "supported_efforts": []}]
        for entry in models:
            mid = model_id(entry)
            if model is not None and mid != model:
                continue
            try:
                native_effort, support_scope = effort_for(record, entry, complexity, effort)
            except RouterError:
                continue
            description = str(entry.get("description", "")).lower()
            role_score = sum(hint in description for hint in ROLE_HINTS[complexity])
            pref_score = len(preferred) - preferred.index(pid) if pid in preferred else 0
            target = NATIVE_TARGETS[complexity]
            fit = 0 if native_effort is None else 7 - abs(EFFORT_ORDER.index(native_effort.lower()) - EFFORT_ORDER.index(target)) if native_effort.lower() in EFFORT_ORDER else 0
            # Explicit user preferences first. Description-based task hints
            # are a starting policy, not a comparative benchmark claim.
            score = (pref_score, role_score, fit, int(pid == current_provider), int(bool(entry.get("is_default"))))
            candidates.append((score, record, entry, native_effort, support_scope))
    if not candidates:
        raise RouterError("No discovered candidate satisfies the requested provider/model/effort locks")
    _, record, entry, selected_effort, scope = max(candidates, key=lambda item: item[0])
    result = {
        "schema_version": 1, "created_at": now(), "machine_key": inventory["machine_key"],
        "scope": "external-run", "routing_status": "recommended",
        "provider": record["id"], "model": model_id(entry), "effort": selected_effort,
        "complexity": complexity, "task_kind": task_kind,
        "locks": {"provider": provider, "model": model, "effort": effort},
        "model_source": entry.get("source", record.get("model_source", "configured_default")),
        "effort_support_scope": scope,
        "selection_basis": "Explicit task preferences, then advertised description and native effort fit; stable tie-breaks. This is not a measured cross-provider quality ranking.",
        "onboarding": inventory.get("onboarding", {}),
        "parent_settings_changed": False,
    }
    return result


def bounded_process(command, timeout):
    if not math.isfinite(timeout) or timeout <= 0:
        raise RouterError("Timeout must be positive and finite")
    argv = command["argv"]
    if not isinstance(argv, list) or not argv or any(not isinstance(x, str) or "\x00" in x for x in argv):
        raise RouterError("Invalid argument vector")
    env = os.environ.copy()
    env.update(command.get("environment", {}))
    kwargs = {"cwd": command.get("cwd"), "env": env, "stdin": subprocess.PIPE,
              "stdout": subprocess.PIPE, "stderr": subprocess.PIPE, "text": True,
              "encoding": "utf-8", "errors": "replace"}
    if os.name == "posix":
        kwargs["start_new_session"] = True
    elif os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    started = time.monotonic()
    process = subprocess.Popen(argv, **kwargs)
    timed_out = False
    try:
        stdout, stderr = process.communicate(input=command.get("stdin"), timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        if os.name == "posix":
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        else:
            # Terminate descendants too; never leave a timed-out provider run.
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, timeout=10)
        stdout, stderr = process.communicate(timeout=10)
    return {"stdout": stdout, "stderr": stderr, "exit_code": process.returncode,
            "timed_out": timed_out, "elapsed_seconds": round(time.monotonic() - started, 3)}


def execute_plan(plan, prompt, *, timeout=180, expected=None, record=None, scratch_root=None, diagnostics_dir=None):
    if plan.get("machine_key") != machine_key():
        raise RouterError("Plan belongs to another machine; discover this machine first")
    pid = plan.get("provider")
    if pid not in PROVIDERS:
        raise RouterError("No supported provider adapter")
    if not isinstance(prompt, str) or not prompt.strip():
        raise RouterError("A nonempty task is required")
    # Never trust an executable or argument list embedded in a saved plan.
    record = record or adapters.discover_provider(pid, include_models=True)
    if not record.get("available"):
        raise RouterError("Selected provider is no longer available; re-discover before dispatch")
    if record.get("authentication", {}).get("status") == "missing":
        raise RouterError("Selected provider requires login; no inference was sent")
    if scratch_root is not None and not Path(scratch_root).is_dir():
        raise RouterError("Scratch root must be an existing, user-authorized directory")
    with tempfile.TemporaryDirectory(prefix="dynamic-model-router-", dir=scratch_root) as folder:
        extra = {}
        if pid == "gemini" and hasattr(adapters, "GEMINI_DENY_TOOLS_POLICY"):
            policy = Path(folder) / "deny-tools.toml"
            policy.write_text(adapters.GEMINI_DENY_TOOLS_POLICY, encoding="utf-8")
            extra["policy_path"] = str(policy)
        command = adapters.build_command(record, model=plan.get("model"), effort=plan.get("effort"),
                                         prompt=prompt, cwd=folder, **extra)
        for artifact in command.get("files", []):
            rel = Path(artifact["path"])
            if rel.is_absolute() or ".." in rel.parts:
                raise RouterError("Run-local configuration must stay in the temporary directory")
            dest = Path(folder) / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(artifact["text"], encoding="utf-8")
        raw = bounded_process(command, timeout)
        if diagnostics_dir is not None:
            # Opt-in local diagnostics let a parser be fixed without replaying
            # an inference. Never bundle these files into the portable skill.
            diagnostic_path = Path(diagnostics_dir) / (pid + "-" + str(time.time_ns()) + ".json")
            write_json(diagnostic_path, {"provider": pid, "requested": command.get("requested"), **raw})
        parsed = adapters.parse_runtime_result(pid, raw["stdout"], raw["stderr"])
    process_ok = raw["exit_code"] == 0 and not raw["timed_out"]
    transport_ok = process_ok and not parsed.get("is_error", False) and parsed.get("success") is True
    answer = parsed.get("text", "")
    check = "unavailable" if expected is None else "error" if not transport_ok else "passed" if answer.strip() == expected else "failed"
    effective_model = parsed.get("model")
    effective_effort = parsed.get("effort")
    is_alias = any(model_id(m) == plan.get("model") and (m.get("is_alias") or m.get("source") == "cli_help_alias") for m in record.get("models", []))
    mismatch = bool(plan.get("model") and effective_model and effective_model != plan["model"] and not is_alias)
    effort_mismatch = bool(plan.get("effort") and effective_effort and effective_effort != plan["effort"])
    exact_model = bool(parsed.get("model_verified") and effective_model and not mismatch)
    exact_effort = bool(parsed.get("effort_verified") and effective_effort and not effort_mismatch)
    status = "error" if not transport_ok or mismatch or effort_mismatch else "verified" if exact_model and (plan.get("effort") is None or exact_effort) else "unverified"
    return {
        "schema_version": 1, "created_at": now(), "provider": pid, "scope": "external-run",
        "requested": {"model": plan.get("model"), "effort": plan.get("effort")},
        "effective": {"model": effective_model, "effort": effective_effort},
        "routing_status": status,
        "model_verified": exact_model, "effort_verified": exact_effort,
        "model_mismatch": mismatch, "effort_mismatch": effort_mismatch,
        "answer_check": check, "dispatch_succeeded": bool(transport_ok),
        "process_succeeded": process_ok,
        "elapsed_seconds": raw["elapsed_seconds"], "timed_out": raw["timed_out"], "exit_code": raw["exit_code"],
        "text": answer, "safety": command.get("safety", {}),
        "warnings": parsed.get("warnings", []) + command.get("warnings", []),
        "error": (parsed.get("error") or parsed.get("errors")) if not transport_ok else None,
        "error_category": parsed.get("error_category") if not transport_ok else None,
        "failure_class": parsed.get("failure_class") if not transport_ok else None,
        "runtime_evidence": parsed.get("metadata", []),
        "models_used": parsed.get("models_used", []),
        "parent_settings_changed": False,
    }


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--state", type=Path, default=state_path(), help="Per-user onboarding/preferences; no credentials")
    sub = p.add_subparsers(dest="command", required=True)
    d = sub.add_parser("discover", help="Detect this machine before routing; no inference requests")
    d.add_argument("--models", action="store_true", help="Also query supported model metadata; may contact signed-in provider")
    d.add_argument("--output", type=Path)
    o = sub.add_parser("onboard", help="Record a question already shown and the user's actual answer")
    o.add_argument("--inventory", type=Path, required=True)
    o.add_argument("--answer", choices=("pending", "no-additional", "additional"), required=True)
    o.add_argument("--extra", action="append", default=[])
    s = sub.add_parser("plan", help="Choose a supported external pair; no model request")
    s.add_argument("--inventory", type=Path, required=True)
    s.add_argument("--complexity", choices=COMPLEXITIES, default="standard")
    s.add_argument("--task-kind", default="general")
    s.add_argument("--provider", choices=PROVIDERS)
    s.add_argument("--model")
    s.add_argument("--effort")
    s.add_argument("--current-provider", choices=PROVIDERS)
    s.add_argument("--output", type=Path)
    r = sub.add_parser("run", help="Run an authorized text handoff in an isolated temporary directory")
    r.add_argument("--plan", type=Path, required=True)
    r.add_argument("--task-file", type=Path, required=True)
    r.add_argument("--timeout", type=float, default=180)
    r.add_argument("--scratch-root", type=Path, help="Existing project directory for temporary runs; required if a provider trusts only this project")
    r.add_argument("--diagnostics-dir", type=Path, help="Opt-in private raw diagnostics; never distribute or put credentials in task packets")
    r.add_argument("--expected", help="Exact deterministic text check, when appropriate")
    r.add_argument("--execute", action="store_true", help="Dispatch; without this, show the plan only")
    r.add_argument("--output", type=Path)
    t = sub.add_parser("smoke", help="One small, independently checked inference per selected provider")
    t.add_argument("--inventory", type=Path, required=True)
    t.add_argument("--provider", choices=PROVIDERS, action="append")
    t.add_argument("--timeout", type=float, default=180)
    t.add_argument("--scratch-root", type=Path)
    t.add_argument("--diagnostics-dir", type=Path)
    t.add_argument("--execute", action="store_true")
    t.add_argument("--output", type=Path)
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        state = load_state(args.state)
        if args.command == "discover":
            result = discover(include_models=args.models, state=state)
        elif args.command == "onboard":
            inv = read_json(args.inventory)
            if inv.get("machine_key") != machine_key():
                raise RouterError("Inventory belongs to another machine")
            state = record_onboarding(state, inv, args.answer, args.extra)
            write_json(args.state, state)
            result = onboarding_status(inv, state)
        elif args.command == "plan":
            inv = read_json(args.inventory)
            if inv.get("machine_key") != machine_key():
                raise RouterError("Discover this machine before planning")
            result = select_plan(inv, complexity=args.complexity, task_kind=args.task_kind,
                                 provider=args.provider, model=args.model, effort=args.effort,
                                 preferences=state.get("preferences"), current_provider=args.current_provider)
        elif args.command == "run":
            plan = read_json(args.plan)
            result = execute_plan(plan, args.task_file.read_text(encoding="utf-8"), timeout=args.timeout, expected=args.expected, scratch_root=args.scratch_root, diagnostics_dir=args.diagnostics_dir) if args.execute else {"dispatch": "not_requested", "plan": plan}
        else:
            inv = read_json(args.inventory)
            if inv.get("machine_key") != machine_key():
                raise RouterError("Discover this machine before smoke testing")
            selected = args.provider or [r["id"] for r in inv["providers"] if r.get("available") and r.get("dispatch_ready") is not False]
            if not selected:
                raise RouterError("No dispatch-ready providers were discovered")
            results = []
            for pid in selected:
                try:
                    plan = select_plan(inv, complexity="light", task_kind="lookup", provider=pid)
                except RouterError as exc:
                    results.append({"provider": pid, "routing_status": "error", "answer_check": "error", "dispatch_succeeded": False, "error": str(exc), "inference_sent": False})
                    continue
                if not args.execute:
                    results.append(plan)
                    continue
                nonce = os.urandom(5).hex()
                expected = "3,5,17|25|" + nonce
                prompt = "Do not call tools or access files. Sort 17,3,5 ascending and compute their sum. Reply in exactly this format, without spaces or markdown: comma-separated-numbers|sum|" + nonce
                # Each provider gets one repeat-safe computation. There is no
                # automatic retry, provider fallback or external action replay.
                try:
                    item = execute_plan(plan, prompt, timeout=args.timeout, expected=expected, scratch_root=args.scratch_root, diagnostics_dir=args.diagnostics_dir)
                except Exception as exc:
                    item = {"provider": pid, "routing_status": "error", "answer_check": "error", "dispatch_succeeded": False, "error_type": type(exc).__name__, "error": str(exc)}
                results.append(item)
                print(json.dumps({"provider": pid, "routing_status": item["routing_status"], "answer_check": item["answer_check"]}), file=sys.stderr, flush=True)
            result = {"schema_version": 1, "created_at": now(), "results": results, "test_scope": "Transport and one synthetic answer; not a task-suitability benchmark"}
        if getattr(args, "output", None):
            write_json(args.output, result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if args.command == "run" and args.execute:
            return 0 if result["dispatch_succeeded"] and result["routing_status"] != "error" and result["answer_check"] != "failed" else 1
        if args.command == "smoke" and args.execute:
            return 0 if all(item.get("dispatch_succeeded") and item.get("answer_check") == "passed" and item.get("routing_status") != "error" for item in result["results"]) else 1
        return 0
    except (RouterError, OSError, ValueError) as exc:
        print(json.dumps({"status": "error", "error_type": type(exc).__name__, "message": str(exc)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
