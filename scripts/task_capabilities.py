#!/usr/bin/env python3
"""Choose capability-qualified interfaces, without invoking tools or models.

The hosting agent supplies a fresh manifest exported from its actual tool schema
or a native tool catalog. Manifest metadata is data, not executable authority.
The caller must re-resolve a selected tool in its own host before invocation.
This module reports declared interface evidence, never successful generation,
account entitlement, or an effective backend model inferred from a tool name.
"""

import hashlib
import re


CAPABILITIES = (
    "text_generation", "image_generation", "image_editing", "vision",
    "audio_generation", "audio_transcription", "video_generation",
)
TEXT_PROVIDERS = ("claude", "agy", "codex", "gemini")
TOOL_EVIDENCE = ("host_tool_schema", "native_tool_catalog", "runtime_observation")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@+\-]{0,255}\Z")


class CapabilityError(ValueError):
    pass


def normalize_required(required):
    if isinstance(required, str):
        required = [required]
    if not isinstance(required, (list, tuple)) or not required:
        raise CapabilityError("At least one explicit required capability is needed")
    if any(not isinstance(item, str) or item not in CAPABILITIES for item in required):
        raise CapabilityError("Unknown required capability")
    return list(dict.fromkeys(required))


def _identifier(value):
    return isinstance(value, str) and bool(_ID.fullmatch(value))


def _manifest_tools(host_tools):
    if host_tools is None:
        return []
    if isinstance(host_tools, dict):
        if host_tools.get("schema_version", 1) != 1:
            raise CapabilityError("Unsupported host-tool manifest schema")
        host_tools = host_tools.get("tools")
    if not isinstance(host_tools, list) or len(host_tools) > 1000:
        raise CapabilityError("Host tools must be a bounded list of interface records")
    return host_tools


def _route_record(raw, *, origin, provider=None):
    if not isinstance(raw, dict):
        return None, "invalid_interface"
    pid = raw.get("provider", provider)
    if provider is not None and pid != provider:
        return None, "provider_scope_mismatch"
    if not _identifier(raw.get("id")) or not _identifier(pid):
        return None, "invalid_identity"
    if raw.get("available") is not True or raw.get("hidden") is True:
        return None, "interface_unavailable"
    authentication = raw.get("authentication", {})
    if not isinstance(authentication, dict):
        return None, "invalid_authentication_metadata"
    if authentication.get("status") == "missing":
        return None, "interface_login_required"
    caps = raw.get("capabilities")
    if not isinstance(caps, list) or not caps or any(cap not in CAPABILITIES for cap in caps):
        return None, "explicit_capability_evidence_required"
    if not _identifier(raw.get("tool")):
        return None, "tool_identity_required"
    model = raw.get("model")
    if model is not None and not _identifier(model):
        return None, "invalid_model_identity"
    evidence = raw.get("evidence")
    if not isinstance(evidence, dict) or evidence.get("kind") not in TOOL_EVIDENCE:
        return None, "current_interface_evidence_required"
    source = evidence.get("source")
    if (not isinstance(source, str) or not source.strip() or len(source) > 2000
            or any(char in source for char in ("\x00", "\n", "\r"))):
        return None, "evidence_source_required"
    mode = raw.get("execution_mode")
    if mode not in ("native_tool", "external_tool"):
        return None, "unsupported_interface_mode"
    return {
        "id": raw["id"], "provider": pid, "tool": raw["tool"],
        "model": model, "capabilities": list(dict.fromkeys(caps)),
        "execution_mode": mode, "origin": origin,
        "evidence": {"kind": evidence["kind"], "source": source},
        "authentication": {"status": authentication.get("status", "unknown")},
        "runtime_verified": False,
        "evidence_scope": "Declared interface capability; not account access or generated-output proof",
    }, None


def capability_candidates(inventory, required, *, host_tools=None):
    """Return eligible interfaces and fixed-code exclusions for this snapshot.

    Existing registered text adapters provide text candidates only. Artifact
    output needs explicit native/external tool routes; a model catalog, model
    description, input-image flag, or vision declaration cannot provide one.
    Tool routes are scoped independently from a provider's text CLI login.
    """
    required = normalize_required(required)
    if not isinstance(inventory, dict) or not isinstance(inventory.get("providers", []), list):
        raise CapabilityError("Provider inventory is malformed")
    routes, excluded, discovery_only = [], [], []

    def add(raw, origin, provider=None):
        route, error = _route_record(raw, origin=origin, provider=provider)
        if error:
            excluded.append({"id": raw.get("id") if isinstance(raw, dict) and _identifier(raw.get("id")) else None,
                             "reason": error})
        else:
            routes.append(route)

    for raw in _manifest_tools(host_tools):
        add(raw, "host_tool_manifest")
    for record in inventory.get("providers", []):
        if not isinstance(record, dict) or not _identifier(record.get("id")):
            excluded.append({"id": None, "reason": "invalid_provider"})
            continue
        pid = record["id"]
        native = record.get("native_capabilities", {})
        if ("image_generation" in required and pid == "codex"
                and record.get("available") is True and record.get("hidden") is not True
                and isinstance(native, dict) and native.get("status") == "advertised"
                and native.get("source") == "codex_cli_app_server_model_provider_capabilities"
                and native.get("scope") == "provider" and native.get("image_generation") is True
                and native.get("execution_verified") is False):
            discovery_only.append({
                "provider": pid, "model": None, "tool": None,
                "capabilities": ["image_generation"], "status": "advertised_not_dispatchable",
                "source": native["source"], "scope": "provider", "eligible": False,
                "dispatch_ready": False, "execution_verified": False,
                "message": "Provider advertises image generation, but the registered text dispatcher lacks an artifact output adapter. Discover a callable image tool before selecting this provider.",
            })
        declared = record.get("capability_routes", [])
        if not isinstance(declared, list) or len(declared) > 1000:
            raise CapabilityError("Provider capability routes must be a bounded list")
        for raw in declared:
            add(raw, "provider_tool_catalog", provider=pid)
        if pid not in TEXT_PROVIDERS:
            continue
        auth = record.get("authentication", {})
        if (record.get("available") is not True or record.get("dispatch_ready") is not True
                or record.get("hidden") is True or not isinstance(auth, dict)
                or auth.get("status") == "missing"):
            excluded.append({"id": pid, "reason": "text_cli_unavailable"})
            continue
        models = record.get("models", [])
        if not isinstance(models, list):
            raise CapabilityError("Provider model catalog is malformed")
        if not models:
            models = [{"id": None}]
        for model in models:
            if not isinstance(model, dict) or model.get("hidden") is True or model.get("available") is False:
                continue
            mid = model.get("id", model.get("model"))
            if mid is not None and not _identifier(mid):
                continue
            identity = pid + ":text:" + (mid or "default")
            if len(identity) > 256:
                identity = pid + ":text:" + hashlib.sha256(mid.encode()).hexdigest()
            routes.append({"id": identity, "provider": pid,
                           "tool": "text_cli", "model": mid, "capabilities": ["text_generation"],
                           "execution_mode": "text_cli", "origin": "registered_text_adapter",
                           "evidence": {"kind": "adapter_contract", "source": "provider_adapters.build_command"},
                           "authentication": {"status": auth.get("status", "unknown")},
                           "runtime_verified": False,
                           "evidence_scope": "Installed text adapter; model availability and inference unverified"})
    counts, identities = {}, {}
    for route in routes:
        counts[route["id"]] = counts.get(route["id"], 0) + 1
        identity = (route["provider"], route["tool"], route["model"])
        identities[identity] = identities.get(identity, 0) + 1
    candidates = []
    for route in routes:
        identity = (route["provider"], route["tool"], route["model"])
        if counts[route["id"]] > 1:
            excluded.append({"id": route["id"], "reason": "ambiguous_interface_id"})
        elif identities[identity] > 1:
            excluded.append({"id": route["id"], "reason": "ambiguous_interface_identity"})
        elif not set(required).issubset(route["capabilities"]):
            excluded.append({"id": route["id"], "reason": "required_capability_unavailable"})
        else:
            candidates.append(route)
    return {"required_capabilities": required, "candidates": candidates, "excluded": excluded,
            "discovery_only": discovery_only}


def select_capability_route(inventory, required, *, host_tools=None, provider=None,
                            candidate=None, model=None):
    """Return a choice prompt intent or a recommendation; never dispatch."""
    for value in (provider, candidate, model):
        if value is not None and not _identifier(value):
            raise CapabilityError("Explicit interface locks must be valid identifiers")
    result = capability_candidates(inventory, required, host_tools=host_tools)
    eligible = result["candidates"]
    result["candidates"] = [route for route in eligible
                            if (provider is None or route["provider"] == provider)
                            and (candidate is None or route["id"] == candidate)
                            and (model is None or route["model"] == model)]
    for route in eligible:
        if route not in result["candidates"]:
            result["excluded"].append({"id": route["id"], "reason": "explicit_lock_mismatch"})
    count = len(result["candidates"])
    result.update(status="blocked" if count == 0 else "ready" if count == 1 else "choice_required",
                  selected=result["candidates"][0] if count == 1 else None,
                  selection_required=count > 1, runtime_verified=False, dispatch_authorized=False,
                  locks={"provider": provider, "candidate": candidate, "model": model},
                  reason="No evidenced interface satisfies the requirements and locks" if count == 0
                  else "One evidenced interface satisfies the requirements and locks" if count == 1
                  else "Multiple evidenced interfaces are available; ask the user to choose before dispatch")
    return result
