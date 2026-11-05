"""Offline behavioral acceptance for portable provider routing.

Provider process boundaries are substituted with tiny local Python processes;
the controller, state transitions, command runner and result parser stay real.
No test invokes an AI provider or reads account credentials.
"""

import contextlib
import io
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import cross_cli_router as router


def model(mid, description="General-purpose model", efforts=("low", "medium", "high"),
          scope="model_catalog", alias=False):
    return {"id": mid, "description": description, "supported_efforts": list(efforts),
            "effort_support_scope": scope, "source": "acceptance_fixture", "is_alias": alias}


def provider(pid, models=None, available=True, ready=True, native=("low", "medium", "high")):
    return {"id": pid, "available": available, "dispatch_ready": ready,
            "executable": sys.executable, "native_efforts": list(native),
            "models": models if models is not None else [model(pid + "-model")],
            "controls": {}, "warnings": []}


def inventory(*providers, machine=None):
    return {"schema_version": 1, "machine_key": machine or router.machine_key(),
            "providers": list(providers)}


def plan(pid="claude", mid="model-a", effort=None):
    return {"schema_version": 1, "machine_key": router.machine_key(),
            "provider": pid, "model": mid, "effort": effort}


def local_command(stdout, code=0):
    """A provider boundary substitute, using an actual shell-free process."""
    def build(record, model=None, effort=None, prompt="", cwd=None, **kwargs):
        program = "import sys; sys.stdin.read(); sys.stdout.write(%r); sys.exit(%d)" % (stdout, code)
        return {"argv": [sys.executable, "-c", program], "stdin": prompt, "cwd": cwd,
                "environment": {}, "safety": {"tools_disabled": True}, "warnings": []}
    return build


def claude_result(text="OK", actual="model-a", **extra):
    result = {"type": "result", "subtype": "success", "is_error": False, "result": text}
    if actual is not None:
        result["modelUsage"] = {actual: {"inputTokens": 1, "outputTokens": 1}}
    result.update(extra)
    return json.dumps(result)


class OnboardingAcceptance(unittest.TestCase):
    def test_first_machine_asks_after_inventory_without_claiming_setup(self):
        inv = inventory(provider("codex"))
        status = router.onboarding_status(inv, {})
        self.assertTrue(status["question_required"])
        self.assertEqual(status["reason"], "first_use")
        self.assertFalse(status["blocks_already_authorized_providers"])

    def test_answer_persists_without_reasking_every_task(self):
        inv = inventory(provider("codex"))
        state = router.record_onboarding({"schema_version": 1}, inv, "no-additional")
        status = router.onboarding_status(inv, state)
        self.assertFalse(status["question_required"])
        self.assertEqual(status["answer"], "no-additional")

    def test_pending_question_is_not_silently_changed_to_declined(self):
        inv = inventory(provider("codex"))
        state = router.record_onboarding({"schema_version": 1}, inv, "pending")
        self.assertEqual(router.onboarding_status(inv, state)["answer"], "pending")
        self.assertFalse(state["machines"][inv["machine_key"]]["setup_authorized"])

    def test_new_provider_triggers_inventory_followup_but_upgrade_does_not(self):
        inv = inventory(provider("codex"))
        state = router.record_onboarding({"schema_version": 1}, inv, "no-additional")
        inv["providers"][0]["version"] = "new-version"
        self.assertFalse(router.onboarding_status(inv, state)["question_required"])
        inv["providers"].append(provider("claude"))
        status = router.onboarding_status(inv, state)
        self.assertTrue(status["question_required"])
        self.assertEqual(status["reason"], "providers_changed")

    def test_copied_state_does_not_onboard_another_machine(self):
        old = inventory(provider("claude"), machine="another-machine")
        state = router.record_onboarding({"schema_version": 1}, old, "no-additional")
        self.assertTrue(router.onboarding_status(inventory(provider("claude")), state)["question_required"])

    def test_additional_provider_request_is_not_setup_authorization(self):
        inv = inventory(provider("codex"))
        state = router.record_onboarding({"schema_version": 1}, inv, "additional", ["Ollama"])
        saved = state["machines"][inv["machine_key"]]
        self.assertEqual(saved["additional_providers"], ["Ollama"])
        self.assertFalse(saved["setup_authorized"])

    def test_additional_answer_needs_provider_name(self):
        with self.assertRaises(router.RouterError):
            router.record_onboarding({}, inventory(), "additional")

    def test_cli_rejects_onboarding_inventory_from_another_machine(self):
        with tempfile.TemporaryDirectory() as folder:
            inv_file, state_file = Path(folder) / "inventory.json", Path(folder) / "state.json"
            inv_file.write_text(json.dumps(inventory(provider("codex"), machine="other-machine")))
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                status = router.main(["--state", str(state_file), "onboard", "--inventory", str(inv_file), "--answer", "no-additional"])
            self.assertNotEqual(status, 0)
            self.assertFalse(state_file.exists())


class SelectionAcceptance(unittest.TestCase):
    def test_task_complexity_changes_provider_pair_from_advertised_roles(self):
        inv = inventory(provider("codex", [model("quick", "Fast lightweight low latency tasks")]),
                        provider("claude", [model("deep", "Advanced complex reasoning")]))
        light = router.select_plan(inv, complexity="light")
        deep = router.select_plan(inv, complexity="deep")
        self.assertEqual((light["provider"], light["model"], light["effort"]), ("codex", "quick", "low"))
        self.assertEqual((deep["provider"], deep["model"], deep["effort"]), ("claude", "deep", "high"))

    def test_explicit_task_preferences_override_starting_role_heuristic(self):
        inv = inventory(provider("codex", [model("code", "Advanced complex reasoning")]),
                        provider("claude", [model("write", "General purpose")]))
        prefs = {"task_provider_order": {"writing": ["claude", "codex"], "coding": ["codex", "claude"]}}
        writing = router.select_plan(inv, complexity="deep", task_kind="writing", preferences=prefs)
        coding = router.select_plan(inv, complexity="deep", task_kind="coding", preferences=prefs)
        self.assertEqual(writing["provider"], "claude")
        self.assertEqual(coding["provider"], "codex")

    def test_explicit_model_and_effort_locks_survive_complexity_change(self):
        inv = inventory(provider("codex", [model("locked"), model("stronger", "Frontier most capable")]))
        result = router.select_plan(inv, complexity="intensive", provider="codex", model="locked", effort="medium")
        self.assertEqual((result["model"], result["effort"]), ("locked", "medium"))
        self.assertEqual(result["routing_status"], "recommended")
        self.assertFalse(result["parent_settings_changed"])

    def test_unknown_model_lock_fails_instead_of_falling_back(self):
        with self.assertRaises(router.RouterError):
            router.select_plan(inventory(provider("codex")), provider="codex", model="not-discovered")

    def test_unavailable_locked_provider_fails_instead_of_switching(self):
        with self.assertRaises(router.RouterError):
            router.select_plan(inventory(provider("claude", available=False), provider("codex")), provider="claude")

    def test_provider_with_known_missing_login_is_not_auto_selected(self):
        missing = provider("claude", [model("apparently-best", "Fast lightweight low latency simple")])
        missing["authentication"] = {"status": "missing", "source": "native_auth_status"}
        usable = provider("codex", [model("usable", "General purpose")])
        inv = inventory(missing, usable)
        result = router.select_plan(inv, complexity="light", preferences={"task_provider_order": {"general": ["claude", "codex"]}})
        self.assertEqual(result["provider"], "codex")
        with self.assertRaises(router.RouterError):
            router.select_plan(inv, provider="claude")

    def test_unknown_authentication_does_not_claim_missing_login(self):
        unknown = provider("agy")
        unknown["authentication"] = {"status": "unknown"}
        self.assertEqual(router.select_plan(inventory(unknown))["provider"], "agy")

    def test_model_lock_needs_provider_namespace(self):
        with self.assertRaises(router.RouterError):
            router.select_plan(inventory(provider("codex")), model="codex-model")

    def test_unsupported_effort_lock_is_not_clamped(self):
        with self.assertRaises(router.RouterError):
            router.select_plan(inventory(provider("codex")), provider="codex", effort="ultra")

    def test_installed_but_not_dispatchable_provider_is_ineligible(self):
        inv = inventory(provider("claude", [model("broken", "Fast lightweight simple")], ready=False),
                        provider("codex", [model("usable", "General purpose")]))
        self.assertEqual(router.select_plan(inv, complexity="light")["provider"], "codex")

    def test_catalog_with_no_effort_does_not_inherit_another_models_levels(self):
        inv = inventory(provider("codex", [model("no-thinking", efforts=())], native=("low", "medium", "high")))
        result = router.select_plan(inv, provider="codex", model="no-thinking", complexity="deep")
        self.assertIsNone(result["effort"])
        with self.assertRaises(router.RouterError):
            router.select_plan(inv, provider="codex", model="no-thinking", effort="high")

    def test_configured_default_without_model_catalog_omits_effort(self):
        inv = inventory(provider("claude", [], native=("low", "medium", "high")))
        result = router.select_plan(inv, provider="claude", complexity="deep")
        self.assertIsNone(result["model"])
        self.assertIsNone(result["effort"])

    def test_provider_without_native_effort_omits_it(self):
        inv = inventory(provider("gemini", [model("flash", efforts=(), scope="none", alias=True)], native=()))
        self.assertIsNone(router.select_plan(inv, complexity="intensive")["effort"])
        with self.assertRaises(router.RouterError):
            router.select_plan(inv, provider="gemini", effort="high")

    def test_gemini_native_thinking_level_case_is_preserved(self):
        gemini = provider("gemini", [model("gemini-3-flash-preview", efforts=("LOW", "HIGH"), scope="model_config")], native=())
        inv = inventory(gemini)
        self.assertEqual(router.select_plan(inv, complexity="light")["effort"], "LOW")
        self.assertEqual(router.select_plan(inv, complexity="deep")["effort"], "HIGH")
        self.assertEqual(router.select_plan(inv, provider="gemini", effort="HIGH")["effort"], "HIGH")
        with self.assertRaises(router.RouterError):
            router.select_plan(inv, provider="gemini", effort="high")

    def test_exact_catalog_variant_chooses_matching_effort(self):
        variants = [model("variant-low", efforts=("low",), scope="catalog_variant"),
                    model("variant-high", efforts=("high",), scope="catalog_variant")]
        inv = inventory(provider("agy", variants))
        result = router.select_plan(inv, provider="agy", complexity="deep")
        self.assertEqual((result["model"], result["effort"]), ("variant-high", "high"))


class ExecutionAcceptance(unittest.TestCase):
    def execute(self, stdout, *, requested=None, record=None, expected="OK", exit_code=0):
        requested = requested or plan()
        record = record or provider("claude", [model("model-a")])
        with patch.object(router.adapters, "discover_provider", return_value=record) as discovery, \
             patch.object(router.adapters, "build_command", side_effect=local_command(stdout, exit_code)):
            result = router.execute_plan(requested, "Synthetic task", expected=expected, timeout=5)
        discovery.assert_called_once_with(requested["provider"], include_models=True)
        return result

    def test_actual_process_and_metadata_establish_separate_answer_and_model_checks(self):
        result = self.execute(claude_result())
        self.assertTrue(result["dispatch_succeeded"])
        self.assertTrue(result["model_verified"])
        self.assertFalse(result["effort_verified"])
        self.assertEqual(result["answer_check"], "passed")
        self.assertFalse(result["parent_settings_changed"])

    def test_matching_answer_does_not_verify_requested_effort(self):
        result = self.execute(claude_result(), requested=plan(effort="high"))
        self.assertEqual(result["routing_status"], "unverified")
        self.assertEqual(result["answer_check"], "passed")

    def test_explicit_effective_effort_allows_verification(self):
        result = self.execute(claude_result(effective_effort="high"), requested=plan(effort="high"))
        self.assertTrue(result["effort_verified"])
        self.assertEqual(result["routing_status"], "verified")

    def test_provider_error_is_failure_even_with_zero_exit_and_expected_text(self):
        result = self.execute(claude_result(is_error=True, subtype="error"))
        self.assertFalse(result["dispatch_succeeded"])
        self.assertEqual(result["routing_status"], "error")
        self.assertEqual(result["answer_check"], "error")

    def test_nonzero_process_exit_is_failure_even_with_success_json(self):
        result = self.execute(claude_result(), exit_code=7)
        self.assertFalse(result["dispatch_succeeded"])
        self.assertEqual(result["routing_status"], "error")
        self.assertEqual(result["answer_check"], "error")

    def test_unstructured_success_sounding_output_is_not_accepted(self):
        result = self.execute("OK")
        self.assertFalse(result["dispatch_succeeded"])
        self.assertEqual(result["answer_check"], "error")

    def test_authentication_failure_remains_prerequisite_not_wrong_answer(self):
        result = self.execute(claude_result(text="Not logged in. Please run /login", actual=None,
                                          is_error=True, subtype="error_during_execution"))
        self.assertEqual(result["answer_check"], "error")
        self.assertEqual(result["error_category"], "authentication")
        self.assertEqual(result["failure_class"], "prerequisite")

    def test_assistant_self_report_does_not_verify_model(self):
        text = "I used model-a with high effort."
        result = self.execute(claude_result(text=text, actual=None), expected=text, requested=plan(effort="high"))
        self.assertTrue(result["dispatch_succeeded"])
        self.assertEqual(result["answer_check"], "passed")
        self.assertFalse(result["model_verified"])
        self.assertFalse(result["effort_verified"])
        self.assertEqual(result["routing_status"], "unverified")

    def test_literal_model_mismatch_is_routing_error(self):
        result = self.execute(claude_result(actual="different-model"))
        self.assertTrue(result["model_mismatch"])
        self.assertFalse(result["model_verified"])
        self.assertEqual(result["routing_status"], "error")

    def test_known_alias_resolution_is_not_literal_model_mismatch(self):
        result = self.execute(claude_result(actual="concrete-sonnet-build"), requested=plan(mid="sonnet"),
                              record=provider("claude", [model("sonnet", alias=True)]))
        self.assertFalse(result["model_mismatch"])
        self.assertTrue(result["model_verified"])

    def test_effort_mismatch_is_routing_error(self):
        result = self.execute(claude_result(effective_effort="low"), requested=plan(effort="high"))
        self.assertTrue(result["effort_mismatch"])
        self.assertFalse(result["effort_verified"])
        self.assertEqual(result["routing_status"], "error")

    def test_answer_failure_does_not_become_passed_from_verified_settings(self):
        result = self.execute(claude_result(text="WRONG", effective_effort="high"), requested=plan(effort="high"))
        self.assertEqual(result["routing_status"], "verified")
        self.assertEqual(result["answer_check"], "failed")

    def test_external_plan_from_another_machine_never_dispatches(self):
        request = plan()
        request["machine_key"] = "another-machine"
        with patch.object(router.adapters, "discover_provider") as discovery, \
             patch.object(router.adapters, "build_command") as build:
            with self.assertRaises(router.RouterError):
                router.execute_plan(request, "task")
        discovery.assert_not_called()
        build.assert_not_called()

    def test_fresh_missing_login_blocks_a_previously_saved_plan(self):
        missing = provider("claude", [model("model-a")])
        missing["authentication"] = {"status": "missing"}
        with patch.object(router.adapters, "discover_provider", return_value=missing), \
             patch.object(router.adapters, "build_command") as build:
            with self.assertRaises(router.RouterError):
                router.execute_plan(plan(), "task")
        build.assert_not_called()

    def test_saved_plan_cannot_supply_an_executable_or_shell_command(self):
        request = plan()
        request.update(executable="/not/a/provider", argv=["/bin/sh", "-c", "exit 99"])
        result = self.execute(claude_result(), requested=request)
        self.assertTrue(result["dispatch_succeeded"])

    def test_shell_metacharacters_in_handoff_stay_literal(self):
        with tempfile.TemporaryDirectory() as folder:
            sentinel = Path(folder) / "should-not-exist"
            prompt = "$(touch '%s'); `touch '%s'`" % (sentinel, sentinel)
            program = "import sys,json; print(json.dumps({'type':'result','is_error':False,'subtype':'success','result':sys.stdin.read()}))"
            def build(record, model=None, effort=None, prompt="", cwd=None, **kwargs):
                return {"argv": [sys.executable, "-c", program], "stdin": prompt, "cwd": cwd}
            with patch.object(router.adapters, "discover_provider", return_value=provider("claude")), \
                 patch.object(router.adapters, "build_command", side_effect=build):
                result = router.execute_plan(plan(), prompt, expected=prompt, timeout=5)
            self.assertEqual(result["answer_check"], "passed")
            self.assertFalse(sentinel.exists())

    def test_process_timeout_is_bounded_and_terminates_local_child(self):
        result = router.bounded_process({"argv": [sys.executable, "-c", "import time; time.sleep(20)"]}, .15)
        self.assertTrue(result["timed_out"])
        self.assertNotEqual(result["exit_code"], 0)
        self.assertLess(result["elapsed_seconds"], 5)

    def test_diagnostics_are_opt_in_and_private_and_scratch_is_cleaned(self):
        raw = claude_result()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            scratch, diagnostics = root / "scratch", root / "private-diagnostics"
            scratch.mkdir()
            with patch.object(router.adapters, "discover_provider", return_value=provider("claude")), \
                 patch.object(router.adapters, "build_command", side_effect=local_command(raw)):
                result = router.execute_plan(plan(), "task", expected="OK", scratch_root=scratch)
                self.assertEqual(result["answer_check"], "passed")
                self.assertEqual(list(root.iterdir()), [scratch])
                self.assertEqual(list(scratch.iterdir()), [])
                result = router.execute_plan(plan(), "task", expected="OK", scratch_root=scratch,
                                             diagnostics_dir=diagnostics)
            files = list(diagnostics.glob("*.json"))
            self.assertEqual(len(files), 1)
            self.assertEqual(json.loads(files[0].read_text())["stdout"], raw)
            self.assertEqual(list(scratch.iterdir()), [])
            if os.name == "posix":
                self.assertEqual(stat.S_IMODE(files[0].stat().st_mode), 0o600)

    def test_smoke_with_no_available_provider_is_not_a_successful_test(self):
        with tempfile.TemporaryDirectory() as folder:
            inv_file = Path(folder) / "inventory.json"
            inv_file.write_text(json.dumps(inventory()))
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                status = router.main(["--state", str(Path(folder) / "state.json"), "smoke", "--inventory", str(inv_file), "--execute"])
            self.assertNotEqual(status, 0)

    def test_smoke_records_missing_login_without_inference(self):
        missing = provider("claude")
        missing["authentication"] = {"status": "missing"}
        with tempfile.TemporaryDirectory() as folder:
            inv_file = Path(folder) / "inventory.json"
            inv_file.write_text(json.dumps(inventory(missing)))
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(io.StringIO()), \
                 patch.object(router.adapters, "discover_provider") as discovery, \
                 patch.object(router.adapters, "build_command") as build:
                status = router.main(["--state", str(Path(folder) / "state.json"), "smoke", "--inventory", str(inv_file), "--execute"])
            result = json.loads(stdout.getvalue())["results"][0]
            self.assertNotEqual(status, 0)
            self.assertFalse(result["inference_sent"])
            self.assertEqual(result["answer_check"], "error")
            discovery.assert_not_called()
            build.assert_not_called()


if __name__ == "__main__":
    unittest.main()
