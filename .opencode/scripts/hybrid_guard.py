#!/usr/bin/env python3
"""Guard de sesión: snapshot Git, validación de alcance, invariantes y tests.

No usa Git reset ni modifica archivos de código. Los estados viven en git-path.
"""
from __future__ import annotations

import argparse
import ast
import datetime as dt
import hashlib
import json
import re
import signal
import shutil
import os
import tempfile
import uuid
from pathlib import Path
import subprocess
import sys
import time
import fcntl
from contextlib import contextmanager
from typing import Optional

STATE_FOLDER = 'opencode-hybrid-guard'
POLICY = '.opencode/hybrid-policy.json'
VERSION = 1
SESSION_VERSION = 1
SESSION_FILE = 'launch-session.json'
HISTORY_FILE = 'launch-history.jsonl'
SESSION_STATUSES = {'idle', 'starting', 'running', 'pending_review', 'reviewed'}
HEARTBEAT_INTERVAL_SECONDS = 3.0
HEARTBEAT_TTL_SECONDS = 15.0
HEARTBEAT_FUTURE_SKEW_SECONDS = 5.0


class LaunchInterrupted(Exception):
    pass


class GuardError(Exception):
    pass


def git(root: Path, *args: str) -> bytes:
    result = subprocess.run(['git', '-C', str(root), *args], capture_output=True)
    if result.returncode:
        raise GuardError(f'git {" ".join(args)}: {result.stderr.decode(errors="replace").strip()}')
    return result.stdout


def project_root(project: str) -> Path:
    root = Path(project).expanduser().resolve()
    if not root.is_dir():
        raise GuardError(f'No existe el proyecto: {root}')
    resolved = Path(os.fsdecode(git(root, 'rev-parse', '--show-toplevel')).strip()).resolve()
    if resolved != root:
        raise GuardError(f'Usa la raíz exacta del repositorio: {resolved}')
    return root


def state_dir(root: Path) -> Path:
    raw = os.fsdecode(git(root, 'rev-parse', '--git-path', STATE_FOLDER)).strip()
    candidate = Path(raw)
    return (candidate if candidate.is_absolute() else root / candidate).resolve()


def relative_path(root: Path, raw: str, must_exist: bool = False, allow_symlink: bool = False) -> str:
    if not raw or '\x00' in raw or '\\' in raw or raw.startswith(('~', '$')):
        raise GuardError(f'Ruta no válida: {raw!r}')
    path = Path(raw)
    if path.is_absolute() or any(p in ('.', '..') for p in path.parts) or raw == '.':
        raise GuardError(f'Ruta debe ser relativa y sin ..: {raw!r}')
    candidate = root / path
    if candidate.is_symlink() and not allow_symlink:
        raise GuardError(f'No se permiten rutas de destino symlink: {raw}')
    parent = candidate.parent.resolve()
    if not parent.is_relative_to(root):
        raise GuardError(f'Ruta fuera del proyecto: {raw}')
    if must_exist and not candidate.is_file():
        raise GuardError(f'No existe el archivo: {raw}')
    return path.as_posix()


def inventory(root: Path) -> dict[str, str]:
    files = git(root, 'ls-files', '--cached', '--others', '--exclude-standard', '-z').split(b'\x00')
    output = {}
    for part in files:
        if not part:
            continue
        name = os.fsdecode(part)
        dest = root / name
        hasher = hashlib.sha256()
        if dest.is_symlink():
            hasher.update(('link:' + os.readlink(dest)).encode('utf-8', errors='surrogateescape'))
        elif dest.is_file():
            hasher.update(b'file:')
            with dest.open('rb') as source:
                for chunk in iter(lambda: source.read(1024 * 1024), b''):
                    hasher.update(chunk)
        elif not dest.exists():
            hasher.update(b'missing:')
        else:
            raise GuardError(f'Tipo de entrada no soportado: {name}')
        output[name] = hasher.hexdigest()
    return output


def extract_python_function(root: Path, locator: str) -> str:
    # ruta::Class.method o ruta::function_name
    try:
        rawpath, qualified = locator.split('::', 1)
    except ValueError:
        raise GuardError('Preservar exige ruta.py::Clase.metodo o ruta.py::funcion')
    rel = relative_path(root, rawpath, must_exist=True)
    if not rel.endswith('.py'):
        raise GuardError('La preservación de función exige un .py')
    source = (root / rel).read_text(encoding='utf-8')
    tree = ast.parse(source, filename=rel)
    nodes = tree.body
    for part in qualified.split('.'):
        matches = [n for n in nodes if isinstance(n, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == part]
        if len(matches) != 1:
            raise GuardError(f'No se encuentra {qualified} en {rel}')
        node = matches[0]
        nodes = node.body if isinstance(node, ast.ClassDef) else []
    if isinstance(node, ast.ClassDef):
        raise GuardError('La preservación se aplica a funciones, no a clases enteras')
    chunk = ''.join(source.splitlines(keepends=True)[node.lineno - 1:node.end_lineno])
    return hashlib.sha256(chunk.encode()).hexdigest()


def load_policy(root: Path) -> dict:
    policy_path = root / POLICY
    if not policy_path.is_file():
        raise GuardError(f'Falta política de pruebas: {POLICY}')
    policy = json.loads(policy_path.read_text(encoding='utf-8'))
    if not isinstance(policy.get('test_profiles'), dict):
        raise GuardError('Política sin test_profiles')
    return policy


def _exact_runtime_write_paths(root: Path, allowed: object) -> list[str]:
    if not isinstance(allowed, list):
        raise GuardError('La lista de escritura temporal debe ser una lista de rutas exactas')
    exact = []
    for raw in allowed:
        if not isinstance(raw, str):
            raise GuardError('Ruta de escritura temporal no válida')
        normalized = relative_path(root, raw)
        if normalized != raw:
            raise GuardError(f'Ruta de escritura temporal no canónica: {raw!r}')
        if any(character in raw for character in '*?[]'):
            raise GuardError(f'No se permiten comodines en permisos temporales: {raw!r}')
        if any(part in ('.opencode', '.git') for part in Path(raw).parts):
            raise GuardError(f'No se permite editar configuración/herramientas: {raw}')
        if raw in exact:
            raise GuardError(f'Ruta de escritura temporal duplicada: {raw}')
        exact.append(raw)
    return exact


def build_opencode_config_content(root: Path, manifest: dict, inherited: Optional[str] = None) -> str:
    """Add task-scoped edit rules to a child-only OpenCode V2 inline config."""
    allowed = _exact_runtime_write_paths(root, manifest.get('allowed'))
    if inherited:
        try:
            config = json.loads(inherited)
        except (TypeError, json.JSONDecodeError) as exc:
            raise GuardError('OPENCODE_CONFIG_CONTENT heredado no es JSON válido; no se lanzará OpenCode') from exc
        if not isinstance(config, dict):
            raise GuardError('OPENCODE_CONFIG_CONTENT heredado debe ser un objeto JSON')
    else:
        config = {}

    global_permissions = config.setdefault('permissions', [])
    if not isinstance(global_permissions, list) or not all(isinstance(rule, dict) for rule in global_permissions):
        raise GuardError('Los permisos globales heredados no son una lista de reglas válida')
    # The supervised child also denies native write/execute routes for the
    # primary agent and other project agents, not only local-coder.
    global_permissions.extend(
        {'action': action, 'resource': '*', 'effect': 'deny'}
        for action in ('edit', 'write', 'apply_patch', 'shell', 'execute', 'computer', 'mcp')
    )

    agents = config.setdefault('agents', {})
    if not isinstance(agents, dict):
        raise GuardError('La sección agents heredada de OPENCODE_CONFIG_CONTENT no es un objeto')

    native_denials = [
        {'action': action, 'resource': '*', 'effect': 'deny'}
        for action in ('edit', 'write', 'apply_patch', 'shell', 'execute', 'computer', 'mcp')
    ]
    project_agents = {item.stem for item in (root / '.opencode' / 'agents').glob('*.md') if item.is_file()}
    project_agents.add('local-coder')
    for name in sorted(project_agents - {'local-coder'}):
        agent = agents.setdefault(name, {})
        if not isinstance(agent, dict):
            raise GuardError(f'La configuración heredada de {name} no es un objeto')
        rules = agent.setdefault('permissions', [])
        if not isinstance(rules, list) or not all(isinstance(rule, dict) for rule in rules):
            raise GuardError(f'Los permisos heredados de {name} no son una lista de reglas válida')
        # Keep each agent's existing read and delegation rules; append only
        # targeted native write/execute denials for this child process.
        rules.extend(dict(rule) for rule in native_denials)

    local_coder = agents.setdefault('local-coder', {})
    if not isinstance(local_coder, dict):
        raise GuardError('La configuración heredada de local-coder no es un objeto')
    permissions = local_coder.setdefault('permissions', [])
    if not isinstance(permissions, list) or not all(isinstance(rule, dict) for rule in permissions):
        raise GuardError('Los permisos heredados de local-coder no son una lista de reglas válida')

    # Fail closed for all local-coder actions except reading/search and the
    # supervised writer. The writer independently checks manifest, state and lease.
    permissions.append({'action': '*', 'resource': '*', 'effect': 'deny'})
    permissions.extend(
        {'action': action, 'resource': '*', 'effect': 'allow'}
        for action in ('read', 'glob', 'grep')
    )
    permissions.extend(
        {'action': 'hybrid_guard_write', 'resource': resource, 'effect': 'ask'}
        for resource in allowed
    )
    return json.dumps(config, ensure_ascii=False, separators=(',', ':'))


def read_active(root: Path) -> tuple[Path, dict]:
    path = state_dir(root) / 'active.json'
    if not path.is_file():
        raise GuardError('No hay tarea activa. Ejecuta begin antes de abrir OpenCode.')
    obj = json.loads(path.read_text(encoding='utf-8'))
    if obj.get('root') != str(root) or obj.get('version') != VERSION:
        raise GuardError('Manifest de otra raíz o versión no compatible')
    return path, obj


def session_path(root: Path) -> Path:
    return state_dir(root) / SESSION_FILE


def history_path(root: Path) -> Path:
    return state_dir(root) / HISTORY_FILE


def _parse_utc(value: object, field: str) -> dt.datetime:
    if not isinstance(value, str) or not value:
        raise GuardError(f'{field} no contiene una fecha UTC válida')
    try:
        parsed = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as exc:
        raise GuardError(f'{field} no contiene una fecha UTC válida') from exc
    if parsed.tzinfo is None:
        raise GuardError(f'{field} debe incluir zona horaria')
    if parsed.utcoffset() != dt.timedelta(0):
        raise GuardError(f'{field} debe estar expresado en UTC')
    return parsed.astimezone(dt.timezone.utc)


def _validate_launch_session(root: Path, record: object) -> dict:
    if not isinstance(record, dict):
        raise GuardError('Registro de supervisión no es un objeto')
    if record.get('version') != SESSION_VERSION:
        raise GuardError('Versión de sesión de lanzamiento no compatible')
    if record.get('root') != str(root):
        raise GuardError('Registro de supervisión de otra raíz')
    status = record.get('status')
    if status not in SESSION_STATUSES:
        raise GuardError(f'Estado de supervisión no válido: {status!r}')
    task_id = record.get('task_id')
    if task_id is not None and (not isinstance(task_id, str) or not task_id):
        raise GuardError('task_id no válido en registro de supervisión')
    session_id = record.get('session_id')
    if status == 'idle':
        if session_id is not None:
            raise GuardError('Estado idle no puede conservar session_id')
    elif not isinstance(session_id, str) or not session_id:
        raise GuardError('Falta session_id en sesión activa')
    now = dt.datetime.now(dt.timezone.utc)
    parsed_times = {}
    for field in ('created_utc', 'updated_utc'):
        parsed = _parse_utc(record.get(field), field)
        if parsed > now + dt.timedelta(seconds=HEARTBEAT_FUTURE_SKEW_SECONDS):
            raise GuardError(f'{field} está demasiado adelantado')
        parsed_times[field] = parsed
    if parsed_times['created_utc'] > parsed_times['updated_utc']:
        raise GuardError('created_utc no puede ser posterior a updated_utc')
    heartbeat = record.get('heartbeat_utc')
    if status in ('starting', 'running'):
        parsed_heartbeat = _parse_utc(heartbeat, 'heartbeat_utc')
        now = dt.datetime.now(dt.timezone.utc)
        if parsed_heartbeat > now + dt.timedelta(seconds=HEARTBEAT_FUTURE_SKEW_SECONDS):
            raise GuardError('heartbeat_utc está demasiado adelantado')
        if parsed_heartbeat > parsed_times['updated_utc']:
            raise GuardError('heartbeat_utc no puede ser posterior a updated_utc')
    elif heartbeat is not None:
        parsed_heartbeat = _parse_utc(heartbeat, 'heartbeat_utc')
        if parsed_heartbeat > parsed_times['updated_utc']:
            raise GuardError('heartbeat_utc no puede ser posterior a updated_utc')
    return record


def read_launch_session(root: Path, *, allow_missing: bool = False) -> Optional[dict]:
    path = session_path(root)
    try:
        raw = path.read_text(encoding='utf-8')
    except FileNotFoundError:
        if allow_missing:
            return None
        raise GuardError(
            'Falta launch-session.json. Ejecuta recover-launch antes de continuar.'
        )
    except (OSError, UnicodeError) as exc:
        raise GuardError(f'No se puede leer launch-session.json: {exc}') from exc
    try:
        record = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise GuardError(
            'launch-session.json está corrupto. Ejecuta recover-launch para preservar evidencia.'
        ) from exc
    return _validate_launch_session(root, record)


def _fsync_directory(folder: Path) -> None:
    fd = os.open(folder, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _atomic_write_bytes(path: Path, content: bytes, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=str(path.parent))
    temporary = Path(name)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, 'wb') as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def write_launch_session(root: Path, record: dict) -> None:
    valid = _validate_launch_session(root, record)
    content = (json.dumps(valid, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    _atomic_write_bytes(session_path(root), content)


SESSION_TRANSITIONS = {
    'idle': {'starting'},
    'starting': {'running', 'pending_review'},
    'running': {'pending_review'},
    'pending_review': {'reviewed'},
    'reviewed': set(),
}


def transition_launch_session(record: dict, new_status: str, **updates) -> dict:
    current = record.get('status')
    if new_status not in SESSION_TRANSITIONS.get(current, set()):
        raise GuardError(f'Transición de supervisión no válida: {current!r} -> {new_status!r}')
    updated = dict(record)
    updated.update(updates)
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    updated['status'] = new_status
    updated['updated_utc'] = now
    if new_status in ('starting', 'running'):
        updated['heartbeat_utc'] = now
    if current == 'idle' and new_status == 'starting':
        updated['session_id'] = updated.get('session_id') or uuid.uuid4().hex
        updated['started_utc'] = now
    return updated


def new_launch_session(root: Path, task_id: Optional[str], status: str = 'idle') -> dict:
    if status not in SESSION_STATUSES:
        raise GuardError(f'Estado inicial de supervisión no válido: {status!r}')
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    return {
        'version': SESSION_VERSION,
        'root': str(root),
        'task_id': task_id,
        'session_id': None if status == 'idle' else uuid.uuid4().hex,
        'status': status,
        'created_utc': now,
        'updated_utc': now,
        'heartbeat_utc': now if status in ('starting', 'running') else None,
        'supervisor_pid': None,
        'child_pid': None,
    }


def heartbeat_is_fresh(record: dict, now: Optional[dt.datetime] = None) -> bool:
    if record.get('status') not in ('starting', 'running'):
        return False
    try:
        heartbeat = _parse_utc(record.get('heartbeat_utc'), 'heartbeat_utc')
    except GuardError:
        return False
    current = now or dt.datetime.now(dt.timezone.utc)
    age = (current.astimezone(dt.timezone.utc) - heartbeat).total_seconds()
    return 0 <= age < HEARTBEAT_TTL_SECONDS


def _active_task_id(root: Path) -> Optional[str]:
    path = state_dir(root) / 'active.json'
    try:
        raw = path.read_bytes()
        manifest = json.loads(raw.decode('utf-8'))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(manifest, dict) or manifest.get('root') != str(root):
        return None
    task_id = manifest.get('task_id')
    if isinstance(task_id, str) and task_id:
        return task_id
    created = manifest.get('created_utc', '')
    return 'legacy-' + hashlib.sha256((str(root) + str(created)).encode()).hexdigest()[:24]


def _preserve_session_file(root: Path, raw: bytes) -> tuple[Path, str]:
    folder = state_dir(root) / 'evidence'
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    digest = hashlib.sha256(raw).hexdigest()
    name = 'launch-session-' + dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '-' + uuid.uuid4().hex[:8] + '.bin'
    target = folder / name
    _atomic_write_bytes(target, raw)
    return target, digest


def _history_event(record: dict) -> tuple[dict, str]:
    canonical = json.dumps(record, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
    digest = hashlib.sha256(canonical.encode('utf-8')).hexdigest()
    event = {
        'event': 'session_reviewed',
        'session_id': record['session_id'],
        'task_id': record.get('task_id'),
        'record_sha256': digest,
        'record': record,
    }
    return event, digest


def _preserve_history_tail(root: Path, tail: bytes) -> None:
    folder = state_dir(root) / 'evidence'
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    name = 'history-tail-' + dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '-' + uuid.uuid4().hex[:8] + '.bin'
    _atomic_write_bytes(folder / name, tail)


def _read_history_records(root: Path) -> list[dict]:
    path = history_path(root)
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return []
    if not raw:
        return []
    pieces = raw.splitlines(keepends=True)
    records = []
    malformed_tail = None
    normalize_history = False
    for index, line in enumerate(pieces):
        is_last = index == len(pieces) - 1
        complete = line.endswith(b'\n')
        try:
            record = json.loads(line.decode('utf-8'))
            if not isinstance(record, dict) or not isinstance(record.get('session_id'), str):
                raise ValueError('invalid history record')
        except (UnicodeError, json.JSONDecodeError, ValueError):
            if not is_last:
                raise GuardError('launch-history.jsonl contiene una línea corrupta antes del final')
            malformed_tail = line
            break
        records.append(record)
        if not complete and is_last:
            normalize_history = True
    if malformed_tail is not None or normalize_history:
        if malformed_tail is not None:
            _preserve_history_tail(root, malformed_tail)
        # Rebuild only the validated prefix; the corrupt bytes remain in evidence.
        unique = {}
        for record in records:
            sid = record['session_id']
            prior = unique.get(sid)
            if prior is not None and prior != record:
                raise GuardError('launch-history.jsonl contiene session_id duplicado con contenido distinto')
            unique[sid] = record
        content = b''.join(
            (json.dumps(item, ensure_ascii=False, separators=(',', ':')) + '\n').encode('utf-8')
            for item in unique.values()
        )
        _atomic_write_bytes(path, content)
        records = list(unique.values())
    return records


def archive_launch_session(root: Path, record: dict) -> None:
    valid = _validate_launch_session(root, record)
    if valid['status'] != 'reviewed' or not valid.get('session_id'):
        raise GuardError('Sólo se pueden archivar sesiones revisadas con session_id')
    event, digest = _history_event(valid)
    records = _read_history_records(root)
    for existing in records:
        if existing.get('session_id') == valid['session_id']:
            if existing.get('record_sha256') == digest and existing.get('record') == valid:
                return
            _preserve_session_file(
                root,
                (json.dumps(valid, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode('utf-8'),
            )
            raise GuardError('launch-history.jsonl ya contiene ese session_id con otro contenido')
    path = history_path(root)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    encoded = (json.dumps(event, ensure_ascii=False, separators=(',', ':')) + '\n').encode('utf-8')
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        view = memoryview(encoded)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise OSError('No se pudo completar la escritura del historial')
            view = view[written:]
        os.fsync(fd)
    finally:
        os.close(fd)
    _fsync_directory(path.parent)



@contextmanager
def operation_lock(root: Path):
    """
    Bloqueo exclusivo entre procesos de Hybrid Guard.

    Devuelve el descriptor para permitir que un proceso
    supervisado herede el bloqueo cuando sea necesario.
    """

    folder = state_dir(root)
    folder.mkdir(parents=True, exist_ok=True)

    lock_path = folder / 'operation.lock'

    fd = os.open(
        lock_path,
        os.O_RDWR | os.O_CREAT,
        0o600,
    )

    try:
        try:
            fcntl.flock(
                fd,
                fcntl.LOCK_EX | fcntl.LOCK_NB,
            )
        except BlockingIOError as exc:
            raise GuardError(
                'Otra operacion de Hybrid Guard esta en curso. '
                'Espera a que termine antes de continuar.'
            ) from exc

        # El descriptor puede compartirse con el proceso hijo.
        yield fd

    finally:
        # No usamos LOCK_UN explícito.
        # El bloqueo se libera cuando todos los descriptores
        # que comparten su apertura han sido cerrados.
        os.close(fd)



def begin(root: Path, args) -> int:
    folder = state_dir(root)
    path = folder / 'active.json'
    folder.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise GuardError('Ya hay una tarea activa. Usa check/finalize; no se pisa el snapshot.')
    previous = read_launch_session(root, allow_missing=True)
    if previous is None:
        raise GuardError('Falta launch-session.json. Ejecuta recover-launch antes de iniciar una tarea.')
    if previous['status'] in ('starting', 'running', 'pending_review'):
        raise GuardError(
            f'No se puede iniciar otra tarea: supervisión en estado {previous["status"]}. '
            'Revisa/recupera esa sesión antes de continuar.'
        )
    if previous['status'] == 'reviewed':
        archive_launch_session(root, previous)
    allowed = [relative_path(root, p) for p in args.allow]
    if len(set(allowed)) != len(allowed):
        raise GuardError('Rutas autorizadas duplicadas')
    _exact_runtime_write_paths(root, allowed)
    saved = {name: extract_python_function(root, name) for name in args.preserve}
    config = load_policy(root)
    if args.test not in config['test_profiles']:
        raise GuardError(f'Perfil de test inexistente: {args.test}')
    before = inventory(root)
    task_id = uuid.uuid4().hex
    manifest = {
        'version': VERSION, 'root': str(root), 'task_id': task_id,
        'created_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
        'started_monotonic_hint': time.time(),
        'allowed': allowed, 'preserved': saved, 'before': before, 'test_profile': args.test,
        'test_passed': False, 'test_result': None,
    }
    # Write the idle session first. If creation of active.json is interrupted,
    # a later begin may safely replace this orphan idle record.
    write_launch_session(root, new_launch_session(root, task_id, 'idle'))
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as fp:
            json.dump(manifest, fp, ensure_ascii=False, indent=2)
    except FileExistsError:
        raise GuardError('Otra tarea comenzó simultáneamente')
    print('GUARD ACTIVADO; no se ha modificado código.')
    print('Único(s) destino(s) permitido(s): ' + ', '.join(allowed))
    print('Funciones protegidas: ' + (', '.join(saved) or '(ninguna)'))
    print('Perfil de tests: ' + args.test)
    print('Inicia OpenCode con .opencode/scripts/hybrid_guard.py launch y utiliza /hybrid-task.')
    print('Al salir, revisa launch-review y confirma solo tras inspección; después ejecuta check y test.')
    return 0


def recover_launch(root: Path, reason: str, confirm: str) -> int:
    if confirm != 'RECUPERAR':
        raise GuardError('Confirmación requerida: RECUPERAR')
    reason = reason.strip()
    if not 10 <= len(reason) <= 500:
        raise GuardError('El motivo debe tener entre 10 y 500 caracteres')

    path = session_path(root)
    current = None
    corrupt_error = None
    try:
        current = read_launch_session(root, allow_missing=True)
    except GuardError as exc:
        corrupt_error = exc

    if current is not None:
        if current['status'] not in ('starting', 'running'):
            raise GuardError(
                f'recover-launch no aplica al estado {current["status"]}; '
                'no se ha cambiado el registro.'
            )
        if heartbeat_is_fresh(current):
            raise GuardError('La supervisión sigue vigente; no se puede recuperar una sesión activa.')
        pending = transition_launch_session(
            current,
            'pending_review',
            reason='supervision_stale',
            recovery={'requested_utc': dt.datetime.now(dt.timezone.utc).isoformat(), 'reason': reason},
        )
        write_launch_session(root, pending)
        print('SUPERVISIÓN EXPIRADA; sesión bloqueada en pending_review.')
        return 0

    evidence = {'kind': 'missing', 'sha256': None}
    if corrupt_error is not None:
        try:
            raw = path.read_bytes()
        except FileNotFoundError:
            raw = None
        if raw is not None:
            evidence_path, digest = _preserve_session_file(root, raw)
            evidence = {
                'kind': 'corrupt',
                'sha256': digest,
                'evidence_path': str(evidence_path.relative_to(state_dir(root))),
            }
        else:
            # The read failure was not a missing file; propagate it rather than
            # mistaking an inaccessible file for an empty installation.
            raise corrupt_error

    pending = new_launch_session(root, _active_task_id(root), 'pending_review')
    pending.update({
        'reason': 'recovered_' + evidence['kind'],
        'recovery': {
            'requested_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
            'reason': reason,
            'evidence': evidence,
        },
    })
    write_launch_session(root, pending)
    print('RECUPERACIÓN REGISTRADA; sesión bloqueada en pending_review.')
    if evidence.get('evidence_path'):
        print('Evidencia preservada en ' + evidence['evidence_path'])
    return 0


def compare(root: Path, manifest: dict) -> tuple[bool, list[str], list[str]]:
    current = inventory(root)
    baseline = manifest['before']
    different = sorted(p for p in set(baseline) | set(current) if baseline.get(p) != current.get(p))
    unauthorized = [p for p in different if p not in manifest['allowed']]
    protected_broken = []
    for locator, initial_hash in manifest['preserved'].items():
        try:
            now = extract_python_function(root, locator)
        except (GuardError, OSError, SyntaxError, UnicodeError) as exc:
            protected_broken.append(f'{locator}: no se puede verificar ({exc})')
        else:
            if now != initial_hash:
                protected_broken.append(f'{locator}: cambió la función original')
    good = not unauthorized and not protected_broken
    return good, different, unauthorized + protected_broken


def check(root: Path, manifest: dict) -> int:
    good, different, problems = compare(root, manifest)
    session = None
    session_error = None
    try:
        session = read_launch_session(root, allow_missing=True)
    except GuardError as exc:
        session_error = exc
    supervision_clean = session is not None and session['status'] in ('idle', 'reviewed')
    print(
        'Supervisión:',
        'OK' if supervision_clean else (
            f'REVISIÓN PENDIENTE ({session["status"]})' if session is not None
            else 'REVISIÓN PENDIENTE (registro ausente o inválido)'
        ),
    )
    if session_error:
        print('  BLOQUEANTE:', session_error)
    if session and session['status'] in ('starting', 'running') and not heartbeat_is_fresh(session):
        print('  BLOQUEANTE: heartbeat de supervisión caducado')
    print('Cambios desde el comienzo (incluye cambios preexistentes si se alteraron):')
    print('\n'.join('  ' + p for p in different) or '  (ninguno)')
    print('Conservación de funciones y alcance:', 'OK' if good else 'FALLO')
    for problem in problems:
        print('  BLOQUEANTE:', problem)
    if not good or session_error:
        return 2
    if not supervision_clean:
        return 3
    return 0


def _direct_process_status(pid: object) -> str:
    if pid is None:
        return 'not_recorded'
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return 'invalid'
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return 'not_running'
    except PermissionError:
        return 'exists_or_inaccessible'
    except (OSError, OverflowError, ValueError):
        return 'unknown'
    return 'exists'


def _print_launch_review(record: Optional[dict], *, lock_blocked: bool = False) -> None:
    if record is None:
        print('No existe launch-session.json; no hay un registro que revisar.')
    else:
        print(f'Supervisión: {record["status"]}')
        if record['status'] in ('starting', 'running'):
            print('Heartbeat vigente:', 'sí' if heartbeat_is_fresh(record) else 'no')
        if record['status'] == 'pending_review' and record.get('reason') in ('launch_incomplete', 'supervision_stale'):
            print(
                'La supervisión anterior expiró:',
                'inicio incompleto' if record['reason'] == 'launch_incomplete' else 'heartbeat caducado',
                '→ revisión pendiente registrada.'
            )
        process_status = _direct_process_status(record.get('child_pid'))
        print(f'Proceso OpenCode directo (PID {record.get("child_pid")}): {process_status}')
        if record['status'] == 'pending_review':
            print('La sesión está lista para revisión humana; ack-launch comprobará el PID directo registrado.')
        elif record['status'] == 'reviewed':
            print('La revisión humana ya está registrada.')
        elif record['status'] == 'idle':
            print('No hay una sesión OpenCode pendiente.')
        if lock_blocked:
            print('Heartbeat caducado, pero el bloqueo de operación sigue retenido; no se pudo persistir pending_review.')
    print(
        'Límite de detección: el PID es una observación puntual y puede reutilizarse. '
        'No se garantiza detectar procesos descendientes desacoplados ni se certifica aislamiento.'
    )


def launch_review(root: Path) -> int:
    """Read status without waiting for launch's flock; persist expiry only if lock is available."""
    try:
        current = read_launch_session(root, allow_missing=True)
    except GuardError as exc:
        print(f'Estado no revisable: {exc}. Ejecuta recover-launch para preservar evidencia.')
        return 2
    if current is None:
        _print_launch_review(None)
        return 0

    lock_blocked = False
    if current['status'] in ('starting', 'running') and not heartbeat_is_fresh(current):
        try:
            with operation_lock(root):
                current = read_launch_session(root)
                if current['status'] in ('starting', 'running') and not heartbeat_is_fresh(current):
                    reason = 'launch_incomplete' if current['status'] == 'starting' else 'supervision_stale'
                    current = transition_launch_session(
                        current, 'pending_review', reason=reason,
                        review_requested_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
                    )
                    write_launch_session(root, current)
        except GuardError as exc:
            if 'Otra operacion' not in str(exc):
                raise
            lock_blocked = True

    _print_launch_review(current, lock_blocked=lock_blocked)
    if lock_blocked or current['status'] in ('starting', 'running'):
        return 3
    return 0


def ack_launch(root: Path, reason: str, confirm: str) -> int:
    if confirm != 'REVIEWED':
        raise GuardError('Confirmación requerida: REVIEWED')
    reason = reason.strip()
    if not 10 <= len(reason) <= 500:
        raise GuardError('El motivo debe tener entre 10 y 500 caracteres')

    current = read_launch_session(root)
    active_path = state_dir(root) / 'active.json'
    if active_path.exists() and _active_task_id(root) != current.get('task_id'):
        raise GuardError('launch-session no corresponde a la tarea activa; no se ha confirmado.')
    if current['status'] == 'reviewed':
        archive_launch_session(root, current)
        print('La sesión ya estaba revisada; el archivado idempotente está garantizado.')
        return 0
    if current['status'] in ('starting', 'running'):
        if heartbeat_is_fresh(current):
            raise GuardError('No se puede confirmar: la supervisión sigue activa.')
        raise GuardError('No se puede confirmar una sesión activa o expirada; ejecuta launch-review primero.')
    if current['status'] != 'pending_review':
        raise GuardError(f'No hay revisión pendiente (estado {current["status"]}).')

    process_status = _direct_process_status(current.get('child_pid'))
    if process_status in ('exists', 'exists_or_inaccessible', 'unknown', 'invalid'):
        raise GuardError(
            f'No se puede confirmar mientras el PID directo no esté descartado ({process_status}). '
            'Revisa manualmente los procesos; esto no determina el estado de descendientes.'
        )

    reviewed = transition_launch_session(
        current, 'reviewed',
        review={
            'reason': reason,
            'confirmed_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
            'reviewed_by': 'human_confirmation',
            'scope_statement': (
                'Una persona revisó la información disponible; esto no garantiza la ausencia '
                'de procesos descendientes ni proporciona aislamiento.'
            ),
            'direct_process_status': process_status,
        },
    )
    write_launch_session(root, reviewed)
    # Persist canonical review first; a retry repairs an interrupted history append idempotently.
    archive_launch_session(root, reviewed)
    print('REVISIÓN HUMANA REGISTRADA y archivada. No certifica ausencia de descendientes ni aislamiento.')
    return 0


def launch_reviews_for_task(root: Path, task_id: Optional[str]) -> list[dict]:
    if task_id is None:
        return []
    reviews = []
    for event in _read_history_records(root):
        record = event.get('record')
        if event.get('event') != 'session_reviewed' or event.get('task_id') != task_id or not isinstance(record, dict):
            continue
        review = record.get('review') or {}
        reviews.append({
            'session_id': record.get('session_id'),
            'reason': review.get('reason'),
            'confirmed_utc': review.get('confirmed_utc'),
            'scope_statement': review.get('scope_statement'),
        })
    return reviews


def write_active(path: Path, manifest: dict) -> None:
    tmp = path.with_suffix('.json.tmp')
    with tmp.open('w', encoding='utf-8') as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def test(root: Path, path: Path, manifest: dict) -> int:
    if check(root, manifest):
        print('Tests NO ejecutados: auditoría de archivos o supervisión pendiente.')
        return 2
    profile = load_policy(root)['test_profiles'][manifest['test_profile']]
    cwd = root / relative_path(root, profile['cwd'])
    argv = profile['argv']
    if not isinstance(argv, list) or not argv or not all(isinstance(x, str) for x in argv):
        raise GuardError('argv no válido en política')
    executable = root / relative_path(root, profile['argv'][0], must_exist=True, allow_symlink=True)
    if not cwd.is_dir():
        raise GuardError(f'No existe cwd: {cwd}')
    timeout = int(profile.get('timeout_seconds', 90))
    if not 1 <= timeout <= 600:
        raise GuardError('timeout_seconds debe estar entre 1 y 600')
    print('Test independiente:', argv, 'cwd:', cwd, flush=True)
    started = time.monotonic()
    try:
        result = subprocess.run([str(executable), *argv[1:]], cwd=cwd, capture_output=True,
                                text=True, timeout=timeout, env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
        captured = result.stdout + '\n' + result.stderr
        print(captured.strip()[-10000:])
        code = result.returncode
        minimum = int(profile.get('min_unittest_tests', 0))
        if code == 0 and minimum:
            match = re.search(r'Ran\s+(\d+)\s+tests?', captured)
            if not match or int(match.group(1)) < minimum or not re.search(r'(?m)^OK\s*$', captured):
                print(f'FALLO: se esperaban al menos {minimum} tests unittest con resultado OK.')
                code = 5
    except subprocess.TimeoutExpired:
        code = 124
        print('TIMEOUT del test independiente')
    manifest['test_result'] = {'returncode': code, 'duration_seconds': round(time.monotonic() - started, 2)}
    manifest['test_passed'] = code == 0
    latest = inventory(root)
    manifest['tested_snapshot'] = {p: latest.get(p) for p in manifest['allowed']} if code == 0 else None
    write_active(path, manifest)
    print('TEST:', 'OK' if code == 0 else f'FALLO ({code})')
    return 0 if code == 0 else 3



def launch(
    root: Path,
    active_path: Path,
    manifest: dict,
    max_minutes: int,
    lock_fd: int,
) -> int:
    """
    Inicia OpenCode bajo supervision.

    Comparte el descriptor de bloqueo con el proceso hijo
    para evitar liberar el flock solo porque desaparezca
    el proceso supervisor.
    """

    if not 1 <= max_minutes <= 120:
        raise GuardError('max-minutes debe ser 1..120')

    if shutil.which('opencode') is None:
        raise GuardError('No se encuentra opencode en el PATH')

    launch_env = os.environ.copy()
    launch_env['OPENCODE_CONFIG_CONTENT'] = build_opencode_config_content(
        root, manifest, inherited=launch_env.get('OPENCODE_CONFIG_CONTENT')
    )

    previous = read_launch_session(root)
    if previous['status'] in ('starting', 'running', 'pending_review'):
        raise GuardError(f'No se puede lanzar con supervisión en estado {previous["status"]}')
    if previous['status'] == 'reviewed':
        archive_launch_session(root, previous)
        previous = new_launch_session(root, manifest.get('task_id'), 'idle')
        write_launch_session(root, previous)
    if previous.get('task_id') != manifest.get('task_id'):
        previous['task_id'] = manifest.get('task_id')
        write_launch_session(root, previous)
    starting = transition_launch_session(
        previous, 'starting', supervisor_pid=os.getpid(), child_pid=None,
        max_minutes=max_minutes, result=None,
    )
    write_launch_session(root, starting)
    started = time.monotonic()

    print(
        f'Sesion OpenCode con limite de {max_minutes} minutos.',
        flush=True,
    )

    try:
        child = subprocess.Popen(
            ['opencode', '--standalone'],
            cwd=root,
            env=launch_env,
            start_new_session=True,
            pass_fds=(lock_fd,),
        )
    except BaseException as exc:
        try:
            pending = transition_launch_session(
                starting, 'pending_review', reason='launch_failed',
                result={'error': f'{type(exc).__name__}: {exc}'},
            )
            write_launch_session(root, pending)
        except Exception:
            # Keep the durable `starting` state as a fail-closed record.
            pass
        raise

    running = transition_launch_session(starting, 'running', child_pid=child.pid)
    try:
        write_launch_session(root, running)
    except Exception:
        _stop_child(child)
        raise

    old_term = signal.getsignal(signal.SIGTERM)
    def handle_term(signum, frame):
        raise LaunchInterrupted('SIGTERM')
    signal.signal(signal.SIGTERM, handle_term)

    code = 1
    timed_out = False
    reason = 'process_exited'
    try:
        code, timed_out = _supervise_child(root, child, running, max_minutes)
        if timed_out:
            reason = 'timeout'
        elif code < 0:
            reason = 'signal_exit'
    except (KeyboardInterrupt, LaunchInterrupted) as exc:
        print(f'Interrupcion recibida: {exc or "Ctrl+C"}.', flush=True)
        reason = 'interrupted'
        code = 130 if isinstance(exc, KeyboardInterrupt) else 143
        _stop_child(child)
    except Exception as exc:
        reason = 'supervisor_error'
        print(f'Fallo del supervisor: {exc}', file=sys.stderr, flush=True)
        _stop_child(child)
        code = 1
    finally:
        signal.signal(signal.SIGTERM, old_term)
        elapsed = round(time.monotonic() - started, 2)
        print(f'OpenCode: exit={code}, duracion={elapsed}s, timeout={timed_out}', flush=True)
        try:
            current = read_launch_session(root)
            if current['status'] in ('starting', 'running'):
                pending = transition_launch_session(
                    current, 'pending_review', reason=reason,
                    result={'returncode': code, 'timed_out': timed_out,
                            'duration_seconds': elapsed},
                )
                write_launch_session(root, pending)
        except Exception as exc:
            print(f'No se pudo persistir pending_review; el estado anterior sigue bloqueando: {exc}',
                  file=sys.stderr, flush=True)
    return code


def _stop_child(child) -> None:
    if child.poll() is None:
        try:
            os.killpg(child.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    deadline = time.monotonic() + 5
    while child.poll() is None and time.monotonic() < deadline:
        time.sleep(0.1)
    if child.poll() is None:
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def _supervise_child(root: Path, child, record: dict, max_minutes: int) -> tuple[int, bool]:
    started = time.monotonic()
    next_heartbeat = started + HEARTBEAT_INTERVAL_SECONDS
    timeout = max_minutes * 60
    current = record
    while True:
        code = child.poll()
        now = time.monotonic()
        if code is not None:
            return code, False
        if now - started >= timeout:
            print('Tiempo limite agotado.', flush=True)
            _stop_child(child)
            return 124, True
        if now >= next_heartbeat:
            current = dict(current)
            current['heartbeat_utc'] = dt.datetime.now(dt.timezone.utc).isoformat()
            current['updated_utc'] = current['heartbeat_utc']
            write_launch_session(root, current)
            next_heartbeat = now + HEARTBEAT_INTERVAL_SECONDS
        time.sleep(min(0.25, max(0.01, next_heartbeat - now)))


def finalize(root: Path, active_path: Path, manifest: dict) -> int:
    if check(root, manifest):
        return 2
    if not manifest.get('test_passed'):
        print('No se puede cerrar: falta un test independiente con salida 0. Ejecuta test.')
        return 3
    # Verify the exact allowed files still match the version that passed tests.
    final_inventory = inventory(root)
    tested = manifest.get('tested_snapshot') or {}
    if any(final_inventory.get(p) != tested.get(p) for p in manifest['allowed']):
        print('FALLO: hubo cambios posteriores a los tests. Ejecuta test otra vez.')
        return 4
    allowed_changes = sorted(p for p in manifest['allowed'] if manifest['before'].get(p) != final_inventory.get(p))
    report = {
        'created_utc': manifest['created_utc'],
        'finished_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
        'duration_seconds': round(time.time() - manifest['started_monotonic_hint'], 2),
        'files_changed': allowed_changes,
        'test_profile': manifest['test_profile'],
        'test_result': manifest['test_result'],
        'launch_reviews': launch_reviews_for_task(root, manifest.get('task_id')),
        'process_review_limitations': (
            'La comprobación de PID es puntual y puede verse afectada por su reutilización; '
            'puede no detectar descendientes desacoplados. La confirmación humana no proporciona aislamiento.'
        ),
        'audit': 'passed',
        'reviewer_approval': 'REQUIERE REVISION HUMANA / INFORME REVIEWER',
    }
    reports = active_path.parent / 'reports'
    reports.mkdir(exist_ok=True)
    stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%d-%H%M%S-%f')
    for collision in range(1000):
        suffix = '' if collision == 0 else f'-{collision}'
        target = reports / f'{stamp}{suffix}.json'
        try:
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            continue
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as output:
                json.dump(report, output, indent=2, ensure_ascii=False)
                output.flush()
                os.fsync(output.fileno())
        except BaseException:
            # Keep an incomplete report as evidence; never reuse or overwrite its name.
            raise
        break
    else:
        raise GuardError('No se pudo reservar un nombre exclusivo para el informe')
    active_path.unlink()
    print(f'GUARD CERRADO; reporte en {target}')
    print('Esto NO realiza commit, ni asegura aprobación de reviewer: consérvala por separado.')
    return 0


def abort(
    root: Path,
    active_path: Path,
    manifest: dict,
    reason: str,
    confirm: str,
    keep_authorized_changes: bool = False,
) -> int:
    """
    Cancela una tarea activa de Hybrid Guard de forma controlada.

    - Exige confirmación explícita.
    - Comprueba que no hay sesiones supervisadas activas.
    - Rechaza modificaciones fuera del alcance autorizado.
    - Conserva los archivos existentes sin restaurarlos.
    - Genera un informe de auditoría.
    - No ejecuta git reset, commit ni push.
    """

    # 1. Exigir confirmación explícita
    if confirm != 'ABORTAR':
        raise GuardError('Confirmación requerida: ABORTAR')

    reason = reason.strip()
    if not 10 <= len(reason) <= 500:
        raise GuardError(
            'El motivo debe tener entre 10 y 500 caracteres'
        )

    # 2. Impedir cancelar durante una sesión supervisada
    if (active_path.parent / 'launch.lock').exists():
        raise GuardError(
            'Existe una sesión supervisada activa o un bloqueo pendiente. '
            'Revisa su estado antes de cancelar.'
        )

    # 3. Comprobar modificaciones fuera de alcance
    if check(root, manifest):
        print(
            'ABORT BLOQUEADO: existen incumplimientos de alcance.'
        )
        return 2

    # 4. Identificar modificaciones autorizadas pendientes
    current = inventory(root)

    changed = sorted(
        p for p in manifest['allowed']
        if manifest['before'].get(p) != current.get(p)
    )

    # 5. Exigir autorización para conservar cambios sin validar
    if changed and not keep_authorized_changes:
        print(
            'ABORT BLOQUEADO: quedan cambios autorizados sin cerrar:'
        )

        for name in changed:
            print(f'  {name}')

        print(
            'Para conservarlos sin validación de tests, '
            'repite con --keep-authorized-changes.'
        )

        return 3

    # 6. Detectar cambios durante la comprobación
    if inventory(root) != current:
        raise GuardError(
            'El inventario cambió durante la cancelación'
        )

    # 7. Preparar el directorio de informes
    reports = active_path.parent / 'reports'
    reports.mkdir(parents=True, exist_ok=True)

    target = reports / (
        dt.datetime.now(dt.timezone.utc).strftime(
            '%Y%m%d-%H%M%S-%f'
        ) + '-abort.json'
    )

    # 8. Construir el informe de auditoría
    report = {
        'event': 'abort',
        'audit': 'passed_at_abort',
        'created_utc': manifest['created_utc'],
        'finished_utc': dt.datetime.now(
            dt.timezone.utc
        ).isoformat(),
        'reason': reason,
        'launch_reviews': launch_reviews_for_task(root, manifest.get('task_id')),
        'process_review_limitations': (
            'La comprobación de PID es puntual y puede verse afectada por su reutilización; '
            'puede no detectar descendientes desacoplados. La confirmación humana no proporciona aislamiento.'
        ),
        'files_changed': changed,
        'authorized_changes_kept': bool(changed),
        'test_passed': bool(manifest.get('test_passed')),
        'test_result': manifest.get('test_result'),
        'reviewer_approval': 'NO IMPLICA APROBACION',
    }

    # 9. Guardar el informe mediante escritura atómica
    temporary = target.with_suffix('.tmp')

    fd = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o600,
    )

    try:
        with os.fdopen(
            fd, 'w', encoding='utf-8'
        ) as output:
            json.dump(
                report,
                output,
                indent=2,
                ensure_ascii=False
            )
            output.flush()
            os.fsync(output.fileno())

        os.replace(temporary, target)

    finally:
        temporary.unlink(missing_ok=True)

    # 10. Cerrar el guard activo
    active_path.unlink()

    print(f'GUARD CANCELADO; reporte en {target}')
    print(
        'No se han restaurado archivos ni realizado commits.'
    )

    if changed:
        print(
            'ATENCION: quedan cambios autorizados sin aprobar.'
        )

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', default='.', help='raíz del repositorio (por defecto cwd)')
    sub = parser.add_subparsers(dest='command', required=True)
    beg = sub.add_parser('begin', help='crear snapshot y activar bloqueo de escritura')
    beg.add_argument('--allow', action='append', required=True, help='ruta RELATIVA EXACTA que se podrá modificar')
    beg.add_argument('--preserve', action='append', default=[], help='archivo.py::Clase.metodo a preservar exactamente')
    beg.add_argument('--test', default='provider_state', help='perfil configurado en hybrid-policy.json')
    launch_parser = sub.add_parser('launch', help='abrir OpenCode supervisado con límite de duración')
    launch_parser.add_argument('--max-minutes', type=int, default=20)
    recovery = sub.add_parser('recover-launch', help='recuperar estado de supervisión ausente, corrupto o expirado')
    recovery.add_argument('--reason', required=True)
    recovery.add_argument('--confirm', required=True)
    sub.add_parser('launch-review', aliases=['launch_review'], help='inspeccionar una sesión y registrar lease expirado')
    acknowledgment = sub.add_parser('ack-launch', help='confirmar revisión humana de una sesión pendiente')
    acknowledgment.add_argument('--reason', required=True)
    acknowledgment.add_argument('--confirm', required=True)
    sub.add_parser('check', help='auditar modificaciones y preservación de tests')
    sub.add_parser('test', help='ejecutar test independiente acotado')
    sub.add_parser('finalize', help='cerrar tarea solo con auditoría y test satisfactorios')

    cancel = sub.add_parser(
        'abort',
        help='cancelar tarea con auditoría y confirmación explícita',
    )
    cancel.add_argument('--reason', required=True)
    cancel.add_argument('--confirm', required=True)
    cancel.add_argument(
        '--keep-authorized-changes',
        action='store_true',
    )

    args = parser.parse_args()
    try:
        root = project_root(args.project)

        if args.command in ('launch-review', 'launch_review'):
            return launch_review(root)

        with operation_lock(root) as lock_fd:
            if args.command == 'begin':
                return begin(root, args)
            if args.command == 'recover-launch':
                return recover_launch(root, args.reason, args.confirm)
            if args.command == 'ack-launch':
                return ack_launch(root, args.reason, args.confirm)
            path, manifest = read_active(root)
            if args.command == 'check':
                return check(root, manifest)
            if args.command == 'launch':
                return launch(
                    root,
                    path,
                    manifest,
                    args.max_minutes,
                    lock_fd,
                )
            if args.command == 'test':
                return test(root, path, manifest)
            if args.command == 'abort':
                return abort(
                    root,
                    path,
                    manifest,
                    args.reason,
                    args.confirm,
                    args.keep_authorized_changes,
                )   
            return finalize(root, path, manifest)
    except (GuardError, OSError, ValueError, json.JSONDecodeError) as exc:
        print('ERROR:', exc, file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
