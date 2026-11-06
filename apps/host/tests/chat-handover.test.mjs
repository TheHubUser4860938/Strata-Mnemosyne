/** The first-start handover (F7): two windows opened together move the browser's archive ONCE, and a
 *  refused move gives its claim back so the next start tries again. */
import test from 'node:test';
import assert from 'node:assert/strict';
import { build } from 'esbuild';
import { fileURLToPath } from 'node:url';

const here = (p) => fileURLToPath(new URL(p, import.meta.url));
async function bundle() {
  const result = await build({
    entryPoints: [here('../src/lib/chat-sync.ts')], bundle: true, format: 'esm', platform: 'node',
    write: false, logLevel: 'silent',
  });
  return import(`data:text/javascript;base64,${Buffer.from(result.outputFiles[0].text).toString('base64')}`);
}

const session = (id, updatedAt) => ({
  id, title: `Chat ${id}`, createdAt: '2026-11-01T10:00:00.000Z', updatedAt,
  workspace: 'C:/w', tokensIn: 0, tokensOut: 0, messages: [],
});
const archive = () => JSON.stringify([session('s_a', '2026-11-03T10:00:00.000Z'), session('s_b', '2026-11-03T10:00:01.000Z')]);

function fakeHost() {
  const store = new Map();
  const host = {
    imports: 0,
    store,
    transport: {
      async list() {
        return { chats: [...store.values()].map(s => ({ id: s.id, rev: 1, createdAt: s.createdAt, updatedAt: s.updatedAt, bytes: 1, title: s.title })) };
      },
      async get(id) { const s = store.get(id); return s ? { rev: 1, session: s } : null; },
      async put(id, text) { store.set(id, JSON.parse(text)); return { rev: 1, conflict: false }; },
      async remove(id) { store.delete(id); },
      async importMany(sessions) {
        host.imports++;
        sessions.forEach(s => store.set(s.id, s));
        return { imported: sessions.map(s => s.id), skipped: [], failed: [] };
      },
    },
  };
  return host;
}

const fakeBrowser = () => {
  const memory = new Map([['strata.sessions.v1', archive()]]);
  return { memory, api: {
    getItem: (k) => memory.get(k) ?? null,
    setItem: (k, v) => { memory.set(k, v); },
    removeItem: (k) => memory.delete(k),
  } };
};

test('two windows on the first start: the archive is handed over once (F7)', async () => {
  const mod = await bundle();
  const host = fakeHost();
  const browser = fakeBrowser();
  const [a, b] = await Promise.all([
    mod.hydrateChats({ transport: host.transport, browser: browser.api, current: [] }),
    mod.hydrateChats({ transport: host.transport, browser: browser.api, current: [] }),
  ]);
  assert.equal(host.imports, 1, 'the window that claims the handover sends it; the other sees the claim');
  assert.equal(a.moved + b.moved, 2, 'the two chats arrive exactly once between them');
  assert.deepEqual([...host.store.keys()].sort(), ['s_a', 's_b'], 'the host ends with the archive');
});

test('a refused move gives the claim back: the next start tries again', async () => {
  const mod = await bundle();
  const host = fakeHost();
  host.transport.importMany = async (sessions) => ({
    imported: sessions.slice(0, 1).map(s => s.id), skipped: [],
    failed: [{ id: 's_b', error: 'disk full', code: 'ENOSPC' }],
  });
  const browser = fakeBrowser();
  const first = await mod.hydrateChats({ transport: host.transport, browser: browser.api, current: [] });
  assert.equal(first.failed.length, 1, 'the refusal is reported');
  assert.equal(browser.memory.get('strata.chats.host.v1'), undefined, 'the claim is returned when the move was not whole');
});
