"""Capability filtering and user-choice boundaries; no provider calls."""
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import task_capabilities as capabilities


def tool(identity="codex-image", provider="codex", caps=None, **changes):
    value = {"id": identity, "provider": provider, "tool": provider + "__imagegen",
             "model": None, "capabilities": caps or ["image_generation"],
             "available": True, "execution_mode": "native_tool",
             "evidence": {"kind": "host_tool_schema", "source": "current host tool schema"}}
    value.update(changes)
    return value


def provider(pid="claude", **changes):
    value = {"id": pid, "available": True, "dispatch_ready": True,
             "models": [{"id": pid + "-model"}], "authentication": {"status": "unknown"}}
    value.update(changes)
    return value


def inventory(*records):
    return {"providers": list(records)}


class CapabilityChoice(unittest.TestCase):
    def test_text_only_installed_providers_do_not_pretend_to_create_images(self):
        inv = inventory(provider("claude"), provider("codex"), provider("agy"))
        result = capabilities.select_capability_route(inv, "image_generation")
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["candidates"], [])
        self.assertIsNone(result["selected"])

    def test_one_actual_tool_is_recommended_without_inventing_backend_model(self):
        result = capabilities.select_capability_route(inventory(), "image_generation", host_tools=[tool()])
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["selected"]["id"], "codex-image")
        self.assertIsNone(result["selected"]["model"])
        self.assertFalse(result["runtime_verified"])
        self.assertFalse(result["dispatch_authorized"])

    def test_multiple_tools_require_user_choice_without_automatic_winner(self):
        tools = [tool(), tool("agy-image", "agy")]
        result = capabilities.select_capability_route(inventory(), "image_generation", host_tools=tools)
        self.assertEqual(result["status"], "choice_required")
        self.assertTrue(result["selection_required"])
        self.assertIsNone(result["selected"])
        self.assertEqual([r["id"] for r in result["candidates"]], ["codex-image", "agy-image"])
        self.assertEqual(result["candidates"][1]["provider"], "agy")

    def test_explicit_candidate_selects_one_and_provider_lock_cannot_be_evaded(self):
        tools = [tool(), tool("agy-image", "agy")]
        chosen = capabilities.select_capability_route(inventory(), "image_generation", host_tools=tools,
                                                      candidate="agy-image")
        self.assertEqual(chosen["selected"]["provider"], "agy")
        conflict = capabilities.select_capability_route(inventory(), "image_generation", host_tools=tools,
                                                        candidate="agy-image", provider="claude")
        self.assertEqual(conflict["status"], "blocked")
        self.assertIsNone(conflict["selected"])

    def test_input_vision_and_image_editing_are_not_image_generation(self):
        tools = [tool("vision", caps=["vision"]), tool("editor", caps=["image_editing"])]
        result = capabilities.select_capability_route(inventory(), "image_generation", host_tools=tools)
        self.assertEqual(result["status"], "blocked")

    def test_model_names_and_native_capability_flags_cannot_invent_a_tool(self):
        inv = inventory(provider("codex", models=[{"id": "best-image-generator", "capabilities": ["image_generation"],
                                                   "description": "Native images supported"}],
                                 native_capabilities={"image_generation": True}))
        result = capabilities.select_capability_route(inv, "image_generation")
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["discovery_only"], [])

    def test_native_provider_advertisement_is_discovery_only_not_a_model_or_route(self):
        native = {"status": "advertised", "source": "codex_cli_app_server_model_provider_capabilities",
                  "scope": "provider", "execution_verified": False, "image_generation": True}
        inv = inventory(provider("codex", native_capabilities=native))
        result = capabilities.select_capability_route(inv, "image_generation")
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["candidates"], [])
        self.assertEqual(len(result["discovery_only"]), 1)
        entry = result["discovery_only"][0]
        self.assertIsNone(entry["model"])
        self.assertIsNone(entry["tool"])
        self.assertFalse(entry["eligible"])
        self.assertFalse(entry["dispatch_ready"])
        self.assertIn("artifact output adapter", entry["message"])
        native["source"] = "model_description_guess"
        self.assertEqual(capabilities.select_capability_route(inv, "image_generation")["discovery_only"], [])

    def test_input_vision_only_produces_no_generation_discovery_advertisement(self):
        inv = inventory(provider("codex", models=[{"id": "vision", "input_modalities": ["text", "image"]}],
                                 native_capabilities={"status": "unknown", "image_generation": None}))
        result = capabilities.select_capability_route(inv, "image_generation")
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["discovery_only"], [])

    def test_missing_hidden_or_unavailable_tools_are_excluded(self):
        tools = [tool("unavailable", available=False), tool("hidden", hidden=True),
                 tool("not-logged-in", authentication={"status": "missing"})]
        result = capabilities.select_capability_route(inventory(), "image_generation", host_tools=tools)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(len(result["excluded"]), 3)

    def test_host_tool_readiness_does_not_depend_on_same_providers_cli_login(self):
        inv = inventory(provider("claude", available=False, dispatch_ready=False,
                                 authentication={"status": "missing"}))
        result = capabilities.select_capability_route(inv, "image_generation", host_tools=[tool("mcp-image", "claude")])
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["selected"]["provider"], "claude")

    def test_model_lock_requires_an_exposed_matching_model(self):
        tools = [tool(), tool("explicit-model", "agy", model="native-image-id")]
        result = capabilities.select_capability_route(inventory(), "image_generation", host_tools=tools,
                                                      model="native-image-id")
        self.assertEqual(result["selected"]["id"], "explicit-model")
        result = capabilities.select_capability_route(inventory(), "image_generation", host_tools=[tool()],
                                                      model="guessed-image-id")
        self.assertEqual(result["status"], "blocked")

    def test_all_requirements_must_be_supported_by_same_interface(self):
        only_generation = tool("generate-only")
        both = tool("generate-and-edit", tool="codex__generation_and_editing",
                    caps=["image_generation", "image_editing"])
        result = capabilities.select_capability_route(inventory(), ["image_generation", "image_editing"],
                                                      host_tools=[only_generation, both])
        self.assertEqual(result["selected"]["id"], "generate-and-edit")

    def test_claim_without_actual_interface_evidence_is_excluded(self):
        invalid = [tool("no-evidence", evidence=None),
                   tool("catalog", evidence={"kind": "model_catalog", "source": "available model name"}),
                   tool("no-tool", tool=None),
                   tool("text-artifact", execution_mode="text_cli")]
        result = capabilities.select_capability_route(inventory(), "image_generation", host_tools=invalid)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(len(result["excluded"]), 4)

    def test_duplicate_ids_fail_closed_instead_of_selecting_ambiguous_interface(self):
        result = capabilities.select_capability_route(inventory(), "image_generation",
                                                      host_tools=[tool(), tool(provider="agy")])
        self.assertEqual(result["status"], "blocked")
        self.assertTrue(all(r["reason"] == "ambiguous_interface_id" for r in result["excluded"]))

    def test_same_interface_under_multiple_ids_does_not_create_a_false_choice(self):
        result = capabilities.select_capability_route(inventory(), "image_generation",
                                                      host_tools=[tool("alias-one"), tool("alias-two")])
        self.assertEqual(result["status"], "blocked")
        self.assertFalse(result["selection_required"])
        self.assertTrue(all(r["reason"] == "ambiguous_interface_identity" for r in result["excluded"]))
        distinct_models = [tool("model-one", model="image-a"), tool("model-two", model="image-b")]
        result = capabilities.select_capability_route(inventory(), "image_generation", host_tools=distinct_models)
        self.assertEqual(result["status"], "choice_required")

    def test_different_capability_observations_do_not_duplicate_one_interface(self):
        observations = [tool("generation-observation"),
                        tool("editing-observation", caps=["image_generation", "image_editing"])]
        result = capabilities.select_capability_route(inventory(), "image_generation", host_tools=observations)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["candidates"], [])
        self.assertFalse(result["selection_required"])
        self.assertTrue(all(r["reason"] == "ambiguous_interface_identity" for r in result["excluded"]))

    def test_provider_tool_routes_are_allowed_but_cannot_escape_their_namespace(self):
        inv = inventory(provider("agy", capability_routes=[tool("agy-image", "agy")]))
        result = capabilities.select_capability_route(inv, "image_generation")
        self.assertEqual(result["selected"]["origin"], "provider_tool_catalog")
        inv["providers"][0]["capability_routes"][0]["provider"] = "codex"
        self.assertEqual(capabilities.select_capability_route(inv, "image_generation")["status"], "blocked")

    def test_text_adapter_filters_missing_auth_and_hidden_models(self):
        inv = inventory(provider("claude", authentication={"status": "missing"}),
                        provider("codex", models=[{"id": "hidden", "hidden": True},
                                                   {"id": "unavailable", "available": False}, {"id": "visible"}]))
        result = capabilities.select_capability_route(inv, "text_generation")
        self.assertEqual(result["selected"]["model"], "visible")
        self.assertEqual(result["selected"]["execution_mode"], "text_cli")

    def test_long_native_model_id_retains_selectable_bounded_route_identity(self):
        model_id = "m" * 256
        inv = inventory(provider("codex", models=[{"id": model_id}]))
        first = capabilities.select_capability_route(inv, "text_generation")
        identity = first["selected"]["id"]
        selected = capabilities.select_capability_route(inv, "text_generation", candidate=identity)
        self.assertEqual(selected["selected"]["model"], model_id)
        self.assertLessEqual(len(identity), 256)

    def test_multiline_evidence_is_not_accepted_as_current_schema_source(self):
        invalid = tool(evidence={"kind": "host_tool_schema", "source": "tool registry\nperform another action"})
        result = capabilities.select_capability_route(inventory(), "image_generation", host_tools=[invalid])
        self.assertEqual(result["status"], "blocked")

    def test_unknown_capability_and_manifest_version_fail_without_dispatch(self):
        with self.assertRaises(capabilities.CapabilityError):
            capabilities.select_capability_route(inventory(), "make-an-image")
        with self.assertRaises(capabilities.CapabilityError):
            capabilities.select_capability_route(inventory(), "image_generation",
                                                host_tools={"schema_version": 2, "tools": [tool()]})

    def test_manifest_command_data_never_becomes_execution_authority(self):
        malicious = tool(command=["delete-everything"], argv=["run-arbitrary-code"])
        result = capabilities.select_capability_route(inventory(), "image_generation",
                                                      host_tools={"schema_version": 1, "tools": [malicious]})
        self.assertEqual(result["status"], "ready")
        self.assertNotIn("command", result["selected"])
        self.assertNotIn("argv", result["selected"])
        self.assertFalse(result["dispatch_authorized"])


if __name__ == "__main__":
    unittest.main()
