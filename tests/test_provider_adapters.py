"""Offline acceptance checks for provider boundaries and runtime evidence."""

import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "provider_adapters.py"
SPEC = importlib.util.spec_from_file_location("provider_adapters", SCRIPT)
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


CLAUDE_HELP = """
 --print Print response
 --output-format <format> text, json, stream-json
 --effort <level> Effort level (low, medium, high, xhigh, max)
 --model <model> Alias (e.g. 'fable', 'opus', or 'sonnet') or full name
                 (e.g. 'claude-fable-5').
 --tools <tools...> Use empty string to disable tools
 --permission-mode <mode> dontAsk, plan
 --strict-mcp-config Use only explicit MCP servers
 --mcp-config <config> JSON configuration
 --safe-mode Disable customizations
 --disable-slash-commands Disable skills
 --no-session-persistence No session persistence
 --no-chrome Disable browser integration
"""
AGY_HELP = """
 --print Single prompt
 --model Model for session
 --effort Reasoning effort (low|medium|high|xhigh|max)
 --output-format Output JSON
 --mode Session mode (accept-edits, auto, plan)
 --sandbox Restrict terminal
 --disable-slash-commands Disable skills
"""
CODEX_HELP = """
 --model <MODEL>
 --config <key=value>
 --ask-for-approval <policy>
 --sandbox <mode>
 --json JSON events
 --skip-git-repo-check Allow scratch workspace
 --ephemeral No stored session
"""
GEMINI_HELP = """
 --model Model
 --prompt Prompt
 --output-format Output format
 --approval-mode plan
 --extensions Extensions
 --policy Additional policy files
"""


def discover(name, include_models=False, catalog=""):
    helps = {"claude": CLAUDE_HELP, "agy": AGY_HELP, "codex": CODEX_HELP, "gemini": GEMINI_HELP}

    def run(argv, timeout):
        if argv[-1] == "models":
            return catalog
        if argv[-1] == "--version":
            return "test-1.0"
        return helps[name]

    with patch.object(module.shutil, "which", return_value="/test/bin/" + name), \
            patch.object(module, "_run_metadata", side_effect=run), \
            patch.object(module, "_gemini_aliases", return_value=[]):
        return module.discover_provider(name, include_models)


class DiscoveryTests(unittest.TestCase):
    def test_discovery_default_never_fetches_catalog_or_sends_prompt(self):
        with patch.object(module.shutil, "which", return_value="/test/bin/agy"), \
                patch.object(module, "_run_metadata", return_value=AGY_HELP) as runner:
            record = module.discover_provider("antigravity")
        self.assertTrue(record["dispatch_ready"])
        runner.assert_called_once_with(["/test/bin/agy", "--help"], 10)
        self.assertEqual(record["models"], [])

    def test_absent_cli_is_not_dispatched(self):
        with patch.object(module.shutil, "which", return_value=None), \
                patch.object(module, "_run_metadata") as runner:
            record = module.discover_provider("claude", True)
        self.assertFalse(record["available"])
        runner.assert_not_called()
        with self.assertRaises(module.AdapterError):
            module.build_command(record, prompt="hello")

    def test_unavailable_help_does_not_pretend_control_support(self):
        with patch.object(module.shutil, "which", return_value="/test/bin/agy"), \
                patch.object(module, "_run_metadata", side_effect=module.AdapterError("timeout")):
            record = module.discover_provider("agy")
        self.assertTrue(record["available"])
        self.assertFalse(record["dispatch_ready"])

    def test_closed_stdin_timeout_and_no_shell_for_metadata(self):
        completed = subprocess.CompletedProcess(["cli", "--help"], 0, "safe help", "")
        with patch.object(module.subprocess, "run", return_value=completed) as runner:
            self.assertEqual(module._run_metadata(["/bin/cli", "--help"], 7), "safe help")
        kwargs = runner.call_args.kwargs
        self.assertEqual(kwargs["stdin"], subprocess.DEVNULL)
        self.assertEqual(kwargs["timeout"], 7)
        self.assertNotIn("shell", kwargs)
        with patch.object(module.subprocess, "run", side_effect=subprocess.TimeoutExpired("cli", 7)):
            with self.assertRaises(module.AdapterError):
                module._run_metadata(["/bin/cli", "--help"], 7)

    def test_claude_aliases_and_efforts_are_from_help_only(self):
        record = discover("claude", True)
        self.assertEqual(record["native_efforts"], ["low", "medium", "high", "xhigh", "max"])
        self.assertEqual([item["id"] for item in record["models"]], ["fable", "opus", "sonnet", "claude-fable-5"])
        self.assertTrue(all(not item["supported_efforts"] for item in record["models"]))
        self.assertFalse(record["account_catalog"])
        self.assertTrue(record["models"][0]["is_alias"])
        self.assertFalse(record["models"][-1]["is_alias"])

    def test_agy_variant_mapping_requires_both_display_label_and_id(self):
        record = discover("agy", True, "Fetching...\nmodel-high\tA Model (High)\nother-low\tOther (High)\nplain\tPlain\n")
        self.assertEqual(record["models"][0]["supported_efforts"], ["high"])
        self.assertEqual(record["models"][1]["supported_efforts"], [])
        self.assertEqual(record["models"][2]["supported_efforts"], [])
        self.assertTrue(record["account_catalog"])
        with self.assertRaises(module.AdapterError):
            module.build_command(record, "model-high", "low", "hi")

    def test_duplicate_and_malformed_catalog_ids_are_excluded(self):
        models = module._agy_models("--evil\tBad\na-high\tA (High)\na-high\tAgain (High)\nb-low\tB (Low)", ["low", "high"])
        self.assertEqual([item["id"] for item in models], ["b-low"])

    def test_gemini_aliases_read_code_without_executing_it(self):
        with tempfile.TemporaryDirectory() as temp:
            bundle = Path(temp) / "bundle"
            bundle.mkdir()
            (bundle / "chunk.js").write_text('var GEMINI_MODEL_ALIAS_AUTO = "auto";\nvar GEMINI_MODEL_ALIAS_FLASH = "flash";', encoding="utf-8")
            models = module._gemini_aliases(str(bundle / "gemini.js"))
        self.assertEqual([item["id"] for item in models], ["auto", "flash"])
        self.assertTrue(all(item["source"] == "installed_cli_bundle" for item in models))
        self.assertTrue(all(item["is_alias"] for item in models))

    def test_gemini_native_settings_require_exact_model_and_sdk_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            bundle = Path(temp) / "bundle"
            bundle.mkdir()
            source = ('var GEMINI_MODEL_ALIAS_AUTO = "auto";\n'
                      'var PREVIEW_GEMINI_MODEL = "gemini-3-pro-preview";\n'
                      'var PREVIEW_GEMINI_FLASH_MODEL = "gemini-future-flash";\n'
                      'ThinkingLevel2["LOW"] = "LOW";\nThinkingLevel2["HIGH"] = "HIGH";')
            (bundle / "chunk.js").write_text(source, encoding="utf-8")
            models = module._gemini_aliases(str(bundle / "gemini.js"))
        self.assertEqual([item["id"] for item in models], ["auto", "gemini-3-pro-preview"])
        self.assertEqual(models[1]["supported_efforts"], ["LOW", "HIGH"])
        self.assertEqual(models[1]["effort_support_scope"], "model_config")

    def test_claude_auth_status_retains_only_allowlisted_metadata(self):
        output = json.dumps({"loggedIn": False, "authMethod": "none", "email": "private@example.test", "accessToken": "SECRET"})
        proc = subprocess.CompletedProcess([], 1, output, "")
        with patch.object(module.subprocess, "run", return_value=proc):
            result = module._claude_authentication("/test/claude")
        self.assertEqual(result, {"status": "missing", "source": "claude_auth_status", "method": "none"})
        self.assertNotIn("SECRET", json.dumps(result))

    def test_codex_live_catalog_only_uses_metadata_rpc_and_paginates(self):
        calls = []

        class Rpc:
            def __init__(self, argv):
                calls.append(("argv", argv))
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def notify(self, method, params):
                calls.append((method, params))
            def request(self, method, params, timeout):
                calls.append((method, params))
                if method == "initialize":
                    return {}
                if params.get("cursor") == "next":
                    return {"data": [{"model": "second", "supportedReasoningEfforts": [], "isDefault": False}], "nextCursor": None}
                return {"data": [{"model": "first", "supportedReasoningEfforts": [{"reasoningEffort": "low"}],
                                  "defaultReasoningEffort": "low", "isDefault": True}], "nextCursor": "next"}

        with patch.object(module, "_rpc_client_class", return_value=Rpc):
            result = module._codex_live_models("/test/codex")
        self.assertEqual([item["id"] for item in result["models"]], ["first", "second"])
        self.assertEqual(result["source"], "codex_cli_app_server_model_list")
        self.assertEqual([name for name, _ in calls], ["argv", "initialize", "initialized", "model/list", "model/list"])

    def test_codex_discovery_prefers_destination_cli_over_cache(self):
        live = {"source": "codex_cli_app_server_model_list", "models": [module._model("actual", "live", efforts=["low"], scope="model_catalog")], "warnings": []}
        with patch.object(module, "_codex_live_models", return_value=live), \
                patch.object(module, "_codex_models") as cache:
            result = discover("codex", True)
        cache.assert_not_called()
        self.assertTrue(result["account_catalog"])
        self.assertEqual(result["models"][0]["id"], "actual")

    def test_codex_cache_fallback_discloses_possible_wrong_client(self):
        cache = {"source": "codex_model_catalog_cache", "models": [module._model("cached", "cache")], "freshness": {}, "warnings": []}
        with patch.object(module, "_codex_live_models", side_effect=module.AdapterError("unavailable")), \
                patch.object(module, "_codex_models", return_value=cache):
            result = discover("codex", True)
        self.assertFalse(result["account_catalog"])
        self.assertIn("another client", " ".join(result["warnings"]))


class CommandTests(unittest.TestCase):
    def test_omitted_pair_stays_omitted(self):
        for name in module.PROVIDERS:
            with self.subTest(provider=name):
                result = module.build_command(discover(name), prompt="hello")
                self.assertNotIn("--model", result["argv"])
                self.assertNotIn("--effort", result["argv"])
                self.assertEqual(result["requested"]["model"], None)
                self.assertEqual(result["requested"]["effort"], None)

    def test_prompt_shell_metacharacters_remain_inert_data(self):
        prompt = '$(touch /tmp/should-never-exist); `uname`\n--dangerously-skip-permissions'
        for name in module.PROVIDERS:
            result = module.build_command(discover(name), prompt=prompt)
            transported = result["stdin"] if result["stdin"] is not None else result["argv"][2]
            self.assertEqual(transported, prompt)
            self.assertNotIn("--dangerously-skip-permissions", result["argv"])

    def test_claude_uses_no_model_tools_and_empty_mcp(self):
        result = module.build_command(discover("claude", True), "opus", "high", "hello")
        argv = result["argv"]
        self.assertEqual(argv[argv.index("--tools") + 1], "")
        self.assertEqual(json.loads(argv[argv.index("--mcp-config") + 1]), {"mcpServers": {}})
        self.assertIn("--safe-mode", argv)
        self.assertTrue(result["safety"]["tools_disabled"])
        self.assertTrue(result["warnings"])

    def test_codex_preserves_readonly_and_never_bypasses(self):
        record = discover("codex")
        record["models"] = [{"id": "example", "supported_efforts": ["low", "high"], "effort_support_scope": "model_catalog"}]
        result = module.build_command(record, "example", "high", "hello")
        argv = result["argv"]
        self.assertEqual(argv[argv.index("--sandbox") + 1], "read-only")
        self.assertEqual(argv[-1], "-")
        self.assertIn('model_reasoning_effort="high"', argv)
        self.assertFalse(any("bypass" in arg for arg in argv))
        with self.assertRaises(module.AdapterError):
            module.build_command(record, "example", "medium", "hello")

    def test_unknown_explicit_model_is_labeled_unverified(self):
        result = module.build_command(discover("claude"), "custom-model", "high", "hello")
        self.assertEqual(len(result["warnings"]), 2)
        self.assertFalse(result["requested"].get("verified", False))

    def test_model_and_effort_validation_rejects_option_injection(self):
        record = discover("claude")
        for model in ("--config", "bad\nname", "a b", "$(bad)", ""):
            with self.subTest(model=model), self.assertRaises(module.AdapterError):
                module.build_command(record, model, None, "hello")
        for effort in ("ultra", "HIGH", "--model", "high\n"):
            with self.subTest(effort=effort), self.assertRaises(module.AdapterError):
                module.build_command(record, "opus", effort, "hello")
        with self.assertRaises(module.AdapterError):
            module.build_command(record, None, "high", "hello")

    def test_gemini_does_not_invent_effort_or_replace_system_config(self):
        record = discover("gemini")
        with self.assertRaises(module.AdapterError):
            module.build_command(record, "flash", "low", "hello")
        result = module.build_command(record, "flash", None, "hello")
        self.assertEqual(result["environment"], {})
        self.assertIn("none", result["argv"])
        self.assertNotIn("--policy", result["argv"])
        self.assertFalse(result["safety"]["tools_disabled"])
        with self.assertRaises(module.AdapterError):
            module.build_command(record, "flash", None, "hello", policy_path="/tmp/deny.toml")

    def test_gemini_native_effort_is_scoped_to_fresh_scratch_files(self):
        record = discover("gemini")
        record["controls"]["effort"] = True
        record["native_efforts"] = ["LOW", "HIGH"]
        record["models"] = [{"id": "gemini-3-flash-preview", "supported_efforts": ["LOW", "HIGH"],
                             "effort_support_scope": "model_config"},
                            {"id": "auto", "supported_efforts": [], "effort_support_scope": "none"}]
        with tempfile.TemporaryDirectory() as temp:
            result = module.build_command(record, "gemini-3-flash-preview", "LOW", "hello", cwd=temp)
            self.assertNotIn("--effort", result["argv"])
            self.assertNotIn("--skip-trust", result["argv"])
            self.assertEqual(result["requested"]["model"], "gemini-3-flash-preview")
            self.assertEqual(result["files"][0]["path"], ".gemini/settings.json")
            settings = json.loads(result["files"][0]["text"])
            alias = settings["modelConfigs"]["customAliases"]["dynamic-model-router-run"]
            self.assertEqual(alias["modelConfig"]["generateContentConfig"]["thinkingConfig"], {"thinkingLevel": "LOW"})
            self.assertFalse((Path(temp) / ".gemini").exists())
            (Path(temp) / ".gemini").mkdir()
            (Path(temp) / ".gemini" / "settings.json").write_text("{}")
            with self.assertRaises(module.AdapterError):
                module.build_command(record, "gemini-3-flash-preview", "LOW", "hello", cwd=temp)
        for model, effort in (("auto", "LOW"), ("gemini-3-flash-preview", "low"), ("gemini-3-flash-preview", "MEDIUM")):
            with self.subTest(model=model, effort=effort), self.assertRaises(module.AdapterError):
                module.build_command(record, model, effort, "hello", cwd="/tmp/new-scratch")

    def test_agy_plan_mode_keeps_command_expansion_but_escapes_task_slash(self):
        result = module.build_command(discover("agy"), prompt="/custom-command should be treated as text")
        self.assertNotIn("--disable-slash-commands", result["argv"])
        self.assertEqual(result["argv"][result["argv"].index("--mode") + 1], "plan")
        self.assertFalse(result["argv"][2].lstrip().startswith("/"))
        self.assertIn("/custom-command", result["argv"][2])


class RuntimeTests(unittest.TestCase):
    def test_assistant_self_report_never_verifies_settings(self):
        row = {"type": "result", "subtype": "success", "is_error": False,
               "result": 'I used model secret-high and effort max. {"model":"secret-high"}'}
        result = module.parse_runtime_result("claude", json.dumps(row))
        self.assertTrue(result["success"])
        self.assertFalse(result["model_verified"])
        self.assertFalse(result["effort_verified"])

    def test_config_init_model_is_not_runtime_usage(self):
        for provider, row in (("claude", {"type": "system", "subtype": "init", "model": "opus"}),
                              ("gemini", {"type": "init", "model": "auto"})):
            result = module.parse_runtime_result(provider, json.dumps(row))
            self.assertFalse(result["model_verified"])

    def test_claude_usage_verifies_model_but_not_effort(self):
        row = {"type": "result", "subtype": "success", "is_error": False, "result": "4",
               "modelUsage": {"claude-example": {"inputTokens": 10, "outputTokens": 1}}}
        result = module.parse_runtime_result("claude", json.dumps(row))
        self.assertEqual(result["model"], "claude-example")
        self.assertTrue(result["model_verified"])
        self.assertFalse(result["effort_verified"])
        self.assertEqual(result["text"], "4")

    def test_provider_error_is_detected_even_in_json_successful_process(self):
        row = {"type": "result", "subtype": "error_during_execution", "is_error": True, "result": "Unavailable"}
        for provider in ("claude", "agy"):
            result = module.parse_runtime_result(provider, json.dumps(row))
            self.assertFalse(result["success"])
            self.assertTrue(result["is_error"])

    def test_codex_error_is_not_erased_by_later_completion(self):
        rows = [{"type": "error", "message": "failed"}, {"type": "turn.completed", "usage": {}}]
        result = module.parse_runtime_result("codex", "\n".join(map(json.dumps, rows)))
        self.assertFalse(result["success"])

    def test_codex_text_and_verification_are_separate(self):
        rows = [{"type": "thread.started", "thread_id": "t"},
                {"type": "item.completed", "item": {"type": "agent_message", "text": "4"}},
                {"type": "turn.completed", "usage": {"output_tokens": 1}}]
        result = module.parse_runtime_result("codex", "\n".join(map(json.dumps, rows)), "model: invented\neffort: high")
        self.assertTrue(result["success"])
        self.assertEqual(result["text"], "4")
        self.assertFalse(result["model_verified"])

    def test_gemini_ignores_zero_or_failed_api_model_entries(self):
        row = {"response": "4", "stats": {"models": {
            "actual": {"api": {"totalRequests": 1, "totalErrors": 0}},
            "unused": {"api": {"totalRequests": 0, "totalErrors": 0}},
            "failed": {"api": {"totalRequests": 1, "totalErrors": 1}}}}}
        result = module.parse_runtime_result("gemini", json.dumps(row))
        self.assertEqual(result["models_used"], ["actual"])
        self.assertTrue(result["model_verified"])

    def test_multi_model_usage_does_not_pick_arbitrary_winner(self):
        row = {"type": "result", "is_error": False, "result": "4", "modelUsage": {"router": {}, "worker": {}}}
        result = module.parse_runtime_result("claude", json.dumps(row))
        self.assertEqual(result["models_used"], ["router", "worker"])
        self.assertIsNone(result["model"])
        self.assertFalse(result["model_verified"])

    def test_unstructured_or_malformed_output_is_not_success(self):
        for output in ("4", "{", "", "I am model X, effort high"):
            result = module.parse_runtime_result("agy", output)
            self.assertIsNone(result["success"])
            self.assertFalse(result["model_verified"])

    def test_authentication_error_is_a_prerequisite_with_safe_message(self):
        row = {"type": "result", "subtype": "error_during_execution", "is_error": True,
               "result": "Not logged in · Please run /login"}
        result = module.parse_runtime_result("claude", json.dumps(row))
        self.assertEqual(result["error"], "Not logged in · Please run /login")
        self.assertEqual(result["error_category"], "authentication")
        self.assertEqual(result["failure_class"], "prerequisite")

    def test_diagnostics_redact_secrets_identity_and_query_urls(self):
        row = {"type": "error", "error": {"type": "unauthorized", "message":
               "Unauthorized Bearer SECRET123 api_key=secretvalue sk-abcdefghijklmnop user@example.com https://host/path?key=private /Users/alice/private/file"}}
        result = module.parse_runtime_result("codex", json.dumps(row))
        encoded = json.dumps(result)
        for secret in ("SECRET123", "secretvalue", "sk-abcdefghijklmnop", "user@example.com", "key=private", "/Users/alice"):
            self.assertNotIn(secret, encoded)
        self.assertEqual(result["error_details"][0]["type"], "unauthorized")

    def test_unstructured_error_is_reported_but_success_warnings_are_not_failure(self):
        result = module.parse_runtime_result("codex", "", "Error: connection retry limit exceeded")
        self.assertFalse(result["success"])
        self.assertEqual(result["error_category"], "transport")
        row = {"type": "turn.completed", "usage": {}}
        result = module.parse_runtime_result("codex", json.dumps(row), "Error: optional telemetry unavailable")
        self.assertTrue(result["success"])
        self.assertFalse(result["is_error"])

    def test_actual_agy_success_schema_has_answer_without_runtime_settings(self):
        row = {"conversation_id": "example", "status": "SUCCESS", "response": "3,5,17|25|nonce\n",
               "duration_seconds": 6.1, "num_turns": 1, "usage": {"input_tokens": 10, "output_tokens": 4}}
        result = module.parse_runtime_result("agy", json.dumps(row))
        self.assertTrue(result["success"])
        self.assertEqual(result["text"].strip(), "3,5,17|25|nonce")
        self.assertFalse(result["model_verified"])
        self.assertFalse(result["effort_verified"])

    def test_gemini_structured_stderr_auth_error_is_prerequisite(self):
        error = {"session_id": "example", "error": {"type": "Error", "code": 41,
                 "message": "Please set an Auth method in your /Users/private/.gemini/settings.json"}}
        result = module.parse_runtime_result("gemini", "", json.dumps(error))
        self.assertFalse(result["success"])
        self.assertEqual(result["error_category"], "authentication")
        self.assertEqual(result["failure_class"], "prerequisite")
        self.assertNotIn("/Users/private", json.dumps(result))

    def test_nested_codex_model_error_is_unwrapped_and_classified(self):
        nested = {"type": "error", "status": 400, "error": {"type": "invalid_request_error",
                  "message": "The 'example' model is not supported when using Codex with a ChatGPT account.",
                  "code": "model_not_found"}}
        result = module.parse_runtime_result("codex", json.dumps({"type": "error", "message": json.dumps(nested)}))
        self.assertFalse(result["success"])
        self.assertEqual(result["error_category"], "model_unavailable")
        self.assertEqual(result["error_details"][0]["type"], "model_not_found")


if __name__ == "__main__":
    unittest.main()
