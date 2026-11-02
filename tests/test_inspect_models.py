"""Offline behavior tests for the distributable catalog helper."""

import contextlib
import importlib.util
import io
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "inspect_models.py"
SPEC = importlib.util.spec_from_file_location("inspect_models", SCRIPT)
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)
NOW = datetime(2026, 11, 2, 5, tzinfo=timezone.utc)


def model(slug="available", efforts=("low", "high"), **overrides):
    result = {
        "slug": slug,
        "display_name": "Test model 🌍",
        "description": "Image-capable test model",
        "visibility": "list",
        "supported_reasoning_levels": [{"effort": effort, "description": "unused"} for effort in efforts],
        "default_reasoning_level": efforts[0] if efforts else None,
        "input_modalities": ["text", "image"],
    }
    result.update(overrides)
    return result


def catalog(*models, **overrides):
    result = {"fetched_at": "2026-11-02T04:00:00Z", "models": list(models)}
    result.update(overrides)
    return result


class CatalogTests(unittest.TestCase):
    def inspect(self, value):
        return module.inspect_catalog(value, now=NOW)

    def test_visible_only_and_hidden_internal_excluded(self):
        result = self.inspect(catalog(
            model(), model("hidden", visibility="hide"), model("unknown", visibility="experimental"),
            model("searchable", visibility="search"), model("custom", visibility=None),
            model("internal", internal=True)))
        self.assertEqual([m["id"] for m in result["models"]], ["available", "searchable", "custom"])

    def test_sparse_efforts_validate_exact_values(self):
        result = self.inspect(catalog(model()))
        self.assertTrue(module.validate_pair(result, "available", "high")["catalog_pair_supported"])
        self.assertFalse(module.validate_pair(result, "available", "low")["runtime_applied"])
        for effort in ["medium", "HIGH", "ultra", "high "]:
            with self.assertRaises(module.CatalogError):
                module.validate_pair(result, "available", effort)
        with self.assertRaises(module.CatalogError):
            module.validate_pair(result, "absent", "low")

    def test_duplicate_id_excludes_all_ambiguous_entries(self):
        result = self.inspect(catalog(model(), model(visibility="hide"), model("other")))
        self.assertEqual([m["id"] for m in result["models"]], ["other"])
        self.assertIn("duplicate model IDs", " ".join(result["warnings"]))
        with self.assertRaises(module.CatalogError):
            module.validate_pair(result, "available", "low")

    def test_malformed_models_do_not_validate(self):
        bad = [model("a", supported_reasoning_levels="high"),
               model("b", default_reasoning_level="ultra"),
               model("c", input_modalities="text"), model("d", description=42),
               model("e", supported_reasoning_levels=[{"effort": "high"}, {"effort": "high"}]),
               model("f", supported_reasoning_levels=[{"effort": 3}]),
               model("newline\n"), 42]
        result = self.inspect(catalog(*bad, model()))
        self.assertEqual([m["id"] for m in result["models"]], ["available"])
        self.assertTrue(result["warnings"])

    def test_missing_effort_metadata_does_not_infer_support(self):
        result = self.inspect(catalog({"slug": "sparse"}))
        self.assertEqual(result["models"][0]["supported_efforts"], [])
        with self.assertRaises(module.CatalogError):
            module.validate_pair(result, "sparse", "low")

    def test_freshness_is_explicit(self):
        self.assertTrue(self.inspect(catalog())["freshness"]["fresh"])
        cases = [
            (None, "missing_timestamp"),
            ("private invalid value", "invalid_timestamp"),
            (42, "invalid_timestamp"),
            ("2026-11-02T04:00:00", "invalid_timestamp"),
            ("2026-10-30T04:00:00Z", "stale"),
            ("2026-11-02T06:00:00Z", "future_timestamp"),
        ]
        for timestamp, status in cases:
            with self.subTest(status=status, timestamp=timestamp):
                actual = self.inspect(catalog(fetched_at=timestamp))["freshness"]
                self.assertFalse(actual["fresh"])
                self.assertEqual(actual["status"], status)
        self.assertNotIn("private invalid value", json.dumps(self.inspect(catalog(fetched_at="private invalid value"))))

    def test_sanitized_output_omits_private_and_unknown_fields(self):
        result = self.inspect(catalog(model(base_instructions="SECRET-INSTRUCTIONS", raw_key="SECRET-RAW"),
                                      identity="SECRET-IDENTITY", etag="SECRET-ETAG"))
        encoded = json.dumps(result, ensure_ascii=False)
        self.assertNotIn("SECRET-", encoded)
        self.assertIn("Test model 🌍", encoded)
        self.assertEqual(set(result["models"][0]), {
            "id", "display_name", "description", "supported_efforts", "default_effort", "input_modalities"})

    def test_codex_home_resolution(self):
        with patch.dict(os.environ, {"CODEX_HOME": "/tmp/test-codex-model-home"}):
            self.assertEqual(module.default_catalog_path(), Path("/tmp/test-codex-model-home/models_cache.json"))
        with patch.dict(os.environ, {"CODEX_HOME": ""}):
            self.assertEqual(module.default_catalog_path(), Path.home() / ".codex" / "models_cache.json")

    def run_cli(self, payload, *options):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "catalog.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            stream = io.StringIO()
            with contextlib.redirect_stdout(stream):
                code = module.main(["--catalog", str(path), *options])
            return code, json.loads(stream.getvalue())

    def test_cli_validation_and_freshness_policy(self):
        code, output = self.run_cli(catalog(model(), fetched_at=None), "--model", "available", "--effort", "high")
        self.assertEqual(code, 0)
        self.assertFalse(output["freshness"]["fresh"])
        self.assertFalse(output["validation"]["runtime_applied"])
        code, output = self.run_cli(catalog(model(), fetched_at=None), "--require-fresh")
        self.assertEqual(code, 2)
        self.assertIn("freshness", output["error"])
        code, output = self.run_cli(catalog(model()), "--model", "available", "--effort", "medium")
        self.assertEqual(code, 2)
        self.assertFalse(output["runtime_applied"])

    def test_invalid_catalog_and_bad_age_fail_clearly(self):
        for value in [[], {"models": "bad"}, None]:
            with self.assertRaises(module.CatalogError):
                self.inspect(value)
        for age in [float("nan"), float("inf"), -1]:
            with self.assertRaises(module.CatalogError):
                module.inspect_catalog(catalog(), max_age_hours=age)
        with self.assertRaises(SystemExit):
            with contextlib.redirect_stderr(io.StringIO()):
                module.parse_args(["--model", "available"])

    def test_invalid_file_error_does_not_disclose_path_or_input(self):
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            code = module.main(["--catalog", "/tmp/SECRET-PRIVATE-PATH/missing-catalog.json"])
        self.assertEqual(code, 2)
        self.assertNotIn("SECRET", stream.getvalue())


if __name__ == "__main__":
    unittest.main()
