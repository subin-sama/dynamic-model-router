#!/usr/bin/env python3
"""A choice-gated, single-use native Codex image-output adapter.

This is separate from the text-work dispatcher. It accepts only a completed
native imageGeneration item, validates PNG bytes, and never treats prose or a
savedPath claim as an image. No parent model/effort or global settings change.
"""

import argparse
import base64
import binascii
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import shutil
import signal
import stat
import struct
import subprocess
import sys
import tempfile
import threading
import time
import zlib

from codex_rpc import RpcClient, RpcError


ROUTE = 'codex-native-image'
MAX_PROMPT = 32000
MAX_REQUEST = 160000
MAX_IMAGE = 32 * 1024 * 1024
MAX_RPC_LINE = 48 * 1024 * 1024
MAX_RPC_TOTAL = 192 * 1024 * 1024
MAX_PIXELS = 20_000_000
TICKET_TTL = 24 * 60 * 60
MAX_DIAGNOSTIC_EVENTS = 512
MAX_PUBLIC_WORKER_TEXT = 8000


def server_argv(executable):
    # Disable dynamically injected app/plugin MCP servers before enumeration.
    # Native per-thread overrides alone are too late for that metadata view.
    return [executable, '--disable', 'apps', '--disable', 'plugins',
            'app-server', '--listen', 'stdio://']


def _version_key(value):
    match = re.fullmatch(r'(\d+)\.(\d+)\.(\d+)(?:-([A-Za-z0-9.+-]+))?', value or '')
    if not match:
        return None
    base = tuple(int(match.group(n)) for n in (1, 2, 3))
    suffix = match.group(4)
    parts = tuple((0, int(p)) if p.isdigit() else (1, p)
                  for p in re.split(r'[.+-]', suffix or '') if p)
    return base + (suffix is None, parts)


def _runtime_candidates(explicit=None):
    if explicit is not None:
        path = Path(explicit).expanduser()
        if not path.is_absolute():
            raise BridgeError('invalid_codex_path', 'An explicit Codex executable must be an absolute path.')
        return [('explicit', path)]
    result = []
    found = shutil.which('codex')
    if found:
        result.append(('PATH', Path(found)))
    if sys.platform == 'darwin':
        for applications in (Path('/Applications'), Path.home() / 'Applications'):
            for app in ('Codex.app', 'ChatGPT.app'):
                resources = applications / app / 'Contents' / 'Resources'
                result.extend([('macos_app_bundle', resources / 'codex-cli' / 'bin' / 'codex'),
                               ('macos_app_bundle', resources / 'codex')])
    return result


def _read_version(executable):
    """Bounded local --version; no provider prompt, shell or auth inspection."""
    output, exceeded = bytearray(), threading.Event()
    try:
        child = subprocess.Popen([str(executable), '--version'], stdin=subprocess.DEVNULL,
                                 stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError:
        return None

    def read():
        try:
            while True:
                chunk = child.stdout.read(512)
                if not chunk:
                    return
                if len(output) + len(chunk) > 4096:
                    exceeded.set()
                    return
                output.extend(chunk)
        except (OSError, ValueError):
            return

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    try:
        child.wait(timeout=4)
        reader.join(timeout=0.5)
        if child.returncode or exceeded.is_set() or reader.is_alive():
            return None
        text = output.decode('utf-8', errors='replace')
        match = re.search(r'\bcodex-cli\s+(\d+\.\d+\.\d+(?:-[A-Za-z0-9.+-]+)?)', text)
        return match.group(1) if match else None
    except subprocess.TimeoutExpired:
        return None
    finally:
        if os.name == 'posix':
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except (OSError, ProcessLookupError):
                pass
        if child.poll() is None:
            child.kill()
        try:
            child.wait(timeout=1)
        except subprocess.TimeoutExpired:
            pass
        child.stdout.close()
        reader.join(timeout=0.2)


def _binary_identity(path):
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or not os.access(str(path), os.X_OK):
        raise BridgeError('codex_not_executable', 'The selected Codex runtime is not an executable regular file.')
    identity = {'device': info.st_dev, 'inode': info.st_ino, 'size': info.st_size,
                'mtime_ns': info.st_mtime_ns}
    return digest(canonical(identity))


def discover_runtime(explicit=None):
    candidates, seen = [], set()
    for source, path in _runtime_candidates(explicit):
        try:
            path = path.resolve(strict=True)
            if path in seen:
                continue
            seen.add(path)
            fingerprint = _binary_identity(path)
            version = _read_version(path)
        except (OSError, BridgeError):
            if explicit is not None:
                raise BridgeError('codex_not_executable', 'The explicit Codex executable is unavailable; no replacement was selected.') from None
            continue
        key = _version_key(version)
        if key is None or key[:3] < (0, 146, 0):
            continue
        candidates.append({'executable': str(path), 'version': version, 'source': source,
                           'fingerprint': fingerprint})
    if not candidates:
        raise BridgeError('compatible_codex_not_found', 'No compatible Codex runtime was detected; this adapter requires native protocol version 0.146 or newer.')
    selected = max(candidates, key=lambda c: _version_key(c['version']))
    return {**selected, 'selection_basis': 'explicit' if explicit is not None else 'newest_detected_native_protocol',
            'metadata_only': True, 'compatible_candidates': len(candidates)}


def bound_runtime(ticket):
    runtime = ticket.get('codex_runtime')
    if not isinstance(runtime, dict):
        # Requests issued before runtime binding keep their original PATH-only
        # semantics rather than silently changing an already selected binary.
        path = _executable()
        return {'executable': path, 'version': None, 'source': 'legacy_PATH',
                'fingerprint': None, 'metadata_only': True}
    path = Path(runtime['executable'])
    if _binary_identity(path) != runtime['fingerprint'] or str(path.resolve(strict=True)) != str(path):
        raise BridgeError('codex_runtime_changed', 'The selected Codex executable changed after preparation; no generation was started.')
    return runtime


class BridgeError(RuntimeError):
    def __init__(self, code, message, details=None):
        self.code = code
        self.details = details or {}
        super().__init__(message)


class BoundedRpcClient(RpcClient):
    """The shared text transport with an explicit native-image wire bound."""
    def _read_stdout(self):
        total = 0
        try:
            while True:
                line = self.process.stdout.readline(MAX_RPC_LINE + 1)
                if not line:
                    break
                total += len(line.encode('utf-8'))
                if len(line) > MAX_RPC_LINE or total > MAX_RPC_TOTAL:
                    self._finish('Native image RPC output exceeded its bound')
                    return
                if not line.strip():
                    continue
                try:
                    message = json.loads(line)
                except ValueError:
                    self._finish('Native image RPC emitted invalid JSON')
                    return
                if not isinstance(message, dict):
                    self._finish('Native image RPC emitted an invalid message')
                    return
                if 'method' in message and 'id' in message:
                    self._decline_server_request(message)
                    continue
                with self._condition:
                    if 'id' in message:
                        if message['id'] in self._pending:
                            self._responses[message['id']] = message
                    elif 'method' in message:
                        if len(self._notifications) >= 20000:
                            self._finish('Native image RPC event count exceeded its bound')
                            return
                        self._notifications.append(message)
                    self._condition.notify_all()
        except (OSError, ValueError):
            pass
        finally:
            self._finish('Native image RPC peer closed its output')


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':')).encode('utf-8')


def digest(value):
    return hashlib.sha256(value).hexdigest()


def destination(value):
    """Resolve a caller-selected parent; never follow a final-file symlink."""
    raw = Path(value).expanduser().absolute()
    parent = raw.parent.resolve(strict=True)
    path = parent / raw.name
    if path.is_symlink():
        raise BridgeError('unsafe_path', 'A symlink destination is not supported.')
    return path


def private_write_new(path, content):
    """Publish complete bytes atomically without replacing any existing file."""
    path = destination(path)
    if path.exists():
        raise BridgeError('destination_exists', 'The destination already exists; it was preserved.')
    fd, temporary = tempfile.mkstemp(prefix='.image-bridge-', dir=str(path.parent))
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        # Hard-link publication is atomic and fails for a competing file or
        # symlink. The temporary file is always our own, in the same directory.
        os.link(temporary, path)
    except FileExistsError:
        raise BridgeError('destination_exists', 'The destination appeared concurrently; it was preserved.') from None
    finally:
        os.unlink(temporary)
    return path


def state_root():
    base = os.environ.get('XDG_STATE_HOME')
    if not base and os.name == 'nt':
        base = os.environ.get('LOCALAPPDATA')
    base = Path(base).expanduser() if base else Path.home() / '.local' / 'state'
    if not base.is_absolute():
        raise BridgeError('invalid_state_root', 'The image bridge state directory must be absolute.')
    # Resolve the caller's configured base (macOS /var and /tmp are normal
    # aliases), then reject symlinks in the bridge-owned descendants.
    base = base.resolve()
    base.mkdir(mode=0o700, parents=True, exist_ok=True)
    parent = base / 'dynamic-model-router'
    result = parent / 'image-requests'
    for directory in (parent, result):
        if directory.is_symlink():
            raise BridgeError('unsafe_state_root', 'The image bridge state directory must not be a symlink.')
        directory.mkdir(mode=0o700, exist_ok=True)
    if result.is_symlink() or result.resolve() != result.absolute():
        raise BridgeError('unsafe_state_root', 'The image bridge state directory must not be a symlink.')
    if os.name == 'posix' and result.stat().st_mode & 0o077:
        raise BridgeError('unsafe_state_permissions', 'The image bridge state directory must be private.')
    return result


def read_json_file(path, limit=MAX_REQUEST):
    path = destination(path)
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
    fd = os.open(str(path), flags)
    with os.fdopen(fd, 'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise BridgeError('invalid_request', 'The image request must be a regular file.')
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise BridgeError('request_too_large', 'The image request exceeded its size limit.')
    try:
        return json.loads(raw.decode('utf-8'))
    except (ValueError, UnicodeError):
        raise BridgeError('invalid_request', 'The image request is not valid UTF-8 JSON.') from None


def _setting(value, label):
    if value is not None and (not isinstance(value, str) or not value or len(value) > 256
                              or any(ord(c) < 32 for c in value)):
        raise BridgeError('invalid_setting', 'The requested native ' + label + ' is invalid.')
    return value


def prepare(prompt, request_file, model=None, effort=None, codex=None):
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > MAX_PROMPT:
        raise BridgeError('invalid_prompt', 'Provide a nonempty image prompt of at most 32000 characters.')
    output = destination(request_file)
    if output.exists():
        raise BridgeError('destination_exists', 'The request destination already exists; it was preserved.')
    runtime = discover_runtime(codex)
    ticket = {'version': 1, 'route': ROUTE, 'request_id': secrets.token_hex(24),
              'created_at': int(time.time()), 'prompt': prompt,
              'prompt_sha256': digest(prompt.encode('utf-8')),
              'settings': {'model': _setting(model, 'model'), 'effort': _setting(effort, 'effort')},
              'codex_runtime': runtime}
    ledger = state_root() / (ticket['request_id'] + '.json')
    private_write_new(ledger, canonical({'version': 1, 'ticket_sha256': digest(canonical(ticket))}))
    try:
        private_write_new(output, canonical(ticket))
    except BaseException:
        ledger.unlink()
        raise
    return {'status': 'choice_required', 'request_file': str(output),
            'routes': [{'id': ROUTE, 'provider': 'codex', 'image_backend_model': 'not_exposed',
                        'tool': 'native image_gen/imagegen through Codex App Server',
                        'availability': 'probe_required'}],
            'selection_required': True, 'generation_authorized': False,
            'bound_coordinator_settings': ticket['settings'],
            'runtime_discovery': runtime,
            'inference_sent': False}


def ticket_for(path):
    ticket = read_json_file(path)
    if (not isinstance(ticket, dict) or ticket.get('version') != 1 or ticket.get('route') != ROUTE
            or not isinstance(ticket.get('request_id'), str)
            or len(ticket['request_id']) != 48
            or any(c not in '0123456789abcdef' for c in ticket['request_id'])
            or not isinstance(ticket.get('prompt'), str) or not ticket['prompt'].strip()
            or len(ticket['prompt']) > MAX_PROMPT
            or ticket.get('prompt_sha256') != digest(ticket['prompt'].encode('utf-8'))
            or type(ticket.get('created_at')) is not int):
        raise BridgeError('invalid_request', 'The image request ticket is invalid.')
    if not 0 <= time.time() - ticket['created_at'] <= TICKET_TTL:
        raise BridgeError('request_expired', 'Prepare a new request; this image request has expired.')
    settings = ticket.get('settings', {})
    if not isinstance(settings, dict) or any(k not in ('model', 'effort') for k in settings):
        raise BridgeError('invalid_request', 'The native settings in this image request are invalid.')
    _setting(settings.get('model'), 'model')
    _setting(settings.get('effort'), 'effort')
    runtime = ticket.get('codex_runtime')
    if runtime is not None and (not isinstance(runtime, dict)
            or not isinstance(runtime.get('executable'), str) or not Path(runtime['executable']).is_absolute()
            or _version_key(runtime.get('version')) is None
            or not isinstance(runtime.get('fingerprint'), str) or len(runtime['fingerprint']) != 64
            or any(c not in '0123456789abcdef' for c in runtime['fingerprint'])):
        raise BridgeError('invalid_request', 'The bound Codex runtime in this image request is invalid.')
    root = state_root()
    record = read_json_file(root / (ticket['request_id'] + '.json'))
    if not isinstance(record, dict) or record.get('ticket_sha256') != digest(canonical(ticket)):
        raise BridgeError('request_changed', 'The issued image request changed; no generation was started.')
    if (root / (ticket['request_id'] + '.claimed')).exists():
        raise BridgeError('request_consumed', 'This image request was already used or cancelled; it will not be replayed.')
    return ticket, root


def claim(ticket, root, outcome):
    path = root / (ticket['request_id'] + '.claimed')
    try:
        private_write_new(path, canonical({'outcome': outcome, 'claimed_at': int(time.time()),
                                           'prompt_sha256': ticket['prompt_sha256']}))
    except BridgeError as error:
        if error.code == 'destination_exists':
            raise BridgeError('request_consumed', 'This image request was already used or cancelled; it will not be replayed.') from None
        raise


def cancel(request_file):
    ticket, root = ticket_for(request_file)
    claim(ticket, root, 'cancelled')
    return {'status': 'cancelled', 'generation_authorized': False, 'inference_sent': False}


def _remaining(deadline):
    left = deadline - time.monotonic()
    if left <= 0:
        raise BridgeError('timeout', 'The native image operation reached its deadline; it was not replayed.')
    return left


def _initialize(rpc, deadline):
    rpc.request('initialize', {'clientInfo': {'name': 'dynamic-model-router-image-bridge', 'version': '0.9.0'},
                               'capabilities': {'experimentalApi': True}}, timeout=min(15, _remaining(deadline)))
    rpc.notify('initialized', {})


def _catalog(rpc, deadline):
    models, cursor, seen = [], None, set()
    for _ in range(10):
        # An explicitly configured model can be hidden from the normal picker;
        # hidden does not mean the current setting is unsupported.
        args = {'limit': 100, 'includeHidden': True}
        if cursor:
            args['cursor'] = cursor
        page = rpc.request('model/list', args, timeout=min(10, _remaining(deadline)))
        if not isinstance(page, dict) or not isinstance(page.get('data'), list):
            raise BridgeError('catalog_invalid', 'The native model catalog was not usable.')
        models.extend(page['data'])
        cursor = page.get('nextCursor')
        if cursor is None:
            return models
        if not isinstance(cursor, str) or not cursor or cursor in seen or len(models) > 1000:
            break
        seen.add(cursor)
    raise BridgeError('catalog_invalid', 'The native model catalog did not finish within its bound.')


def _disabled_mcp_config(rpc, deadline):
    disabled, cursor, seen = {}, None, set()
    for _ in range(10):
        args = {'limit': 100, 'detail': 'toolsAndAuthOnly'}
        if cursor:
            args['cursor'] = cursor
        page = rpc.request('mcpServerStatus/list', args, timeout=min(15, _remaining(deadline)))
        if not isinstance(page, dict) or not isinstance(page.get('data'), list):
            raise BridgeError('mcp_status_unavailable', 'Configured MCP servers could not be isolated before generation.')
        for server in page['data']:
            name = server.get('name') if isinstance(server, dict) else None
            if not isinstance(name, str) or not name or len(name) > 1000:
                raise BridgeError('mcp_status_invalid', 'A configured MCP server name was invalid.')
            # The installed native override parser splits dotted paths without
            # TOML quoting rules. Override only each existing enabled leaf so
            # the original transport survives. Literal dots are unsupported;
            # never create a different server by guessing an escaped key.
            if '.' in name or any(ord(c) < 32 for c in name):
                raise BridgeError('mcp_name_unsupported', 'A configured MCP server name cannot be safely isolated by this native override parser.')
            disabled['mcp_servers.' + name + '.enabled'] = False
        cursor = page.get('nextCursor')
        if cursor is None:
            return disabled
        if not isinstance(cursor, str) or not cursor or cursor in seen or len(disabled) > 1000:
            break
        seen.add(cursor)
    raise BridgeError('mcp_status_invalid', 'Configured MCP enumeration exceeded its bound.')


def _verify_mcp_isolated(rpc, thread_id, deadline):
    cursor, seen, count = None, set(), 0
    for _ in range(10):
        args = {'limit': 100, 'detail': 'toolsAndAuthOnly', 'threadId': thread_id}
        if cursor:
            args['cursor'] = cursor
        page = rpc.request('mcpServerStatus/list', args, timeout=min(15, _remaining(deadline)))
        if not isinstance(page, dict) or not isinstance(page.get('data'), list):
            raise BridgeError('mcp_isolation_unverified', 'The native worker MCP isolation could not be verified.')
        for server in page['data']:
            if not isinstance(server, dict) or not isinstance(server.get('tools'), dict) or server['tools']:
                raise BridgeError('mcp_isolation_unverified', 'The native worker still exposes MCP tools; no image turn was started.')
        count += len(page['data'])
        cursor = page.get('nextCursor')
        if cursor is None:
            return
        if not isinstance(cursor, str) or not cursor or cursor in seen or count > 1000:
            break
        seen.add(cursor)
    raise BridgeError('mcp_isolation_unverified', 'The native worker MCP inventory exceeded its bound.')


def _efforts(model):
    return [e['reasoningEffort'] for e in model.get('supportedReasoningEfforts', [])
            if isinstance(e, dict) and isinstance(e.get('reasoningEffort'), str)]


def _eligible_choices(models):
    choices = []
    for item in models:
        # Hidden/reserve entries can verify an existing exact selection, but
        # are not general fallback recommendations for a new work unit.
        if (not isinstance(item, dict) or item.get('hidden') is True
                or 'image' not in item.get('inputModalities', [])):
            continue
        model = item.get('model')
        if not isinstance(model, str) or not model or len(model) > 256 or any(ord(c) < 32 for c in model):
            continue
        choices.append({'model': model, 'supported_efforts': _efforts(item),
                        'default_effort': item.get('defaultReasoningEffort'),
                        'catalog_default': item.get('isDefault') is True,
                        'role': 'chat_coordinator_not_image_backend'})
    return choices[:30]


def _start_native(rpc, cwd, deadline, model=None, effort=None, runtime=None):
    caps = rpc.request('modelProvider/capabilities/read', {}, timeout=min(10, _remaining(deadline)))
    if not isinstance(caps, dict) or caps.get('imageGeneration') is not True or caps.get('namespaceTools') is False:
        raise BridgeError('native_image_unavailable', 'The configured Codex provider does not expose required native image controls.')
    account = rpc.request('account/read', {'refreshToken': False}, timeout=min(10, _remaining(deadline)))
    account = account.get('account') if isinstance(account, dict) else None
    if not isinstance(account, dict):
        raise BridgeError('authentication_required', 'Codex native authentication is required before image generation.')
    if account.get('planType') == 'free':
        raise BridgeError('account_not_eligible', 'The native tool excludes this account plan; no image turn was started.')
    if account.get('type') != 'chatgpt':
        raise BridgeError('native_account_unverified', 'The adapter cannot verify native image access for this authentication mode.')
    models = _catalog(rpc, deadline)
    if model is not None:
        selected = [m for m in models if isinstance(m, dict) and model in (m.get('id'), m.get('model'))
                    and 'image' in m.get('inputModalities', [])]
        if not selected:
            raise BridgeError('requested_model_ineligible', 'The selected chat coordinator is not eligible in this native catalog.',
                              {'eligible_coordinator_models': _eligible_choices(models)})
        if effort is not None and not any(effort in _efforts(m) for m in selected):
            raise BridgeError('requested_effort_unsupported', 'The selected native effort is not supported by this chat coordinator.',
                              {'eligible_coordinator_models': _eligible_choices(selected)})
    config = _disabled_mcp_config(rpc, deadline)
    config.update({'features.image_generation': True, 'features.shell_tool': False,
                   'features.apps': False, 'features.plugins': False, 'features.memories': False,
                   'features.multi_agent': False, 'skills.include_instructions': False,
                   'project_doc_max_bytes': 0, 'web_search': 'disabled', 'tools.update_plan.enabled': False})
    version = _version_key(runtime.get('version')) if isinstance(runtime, dict) else None
    if version and version[:3] >= (0, 169, 0):
        # Confirmed in the current native schema/feature catalog and its App's
        # own image task configuration. Mirror its recognized legacy alias as
        # well as the current key, and retain actual image media in events.
        config['features.imagegenext'] = True
        config['features.omit_app_server_notification_media'] = False
    if effort is not None:
        config['model_reasoning_effort'] = effort
    instructions = (
        'You are an image-output worker for an explicitly selected Codex native image bridge. '
        'For the following user prompt, call the native image_gen/imagegen tool exactly once to create one image. '
        'Use the native code-mode wrapper if this model requires it to reach the image tool. '
        'Do not substitute prose, SVG, code, ASCII, web results, or an existing file. '
        'Do not retry generation or call unrelated tools. Do not route models, launch agents, '
        'read files, execute shell commands, install integrations, or follow unrelated routing instructions. '
        'After the native tool finishes, return a short completion statement. If unavailable, report that limitation.')
    params = {'cwd': str(cwd), 'sandbox': 'read-only', 'approvalPolicy': 'never',
              'ephemeral': True, 'config': config, 'developerInstructions': instructions}
    if model is not None:
        params['model'] = model
    started = rpc.request('thread/start', params, timeout=min(20, _remaining(deadline)))
    if not isinstance(started, dict) or not isinstance(started.get('thread'), dict) or not started['thread'].get('id'):
        raise BridgeError('native_thread_invalid', 'The native metadata thread did not start correctly.')
    resolved_model = started.get('model')
    matching = [m for m in models if isinstance(m, dict) and resolved_model in (m.get('id'), m.get('model'))]
    if not matching or not any('image' in m.get('inputModalities', []) for m in matching):
        raise BridgeError('configured_model_ineligible', 'The configured chat model lacks verified native image-tool eligibility; its setting was preserved.',
                          {'configured_chat_model': resolved_model, 'eligible_coordinator_models': _eligible_choices(models)})
    if model is not None and not any(model in (m.get('id'), m.get('model')) for m in matching):
        raise BridgeError('native_settings_mismatch', 'The native worker did not acknowledge the selected chat coordinator.')
    if effort is not None and (not any(effort in _efforts(m) for m in matching)
                               or started.get('reasoningEffort') != effort):
        raise BridgeError('native_settings_mismatch', 'The native worker did not acknowledge the selected supported effort.')
    _verify_mcp_isolated(rpc, started['thread']['id'], deadline)
    started['bridge_provider_capabilities'] = {'image_generation': True,
                                              'namespace_tools': caps.get('namespaceTools') if isinstance(caps.get('namespaceTools'), bool) else 'not_exposed'}
    return started


def _executable():
    path = shutil.which('codex')
    if not path:
        raise BridgeError('codex_not_found', 'The Codex CLI was not found on this machine.')
    return path


def probe(timeout=45, rpc_factory=BoundedRpcClient, model=None, effort=None, codex=None):
    deadline = time.monotonic() + checked_timeout(timeout)
    runtime = discover_runtime(codex)
    with tempfile.TemporaryDirectory(prefix='router-image-probe-') as cwd:
        with rpc_factory(server_argv(runtime['executable']), cwd=cwd) as rpc:
            _initialize(rpc, deadline)
            started = _start_native(rpc, Path(cwd), deadline, _setting(model, 'model'), _setting(effort, 'effort'), runtime)
    return {'status': 'available', 'route': ROUTE, 'provider': 'codex',
            'reported_chat_model': started.get('model'), 'reported_effort': started.get('reasoningEffort'),
            'requested_coordinator_settings': {'model': model, 'effort': effort},
            'runtime_discovery': runtime, 'provider_capabilities': started['bridge_provider_capabilities'],
            'image_backend_model': 'not_exposed', 'native_metadata_checks': 'passed',
            'artifact_generation_verified': False, 'metadata_thread_only': True,
            'generation_authorized': False, 'inference_sent': False}


def checked_timeout(value):
    if not isinstance(value, (int, float)) or not math.isfinite(value) or not 1 <= value <= 600:
        raise BridgeError('invalid_timeout', 'The timeout must be between 1 and 600 seconds.')
    return value


def validate_png(data):
    if not isinstance(data, bytes) or not 57 <= len(data) <= MAX_IMAGE or not data.startswith(b'\x89PNG\r\n\x1a\n'):
        raise BridgeError('artifact_invalid', 'Native output is not a supported complete PNG image.')
    offset, width, height, expected, ended = 8, None, None, None, False
    compressed = bytearray()
    while offset + 12 <= len(data):
        length = struct.unpack('>I', data[offset:offset + 4])[0]
        kind = data[offset + 4:offset + 8]
        end = offset + 12 + length
        if end > len(data) or length > MAX_IMAGE:
            raise BridgeError('artifact_invalid', 'A native PNG chunk was truncated.')
        payload = data[offset + 8:offset + 8 + length]
        crc = struct.unpack('>I', data[offset + 8 + length:end])[0]
        if zlib.crc32(kind + payload) & 0xffffffff != crc:
            raise BridgeError('artifact_invalid', 'A native PNG chunk failed its checksum.')
        if offset == 8:
            if kind != b'IHDR' or length != 13:
                raise BridgeError('artifact_invalid', 'The native PNG header was invalid.')
            width, height, depth, color, compression, filtering, interlace = struct.unpack('>IIBBBBB', payload)
            channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(color)
            allowed = {0: (1, 2, 4, 8, 16), 2: (8, 16), 3: (1, 2, 4, 8), 4: (8, 16), 6: (8, 16)}
            if (not width or not height or width * height > MAX_PIXELS or channels is None
                    or depth not in allowed[color] or compression or filtering or interlace):
                raise BridgeError('artifact_unsupported', 'The PNG dimensions or encoding exceed the supported validation bounds.')
            expected = height * (1 + (width * channels * depth + 7) // 8)
        elif kind == b'IHDR':
            raise BridgeError('artifact_invalid', 'The native PNG has duplicate headers.')
        if kind == b'IDAT':
            compressed.extend(payload)
        if kind == b'IEND':
            if length or end != len(data):
                raise BridgeError('artifact_invalid', 'The native PNG ending was invalid.')
            ended = True
            break
        offset = end
    if not ended or not compressed or expected is None or expected > MAX_PIXELS * 8 + 20000:
        raise BridgeError('artifact_invalid', 'The native PNG is missing image data or its ending.')
    try:
        decoder = zlib.decompressobj()
        pixels = decoder.decompress(bytes(compressed), expected + 1)
        if len(pixels) != expected or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
            raise ValueError()
        stride = expected // height
        if any(pixels[y * stride] > 4 for y in range(height)):
            raise ValueError()
    except (ValueError, zlib.error):
        raise BridgeError('artifact_invalid', 'The native PNG raster failed independent validation.') from None
    return {'media_type': 'image/png', 'width': width, 'height': height,
            'bytes': len(data), 'sha256': digest(data), 'validation': 'passed'}


def _native_saved_png(item, thread_id, codex_home):
    file_id, saved = item.get('fileId'), item.get('savedPath')
    if not isinstance(file_id, str) or not file_id or len(file_id) > 1000 or not isinstance(saved, str):
        raise BridgeError('artifact_unavailable', 'The native attachment has no supported local generated-image output path.')
    if not isinstance(thread_id, str) or not thread_id or Path(thread_id).name != thread_id:
        raise BridgeError('artifact_invalid', 'The native attachment thread identity is invalid.')
    raw = Path(saved)
    home = Path(codex_home).expanduser()
    if not raw.is_absolute() or not home.is_absolute() or '..' in raw.parts:
        raise BridgeError('artifact_unsafe_path', 'The native attachment is outside its authorized generated-image directory.')
    home = home.resolve(strict=True)
    allowed = home / 'generated_images' / thread_id
    try:
        relative = raw.relative_to(allowed)
    except ValueError:
        raise BridgeError('artifact_unsafe_path', 'The native attachment is outside this active thread\'s generated-image directory.') from None
    if not relative.parts:
        raise BridgeError('artifact_unsafe_path', 'The native attachment must name an image file.')
    # No filesystem paths from agent prose or arbitrary URLs are considered.
    # Only this completed native item's fileId-backed savedPath is eligible.
    for path in [home / 'generated_images', allowed] + [allowed.joinpath(*relative.parts[:i]) for i in range(1, len(relative.parts) + 1)]:
        if path.is_symlink():
            raise BridgeError('artifact_unsafe_path', 'A native generated-image path component is a symlink.')
    if raw.resolve(strict=True) != raw:
        raise BridgeError('artifact_unsafe_path', 'The native generated-image path did not remain canonical.')
    fd = os.open(str(raw), os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or not 57 <= info.st_size <= MAX_IMAGE:
            raise BridgeError('artifact_invalid', 'The native generated image is not a bounded regular file.')
        data = stream.read(MAX_IMAGE + 1)
    validation = validate_png(data)
    validation['payload_source'] = 'matching_native_generated_image_file'
    return data, validation


def image_bytes(item, thread_id=None, codex_home=None):
    encoded = item.get('result')
    if (not isinstance(encoded, str) or not encoded) and item.get('fileId'):
        if codex_home is None:
            raise BridgeError('artifact_unavailable', 'The native attachment store identity has no verified local output root.')
        return _native_saved_png(item, thread_id, codex_home)
    if not isinstance(encoded, str) or not encoded or len(encoded) > (MAX_IMAGE * 4 // 3 + 64):
        raise BridgeError('artifact_invalid', 'The completed native image item did not contain bounded image bytes.')
    if encoded.startswith('data:image/png;base64,'):
        encoded = encoded.split(',', 1)[1]
    try:
        data = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        raise BridgeError('artifact_invalid', 'The native image payload was not valid base64.') from None
    validation = validate_png(data)
    validation['payload_source'] = 'inline_native_image_result'
    return data, validation


def _native_codex_home():
    # RpcClient inherits this process's environment unchanged. Do not override
    # CODEX_HOME, read credentials, or guess a different runtime's cache root.
    value = os.environ.get('CODEX_HOME')
    home = Path(value).expanduser() if value else Path.home() / '.codex'
    return str(home) if home.is_absolute() else None


def _record(proof, value):
    if len(proof) < MAX_DIAGNOSTIC_EVENTS:
        proof.append(value)


def _diagnostic_string(value, limit=256):
    return value[:limit] if isinstance(value, str) else None


def _public_message(proof, item, native_method, thread_id, turn_id):
    # agentMessage is public output; reasoning and all of its summaries/deltas
    # are intentionally excluded. Keep only a bounded completed public message.
    text = item.get('text')
    if item.get('type') != 'agentMessage' or not isinstance(text, str) or not text:
        return
    # Public worker text is useful for an unavailable-tool explanation, but is
    # not a channel for retaining image data or credential-shaped material.
    text = re.sub(r'data:[^\s,]*;base64,[A-Za-z0-9+/=_-]+', '[image payload omitted]', text)
    text = re.sub(r'(?:iVBORw0KGgo|/9j/|UklGR)[A-Za-z0-9+/=_-]+', '[image payload omitted]', text)
    text = re.sub(r'(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{256,}={0,2}', '[encoded payload omitted]', text)
    text = re.sub(r'\bsk-[A-Za-z0-9_-]{12,}', '[credential omitted]', text)
    text = re.sub(r'(?i)\bBearer\s+[A-Za-z0-9._~+/-]{12,}=*', 'Bearer [credential omitted]', text)
    if any(p.get('event') == 'public_agent_message' and p.get('item_id') == item.get('id')
           and p.get('text') == text for p in proof):
        return
    used = sum(len(p.get('text', '')) for p in proof if p.get('event') == 'public_agent_message')
    remaining = MAX_PUBLIC_WORKER_TEXT - used
    if remaining <= 0:
        return
    _record(proof, {'event': 'public_agent_message', 'native_method': native_method,
                    'thread_id': thread_id, 'turn_id': turn_id, 'item_id': _diagnostic_string(item.get('id')),
                    'phase': _diagnostic_string(item.get('phase'), 64), 'text': text[:remaining],
                    'truncated': len(text) > remaining})


def _run_image_turn(rpc, started, prompt, deadline, proof=None):
    if proof is None:
        proof = []
    thread_id = started['thread']['id']
    response = rpc.request('turn/start', {'threadId': thread_id,
                           'input': [{'type': 'text', 'text': prompt}]}, timeout=min(20, _remaining(deadline)))
    turn_id = response.get('turn', {}).get('id') if isinstance(response, dict) else None
    if not turn_id:
        raise BridgeError('native_turn_invalid', 'The native image turn did not start correctly.')
    images = {}
    _record(proof, {'event': 'turn/start', 'thread_id': thread_id, 'turn_id': turn_id})
    allowed = {'userMessage', 'agentMessage', 'reasoning', 'imageGeneration', 'contextCompaction'}

    def accept(item, native_method):
        kind = item.get('type')
        _record(proof, {'event': 'item_observed', 'native_method': native_method,
                        'thread_id': thread_id, 'turn_id': turn_id,
                        'type': _diagnostic_string(kind), 'item_id': _diagnostic_string(item.get('id')),
                        'status': _diagnostic_string(item.get('status'))})
        _public_message(proof, item, native_method, thread_id, turn_id)
        if kind not in allowed:
            raise BridgeError('unexpected_tool', 'The native worker attempted a tool outside the image-only contract.')
        if kind == 'imageGeneration':
            if item.get('status') != 'completed':
                raise BridgeError('native_generation_failed', 'The native image tool did not complete; this request will not be replayed.')
            key = item.get('id')
            if not isinstance(key, str) or not key:
                raise BridgeError('native_item_invalid', 'The completed native image item lacked its identity.')
            if key in images and (images[key].get('result'), images[key].get('fileId')) != (item.get('result'), item.get('fileId')):
                raise BridgeError('native_item_changed', 'The same completed native image item reported conflicting image bytes.')
            images[key] = item
            if not any(p.get('event') == 'native_image_item' and p.get('item_id') == key for p in proof):
                encoded = item.get('result')
                _record(proof, {'event': 'native_image_item', 'native_method': native_method,
                              'native_type': kind, 'thread_id': thread_id, 'turn_id': turn_id,
                              'item_id': key, 'status': item.get('status'),
                              'native_file_id': _diagnostic_string(item.get('fileId')),
                              'encoded_result_sha256': digest(encoded.encode('utf-8')) if isinstance(encoded, str) else None,
                              'encoded_result_characters': len(encoded) if isinstance(encoded, str) else None})
            if len(images) > 1:
                raise BridgeError('unexpected_image_count', 'The native turn produced more than the one requested image.')

    try:
        while True:
            # Drain notification headers from this dedicated native process so
            # an unscoped/legacy method is visible in opt-in failure evidence.
            # Never retain its payload or interpret it as an image result.
            event = rpc.wait_notification(lambda e: True, timeout=_remaining(deadline))
            method, params = event.get('method'), event.get('params', {})
            if not isinstance(params, dict):
                params = {}
            owned = params.get('threadId') == thread_id
            safe_method = method[:128] if isinstance(method, str) else 'invalid'
            scope = 'matching_thread' if owned else 'unscoped_or_other_thread'
            if not any(p.get('event') == 'notification_method' and p.get('method') == safe_method
                       and p.get('scope') == scope for p in proof):
                _record(proof, {'event': 'notification_method', 'method': safe_method, 'scope': scope})
            if method == 'client/serverRequestDeclined':
                raise BridgeError('unexpected_approval_or_tool', 'An unsupported native approval or client-tool request was declined.')
            if not owned:
                continue
            if method in ('item/started', 'item/completed') and params.get('turnId') == turn_id:
                item = params.get('item', {})
                if method == 'item/started':
                    _record(proof, {'event': 'item_observed', 'native_method': method,
                                    'thread_id': thread_id, 'turn_id': turn_id,
                                    'type': _diagnostic_string(item.get('type')),
                                    'item_id': _diagnostic_string(item.get('id')),
                                    'status': _diagnostic_string(item.get('status'))})
                if item.get('type') not in allowed:
                    raise BridgeError('unexpected_tool', 'The native worker attempted a tool outside the image-only contract.')
                if method == 'item/completed':
                    accept(item, method)
            elif method == 'turn/completed' and params.get('turn', {}).get('id') == turn_id:
                turn = params['turn']
                _record(proof, {'event': 'turn/completed', 'thread_id': thread_id,
                                'turn_id': turn_id, 'status': turn.get('status')})
                if turn.get('status') != 'completed':
                    raise BridgeError('native_turn_failed', 'The native image turn failed; this request will not be replayed.')
                for item in turn.get('items', []):
                    accept(item, method)
                if len(images) != 1:
                    raise BridgeError('native_image_missing', 'No completed native image item was returned; prose is not accepted as an image.')
                return next(iter(images.values())), proof
    except BaseException:
        try:
            rpc.request('turn/interrupt', {'threadId': thread_id, 'turnId': turn_id}, timeout=3)
        except Exception:
            pass
        raise


def generate(request_file, selected_route=None, output=None, execute=False, timeout=240,
             rpc_factory=BoundedRpcClient, evidence_file=None):
    # No discovery, server process or inference is allowed before this gate.
    ticket, ledger = ticket_for(request_file)
    if not execute or selected_route is None:
        return {'status': 'choice_required', 'route': ROUTE,
                'selection_required': True, 'generation_authorized': False, 'inference_sent': False}
    if selected_route != ROUTE:
        raise BridgeError('wrong_route', 'The selected route does not match this image request.')
    if not output:
        raise BridgeError('output_required', 'Choose a new output file before image generation.')
    target = destination(output)
    if target.exists():
        raise BridgeError('destination_exists', 'The image output already exists; it was preserved.')
    if target.suffix.lower() != '.png':
        raise BridgeError('output_format_unsupported', 'This adapter validates PNG output; use a new .png destination.')
    evidence_target = destination(evidence_file) if evidence_file else None
    if evidence_target and (evidence_target.exists() or evidence_target == target):
        raise BridgeError('destination_exists', 'Choose a new, distinct native evidence file; existing files were preserved.')
    deadline = time.monotonic() + checked_timeout(timeout)
    runtime = bound_runtime(ticket)
    started, proof, validation, claimed = None, [], None, False

    def save_evidence(status, error=None):
        if not evidence_target:
            return
        ack = ({'thread_id': started['thread']['id'], 'model': started.get('model'),
                'reasoning_effort': started.get('reasoningEffort')} if started else None)
        evidence = {'version': 1, 'route': ROUTE, 'status': status, 'thread_start': ack,
                    'native_events': proof, 'decoded_artifact': validation,
                    'runtime_discovery': runtime,
                    'request_claimed': claimed, 'diagnostic_event_limit_reached': len(proof) >= MAX_DIAGNOSTIC_EVENTS,
                    'contains_private_reasoning': False, 'contains_image_payload': False}
        if error is not None:
            evidence['failure'] = {'exception_type': type(error).__name__,
                                   'code': error.code if isinstance(error, BridgeError) else 'native_or_filesystem_error'}
            if isinstance(error, RpcError):
                evidence['failure'].update(code='native_rpc_error', native_method=error.method,
                                           native_error_code=error.code if type(error.code) is int else None)
        private_write_new(evidence_target, canonical(evidence))

    try:
        with tempfile.TemporaryDirectory(prefix='router-image-worker-') as cwd:
            with rpc_factory(server_argv(runtime['executable']), cwd=cwd) as rpc:
                _initialize(rpc, deadline)
                settings = ticket.get('settings', {})
                started = _start_native(rpc, Path(cwd), deadline, settings.get('model'), settings.get('effort'), runtime)
                # Claim immediately before the first inference request. Transport or
                # artifact failures after this point cannot silently generate again.
                claim(ticket, ledger, 'generation_started')
                claimed = True
                item, proof = _run_image_turn(rpc, started, ticket['prompt'], deadline, proof)
                data, validation = image_bytes(item, started['thread']['id'], _native_codex_home())
                private_write_new(target, data)
                save_evidence('generated')
    except BaseException as error:
        try:
            save_evidence('error', error)
        except Exception:
            # Preserve the primary failure and any user/concurrent file. A
            # diagnostic-file problem never authorizes another native turn.
            pass
        raise
    return {'status': 'generated', 'route': ROUTE, 'provider': 'codex',
            'selection_source': 'explicit_selected_route_argument', 'inference_sent': True,
            'bound_coordinator_settings': ticket.get('settings', {}),
            'runtime_discovery': runtime,
            'artifact': {'path': str(target), **validation},
            'runtime': {'reported_chat_model': started.get('model'),
                        'reported_effort': started.get('reasoningEffort'), 'image_backend_model': 'not_exposed'},
            'evidence': {'native_image_item': True, 'native_image_status': item.get('status'),
                         'native_turn_status': 'completed', 'answer_validation': 'passed_png_structure_and_raster'}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('probe', help='Read native metadata without inference or generation.')
    p.add_argument('--timeout', type=float, default=45)
    p.add_argument('--model', help='Optional native chat coordinator, not the hidden image backend.')
    p.add_argument('--effort', help='Optional supported native effort for that coordinator.')
    p.add_argument('--codex', help='Optional absolute Codex executable; otherwise discover a compatible local runtime.')
    p = sub.add_parser('prepare', help='Prepare a single-use request and require a route choice.')
    p.add_argument('--prompt', required=True)
    p.add_argument('--request-file', required=True)
    p.add_argument('--model', help='Bind an optional native chat coordinator to this request.')
    p.add_argument('--effort', help='Bind its optional native reasoning effort to this request.')
    p.add_argument('--codex', help='Bind an optional absolute Codex executable to this request.')
    p = sub.add_parser('cancel', help='Cancel a pending request without calling a provider.')
    p.add_argument('--request-file', required=True)
    p = sub.add_parser('generate', help='Execute only after an explicit matching route selection.')
    p.add_argument('--request-file', required=True)
    p.add_argument('--selected-route')
    p.add_argument('--output')
    p.add_argument('--execute', action='store_true')
    p.add_argument('--timeout', type=float, default=240)
    p.add_argument('--evidence-file', default=os.environ.get('DYNAMIC_MODEL_ROUTER_IMAGE_EVIDENCE_FILE'),
                   help='Optional new private file for sanitized native event evidence; off unless explicitly configured.')
    args = parser.parse_args(argv)
    try:
        if args.command == 'probe':
            result = probe(args.timeout, model=args.model, effort=args.effort, codex=args.codex)
        elif args.command == 'prepare':
            result = prepare(args.prompt, args.request_file, args.model, args.effort, args.codex)
        elif args.command == 'cancel':
            result = cancel(args.request_file)
        else:
            result = generate(args.request_file, args.selected_route, args.output, args.execute, args.timeout,
                              evidence_file=args.evidence_file)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except BridgeError as error:
        print(json.dumps({'status': 'error', 'code': error.code, 'message': str(error),
                          'automatic_retry': False, **error.details}, ensure_ascii=False))
    except RpcError as error:
        print(json.dumps({'status': 'error', 'code': 'native_rpc_error',
                          'native_method': error.method,
                          'native_error_code': error.code if type(error.code) is int else None,
                          'message': 'The native interface rejected this operation; no automatic retry was made.',
                          'automatic_retry': False}))
    except (OSError, RuntimeError, TimeoutError, ValueError):
        # Native diagnostics can contain account/project details. Keep them out
        # of a shared chat response and never turn infrastructure failure into
        # a model escalation or automatic image retry.
        print(json.dumps({'status': 'error', 'code': 'native_or_filesystem_error',
                          'message': 'The native operation or local file prerequisite failed; no automatic retry was made.',
                          'automatic_retry': False}))
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
