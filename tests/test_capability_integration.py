"""Capability menus and text-dispatch boundaries, without model calls."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import cross_cli_router as router


def inventory():
    return {"schema_version": 1, "machine_key": router.machine_key(), "providers": [
        {"id": name, "available": True, "dispatch_ready": True,
         "models": [{"id": name + "-text", "supported_efforts": ["low", "medium"]}]}
        for name in ("claude", "agy", "codex")]}


def tool(cid, provider="codex"):
    return {"id": cid, "provider": provider, "tool": cid + "_image",
            "model": None, "capabilities": ["image_generation"], "available": True,
            "execution_mode": "native_tool",
            "evidence": {"kind": "host_tool_schema", "source": "Current test-host tool definition"}}


class CapabilityIntegration(unittest.TestCase):
    def test_image_task_kind_never_selects_a_text_model(self):
        result = router.select_plan(inventory(), task_kind="image_generation")
        self.assertEqual(result["status"], "blocked")
        self.assertIsNone(result["selected"])
        self.assertFalse(result["text_dispatch_supported"])

    def test_explicit_requirement_filters_before_model_ranking(self):
        result = router.select_plan(inventory(), required_capabilities=["image_generation"])
        self.assertEqual(result["status"], "blocked")

    def test_two_reachable_tools_wait_for_choice(self):
        result = router.select_plan(inventory(), task_kind="image_generation",
                                    host_tools=[tool("first"), tool("second", "another-service")])
        self.assertEqual(result["status"], "choice_required")
        self.assertIsNone(result["selected"])
        self.assertFalse(result["dispatch_authorized"])

    def test_explicit_choice_resolves_menu_without_dispatch(self):
        result = router.select_plan(inventory(), task_kind="image_generation", candidate="second",
                                    host_tools=[tool("first"), tool("second", "another-service")])
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["selected"]["id"], "second")
        self.assertIsNone(result["selected"]["model"])
        self.assertFalse(result["dispatch_authorized"])

    def test_model_lock_cannot_match_hidden_backend(self):
        result = router.select_plan(inventory(), task_kind="image_generation", provider="codex",
                                    model="codex-text", host_tools=[tool("first")])
        self.assertEqual(result["status"], "blocked")

    def test_effort_lock_is_not_silently_dropped_for_image_tools(self):
        with self.assertRaises(router.RouterError):
            router.select_plan(inventory(), task_kind="image_generation", effort="high", host_tools=[tool("first")])

    def test_run_rejects_even_selected_capability_before_discovery(self):
        plan = router.select_plan(inventory(), task_kind="image_generation", host_tools=[tool("first")])
        with patch.object(router.adapters, "discover_provider") as discover, patch.object(router, "bounded_process") as process:
            with self.assertRaises(router.RouterError):
                router.execute_plan(plan, "Generate an image.")
        discover.assert_not_called()
        process.assert_not_called()

    def test_old_or_forged_image_plan_cannot_bypass_text_boundary(self):
        plan = {"machine_key": router.machine_key(), "provider": "claude", "task_kind": "image_generation",
                "required_capabilities": ["text_generation"]}
        with patch.object(router.adapters, "discover_provider") as discover:
            with self.assertRaises(router.RouterError):
                router.execute_plan(plan, "Generate an image.")
        discover.assert_not_called()

    def test_normal_text_routing_remains_automatic(self):
        result = router.select_plan(inventory(), task_kind="writing", provider="claude")
        self.assertEqual(result["provider"], "claude")
        self.assertEqual(result["required_capabilities"], ["text_generation"])
        self.assertNotIn("selected", result)

    def test_cli_capability_choice_roundtrip_sends_no_process(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "inventory.json").write_text(json.dumps(inventory()))
            (root / "tools.json").write_text(json.dumps({"schema_version": 1, "tools": [tool("first"), tool("second")]}))
            args = ["--state", str(root / "state.json"), "capabilities", "--inventory", str(root / "inventory.json"),
                    "--required", "image_generation", "--host-tools", str(root / "tools.json"), "--output", str(root / "menu.json")]
            with patch.object(router, "bounded_process") as process, contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(router.main(args), 0)
                self.assertEqual(json.loads((root / "menu.json").read_text())["status"], "choice_required")
                self.assertEqual(router.main(args + ["--candidate", "second"]), 0)
            result = json.loads((root / "menu.json").read_text())
            self.assertEqual(result["selected"]["id"], "second")
            self.assertFalse(result["runtime_verified"])
            process.assert_not_called()
            self.assertFalse((root / "state.json").exists())

    def test_wrong_machine_snapshot_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); data = inventory(); data["machine_key"] = "another-machine"
            (root / "inventory.json").write_text(json.dumps(data))
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(router.main(["--state", str(root / "state.json"), "capabilities", "--inventory",
                                              str(root / "inventory.json"), "--required", "image_generation"]), 2)

    def test_empty_explicit_requirements_are_invalid(self):
        with self.assertRaises(ValueError):
            router.select_plan(inventory(), required_capabilities=[])


if __name__ == "__main__":
    unittest.main()
