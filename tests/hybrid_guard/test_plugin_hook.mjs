import assert from 'node:assert/strict';
import { afterEach, test } from 'node:test';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { execFileSync, spawn } from 'node:child_process';
import { once } from 'node:events';
import { randomUUID } from 'node:crypto';
import plugin from '../../.opencode/plugins/hybrid-guard/index.ts';

const roots = new Set();
const diagnosticFiles = new Set();
const diagnosticDirectory = '/private/tmp/opencode-2.1.3-arm64/profile/diagnostics';
const now = () => new Date().toISOString();
const writerContext = (overrides = {}) => ({
  agent: 'local-coder', sessionID: 'opencode-session-1',
  messageID: 'message-write-1', id: 'call-write-1', ...overrides,
});

function fixture({ status = 'running', session = true, active = true, heartbeat = now(),
  version = 1, sessionRoot, taskId = 'task-1', sessionTaskId = taskId } = {}) {
  const root = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'hybrid-guard-hook-')));
  roots.add(root);
  execFileSync('git', ['init', '-q', root]);
  fs.writeFileSync(path.join(root, 'allowed.txt'), '');
  fs.writeFileSync(path.join(root, 'outside.txt'), '');
  const state = execFileSync('git', ['-C', root, 'rev-parse', '--git-path', 'opencode-hybrid-guard'],
    { encoding: 'utf8' }).trim();
  const folder = path.resolve(root, state);
  fs.mkdirSync(folder, { recursive: true });
  if (active) {
    fs.writeFileSync(path.join(folder, 'active.json'), JSON.stringify({
      version: 1, root, task_id: taskId, allowed: ['allowed.txt'],
    }));
  }
  if (session) {
    fs.writeFileSync(path.join(folder, 'launch-session.json'), JSON.stringify({
      version, root: sessionRoot ?? root, task_id: sessionTaskId, session_id: 'session-1',
      status, created_utc: now(), updated_utc: now(), heartbeat_utc: heartbeat,
    }));
  }
  return { root, folder };
}

async function runtimeFor(root, {
  permission = { assert: async () => {} }, diagnostics = false,
  diagnosticFile = `test-${process.pid}-${randomUUID()}.jsonl`,
} = {}) {
  const registered = [];
  const tools = [];
  const permissionCalls = [];
  const permissionHooks = [];
  const eventQueue = [];
  let wakeEvent;
  let subscriptionStarted = false;
  let subscriptionClosed = false;
  let permissionHookDisposed = false;
  const eventContext = {
    subscribe: ({ signal } = {}) => {
      subscriptionStarted = true;
      return {
        async *[Symbol.asyncIterator]() {
          try {
            while (!signal?.aborted) {
              if (eventQueue.length) {
                yield eventQueue.shift();
                continue;
              }
              await new Promise(resolve => {
                wakeEvent = resolve;
                signal?.addEventListener('abort', resolve, { once: true });
              });
            }
          } finally {
            subscriptionClosed = true;
          }
        },
      };
    },
  };
  const context = { location: { project: { canonical: root }, directory: root }, tool: {
    hook: async (name, handler) => registered.push({ name, handler }),
    transform: async callback => callback({ add: definition => tools.push(definition) }),
  }, event: eventContext, permission: {
    hook: async (name, handler) => {
      permissionHooks.push({ name, handler });
      return { dispose: async () => { permissionHookDisposed = true; } };
    },
    assert: permission?.assert,
  } };
  if (permission !== undefined) {
    context.permission.assert = permission === null || typeof permission.assert !== 'function'
      ? permission?.assert
      : (...args) => {
          permissionCalls.push(args[0]);
          return permission.assert(...args);
        };
  }
  const previousDiagnostics = process.env.HYBRID_IDENTITY_DIAGNOSTICS;
  const previousDiagnosticTestFile = process.env.HYBRID_IDENTITY_DIAGNOSTIC_TEST_FILE;
  const previousNodeEnv = process.env.NODE_ENV;
  assert.equal(path.basename(diagnosticFile), diagnosticFile, 'test diagnostic filename must be a basename');
  const diagnosticPath = path.join(diagnosticDirectory, diagnosticFile);
  diagnosticFiles.add(diagnosticPath);
  process.env.NODE_ENV = 'test';
  process.env.HYBRID_IDENTITY_DIAGNOSTIC_TEST_FILE = diagnosticFile;
  if (diagnostics) process.env.HYBRID_IDENTITY_DIAGNOSTICS = '1';
  else delete process.env.HYBRID_IDENTITY_DIAGNOSTICS;
  let cleanup;
  try {
    cleanup = await plugin.setup(context);
  } finally {
    if (previousDiagnostics === undefined) delete process.env.HYBRID_IDENTITY_DIAGNOSTICS;
    else process.env.HYBRID_IDENTITY_DIAGNOSTICS = previousDiagnostics;
    if (previousDiagnosticTestFile === undefined) delete process.env.HYBRID_IDENTITY_DIAGNOSTIC_TEST_FILE;
    else process.env.HYBRID_IDENTITY_DIAGNOSTIC_TEST_FILE = previousDiagnosticTestFile;
    if (previousNodeEnv === undefined) delete process.env.NODE_ENV;
    else process.env.NODE_ENV = previousNodeEnv;
  }
  const hook = registered.find(entry => entry.name === 'execute.before')?.handler;
  assert.equal(typeof hook, 'function', 'the actual execute.before hook must be registered');
  return {
    hook, tools, permissionCalls, permissionHooks, diagnosticPath,
    readDiagnostics: () => fs.existsSync(diagnosticPath)
      ? fs.readFileSync(diagnosticPath, 'utf8').split('\n').filter(Boolean).map(line => JSON.parse(line))
      : [],
    emit: event => { eventQueue.push(event); wakeEvent?.(); },
    captureLogs: async operation => {
      return operation();
    },
    get subscriptionStarted() { return subscriptionStarted; },
    get subscriptionClosed() { return subscriptionClosed; },
    get permissionHookDisposed() { return permissionHookDisposed; },
    cleanup,
  };
}

async function hookFor(root) {
  return (await runtimeFor(root)).hook;
}

afterEach(() => {
  for (const root of roots) fs.rmSync(root, { recursive: true, force: true });
  roots.clear();
  for (const file of diagnosticFiles) fs.rmSync(file, { force: true });
  diagnosticFiles.clear();
  try { fs.rmdirSync(diagnosticDirectory); } catch (error) {
    if (error.code !== 'ENOENT' && error.code !== 'ENOTEMPTY') throw error;
  }
});

test('actual OpenCode hook permits an exact authorized write during a fresh running lease', async () => {
  const { root } = fixture();
  const hook = await hookFor(root);
  assert.doesNotThrow(() => hook({ tool: 'write', input: { filePath: 'allowed.txt' } }));
});

test('plugin registers a supervised writer that updates an authorized file', async () => {
  const { root } = fixture();
  const runtime = await runtimeFor(root);
  const writer = runtime.tools.find(item => item.name === 'write' && item.options?.namespace === 'hybrid_guard');
  assert.ok(writer, 'the namespaced Hybrid Guard write tool must be registered');
  await writer.execute({ path: 'allowed.txt', content: 'supervised output\n' }, writerContext());
  assert.equal(fs.readFileSync(path.join(root, 'allowed.txt'), 'utf8'), 'supervised output\n');
});

test('supervised writer waits for the native allow-once decision before writing', async () => {
  const { root } = fixture();
  let resolvePermission;
  const runtime = await runtimeFor(root, {
    permission: { assert: () => new Promise(resolve => { resolvePermission = resolve; }) },
  });
  const writer = runtime.tools.find(item => item.name === 'write' && item.options?.namespace === 'hybrid_guard');
  const context = writerContext();
  let finished = false;
  const pending = writer.execute({ path: 'allowed.txt', content: 'authorized once\n' }, context).then(result => {
    finished = true;
    return result;
  });
  await Promise.resolve();
  assert.equal(finished, false);
  assert.equal(fs.readFileSync(path.join(root, 'allowed.txt'), 'utf8'), '');
  assert.equal(runtime.permissionCalls.length, 1);
  resolvePermission();
  await pending;
  assert.equal(finished, true);
  assert.equal(fs.readFileSync(path.join(root, 'allowed.txt'), 'utf8'), 'authorized once\n');
  assert.deepEqual(runtime.permissionCalls, [{
    sessionID: context.sessionID,
    agent: 'local-coder',
    source: { type: 'tool', messageID: context.messageID, id: context.id },
    action: 'hybrid_guard_write',
    resources: ['allowed.txt'],
    save: [],
  }]);
});

test('supervised writer propagates native rejection without changing the file or leaving a temporary', async () => {
  const { root } = fixture();
  const denial = Object.assign(new Error('permission rejected'), { name: 'PermissionDenied' });
  const runtime = await runtimeFor(root, { permission: { assert: async () => { throw denial; } } });
  const writer = runtime.tools.find(item => item.name === 'write');
  await assert.rejects(
    writer.execute({ path: 'allowed.txt', content: 'must not persist' }, writerContext()),
    error => error === denial,
  );
  assert.equal(fs.readFileSync(path.join(root, 'allowed.txt'), 'utf8'), '');
  assert.deepEqual(fs.readdirSync(root).filter(name => name.includes('.hybrid-guard-')), []);
});

test('supervised writer rejects non-local agents and incomplete context before asking', async () => {
  const { root } = fixture();
  const runtime = await runtimeFor(root);
  const writer = runtime.tools.find(item => item.name === 'write');
  await assert.rejects(writer.execute({ path: 'allowed.txt', content: 'no' }, writerContext({ agent: 'orchestrator' })), /local-coder/);
  for (const field of ['sessionID', 'messageID', 'id']) {
    await assert.rejects(writer.execute({ path: 'allowed.txt', content: 'no' }, writerContext({ [field]: '' })), /contexto/);
    await assert.rejects(writer.execute({ path: 'allowed.txt', content: 'no' }, writerContext({ [field]: 17 })), /contexto/);
  }
  await assert.rejects(writer.execute({ path: 'allowed.txt', content: 'no' }, undefined), /contexto/);
  assert.deepEqual(runtime.permissionCalls, []);
});

test('supervised writer fails closed when native permission API is absent', async () => {
  const { root } = fixture();
  const runtime = await runtimeFor(root, { permission: null });
  const writer = runtime.tools.find(item => item.name === 'write');
  await assert.rejects(writer.execute({ path: 'allowed.txt', content: 'no' }, writerContext()), /permission\.assert/);
  assert.equal(fs.readFileSync(path.join(root, 'allowed.txt'), 'utf8'), '');
});

test('supervised writer rejects invalid scope or lease before requesting permission', async () => {
  const outside = fixture();
  const outsideRuntime = await runtimeFor(outside.root);
  const outsideWriter = outsideRuntime.tools.find(item => item.name === 'write');
  await assert.rejects(
    outsideWriter.execute({ path: 'outside.txt', content: 'no' }, writerContext()),
    /fuera de alcance/,
  );
  assert.deepEqual(outsideRuntime.permissionCalls, []);

  const absentTask = fixture({ active: false });
  const absentRuntime = await runtimeFor(absentTask.root);
  const absentWriter = absentRuntime.tools.find(item => item.name === 'write');
  await assert.rejects(
    absentWriter.execute({ path: 'allowed.txt', content: 'no' }, writerContext()),
    /no existe tarea activa/,
  );
  assert.deepEqual(absentRuntime.permissionCalls, []);

  const invalidContent = fixture();
  const invalidContentRuntime = await runtimeFor(invalidContent.root);
  const invalidContentWriter = invalidContentRuntime.tools.find(item => item.name === 'write');
  await assert.rejects(
    invalidContentWriter.execute({ path: 'allowed.txt', content: 7 }, writerContext()),
    /contenido ausente/,
  );
  assert.deepEqual(invalidContentRuntime.permissionCalls, []);

  for (const opts of [
    { status: 'pending_review' },
    { heartbeat: new Date(Date.now() - 16000).toISOString() },
  ]) {
    const { root } = fixture(opts);
    const runtime = await runtimeFor(root);
    const writer = runtime.tools.find(item => item.name === 'write');
    await assert.rejects(
      writer.execute({ path: 'allowed.txt', content: 'no' }, writerContext()),
      /sesión no está running|heartbeat caducado/,
    );
    assert.deepEqual(runtime.permissionCalls, []);
  }
});

test('each supervised write performs its own permission assertion', async () => {
  const { root } = fixture();
  const runtime = await runtimeFor(root);
  const writer = runtime.tools.find(item => item.name === 'write');
  await writer.execute({ path: 'allowed.txt', content: 'first\n' }, writerContext({ id: 'call-one' }));
  await writer.execute({ path: 'allowed.txt', content: 'second\n' }, writerContext({ id: 'call-two' }));
  assert.equal(fs.readFileSync(path.join(root, 'allowed.txt'), 'utf8'), 'second\n');
  assert.equal(runtime.permissionCalls.length, 2);
  assert.deepEqual(runtime.permissionCalls.map(call => call.source.id), ['call-one', 'call-two']);
});

test('identity probe requests the exact native permission before returning runtime identity', async () => {
  const { root } = fixture();
  const runtime = await runtimeFor(root);
  const probe = runtime.tools.find(item => item.name === 'identity_probe' && item.options?.namespace === 'hybrid');
  assert.ok(probe, 'the experimental hybrid_identity_probe tool must be registered');
  assert.deepEqual(probe.input, {
    type: 'object', properties: {}, required: [], additionalProperties: false,
  });
  const context = {
    agent: 'local-coder',
    sessionID: 'session-0123456789',
    messageID: 'message-9876543210',
    id: 'call-abcdef123456',
    directory: '/must-not-be-returned',
    worktree: '/must-not-be-returned-either',
  };
  const result = await probe.execute({ agent: 'forged-agent', sessionID: 'forged-session' }, context);
  assert.deepEqual(JSON.parse(result.content), {
    experimental: true,
    agent: { present: true, type: 'string', value: 'local-coder' },
    sessionID: { present: true, type: 'string', suffix: '23456789' },
    messageID: { present: true, type: 'string', suffix: '76543210' },
    callID: { present: true, type: 'string', suffix: 'ef123456' },
  });
  assert.deepEqual(runtime.permissionCalls, [{
    sessionID: context.sessionID,
    agent: 'local-coder',
    source: { type: 'tool', messageID: context.messageID, id: context.id },
    action: 'hybrid_identity_probe',
    resources: ['runtime-context'],
    save: [],
  }]);
});

test('identity diagnostics are inactive by default', async () => {
  const { root } = fixture();
  const runtime = await runtimeFor(root);
  const probe = runtime.tools.find(item => item.name === 'identity_probe');
  const result = await runtime.captureLogs(() => probe.execute({}, {
    agent: 'local-coder', sessionID: 'session-default', messageID: 'message-default', id: 'call-default',
  }));
  assert.deepEqual(runtime.permissionHooks, []);
  assert.equal(runtime.subscriptionStarted, false);
  assert.equal(typeof runtime.cleanup, 'undefined');
  assert.equal(fs.existsSync(runtime.diagnosticPath), false, 'disabled diagnostics must not create a file');
  assert.equal(JSON.parse(result.content).agent.value, 'local-coder');
});

test('disabled diagnostics neither create nor modify the diagnostic JSONL file', async () => {
  const { root } = fixture();
  fs.mkdirSync(diagnosticDirectory, { recursive: true, mode: 0o700 });
  const diagnosticFile = `disabled-${process.pid}-${randomUUID()}.jsonl`;
  const diagnosticPath = path.join(diagnosticDirectory, diagnosticFile);
  const priorContents = '{"preexisting":"preserve"}\n';
  fs.writeFileSync(diagnosticPath, priorContents, { mode: 0o600 });
  const runtime = await runtimeFor(root, { diagnosticFile });
  const probe = runtime.tools.find(item => item.name === 'identity_probe');
  await probe.execute({}, {
    agent: 'local-coder', sessionID: 'session-disabled', messageID: 'message-disabled', id: 'call-disabled',
  });
  assert.equal(fs.readFileSync(diagnosticPath, 'utf8'), priorContents);
});

test('enabled diagnostics persist timestamped JSONL records with restrictive permissions', async () => {
  const { root } = fixture();
  const runtime = await runtimeFor(root, { diagnostics: true });
  const probe = runtime.tools.find(item => item.name === 'identity_probe');
  await probe.execute({}, {
    agent: 'local-coder', sessionID: 'session-persist-12345678',
    messageID: 'message-persist-abcdefgh', id: 'call-persist-ijklmnop',
  });
  const records = runtime.readDiagnostics();
  assert.ok(records.length >= 2, 'the assert and result must be persisted');
  assert.ok(records.every(record => record.prefix === 'HYBRID_IDENTITY_DIAG'));
  assert.ok(records.every(record => Number.isFinite(Date.parse(record.timestamp))));
  assert.ok(records.some(record => record.event === 'assert.before' && record.callID === 'ijklmnop'));
  assert.ok(records.some(record => record.event === 'assert.resolved' && record.sessionID === '12345678'));
  assert.equal(fs.statSync(runtime.diagnosticPath).mode & 0o777, 0o600);
  assert.equal(fs.statSync(diagnosticDirectory).mode & 0o777, 0o700);
  await runtime.cleanup();
});

test('diagnostics leave the probe result and filesystem unchanged and never call the writer', async () => {
  const { root } = fixture();
  const runtime = await runtimeFor(root, { diagnostics: true });
  const probe = runtime.tools.find(item => item.name === 'identity_probe');
  const before = fs.readFileSync(path.join(root, 'allowed.txt'), 'utf8');
  const result = await runtime.captureLogs(() => probe.execute({}, {
    agent: 'local-coder', sessionID: 'session-diagnostic', messageID: 'message-diagnostic', id: 'call-diagnostic',
  }));
  assert.deepEqual(JSON.parse(result.content), {
    experimental: true,
    agent: { present: true, type: 'string', value: 'local-coder' },
    sessionID: { present: true, type: 'string', suffix: 'agnostic' },
    messageID: { present: true, type: 'string', suffix: 'agnostic' },
    callID: { present: true, type: 'string', suffix: 'agnostic' },
  });
  assert.equal(fs.readFileSync(path.join(root, 'allowed.txt'), 'utf8'), before);
  assert.deepEqual(runtime.tools.map(tool => [tool.options.namespace, tool.name]), [
    ['hybrid_guard', 'write'], ['hybrid', 'identity_probe'],
  ]);
  assert.equal(runtime.permissionCalls.length, 1);
  await runtime.cleanup();
  assert.equal(runtime.permissionHookDisposed, true);
});

test('identity diagnostics records ask and allow evaluations without mutating effects', async () => {
  const { root } = fixture();
  const runtime = await runtimeFor(root, { diagnostics: true });
  assert.deepEqual(runtime.permissionHooks.map(item => item.name), ['evaluate']);
  assert.equal(runtime.subscriptionStarted, true);
  const evaluate = runtime.permissionHooks[0].handler;
  for (const effect of ['ask', 'allow']) {
    const event = {
      action: 'hybrid_identity_probe', resources: ['runtime-context'], agent: 'local-coder',
      effect, sessionID: `session-${effect}-12345678`,
      source: { type: 'tool', messageID: 'message-1', id: `call-${effect}-abcdefgh` },
    };
    await runtime.captureLogs(() => evaluate(event));
    assert.equal(event.effect, effect);
    assert.deepEqual(event.resources, ['runtime-context']);
  }
  const entries = runtime.readDiagnostics();
  assert.deepEqual(entries.map(entry => entry.effect), ['ask', 'allow']);
  assert.deepEqual(entries.map(entry => entry.action), ['hybrid_identity_probe', 'hybrid_identity_probe']);
  assert.deepEqual(entries.map(entry => entry.resources), [['runtime-context'], ['runtime-context']]);
  assert.deepEqual(entries.map(entry => entry.agent), ['local-coder', 'local-coder']);
  assert.deepEqual(entries.map(entry => entry.sessionID), ['12345678', '12345678']);
  assert.deepEqual(entries.map(entry => entry.callID), ['abcdefgh', 'abcdefgh']);
  await runtime.cleanup();
});

test('permission asked and replied events correlate by request ID without requiring action on reply', async () => {
  const { root } = fixture();
  const runtime = await runtimeFor(root, { diagnostics: true });
  const evaluate = runtime.permissionHooks[0].handler;
  await runtime.captureLogs(() => evaluate({
    action: 'hybrid_identity_probe', resources: ['runtime-context'], agent: 'local-coder',
    effect: 'ask', sessionID: 'session-correlated-12345678',
    source: { type: 'tool', messageID: 'message-1', id: 'call-correlated-abcdefgh' },
  }));
  await runtime.captureLogs(async () => {
    runtime.emit({ type: 'session.idle', properties: {} });
    runtime.emit({ type: 'permission.replied', properties: {} });
    await new Promise(resolve => setImmediate(resolve));
    runtime.emit({ type: 'permission.asked', properties: {
      id: 'permission-request-1', sessionID: 'session-correlated-12345678',
      permission: 'hybrid_identity_probe', patterns: ['runtime-context'],
      tool: { messageID: 'message-1', callID: 'call-correlated-abcdefgh' },
    } });
    await new Promise(resolve => setImmediate(resolve));
    runtime.emit({ type: 'permission.replied', properties: {
      requestID: 'permission-request-1', sessionID: 'session-correlated-12345678', reply: 'once',
    } });
    await new Promise(resolve => setImmediate(resolve));
  });
  const entries = runtime.readDiagnostics();
  const asked = entries.find(entry => entry.event === 'permission.asked');
  const replied = entries.find(entry => entry.event === 'permission.replied');
  assert.equal(asked.requestID, 'permission-request-1');
  assert.equal(asked.callID, 'abcdefgh');
  assert.equal(replied.requestID, asked.requestID);
  assert.equal(replied.decision, 'once');
  assert.equal(replied.action, 'hybrid_identity_probe');
  await runtime.cleanup();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(runtime.subscriptionClosed, true);
  assert.equal(runtime.permissionHookDisposed, true);
});

test('identity diagnostics logs and propagates the original permission error', async () => {
  const { root } = fixture();
  const denial = Object.assign(new Error('permission denied for runtime-context'), { name: 'PermissionDenied' });
  const runtime = await runtimeFor(root, {
    diagnostics: true,
    permission: { assert: async () => { throw denial; } },
  });
  const probe = runtime.tools.find(item => item.name === 'identity_probe');
  await runtime.captureLogs(() => assert.rejects(probe.execute({}, {
    agent: 'local-coder', sessionID: 'session-error', messageID: 'message-error', id: 'call-error',
  }), error => error === denial));
  const failure = runtime.readDiagnostics().find(entry => entry.event === 'assert.error');
  assert.equal(failure.errorType, 'PermissionDenied');
  assert.equal(failure.errorMessage, denial.message);
  assert.deepEqual(runtime.permissionCalls, [{
    sessionID: 'session-error', agent: 'local-coder',
    source: { type: 'tool', messageID: 'message-error', id: 'call-error' },
    action: 'hybrid_identity_probe', resources: ['runtime-context'], save: [],
  }]);
  await runtime.cleanup();
});

test('identity probe waits for a pending permission before producing a result', async () => {
  const { root } = fixture();
  let resolvePermission;
  const runtime = await runtimeFor(root, {
    permission: { assert: () => new Promise(resolve => { resolvePermission = resolve; }) },
  });
  const probe = runtime.tools.find(item => item.name === 'identity_probe' && item.options?.namespace === 'hybrid');
  const context = {
    agent: 'local-coder', sessionID: 'session-pending', messageID: 'message-pending', id: 'call-pending',
  };
  let resultReady = false;
  const pending = probe.execute({}, context).then(result => {
    resultReady = true;
    return result;
  });
  await Promise.resolve();
  assert.equal(resultReady, false);
  assert.equal(runtime.permissionCalls.length, 1);
  resolvePermission();
  const result = await pending;
  assert.equal(resultReady, true);
  assert.equal(JSON.parse(result.content).agent.value, 'local-coder');
});

test('identity probe propagates native permission denial without returning identity', async () => {
  const { root } = fixture();
  const denial = new Error('permission denied');
  const runtime = await runtimeFor(root, { permission: { assert: async () => { throw denial; } } });
  const probe = runtime.tools.find(item => item.name === 'identity_probe');
  await assert.rejects(probe.execute({}, {
    agent: 'local-coder', sessionID: 'session-denied', messageID: 'message-denied', id: 'call-denied',
  }), error => error === denial);
  assert.equal(runtime.permissionCalls.length, 1);
});

test('identity probe propagates a human rejection without converting it to a result', async () => {
  const { root } = fixture();
  const rejection = new Error('human rejected permission');
  const runtime = await runtimeFor(root, { permission: { assert: async () => { throw rejection; } } });
  const probe = runtime.tools.find(item => item.name === 'identity_probe');
  await assert.rejects(probe.execute({}, {
    agent: 'local-coder', sessionID: 'session-rejected', messageID: 'message-rejected', id: 'call-rejected',
  }), error => error === rejection);
  assert.equal(runtime.permissionCalls.length, 1);
});

test('identity probe rejects orchestrator and other agents before requesting permission', async () => {
  const { root } = fixture();
  const runtime = await runtimeFor(root);
  const probe = runtime.tools.find(item => item.name === 'identity_probe');
  for (const agent of ['orchestrator', 'explorer', 'reviewer', 'other']) {
    await assert.rejects(probe.execute({}, {
      agent, sessionID: 'session-valid', messageID: 'message-valid', id: 'call-valid',
    }), /local-coder/);
  }
  assert.deepEqual(runtime.permissionCalls, []);
});

test('identity probe rejects missing context and incomplete runtime identifiers before permission', async () => {
  const { root } = fixture();
  const runtime = await runtimeFor(root);
  const probe = runtime.tools.find(item => item.name === 'identity_probe');
  await assert.rejects(probe.execute({}, undefined), /contexto/);
  await assert.rejects(probe.execute({}, null), /contexto/);
  for (const field of ['sessionID', 'messageID', 'id']) {
    const context = {
      agent: 'local-coder', sessionID: 'session-valid', messageID: 'message-valid', id: 'call-valid',
    };
    context[field] = '';
    await assert.rejects(probe.execute({}, context), /contexto/);
    context[field] = 17;
    await assert.rejects(probe.execute({}, context), /contexto/);
  }
  assert.deepEqual(runtime.permissionCalls, []);
});

test('identity probe fails closed when ctx.permission.assert is unavailable', async () => {
  const { root } = fixture();
  for (const permission of [null, {}, { assert: null }]) {
    const runtime = await runtimeFor(root, { permission });
    const probe = runtime.tools.find(item => item.name === 'identity_probe');
    await assert.rejects(probe.execute({}, {
      agent: 'local-coder', sessionID: 'session-no-api', messageID: 'message-no-api', id: 'call-no-api',
    }), /permission\.assert/);
    assert.deepEqual(runtime.permissionCalls, []);
  }
});

test('identity probe has no file or process side effects and does not invoke the writer', async () => {
  const { root } = fixture();
  const runtime = await runtimeFor(root);
  const probe = runtime.tools.find(item => item.name === 'identity_probe');
  const before = fs.readFileSync(path.join(root, 'allowed.txt'), 'utf8');
  const result = await probe.execute({}, {
    agent: 'local-coder', sessionID: 'session-readonly', messageID: 'message-readonly', id: 'call-readonly',
  });
  assert.equal(JSON.parse(result.content).agent.value, 'local-coder');
  assert.equal(fs.readFileSync(path.join(root, 'allowed.txt'), 'utf8'), before);
  assert.doesNotMatch(probe.execute.toString(), /\b(?:writeSupervised|execFileSync|spawn|fs)\b/);
  assert.deepEqual(runtime.tools.map(tool => [tool.options.namespace, tool.name]), [
    ['hybrid_guard', 'write'], ['hybrid', 'identity_probe'],
  ]);
});

test('supervised writer rejects a path outside the active manifest', async () => {
  const { root } = fixture();
  const runtime = await runtimeFor(root);
  const writer = runtime.tools.find(item => item.name === 'write');
  await assert.rejects(writer.execute({ path: 'outside.txt', content: 'must not write' }, writerContext()), /fuera de alcance/);
  assert.deepEqual(runtime.permissionCalls, []);
  assert.equal(fs.readFileSync(path.join(root, 'outside.txt'), 'utf8'), '');
});

test('supervised writer rejects pending review and an expired heartbeat', async () => {
  for (const opts of [
    { status: 'pending_review' },
    { heartbeat: new Date(Date.now() - 16000).toISOString() },
  ]) {
    const { root } = fixture(opts);
    const runtime = await runtimeFor(root);
    const writer = runtime.tools.find(item => item.name === 'write');
    await assert.rejects(writer.execute({ path: 'allowed.txt', content: 'must not write' }, writerContext()), /sesión no está running|heartbeat caducado/);
    assert.deepEqual(runtime.permissionCalls, []);
    assert.equal(fs.readFileSync(path.join(root, 'allowed.txt'), 'utf8'), '');
  }
});

test('actual hook rejects a path outside scope even during running', async () => {
  const { root } = fixture();
  const hook = await hookFor(root);
  assert.throws(() => hook({ tool: 'edit', input: { filePath: 'outside.txt' } }), /fuera de alcance/);
});

test('actual hook rejects an expired lease', async () => {
  const expired = new Date(Date.now() - 16000).toISOString();
  const { root } = fixture({ heartbeat: expired });
  const hook = await hookFor(root);
  assert.throws(() => hook({ tool: 'write', input: { filePath: 'allowed.txt' } }), /heartbeat caducado/);
});

test('SIGKILL with a fresh lease stops authorizing writes when the real lease expires', async () => {
  const { root, folder } = fixture({ session: false });
  const hook = await hookFor(root);
  const guardPath = path.resolve('.opencode/scripts/hybrid_guard.py');
  const script = String.raw`import importlib.util, os, pathlib, sys, time
root = pathlib.Path(sys.argv[1])
spec = importlib.util.spec_from_file_location('guard_live_lease', sys.argv[2])
guard = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = guard
spec.loader.exec_module(guard)
with guard.operation_lock(root):
    state = guard.new_launch_session(root, 'task-1', 'running')
    state['supervisor_pid'] = os.getpid()
    guard.write_launch_session(root, state)
    print(state['heartbeat_utc'], flush=True)
    time.sleep(60)
`;
  const supervisor = spawn(process.env.PYTHON ?? 'python3', ['-c', script, root, guardPath], {
    stdio: ['ignore', 'pipe', 'inherit'],
  });
  try {
    let output = '';
    const ready = new Promise((resolve, reject) => {
      supervisor.stdout.setEncoding('utf8');
      supervisor.stdout.on('data', chunk => {
        output += chunk;
        if (output.includes('\n')) resolve(output.trim().split('\n')[0]);
      });
      supervisor.once('error', reject);
      supervisor.once('exit', (code, signal) => reject(new Error(`supervisor exited before lease: ${code}/${signal}`)));
    });
    const heartbeat = await ready;
    const heartbeatMs = Date.parse(heartbeat);
    assert.ok(Number.isFinite(heartbeatMs));
    assert.ok(Date.now() - heartbeatMs < 15_000, 'supervisor must start with a fresh lease');
    const sessionPath = path.join(folder, 'launch-session.json');
    const live = JSON.parse(fs.readFileSync(sessionPath, 'utf8'));
    assert.equal(live.status, 'running');
    assert.doesNotThrow(() => hook({ tool: 'write', input: { filePath: 'allowed.txt' } }));

    supervisor.kill('SIGKILL');
    const [, signal] = await once(supervisor, 'exit');
    assert.equal(signal, 'SIGKILL');
    const remainingMs = heartbeatMs + 15_100 - Date.now();
    if (remainingMs > 0) await new Promise(resolve => setTimeout(resolve, remainingMs));
    assert.throws(
      () => hook({ tool: 'write', input: { filePath: 'allowed.txt' } }),
      /heartbeat caducado/,
    );
  } finally {
    if (supervisor.exitCode === null && supervisor.signalCode === null) {
      supervisor.kill('SIGKILL');
      await once(supervisor, 'exit');
    }
  }
});

test('actual hook rejects a heartbeat timestamp too far in the future', async () => {
  const future = new Date(Date.now() + 60_000).toISOString();
  const { root } = fixture({ heartbeat: future });
  const hook = await hookFor(root);
  assert.throws(() => hook({ tool: 'write', input: { filePath: 'allowed.txt' } }), /timestamps.*adelantados/);
});

test('actual hook rejects timestamps without an explicit UTC zone', async () => {
  const { root, folder } = fixture();
  const sessionPath = path.join(folder, 'launch-session.json');
  const session = JSON.parse(fs.readFileSync(sessionPath, 'utf8'));
  session.heartbeat_utc = new Date().toISOString().replace(/Z$/, '');
  fs.writeFileSync(sessionPath, JSON.stringify(session));
  const hook = await hookFor(root);
  assert.throws(() => hook({ tool: 'write', input: { filePath: 'allowed.txt' } }), /timestamps.*inválidos/);
});

test('actual hook rejects heartbeat newer than updated_utc', async () => {
  const { root, folder } = fixture();
  const sessionPath = path.join(folder, 'launch-session.json');
  const session = JSON.parse(fs.readFileSync(sessionPath, 'utf8'));
  session.updated_utc = new Date(Date.now() - 10_000).toISOString();
  fs.writeFileSync(sessionPath, JSON.stringify(session));
  const hook = await hookFor(root);
  assert.throws(() => hook({ tool: 'write', input: { filePath: 'allowed.txt' } }), /timestamps.*incoherentes/);
});

test('actual hook rejects pending_review and starting states', async () => {
  for (const status of ['pending_review', 'starting', 'idle']) {
    const { root } = fixture({ status });
    const hook = await hookFor(root);
    assert.throws(() => hook({ tool: 'write', input: { filePath: 'allowed.txt' } }), /sesión no está running/);
  }
});

test('actual hook rejects absent task/session records', async () => {
  const absentTask = fixture({ active: false });
  const hookWithoutTask = await hookFor(absentTask.root);
  assert.throws(() => hookWithoutTask({ tool: 'write', input: { filePath: 'allowed.txt' } }), /tarea activa/);

  const absentSession = fixture({ session: false });
  const hookWithoutSession = await hookFor(absentSession.root);
  assert.throws(() => hookWithoutSession({ tool: 'write', input: { filePath: 'allowed.txt' } }), /launch-session/);
});

test('actual hook rejects corrupt, incompatible, wrong-root and cross-task state', async () => {
  for (const fixtureOptions of [
    { session: false }, { version: 77 }, { sessionRoot: '/wrong/root' }, { sessionTaskId: 'other-task' },
  ]) {
    const { root, folder } = fixture(fixtureOptions);
    if (fixtureOptions.session === false) {
      fs.writeFileSync(path.join(folder, 'launch-session.json'), '{broken');
    }
    const hook = await hookFor(root);
    assert.throws(() => hook({ tool: 'write', input: { filePath: 'allowed.txt' } }), /launch-session|incompatible|otra raíz|tarea/);
  }
});

test('actual hook validates every path in an apply_patch event', async () => {
  const { root } = fixture();
  const hook = await hookFor(root);
  assert.throws(() => hook({ tool: 'apply_patch', input: {
    patchText: '*** Begin Patch\n*** Update File: allowed.txt\n*** Add File: outside.txt\n*** End Patch',
  } }), /fuera de alcance/);
});

test('supervised writer rejects traversal and symlink redirects outside the repository', async () => {
  const { root } = fixture();
  const external = fs.mkdtempSync(path.join(os.tmpdir(), 'hybrid-guard-outside-'));
  roots.add(external);
  fs.writeFileSync(path.join(external, 'secret.txt'), 'untouched\n');
  fs.rmSync(path.join(root, 'allowed.txt'));
  fs.symlinkSync(path.join(external, 'secret.txt'), path.join(root, 'allowed.txt'));
  fs.mkdirSync(path.join(root, 'nested'));
  fs.symlinkSync(external, path.join(root, 'nested', 'redirect'));
  const runtime = await runtimeFor(root);
  const writer = runtime.tools.find(item => item.name === 'write' && item.options?.namespace === 'hybrid_guard');
  await assert.rejects(writer.execute({ path: '../outside.txt', content: 'must not escape' }, writerContext()));
  await assert.rejects(writer.execute({ path: 'allowed.txt', content: 'must not follow link' }, writerContext()), /symlink|fuera del proyecto|alcance/);
  await assert.rejects(writer.execute({ path: 'nested/redirect/secret.txt', content: 'must not follow parent link' }, writerContext()), /fuera del proyecto|alcance/);
  assert.equal(fs.readFileSync(path.join(external, 'secret.txt'), 'utf8'), 'untouched\n');
});

test('supervised writer fails closed if its parent path is swapped for an external symlink before rename', async () => {
  const { root } = fixture();
  const outside = fs.mkdtempSync(path.join(os.tmpdir(), 'hybrid-guard-race-outside-'));
  roots.add(outside);
  const nested = path.join(root, 'nested');
  const moved = path.join(root, 'nested-original');
  const externalTarget = path.join(outside, 'allowed.txt');
  fs.mkdirSync(nested);
  fs.writeFileSync(path.join(nested, 'allowed.txt'), 'inside original\n');
  fs.writeFileSync(externalTarget, 'outside original\n');
  const stateFolder = path.resolve(root, execFileSync('git', ['-C', root, 'rev-parse', '--git-path', 'opencode-hybrid-guard'], { encoding: 'utf8' }).trim());
  const statePath = path.join(stateFolder, 'active.json');
  const state = JSON.parse(fs.readFileSync(statePath, 'utf8'));
  state.allowed = ['nested/allowed.txt'];
  fs.writeFileSync(statePath, JSON.stringify(state));
  const runtime = await runtimeFor(root);
  const writer = runtime.tools.find(item => item.name === 'write' && item.options?.namespace === 'hybrid_guard');
  const realRename = fs.renameSync;
  let swapped = false;
  fs.renameSync = (from, to) => {
    if (!swapped && to === path.join(nested, 'allowed.txt')) {
      swapped = true;
      realRename(nested, moved);
      fs.symlinkSync(outside, nested, 'dir');
      try {
        return realRename(from, to);
      } finally {
        fs.unlinkSync(nested);
        realRename(moved, nested);
      }
    }
    return realRename(from, to);
  };
  try {
    await assert.rejects(writer.execute({ path: 'nested/allowed.txt', content: 'must not escape\n' }, writerContext()));
  } finally {
    fs.renameSync = realRename;
  }
  assert.equal(swapped, true, 'the test must replace the parent at the final rename boundary');
  assert.equal(fs.readFileSync(externalTarget, 'utf8'), 'outside original\n');
  assert.equal(fs.readFileSync(path.join(nested, 'allowed.txt'), 'utf8'), 'inside original\n');
});

test('hook denials state their scope without claiming sandbox or process isolation', async () => {
  const { root } = fixture({ status: 'pending_review' });
  const hook = await hookFor(root);
  assert.throws(() => hook({ tool: 'write', input: { filePath: 'allowed.txt' } }), error => {
    assert.match(error.message, /pending_review/);
    assert.doesNotMatch(error.message, /sandbox|aislamiento garantizado/i);
    return true;
  });
});
