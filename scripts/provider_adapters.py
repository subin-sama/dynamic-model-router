#!/usr/bin/env python3
"""Read-only CLI discovery, safe argv construction, and runtime evidence parsing.

Discovery never sends a prompt. ``include_models=True`` permits the documented
Antigravity catalog request; other catalogs are read locally. Model aliases and
cached metadata do not establish account entitlement or effective runtime values.
The caller owns execution, timeouts, temporary files, and result acceptance.
"""

import importlib.util
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


PROVIDERS = ("claude", "agy", "codex", "gemini")
HELP_TIMEOUT_SECONDS = 10
CATALOG_TIMEOUT_SECONDS = 25
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@+\-]{0,255}\Z")
_ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


class AdapterError(ValueError):
    """The discovered CLI cannot safely express a requested run."""


def _canonical(name: str) -> str:
    name = "agy" if name == "antigravity" else name
    if name not in PROVIDERS:
        raise AdapterError("Unknown provider")
    return name


def _identifier(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise AdapterError("Invalid " + label)
    return value


def _run_metadata(argv: List[str], timeout: int) -> str:
    # No shell, inherited stdin, login, or AI prompt. A closed stdin also stops
    # an unexpected authentication prompt from consuming the caller's input.
    try:
        completed = subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True,
                                   text=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AdapterError("Metadata command failed or timed out") from exc
    if completed.returncode != 0:
        raise AdapterError("Metadata command exited unsuccessfully")
    output = completed.stdout + "\n" + completed.stderr
    if len(output) > 2_000_000:
        raise AdapterError("Metadata output exceeded the size limit")
    return _ANSI.sub("", output).strip()


def _option_section(help_text: str, flag: str) -> str:
    match = re.search(r"(?m)^[ \t]*(?:-[A-Za-z],[ \t]*)?" + re.escape(flag) + r"(?:\s|$)", help_text)
    if not match:
        return ""
    rest = help_text[match.start():]
    first_line_end = rest.find("\n")
    if first_line_end < 0:
        return rest
    offset = first_line_end + 1
    following = re.search(r"(?m)^[ \t]*(?:-[A-Za-z],[ \t]*)?--[a-z]", rest[offset:])
    return rest[:following.start() + offset] if following else rest


def _native_efforts(help_text: str) -> List[str]:
    section = _option_section(help_text, "--effort")
    match = re.search(r"\((low(?:\s*[,|]\s*[a-z]+)+)\)", section)
    return list(dict.fromkeys(re.split(r"\s*[,|]\s*", match.group(1)))) if match else []


def _model(model_id: str, source: str, description: Optional[str] = None,
           efforts: Optional[List[str]] = None, scope: str = "unknown") -> Dict[str, Any]:
    efforts = efforts or []
    return {"id": _identifier(model_id, "model ID"), "supported_efforts": efforts,
            "default_effort": efforts[0] if len(efforts) == 1 else None,
            "description": description, "source": source,
            "effort_support_scope": scope}


def _claude_aliases(help_text: str) -> List[Dict[str, Any]]:
    section = _option_section(help_text, "--model")
    ids = re.findall(r"['\"]([A-Za-z0-9][A-Za-z0-9._-]*)['\"]", section)
    models = [_model(value, "installed_cli_help", "CLI model example or alias; account access unverified",
                     scope="provider_cli") for value in dict.fromkeys(ids)]
    for item in models:
        item["is_alias"] = not item["id"].startswith("claude-")
    return models


def _agy_models(text: str, native_efforts: List[str]) -> List[Dict[str, Any]]:
    models = []
    for line in text.splitlines():
        cells = line.strip().split("\t", 1)
        if len(cells) != 2 or not _ID.fullmatch(cells[0]):
            continue
        description = cells[1].strip()
        match = re.search(r"\(([A-Za-z]+)\)\s*$", description)
        effort = match.group(1).lower() if match else None
        # Map only an explicit display-name label that also matches the ID.
        mapped = effort in native_efforts and cells[0].endswith("-" + effort)
        models.append(_model(cells[0], "agy_models", description,
                             [effort] if mapped else [],
                             "catalog_variant" if mapped else "provider_cli"))
    ids = [item["id"] for item in models]
    return [item for item in models if ids.count(item["id"]) == 1]


def _codex_models() -> Dict[str, Any]:
    path = Path(__file__).with_name("inspect_models.py")
    spec = importlib.util.spec_from_file_location("router_catalog_adapter", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    catalog_path = module.default_catalog_path()
    if catalog_path.stat().st_size > 4_000_000:
        raise AdapterError("Codex catalog exceeds the size limit")
    result = module.inspect_catalog(json.loads(catalog_path.read_text(encoding="utf-8")))
    for item in result["models"]:
        item.update(source=result["source"], effort_support_scope="model_catalog")
    return result


def _rpc_client_class():
    path = Path(__file__).with_name("codex_rpc.py")
    spec = importlib.util.spec_from_file_location("router_provider_rpc", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.RpcClient


def _codex_live_models(executable: str) -> Dict[str, Any]:
    """Query the destination CLI's catalog; no thread or inference is started."""
    client_class = _rpc_client_class()
    deadline = time.monotonic() + CATALOG_TIMEOUT_SECONDS

    def remaining():
        value = deadline - time.monotonic()
        if value <= 0:
            raise AdapterError("Live CLI catalog timed out")
        return min(10, value)

    raw_models, cursor, cursors = [], None, set()
    with client_class([executable, "app-server", "--listen", "stdio://"]) as rpc:
        rpc.request("initialize", {"clientInfo": {"name": "dynamic-model-router-discovery", "version": "0.1.0"},
                                   "capabilities": {"experimentalApi": True}}, timeout=remaining())
        rpc.notify("initialized", {})
        for _ in range(10):
            params = {"limit": 100, "includeHidden": False}
            if cursor is not None:
                params["cursor"] = cursor
            page = rpc.request("model/list", params, timeout=remaining())
            if not isinstance(page, dict) or not isinstance(page.get("data"), list):
                raise AdapterError("Live CLI model catalog is malformed")
            raw_models.extend(page["data"])
            if len(raw_models) > 1000:
                raise AdapterError("Live CLI model catalog exceeded its size limit")
            cursor = page.get("nextCursor")
            if cursor is None:
                break
            if not isinstance(cursor, str) or not cursor or len(cursor) > 1000 or cursor in cursors:
                raise AdapterError("Live CLI model pagination is invalid")
            cursors.add(cursor)
        else:
            raise AdapterError("Live CLI model pagination did not finish")
    models, seen, duplicate = [], set(), set()
    for raw in raw_models:
        if not isinstance(raw, dict):
            continue
        mid = raw.get("model")
        if isinstance(mid, str):
            if mid in seen:
                duplicate.add(mid)
            seen.add(mid)
        if raw.get("hidden") is True:
            continue
        try:
            _identifier(mid, "model ID")
            raw_efforts = raw.get("supportedReasoningEfforts", [])
            if not isinstance(raw_efforts, list) or any(not isinstance(item, dict) for item in raw_efforts):
                continue
            efforts = [_identifier(item.get("reasoningEffort"), "effort") for item in raw_efforts]
            default = raw.get("defaultReasoningEffort")
            if len(efforts) != len(set(efforts)) or (default is not None and default not in efforts):
                continue
            description = raw.get("description")
            item = _model(mid, "codex_cli_app_server_model_list",
                          description[:2000] if isinstance(description, str) else None,
                          efforts, "model_catalog")
            item["default_effort"] = default
            item["is_default"] = raw.get("isDefault") is True
            item["is_alias"] = False
            models.append(item)
        except AdapterError:
            continue
    models = [item for item in models if item["id"] not in duplicate]
    if not models:
        raise AdapterError("Live CLI catalog contains no unambiguous supported models")
    return {"models": models, "source": "codex_cli_app_server_model_list",
            "warnings": ["Live CLI catalog advertises available choices; successful inference remains unverified"]}


def _claude_authentication(executable: str) -> Dict[str, Any]:
    """Read only native auth-status metadata; never expose account identifiers."""
    result = {"status": "unknown", "source": "claude_auth_status"}
    try:
        proc = subprocess.run([executable, "auth", "status", "--json"], stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, timeout=HELP_TIMEOUT_SECONDS, check=False)
        if len(proc.stdout) > 100_000:
            return result
        data = json.loads(proc.stdout)
        if not isinstance(data, dict):
            return result
        if data.get("loggedIn") is True:
            result["status"] = "authenticated"
        elif data.get("loggedIn") is False:
            result["status"] = "missing"
        if data.get("authMethod") in ("none", "claude.ai", "oauth", "api_key", "apiKey", "bedrock", "vertex", "foundry"):
            result["method"] = data["authMethod"]
    except (OSError, ValueError, subprocess.TimeoutExpired):
        pass
    return result


def _gemini_aliases(executable: str) -> List[Dict[str, Any]]:
    # Read installed JavaScript constants, never execute package code or read
    # account settings. No hard-coded current model IDs survive an upgrade.
    bundle = Path(executable).resolve().parent
    if bundle.name != "bundle":
        return []
    remaining = 64_000_000
    try:
        files = sorted(bundle.glob("*.js"), key=lambda p: p.stat().st_size)
        for path in files:
            size = path.stat().st_size
            if size > 8_000_000 or size > remaining:
                continue
            remaining -= size
            source = path.read_text(encoding="utf-8")
            ids = re.findall(r'\b(?:var|const)\s+GEMINI_MODEL_ALIAS_[A-Z_]+\s*=\s*["\']([^"\']+)["\']', source)
            if ids:
                models = [_model(value, "installed_cli_bundle", "Native Gemini alias; account access unverified",
                                 scope="none") for value in dict.fromkeys(ids)]
                for item in models:
                    item["is_alias"] = True
                    item["is_default"] = item["id"] == "auto"
                # These documented Gemini 3 models support LOW/HIGH thinking
                # levels. Require matching installed SDK enum evidence too;
                # a future model-name change does not inherit this capability.
                sdk_levels = re.findall(r'ThinkingLevel\w*\["(LOW|HIGH)"\]\s*=\s*"\1"', source)
                concrete = re.findall(r'\b(?:var|const)\s+PREVIEW_GEMINI_(?:MODEL|FLASH_MODEL)\s*=\s*["\']([^"\']+)["\']', source)
                if set(sdk_levels) == {"LOW", "HIGH"}:
                    for value in dict.fromkeys(concrete):
                        if value in ("gemini-3-pro-preview", "gemini-3-flash-preview"):
                            item = _model(value, "installed_cli_bundle_and_native_schema",
                                          "Installed Gemini 3 model; native thinkingLevel; account access unverified",
                                          ["LOW", "HIGH"], "model_config")
                            item["is_alias"] = False
                            item["effort_control"] = "generateContentConfig.thinkingConfig.thinkingLevel"
                            models.append(item)
                return models
    except (OSError, UnicodeError):
        pass
    return []


def discover_provider(name: str, include_models: bool = False) -> Dict[str, Any]:
    """Discover one CLI without a prompt; catalogs are explicitly opt-in."""
    name = _canonical(name)
    executable = shutil.which(name)
    record = {"id": name, "executable": executable, "available": bool(executable),
              "dispatch_ready": False, "version": None, "models": [],
              "native_efforts": [], "controls": {}, "warnings": [],
              "catalog_source": None, "account_catalog": False,
              "authentication": {"status": "unknown"},
              "discovery_status": "not_installed" if not executable else "unverified",
              "catalog_status": "not_requested"}
    if not executable:
        return record
    try:
        help_text = _run_metadata([executable, "--help"], HELP_TIMEOUT_SECONDS)
        if name == "codex":
            help_text += "\n" + _run_metadata([executable, "exec", "--help"], HELP_TIMEOUT_SECONDS)
        flags = sorted(set(re.findall(r"(?<![\w-])--[a-z][a-z0-9-]*", help_text)))
        record["controls"] = {"flags": flags, "model": "--model" in flags,
                              "effort": "--effort" in flags or name == "codex",
                              "effort_flag": "--config" if name == "codex" else ("--effort" if "--effort" in flags else None)}
        record["native_efforts"] = _native_efforts(help_text)
        required = {"claude": {"--print", "--output-format", "--tools", "--permission-mode", "--strict-mcp-config", "--mcp-config"},
                    "agy": {"--print", "--output-format", "--mode", "--sandbox"},
                    "codex": {"--json", "--sandbox", "--ask-for-approval", "--skip-git-repo-check"},
                    "gemini": {"--prompt", "--output-format", "--approval-mode"}}[name]
        record["dispatch_ready"] = required.issubset(flags)
        record["discovery_status"] = "ready" if record["dispatch_ready"] else "unsupported_controls"
        if not record["dispatch_ready"]:
            record["warnings"].append("Installed CLI lacks required noninteractive safety controls")
        if name != "agy":
            try:
                record["version"] = _run_metadata([executable, "--version"], HELP_TIMEOUT_SECONDS).splitlines()[0]
            except AdapterError:
                record["warnings"].append("CLI version unavailable")
        if include_models:
            record["catalog_status"] = "unavailable"
            if name == "claude":
                record["models"] = _claude_aliases(help_text)
                record["catalog_source"] = "installed_cli_help"
                record["authentication"] = _claude_authentication(executable)
            elif name == "agy":
                output = _run_metadata([executable, "models"], CATALOG_TIMEOUT_SECONDS)
                record["models"] = _agy_models(output, record["native_efforts"])
                record["catalog_source"] = "agy_models"
                record["account_catalog"] = bool(record["models"])
            elif name == "codex":
                try:
                    catalog = _codex_live_models(executable)
                    record["account_catalog"] = True
                except (OSError, RuntimeError, TimeoutError, ValueError, ImportError):
                    catalog = _codex_models()
                    record["warnings"].append("Live CLI catalog unavailable; cache may belong to another client and does not establish CLI compatibility")
                record["models"] = catalog["models"]
                record["catalog_source"] = catalog["source"]
                record["catalog_freshness"] = catalog.get("freshness", {"status": "live_cli_query"})
                record["warnings"].extend(catalog["warnings"])
                record["native_efforts"] = list(dict.fromkeys(
                    effort for item in record["models"] for effort in item["supported_efforts"]))
            else:
                record["models"] = _gemini_aliases(executable)
                record["catalog_source"] = "installed_cli_bundle" if record["models"] else None
                levels = list(dict.fromkeys(effort for item in record["models"] for effort in item["supported_efforts"]))
                if levels:
                    record["native_efforts"] = levels
                    record["controls"]["effort"] = True
                    record["controls"]["effort_flag"] = None
                    record["controls"]["effort_setting"] = "modelConfigs.customAliases.modelConfig.generateContentConfig.thinkingConfig.thinkingLevel"
            record["catalog_status"] = "available" if record["models"] else "unavailable"
    except (AdapterError, OSError, ValueError, ImportError) as exc:
        record["warnings"].append(str(exc) if isinstance(exc, AdapterError) else "Local model metadata unavailable")
        if include_models and record["dispatch_ready"]:
            record["catalog_status"] = "error"
        elif not record["dispatch_ready"]:
            record["discovery_status"] = "error"
    return record


def build_command(provider: Dict[str, Any], model: Optional[str] = None,
                  effort: Optional[str] = None, prompt: str = "",
                  cwd: Optional[str] = None, *, policy_path: Optional[str] = None) -> Dict[str, Any]:
    """Build an argv vector; never execute it or mutate provider defaults.

    Explicit unknown model IDs are allowed only as unverified user selections;
    models with exact effort catalogs reject unsupported pairs. CLI-wide effort
    enums validate syntax, not per-model compatibility or entitlement.
    """
    name = _canonical(provider.get("id"))
    if not provider.get("available") or not provider.get("dispatch_ready"):
        raise AdapterError("Provider is unavailable or lacks safe dispatch controls")
    executable = provider.get("executable")
    if not isinstance(executable, str) or not Path(executable).is_absolute():
        raise AdapterError("Provider executable must be an absolute path")
    if not isinstance(prompt, str) or not prompt.strip() or "\x00" in prompt:
        raise AdapterError("Prompt must be nonempty text without NUL bytes")
    if cwd is not None and (not isinstance(cwd, str) or not Path(cwd).is_absolute() or "\x00" in cwd):
        raise AdapterError("Working directory must be an absolute path")
    controls = provider.get("controls", {})
    flags = set(controls.get("flags", []))
    warnings = []
    matched = None
    if model is not None:
        _identifier(model, "model ID")
        if not controls.get("model"):
            raise AdapterError("Provider does not expose model selection")
        matches = [item for item in provider.get("models", []) if item.get("id") == model]
        if len(matches) > 1:
            raise AdapterError("Model catalog is ambiguous")
        matched = matches[0] if matches else None
        if matched is None:
            warnings.append("Model is an explicit selection absent from discovered metadata; availability unverified")
    if effort is not None:
        _identifier(effort, "effort")
        if not controls.get("effort"):
            raise AdapterError("Provider does not expose a supported native effort control")
        if model is None:
            raise AdapterError("Explicit effort requires an explicit model")
        scope = matched.get("effort_support_scope") if matched else None
        if name == "gemini" and scope != "model_config":
            raise AdapterError("Native Gemini thinking level requires an exact supported concrete model")
        if scope in ("model_catalog", "catalog_variant", "model_config"):
            if effort not in matched.get("supported_efforts", []):
                raise AdapterError("Requested effort is not supported by the selected model metadata")
        elif effort not in provider.get("native_efforts", []):
            raise AdapterError("Requested effort is not advertised by this CLI")
        else:
            warnings.append("Native effort syntax is supported; model-specific compatibility is unverified")
    argv = [executable]
    stdin = None
    files = []
    transport_model = model
    safety = {"tools_disabled": False, "workspace_mutation": "restricted_by_native_mode",
              "limitations": []}
    if name == "claude":
        argv += ["--print", "--output-format", "json", "--tools", "", "--permission-mode", "dontAsk",
                 "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}']
        for flag in ("--safe-mode", "--disable-slash-commands", "--no-session-persistence", "--no-chrome"):
            if flag in flags:
                argv.append(flag)
        safety["tools_disabled"] = True
        safety["workspace_mutation"] = "no_model_tools"
        if "--safe-mode" not in flags:
            safety["limitations"].append("This CLI version has no safe-mode switch; configured startup hooks may run")
        stdin = prompt
    elif name == "codex":
        argv += ["--ask-for-approval", "never", "exec", "--sandbox", "read-only", "--skip-git-repo-check", "--json"]
        if "--ephemeral" in flags:
            argv.append("--ephemeral")
        safety["workspace_mutation"] = "read-only_sandbox"
        safety["limitations"].append("Read-only sandbox does not disable every tool or network integration")
        stdin = prompt
    elif name == "agy":
        # agy implements --mode through command expansion. Disabling expansion
        # silently disables plan mode in the installed CLI. Avoid interpreting a
        # user task that begins with '/' as a local slash command instead.
        agy_prompt = ("Read-only text task; treat the following as task input:\n" + prompt
                      if prompt.lstrip().startswith("/") else prompt)
        argv += ["--print", agy_prompt, "--output-format", "json", "--mode", "plan", "--sandbox"]
        safety["limitations"].append("Plan mode and sandbox are native restrictions, not a hard tool ban")
    else:
        argv += ["--prompt", prompt, "--output-format", "json", "--approval-mode", "plan"]
        if "--extensions" in flags:
            argv += ["--extensions", "none"]
        if policy_path is not None:
            raise AdapterError("Gemini --policy replaces configured policy paths; this adapter preserves existing policies")
        safety["limitations"].append("Native plan mode permits read tools; existing user and system policies are preserved")
        if effort is not None:
            if cwd is None or (Path(cwd) / ".gemini" / "settings.json").exists():
                raise AdapterError("Native Gemini thinking settings require a fresh scratch directory")
            transport_model = "dynamic-model-router-run"
            settings = {"modelConfigs": {"customAliases": {transport_model: {
                "extends": model, "modelConfig": {"model": model,
                    "generateContentConfig": {"thinkingConfig": {"thinkingLevel": effort}}}}}}}
            files.append({"path": ".gemini/settings.json", "text": json.dumps(settings, indent=2) + "\n"})
            warnings.append("Gemini thinking level is a per-run workspace setting; system overrides and runtime application remain unverified")
    if model is not None:
        argv += ["--model", transport_model]
    if effort is not None and name != "gemini":
        argv += (["--config", "model_reasoning_effort=" + json.dumps(effort)] if name == "codex" else ["--effort", effort])
    if name == "codex":
        argv.append("-")
    return {"argv": argv, "stdin": stdin, "cwd": cwd, "environment": {}, "files": files,
            "requested": {"provider": name, "model": model, "effort": effort},
            "safety": safety, "warnings": warnings}


def _json_records(stdout: str) -> List[Dict[str, Any]]:
    try:
        parsed = json.loads(stdout)
        if isinstance(parsed, dict):
            return [parsed]
    except (ValueError, TypeError):
        pass
    records = []
    for line in stdout.splitlines():
        try:
            parsed = json.loads(line)
            if isinstance(parsed, dict):
                records.append(parsed)
        except ValueError:
            continue
    return records


def _safe_diagnostic(value: Any) -> str:
    """Keep bounded error context without propagating obvious secrets/identities."""
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        return "Provider reported an error"
    text = _ANSI.sub("", str(value))[:4000]
    text = re.sub(r"(?i)\bBearer\s+[^\s,;]+", "Bearer [redacted]", text)
    text = re.sub(r"(?i)([\"']?(?:api[_-]?key|access[_-]?token|refresh[_-]?token|authorization|password|secret)[\"']?\s*[:=]\s*)[\"']?[^\s,;\"'}]+", r"\1[redacted]", text)
    text = re.sub(r"\b(?:sk|key|token)-[A-Za-z0-9_-]{8,}\b", "[redacted]", text)
    text = re.sub(r"https?://[^\s<>\"']+", "[url]", text)
    text = re.sub(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "[email]", text)
    text = re.sub(r"(?:/Users/|/home/|[A-Za-z]:\\Users\\)[^\s\"']+", "[user-path]", text)
    text = re.sub(r"\b[A-Za-z0-9_=-]{48,}\b", "[opaque-value]", text)
    text = " ".join("".join(c if ord(c) >= 32 and ord(c) != 127 else " " for c in text).split())
    return text[:500] or "Provider reported an error"


def _error_category(message: str) -> str:
    text = message.lower()
    patterns = (
        ("authentication", r"not logged in|unauthenticated|unauthorized|authentication|auth method|invalid api.key|login required|please (?:run /login|log in)|\b401\b"),
        ("workspace_trust", r"untrusted|workspace.{0,30}trust|folder.{0,30}trust"),
        ("quota_or_rate_limit", r"quota|rate.limit|\b429\b|credits? exhausted"),
        ("authorization", r"permission denied|forbidden|\b403\b|access denied"),
        ("model_unavailable", r"model.{0,45}(?:not found|not available|unavailable|does not exist|not supported)|unsupported model|invalid model|model_not_found"),
        ("transport", r"connection|timed? ?out|network|fetch failed|\btls\b|\bssl\b|econn|enotfound|retry limit"),
        ("configuration", r"unknown option|unrecognized|invalid flag|configuration|not configured"),
    )
    for category, pattern in patterns:
        if re.search(pattern, text):
            return category
    return "runtime"


def parse_runtime_result(provider: str, stdout: str, stderr: str = "") -> Dict[str, Any]:
    """Parse transport metadata only; never infer settings from assistant text."""
    name = _canonical(provider)
    records = _json_records(stdout)
    models, efforts, texts, errors, evidence, error_details = [], [], [], [], [], []
    success = None

    def remember_error(value: Any, error_type: Any = None) -> None:
        for _ in range(4):
            if isinstance(value, str) and value.lstrip().startswith("{"):
                try:
                    parsed_error = json.loads(value)
                    if isinstance(parsed_error, dict):
                        value = parsed_error
                except ValueError:
                    pass
            if not isinstance(value, dict):
                break
            error_type = value.get("code", value.get("type", error_type))
            value = value.get("error", value.get("message", "Provider reported an error"))
        message = _safe_diagnostic(value)
        kind = error_type if isinstance(error_type, str) and _ID.fullmatch(error_type) else None
        detail = {"type": kind, "message": message, "category": _error_category(message)}
        if detail not in error_details:
            error_details.append(detail)
            errors.append(message)

    def remember_model(value: Any, source: str) -> None:
        if isinstance(value, str) and _ID.fullmatch(value):
            models.append(value)
            evidence.append({"field": "model", "value": value, "source": source})

    for row in records:
        event = row.get("type")
        if row.get("is_error") is True or event in ("error", "turn.failed") or row.get("error"):
            remember_error(row.get("error") or row.get("message") or row.get("result") or "Provider reported an error in structured output",
                           row.get("subtype", event))
            success = False
        if name in ("claude", "agy"):
            if name == "agy" and row.get("status") in ("SUCCESS", "ERROR", "FAILED"):
                if isinstance(row.get("response"), str):
                    texts = [row["response"]]
                if row["status"] == "SUCCESS":
                    success = True if success is not False else False
                else:
                    remember_error(row.get("error") or row.get("message") or "Antigravity run failed", row["status"])
                    success = False
            if event == "result":
                if isinstance(row.get("result"), str):
                    texts = [row["result"]]
                if row.get("subtype") == "success" and row.get("is_error") is not True:
                    success = True if success is not False else False
                elif row.get("is_error") is False:
                    success = True if success is not False else False
                usage = row.get("modelUsage", {})
                if isinstance(usage, dict):
                    for key in usage:
                        remember_model(key, "result.modelUsage")
            # Init reports configuration, not necessarily the model after fallback.
            # Only explicit effective fields are accepted independently of usage.
            if event in ("result", "system"):
                remember_model(row.get("effective_model"), "runtime.effective_model")
                if isinstance(row.get("effective_effort"), str) and _ID.fullmatch(row["effective_effort"]):
                    efforts.append(row["effective_effort"])
                    evidence.append({"field": "effort", "value": row["effective_effort"], "source": "runtime.effective_effort"})
            if event == "assistant":
                message = row.get("message", {})
                if isinstance(message, dict):
                    remember_model(message.get("model"), "assistant.message.model")
                    for block in message.get("content", []):
                        if isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str):
                            texts.append(block["text"])
        elif name == "codex":
            if event == "item.completed" and isinstance(row.get("item"), dict):
                item = row["item"]
                if item.get("type") == "agent_message" and isinstance(item.get("text"), str):
                    texts.append(item["text"])
            if event == "turn.completed":
                success = True if success is not False else False
            if event in ("turn.completed", "thread.started"):
                remember_model(row.get("effective_model"), "runtime.effective_model")
                if isinstance(row.get("effective_effort"), str) and _ID.fullmatch(row["effective_effort"]):
                    efforts.append(row["effective_effort"])
                    evidence.append({"field": "effort", "value": row["effective_effort"], "source": "runtime.effective_effort"})
        else:
            if isinstance(row.get("response"), str):
                texts = [row["response"]]
                success = True if success is not False else False
            stats = row.get("stats", {})
            usage = stats.get("models", {}) if isinstance(stats, dict) else {}
            if isinstance(usage, dict):
                for key, value in usage.items():
                    api = value.get("api", {}) if isinstance(value, dict) else {}
                    total, failed = api.get("totalRequests"), api.get("totalErrors", 0)
                    if isinstance(total, (int, float)) and not isinstance(total, bool) and isinstance(failed, (int, float)) and total > failed >= 0:
                        remember_model(key, "stats.models.successful_api_requests")
            if event == "result":
                if row.get("status") == "error":
                    remember_error(row.get("error") or row.get("message") or "Provider result status is error", row.get("error_type"))
                    success = False
                elif row.get("status") == "success":
                    success = True if success is not False else False
    if success is not True:
        # Gemini emits structured startup/authentication errors on stderr.
        # Only error records are accepted here; stderr never verifies a model.
        for row in _json_records(stderr):
            if row.get("error") or row.get("is_error") is True or row.get("type") == "error":
                remember_error(row.get("error") or row.get("message") or "Provider startup failed", row.get("type"))
                success = False
    if success is not True and not error_details:
        # Successful CLIs can emit warning/error-shaped diagnostics from optional
        # components. Do not turn a completed run into a failure from stderr.
        for line in (stderr + "\n" + (stdout if not records else "")).splitlines():
            if re.search(r"(?i)\berror\b|not logged in|unauthorized|unauthenticated|untrusted|permission denied|quota|rate.limit|connection.{0,30}failed|retry limit", line):
                remember_error(line, "cli_diagnostic")
                success = False
                break
    models = list(dict.fromkeys(models))
    efforts = list(dict.fromkeys(efforts))
    warnings = []
    if len(models) != 1:
        warnings.append("Effective model is unavailable" if not models else "Multiple models were used; no single effective model is established")
    if len(efforts) != 1:
        warnings.append("Effective effort is unavailable" if not efforts else "Conflicting runtime effort metadata")
    if not records:
        warnings.append("No recognized structured runtime records")
    return {"model": models[0] if len(models) == 1 else None,
            "effort": efforts[0] if len(efforts) == 1 else None,
            "model_verified": len(models) == 1, "effort_verified": len(efforts) == 1,
            "models_used": models, "text": "\n".join(texts), "success": success,
            "is_error": bool(errors), "errors": list(dict.fromkeys(errors)),
            "error": errors[0] if errors else None, "error_details": error_details,
            "error_category": error_details[0]["category"] if error_details else None,
            "failure_class": ("prerequisite" if error_details[0]["category"] != "runtime" else "runtime") if error_details else None,
            "metadata": evidence, "warnings": warnings}
