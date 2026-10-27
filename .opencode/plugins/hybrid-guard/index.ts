// OpenCode V2 project plugin. No NPM dependencies.
// Refuses to write without a user-created active guard manifest.
import fs from 'node:fs';
import path from 'node:path';
import { randomUUID } from 'node:crypto';
import { execFileSync } from 'node:child_process';

const SESSION_VERSION = 1;
const HEARTBEAT_TTL_MS = 15_000;
const FUTURE_SKEW_MS = 5_000;
const IDENTITY_DIAG_PREFIX = 'HYBRID_IDENTITY_DIAG';
const IDENTITY_DIAG_PROFILE_ROOT = '/private/tmp/opencode-2.1.3-arm64/profile';
const IDENTITY_DIAG_DIRECTORY = path.join(IDENTITY_DIAG_PROFILE_ROOT, 'diagnostics');

function suffix(value: unknown): string | null {
  return typeof value === 'string' && value.length > 0 ? value.slice(-8) : null;
}
function errorSummary(error: unknown): { errorType: string; errorMessage: string } {
  if (error instanceof Error) {
    return { errorType: error.name || 'Error', errorMessage: error.message.slice(0, 500) };
  }
  return {
    errorType: error === null ? 'null' : typeof error,
    errorMessage: String(error).slice(0, 500),
  };
}
function isObject(value: unknown): value is Record<string, any> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}
function nonEmptyString(...values: unknown[]): string | undefined {
  return values.find((value): value is string => typeof value === 'string' && value.length > 0);
}
function stringList(...values: unknown[]): string[] | undefined {
  return values.find((value): value is string[] =>
    Array.isArray(value) && value.every(item => typeof item === 'string'));
}

function isWithin(root: string, target: string): boolean {
  const relative = path.relative(root, target);
  return relative === '' || (!relative.startsWith('..' + path.sep) && relative !== '..' && !path.isAbsolute(relative));
}
function utcTimestamp(value: unknown): number {
  if (typeof value !== 'string' ||
      !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|\+00:00)$/.test(value)) return NaN;
  return Date.parse(value);
}
function canonicalTarget(root: string, userPath: unknown): string {
  if (typeof userPath !== 'string' || !userPath.trim() || userPath.includes('\0') || userPath.includes('\n')) {
    throw new Error('HybridGuard: ruta ausente o no válida');
  }
  const raw = path.resolve(root, userPath);
  let parent = path.dirname(raw);
  // Resolve parents so that symlink directories cannot redirect edits outside project.
  while (!fs.existsSync(parent)) {
    const next = path.dirname(parent);
    if (next === parent) throw new Error('HybridGuard: no se puede resolver destino');
    parent = next;
  }
  const resolved = path.resolve(fs.realpathSync(parent), path.relative(parent, raw));
  if (fs.existsSync(raw) && fs.lstatSync(raw).isSymbolicLink()) {
    throw new Error('HybridGuard: destino symlink bloqueado');
  }
  if (!isWithin(root, resolved)) throw new Error('HybridGuard: destino fuera del proyecto');
  return resolved;
}

function allowedPath(root: string, allowed: string[], userPath: unknown) {
  const dest = canonicalTarget(root, userPath);
  // Exact paths: deliberate. No implicit permission to edit sibling tests.
  const allowedPaths = allowed.map(p => canonicalTarget(root, p));
  if (!allowedPaths.includes(dest)) throw new Error(`HybridGuard: escritura fuera de alcance: ${String(userPath)}`);
}

function parsePaths(tool: string, input: any): string[] {
  if (tool === 'hybrid_guard_write') {
    if (typeof input?.path !== 'string') throw new Error('HybridGuard: falta la ruta de escritura');
    return [input.path];
  }
  if (tool === 'edit' || tool === 'write') {
    const name = input?.filePath ?? input?.file_path ?? input?.path;
    if (typeof name !== 'string') throw new Error('HybridGuard: herramienta de edición sin filePath reconocido');
    return [name];
  }
  if (tool === 'apply_patch' || tool === 'patch') {
    const patch = input?.patchText ?? input?.patch;
    if (typeof patch !== 'string' || patch.length > 200000) {
      throw new Error('HybridGuard: patch ausente o demasiado grande');
    }
    const paths: string[] = [];
    // Covers Add/Update/Delete/Move. Unknown patch formats fail closed.
    for (const line of patch.split('\n')) {
      const m = /^\*\*\* (?:Add File|Update File|Delete File|Move to): (.+)$/.exec(line);
      if (m) paths.push(m[1].trim());
    }
    if (!paths.length) throw new Error('HybridGuard: formato de patch no reconocido');
    return paths;
  }
  return [];
}

function safeShell(command: unknown, allowed: string[]): boolean {
  if (typeof command !== 'string' || command.includes('\n') || command.includes('\r')) return false;
  if (command === 'pwd' || command === 'git status --short' || command === 'git status --porcelain') return true;
  if (command === 'git --no-pager diff --stat') return true;
  // Restrict inspected file path to allowlist; do not run arbitrary shell syntax.
  for (const p of allowed) {
    if (/^[a-zA-Z0-9_./-]+$/.test(p) &&
        (command === `git --no-pager diff -- ${p}` || command === `git diff -- ${p}`)) return true;
  }
  return false;
}

export default {
  id: 'hybrid-guard',
  async setup(ctx: any) {
    const root = fs.realpathSync(ctx.location.project.canonical || ctx.location.directory);
    const identityDiagnostics = process.env.HYBRID_IDENTITY_DIAGNOSTICS === '1';
    const testDiagnosticFile = process.env.NODE_ENV === 'test'
      ? process.env.HYBRID_IDENTITY_DIAGNOSTIC_TEST_FILE
      : undefined;
    const diagnosticFileName = typeof testDiagnosticFile === 'string' &&
      testDiagnosticFile === path.basename(testDiagnosticFile) &&
      testDiagnosticFile.endsWith('.jsonl')
      ? testDiagnosticFile
      : 'identity-permissions.jsonl';
    const diagnosticFilePath = path.join(IDENTITY_DIAG_DIRECTORY, diagnosticFileName);
    const diagnosticController = identityDiagnostics ? new AbortController() : undefined;
    const evaluatedCalls = new Map<string, {
      action: string;
      resources: string[];
      agent: string | null;
      sessionID: string;
      callID: string;
    }>();
    const pendingPermissionRequests = new Map<string, {
      action: string;
      resources: string[];
      agent: string | null;
      sessionID: string;
      callID: string | null;
    }>();
    let diagnosticPermissionHook: any;
    let diagnosticEventTask: Promise<void> | undefined;
    const diagnosticLog = (record: Record<string, unknown>) => {
      if (!identityDiagnostics) return;
      let fd: number | undefined;
      try {
        const profile = fs.lstatSync(IDENTITY_DIAG_PROFILE_ROOT);
        const uid = typeof process.getuid === 'function' ? process.getuid() : undefined;
        if (!profile.isDirectory() || profile.isSymbolicLink() ||
            fs.realpathSync(IDENTITY_DIAG_PROFILE_ROOT) !== IDENTITY_DIAG_PROFILE_ROOT ||
            (uid !== undefined && profile.uid !== uid) || (profile.mode & 0o077) !== 0) return;

        fs.mkdirSync(IDENTITY_DIAG_DIRECTORY, { recursive: true, mode: 0o700 });
        const directory = fs.lstatSync(IDENTITY_DIAG_DIRECTORY);
        if (!directory.isDirectory() || directory.isSymbolicLink() ||
            fs.realpathSync(IDENTITY_DIAG_DIRECTORY) !== IDENTITY_DIAG_DIRECTORY ||
            (uid !== undefined && directory.uid !== uid)) return;
        if ((directory.mode & 0o777) !== 0o700) fs.chmodSync(IDENTITY_DIAG_DIRECTORY, 0o700);

        if (fs.existsSync(diagnosticFilePath)) {
          const existing = fs.lstatSync(diagnosticFilePath);
          if (!existing.isFile() || existing.isSymbolicLink() || existing.nlink !== 1 ||
              (uid !== undefined && existing.uid !== uid)) return;
        }
        if (typeof fs.constants.O_NOFOLLOW !== 'number') return;
        const flags = fs.constants.O_WRONLY | fs.constants.O_APPEND | fs.constants.O_CREAT |
          fs.constants.O_NOFOLLOW;
        fd = fs.openSync(diagnosticFilePath, flags, 0o600);
        const opened = fs.fstatSync(fd);
        if (!opened.isFile() || opened.nlink !== 1 || (uid !== undefined && opened.uid !== uid)) return;
        if ((opened.mode & 0o777) !== 0o600) fs.fchmodSync(fd, 0o600);
        const entry = {
          prefix: IDENTITY_DIAG_PREFIX,
          timestamp: new Date().toISOString(),
          ...record,
        };
        fs.writeSync(fd, `${JSON.stringify(entry)}\n`, undefined, 'utf8');
        fs.fsyncSync(fd);
      } catch {
        // Diagnostics must never change permission decisions or tool results.
      } finally {
        if (fd !== undefined) {
          try { fs.closeSync(fd); } catch { /* Best-effort close for diagnostic output. */ }
        }
      }
    };
    const correlationKey = (sessionID: string, callID: string) => `${sessionID}\0${callID}`;
    if (identityDiagnostics) {
      diagnosticPermissionHook = await ctx.permission.hook('evaluate', (event: any) => {
        if (event?.action !== 'hybrid_identity_probe' ||
            !Array.isArray(event.resources) || event.resources.length !== 1 ||
            event.resources[0] !== 'runtime-context') return;
        const callID = nonEmptyString(event.source?.id);
        const sessionID = nonEmptyString(event.sessionID);
        const agent = nonEmptyString(event.agent) ?? null;
        const resources = [...event.resources];
        if (event.effect === 'ask' && callID && sessionID) {
          evaluatedCalls.set(correlationKey(sessionID, callID), {
            action: event.action,
            resources,
            agent,
            sessionID,
            callID,
          });
        }
        diagnosticLog({
          event: 'permission.evaluate',
          action: event.action,
          resources,
          agent,
          effect: event.effect,
          sessionID: suffix(event.sessionID),
          callID: suffix(event.source?.id),
        });
      });

      const permissionProperties = (event: unknown): Record<string, any> | undefined => {
        if (!isObject(event)) return undefined;
        return isObject(event.properties) ? event.properties : event;
      };
      const controller = diagnosticController!;
      diagnosticEventTask = (async () => {
        try {
          for await (const event of ctx.event.subscribe({ signal: controller.signal })) {
            if (!isObject(event) ||
                (event.type !== 'permission.asked' && event.type !== 'permission.replied')) continue;
            const properties = permissionProperties(event);
            if (!properties) continue;
            if (event.type === 'permission.asked') {
              const sessionID = nonEmptyString(properties.sessionID);
              const callID = nonEmptyString(
                properties.source?.id,
                properties.tool?.callID,
                properties.tool?.id,
              );
              const action = nonEmptyString(properties.action, properties.permission);
              const resources = stringList(properties.resources, properties.patterns);
              const evaluated = sessionID && callID
                ? evaluatedCalls.get(correlationKey(sessionID, callID))
                : undefined;
              const matchesTarget = Boolean(sessionID) && (evaluated !== undefined ||
                (action === 'hybrid_identity_probe' && resources?.length === 1 && resources[0] === 'runtime-context'));
              if (!matchesTarget) continue;
              const requestID = nonEmptyString(properties.requestID, properties.id);
              const record = evaluated ?? {
                action: action!,
                resources: resources!,
                agent: nonEmptyString(properties.agent) ?? null,
                sessionID: sessionID!,
                callID: callID ?? null,
              };
              if (requestID) pendingPermissionRequests.set(requestID, record);
              diagnosticLog({
                event: 'permission.asked',
                requestID: requestID ?? null,
                action: record.action,
                resources: record.resources,
                agent: record.agent,
                sessionID: suffix(record.sessionID),
                callID: suffix(record.callID),
              });
              if (sessionID && callID) evaluatedCalls.delete(correlationKey(sessionID, callID));
              continue;
            }

            const requestID = nonEmptyString(properties.requestID, properties.id);
            if (!requestID) continue;
            const record = pendingPermissionRequests.get(requestID);
            if (!record) continue;
            diagnosticLog({
              event: 'permission.replied',
              requestID,
              decision: nonEmptyString(properties.decision, properties.reply) ?? null,
              action: record.action,
              resources: record.resources,
              agent: record.agent,
              sessionID: suffix(record.sessionID),
              callID: suffix(record.callID),
            });
            pendingPermissionRequests.delete(requestID);
          }
        } catch {
          // Event stream errors are intentionally not persisted; only permission events are in scope.
        }
      })();
    }
    const storage = execFileSync('git', ['-C', root, 'rev-parse', '--git-path', 'opencode-hybrid-guard'], { encoding: 'utf8' }).trim();
    const folder = path.resolve(root, storage);
    const statePath = path.join(folder, 'active.json');
    function active(): { root: string; allowed: string[] } | null {
      if (!fs.existsSync(statePath)) return null;
      let data: any;
      try {
        data = JSON.parse(fs.readFileSync(statePath, 'utf8'));
      } catch {
        throw new Error('HybridGuard: snapshot ausente o corrupto; edición bloqueada');
      }
      if (data.root !== root || data.version !== 1 || typeof data.task_id !== 'string' ||
          !Array.isArray(data.allowed) || !data.allowed.every((item: unknown) => typeof item === 'string')) {
        throw new Error('HybridGuard: snapshot incoherente; edición bloqueada');
      }
      return data;
    }
    function requireRunningLease(task: { root: string; task_id: string }) {
      const sessionPath = path.join(folder, 'launch-session.json');
      let session: any;
      try {
        session = JSON.parse(fs.readFileSync(sessionPath, 'utf8'));
      } catch {
        throw new Error('HybridGuard: launch-session ausente o corrupto; escritura bloqueada. Ejecuta recover-launch.');
      }
      if (!session || typeof session !== 'object' || Array.isArray(session) ||
          session.version !== SESSION_VERSION || session.root !== root ||
          session.task_id !== task.task_id || typeof session.session_id !== 'string' || !session.session_id) {
        throw new Error('HybridGuard: launch-session incompatible o de otra tarea; escritura bloqueada.');
      }
      if (session.status !== 'running') {
        throw new Error(`HybridGuard: sesión no está running (${String(session.status)}); escritura bloqueada.`);
      }
      const created = utcTimestamp(session.created_utc);
      const updated = utcTimestamp(session.updated_utc);
      const heartbeat = utcTimestamp(session.heartbeat_utc);
      const now = Date.now();
      if (![created, updated, heartbeat].every(Number.isFinite) ||
          created > now + FUTURE_SKEW_MS || updated > now + FUTURE_SKEW_MS ||
          heartbeat > now + FUTURE_SKEW_MS) {
        throw new Error('HybridGuard: timestamps de launch-session inválidos o adelantados; escritura bloqueada.');
      }
      if (created > updated || heartbeat > updated) {
        throw new Error('HybridGuard: timestamps de launch-session incoherentes; escritura bloqueada.');
      }
      const age = now - heartbeat;
      if (age < 0 || age >= HEARTBEAT_TTL_MS) {
        throw new Error('HybridGuard: heartbeat caducado; escritura bloqueada y revisión requerida.');
      }
    }
    function validateWriteBeforePermission(input: any): string {
      const task = active();
      if (!task) throw new Error('HybridGuard: no existe tarea activa. Ejecuta hybrid_guard.py begin.');
      requireRunningLease(task);
      if (typeof input?.content !== 'string' || Buffer.byteLength(input.content, 'utf8') > 2_000_000) {
        throw new Error('HybridGuard: contenido ausente o superior a 2 MB');
      }
      const target = canonicalTarget(root, input.path);
      const relativeTarget = path.relative(root, target).split(path.sep).join('/');
      allowedPath(root, task.allowed, relativeTarget);
      const parent = path.dirname(target);
      if (!fs.statSync(parent).isDirectory()) throw new Error('HybridGuard: el directorio destino no existe');
      return relativeTarget;
    }
    function writeSupervised(input: any) {
      const task = active();
      if (!task) throw new Error('HybridGuard: no existe tarea activa. Ejecuta hybrid_guard.py begin.');
      requireRunningLease(task);
      if (typeof input?.content !== 'string' || Buffer.byteLength(input.content, 'utf8') > 2_000_000) {
        throw new Error('HybridGuard: contenido ausente o superior a 2 MB');
      }
      const target = canonicalTarget(root, input.path);
      const relativeTarget = path.relative(root, target).split(path.sep).join('/');
      allowedPath(root, task.allowed, relativeTarget);
      const parent = path.dirname(target);
      if (!fs.statSync(parent).isDirectory()) throw new Error('HybridGuard: el directorio destino no existe');
      const mode = fs.existsSync(target) ? fs.statSync(target).mode & 0o777 : 0o644;
      const temporary = path.join(parent, `.${path.basename(target)}.hybrid-guard-${randomUUID()}.tmp`);
      try {
        fs.writeFileSync(temporary, input.content, { encoding: 'utf8', flag: 'wx', mode });
        // Re-read both durable records immediately before replacing the destination.
        const current = active();
        if (!current || current.task_id !== task.task_id || !current.allowed.includes(relativeTarget)) {
          throw new Error('HybridGuard: el manifiesto cambió durante la escritura');
        }
        requireRunningLease(current);
        if (canonicalTarget(root, relativeTarget) !== target || fs.realpathSync(parent) !== parent) {
          throw new Error('HybridGuard: la ruta cambió durante la escritura');
        }
        fs.renameSync(temporary, target);
      } finally {
        if (fs.existsSync(temporary)) fs.unlinkSync(temporary);
      }
      return { content: `Hybrid Guard escribió ${path.relative(root, target)}` };
    }

    await ctx.tool.transform((editor: any) => {
      editor.add({
        name: 'write',
        description: 'Escribe el contenido completo de un único archivo autorizado por Hybrid Guard.',
        input: {
          type: 'object',
          properties: {
            path: { type: 'string', description: 'Ruta relativa exacta del archivo dentro del proyecto' },
            content: { type: 'string', maxLength: 2_000_000 },
          },
          required: ['path', 'content'],
          additionalProperties: false,
        },
        options: { namespace: 'hybrid_guard', codemode: false },
        execute: async (input: any, context: any) => {
          if (context === null || typeof context !== 'object') {
            throw new Error('hybrid_guard_write: contexto de ejecución ausente');
          }
          if (context.agent !== 'local-coder') {
            throw new Error('hybrid_guard_write: solo local-coder puede solicitar escrituras');
          }
          const { sessionID, messageID, id } = context;
          if ([sessionID, messageID, id].some(value => typeof value !== 'string' || value.length === 0)) {
            throw new Error('hybrid_guard_write: contexto de ejecución incompleto');
          }

          const relativeTarget = validateWriteBeforePermission(input);
          if (typeof ctx.permission?.assert !== 'function') {
            throw new Error('hybrid_guard_write: ctx.permission.assert no está disponible');
          }
          await ctx.permission.assert({
            sessionID,
            agent: 'local-coder',
            source: { type: 'tool', messageID, id },
            action: 'hybrid_guard_write',
            resources: [relativeTarget],
            save: [],
          });
          return writeSupervised(input);
        },
      });
      editor.add({
        name: 'identity_probe',
        description: 'EXPERIMENTAL: devuelve solo la identidad y los IDs abreviados del contexto de ejecución de esta herramienta.',
        input: {
          type: 'object',
          properties: {},
          required: [],
          additionalProperties: false,
        },
        options: { namespace: 'hybrid', codemode: false },
        execute: async (_input: any, context: any) => {
          if (context === null || typeof context !== 'object') {
            throw new Error('hybrid_identity_probe: contexto de ejecución ausente');
          }
          if (context.agent !== 'local-coder') {
            throw new Error('hybrid_identity_probe: solo local-coder puede ejecutar el sondeo');
          }
          const { sessionID, messageID, id } = context;
          if ([sessionID, messageID, id].some(value => typeof value !== 'string' || value.length === 0)) {
            throw new Error('hybrid_identity_probe: contexto de ejecución incompleto');
          }
          if (typeof ctx.permission?.assert !== 'function') {
            throw new Error('hybrid_identity_probe: ctx.permission.assert no está disponible');
          }
          const permissionInput = {
            sessionID,
            agent: context.agent,
            source: { type: 'tool', messageID, id },
            action: 'hybrid_identity_probe',
            resources: ['runtime-context'],
            save: [],
          };
          if (identityDiagnostics) {
            diagnosticLog({
              event: 'assert.before',
              action: permissionInput.action,
              resources: permissionInput.resources,
              agent: permissionInput.agent,
              sessionID: suffix(sessionID),
              callID: suffix(id),
            });
          }
          try {
            await ctx.permission.assert(permissionInput);
          } catch (error) {
            if (identityDiagnostics) {
              diagnosticLog({
                event: 'assert.error',
                action: permissionInput.action,
                resources: permissionInput.resources,
                agent: permissionInput.agent,
                sessionID: suffix(sessionID),
                callID: suffix(id),
                ...errorSummary(error),
              });
            }
            throw error;
          }
          if (identityDiagnostics) {
            diagnosticLog({
              event: 'assert.resolved',
              action: permissionInput.action,
              resources: permissionInput.resources,
              agent: permissionInput.agent,
              sessionID: suffix(sessionID),
              callID: suffix(id),
            });
          }
          const field = (name: 'agent' | 'sessionID' | 'messageID' | 'id') => {
            const present = context !== null && typeof context === 'object' && name in context;
            const value = present ? context[name] : undefined;
            const type = typeof value;
            if (name === 'agent') {
              return {
                present,
                type,
                ...(type === 'string' && value.length > 0 ? { value } : {}),
              };
            }
            return {
              present,
              type,
              ...(type === 'string' && value.length > 0 ? { suffix: value.slice(-8) } : {}),
            };
          };
          return {
            content: JSON.stringify({
              experimental: true,
              agent: field('agent'),
              sessionID: field('sessionID'),
              messageID: field('messageID'),
              callID: field('id'),
            }),
          };
        },
      });
    });

    await ctx.tool.hook('execute.before', (event: any) => {
      const name = String(event.tool);
      const config = active();
      if (name === 'shell' || name === 'bash') {
        if (!safeShell(event.input?.command, config?.allowed ?? [])) {
          throw new Error('HybridGuard: shell bloqueada. Ejecuta los tests con hybrid_guard.py test desde tu terminal.');
        }
        return;
      }
      if (['edit', 'write', 'apply_patch', 'patch', 'hybrid_guard_write'].includes(name)) {
        if (!config) throw new Error('HybridGuard: no existe tarea activa. Ejecuta hybrid_guard.py begin.');
        requireRunningLease(config);
        for (const p of parsePaths(name, event.input)) allowedPath(root, config.allowed, p);
        return;
      }
      // Code-mode may invoke nested methods bypassing the normal write path.
      if (name === 'execute' || name === 'computer') {
        throw new Error('HybridGuard: ejecución dinámica bloqueada durante pruebas endurecidas');
      }
      // Unknown custom/MCP tools are not a secure sandbox; permissions must deny them.
    });

    if (identityDiagnostics) {
      return async () => {
        diagnosticController!.abort();
        await diagnosticPermissionHook?.dispose?.();
        await diagnosticEventTask;
      };
    }
  },
};
