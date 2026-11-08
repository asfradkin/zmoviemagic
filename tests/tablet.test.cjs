const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

const requestId = '65b80b5f-4a08-4c26-8d92-f2bb90f9b890';
const source = fs.readFileSync(path.join(__dirname, '../static/tablet.js'), 'utf8');

function harness(replies, storage = {}) {
    const scope = {};
    vm.runInNewContext(source, scope);
    const timers = new Map();
    const calls = [], messages = [], busy = [];
    let now = 0, id = 0;
    const controller = scope.MovieTablet.createController({
        fetch(url, options) {
            calls.push({ url, options });
            const reply = replies.shift();
            if (reply instanceof Error) { return Promise.reject(reply); }
            if (typeof reply === 'function') { return reply(); }
            if (!reply) { throw new Error('Unexpected fetch'); }
            return Promise.resolve({ ok: reply.status < 400, status: reply.status,
                json: () => Promise.resolve(reply.body) });
        },
        now: () => now,
        setTimeout(callback, delay) { timers.set(++id, { callback, at: now + delay }); return id; },
        clearTimeout(id) { timers.delete(id); },
        makeKey: () => 'tablet-test-001',
        onMessage: message => messages.push(message),
        onBusy: value => busy.push(value),
        savePending: record => { if (storage.denied) { throw new Error('denied'); } storage.pending = record; },
        clearPending: () => { if (storage.denied) { throw new Error('denied'); } delete storage.pending; }
    });
    return { controller, calls, messages, busy,
        async flush() { for (let i = 0; i < 10; i++) { await Promise.resolve(); } },
        async tick(ms) {
            now += ms;
            const due = [...timers.entries()].filter(([, t]) => t.at <= now);
            for (const [id, timer] of due) {
                if (timers.delete(id)) { timer.callback(); }
            }
            await this.flush();
        }
    };
}

const accepted = () => ({ status: 202, body: { request_id: requestId, movie_key: 'luca', command_state: 'queued', playback: { state: 'unknown' } } });
const state = command_state => ({ status: 200, body: { request: { request_id: requestId, movie_key: 'luca', command_state } } });

test('POST uses stable key and one idempotency key; repeats blocked; polls at 500ms then 1s', async () => {
    const h = harness([accepted(), state('dispatching'), state('command_sent')]);
    h.controller.play('luca');
    h.controller.play('moana');
    await h.flush();
    assert.equal(h.calls.length, 1);
    assert.equal(h.calls[0].options.method, 'POST');
    assert.deepEqual(JSON.parse(h.calls[0].options.body), { movie_key: 'luca' });
    assert.equal(h.calls[0].options.headers['Idempotency-Key'], 'tablet-test-001');
    await h.tick(499);
    assert.equal(h.calls.length, 1);
    await h.tick(1);
    assert.equal(h.calls[1].url, '/api/status?request_id=' + requestId);
    await h.tick(999);
    assert.equal(h.calls.length, 2);
    await h.tick(1);
    assert.equal(h.controller.isBusy(), false);
    assert.match(h.messages.at(-1), /Request sent/);
    assert.doesNotMatch(h.messages.join(' '), /playing/i);
    assert.deepEqual(h.busy, [true, false]);
});

test('network error never retries POST or falls back to legacy GET', async () => {
    const h = harness([new Error('offline')]);
    h.controller.play('luca');
    await h.flush();
    await h.tick(20000);
    assert.equal(h.calls.length, 1);
    assert.match(h.messages.at(-1), /may have reached/);
    assert.equal(h.controller.isBusy(), false);
});

test('20-second timeout ignores a late acceptance', async () => {
    let complete;
    const h = harness([() => new Promise(resolve => { complete = resolve; })]);
    h.controller.play('luca');
    await h.tick(20000);
    complete({ ok: true, status: 202, json: () => Promise.resolve({ request_id: requestId }) });
    await h.flush();
    await h.tick(1000);
    assert.equal(h.calls.length, 1);
    assert.match(h.messages.at(-1), /may have reached/);
});

test('polling stops after 20 seconds without claiming delivery', async () => {
    const h = harness([accepted(), ...Array.from({ length: 21 }, () => state('dispatching'))]);
    h.controller.play('luca');
    await h.flush();
    await h.tick(500);
    for (let i = 0; i < 20; i++) { await h.tick(1000); }
    const count = h.calls.length;
    await h.tick(1000);
    assert.equal(h.calls.length, count);
    assert.match(h.messages.at(-1), /may have reached/);
});

test('busy rejection is shown with no command retry', async () => {
    const h = harness([{ status: 429, body: { error: { message: 'The TV is handling another request.' } } }]);
    h.controller.play('luca');
    await h.flush();
    assert.match(h.messages.at(-1), /another request/);
    await h.tick(20000);
    assert.equal(h.calls.length, 1);
});

test('unknown delivery and missing status remain uncertain', async () => {
    for (const reply of [state('unknown'), { status: 404, body: { error: { code: 'request_not_found' } } }]) {
        const h = harness([accepted(), reply]);
        h.controller.play('luca');
        await h.flush();
        await h.tick(500);
        assert.match(h.messages.at(-1), /may have reached/);
    }
});

test('known command rejection shows sanitized error', async () => {
    const h = harness([accepted(), { status: 200, body: { request: {
        request_id: requestId, movie_key: 'luca', command_state: 'failed', error: { code: 'device_unauthorized' }
    } } }]);
    h.controller.play('luca');
    await h.flush();
    await h.tick(500);
    assert.match(h.messages.at(-1), /caregiver.*authorization/);
});

test('reload recovery performs only GET and blocks another launch until status completes', async () => {
    const storage = {};
    const first = harness([accepted()], storage);
    first.controller.play('luca');
    await first.flush();
    assert.equal(storage.pending.request_id, requestId);
    const reloaded = harness([state('command_sent')], storage);
    reloaded.controller.recover(storage.pending);
    reloaded.controller.play('moana');
    await reloaded.flush();
    assert.equal(reloaded.calls.length, 1);
    assert.equal(reloaded.calls[0].options.method, 'GET');
    assert.equal(storage.pending, undefined);
    assert.equal(reloaded.controller.isBusy(), false);
});

test('expired and malformed stored requests create no network calls', async () => {
    for (const record of [{ request_id: 'bad', accepted_at: 0 },
                          { request_id: requestId, accepted_at: -900001 },
                          { request_id: requestId, accepted_at: 100 }]) {
        const storage = { pending: record };
        const h = harness([], storage);
        h.controller.recover(record);
        await h.flush();
        assert.equal(h.calls.length, 0);
        assert.equal(storage.pending, undefined);
    }
});

test('storage denial does not interrupt launch or cause retries', async () => {
    const h = harness([accepted(), state('command_sent')], { denied: true });
    h.controller.play('luca');
    await h.flush();
    await h.tick(500);
    assert.equal(h.calls.length, 2);
    assert.match(h.messages.at(-1), /Request sent/);
});

test('unknown request stays available for read-only recovery', async () => {
    const storage = {};
    const h = harness([accepted(), state('unknown')], storage);
    h.controller.play('luca');
    await h.flush();
    await h.tick(500);
    assert.equal(storage.pending.request_id, requestId);
    assert.match(h.messages.at(-1), /may have reached/);
});

test('unexpected server failure is uncertain and never retried', async () => {
    const h = harness([{ status: 500, body: { error: { message: 'Internal Server Error' } } }]);
    h.controller.play('luca');
    await h.flush();
    assert.match(h.messages.at(-1), /may have reached/);
    assert.equal(h.calls.length, 1);
});

test('cooldown blocks taps until Retry-After without automatically launching', async () => {
    const h = harness([{ status: 429, body: { error: { retry_after_seconds: 3 } } }]);
    h.controller.play('luca'); await h.flush();
    await h.tick(2999); h.controller.play('moana');
    assert.equal(h.calls.length, 1); assert.equal(h.controller.isBusy(), true);
    await h.tick(1); assert.equal(h.controller.isBusy(), false); assert.equal(h.calls.length, 1);
});

test('uncertain delivery requires deliberate confirmation before a fresh request', async () => {
    const h = harness([new Error('offline'), accepted()]);
    h.controller.play('luca'); await h.flush();
    h.controller.play('luca'); assert.equal(h.calls.length, 1);
    assert.equal(h.controller.needsConfirmation(), true);
    h.controller.play('luca', 'Luca', true); await h.flush(); assert.equal(h.calls.length, 2);
});

test('hidden page pauses polling and resumes with a query only', async () => {
    const h = harness([accepted(), state('command_sent')]);
    h.controller.play('luca'); await h.flush(); h.controller.visibility(true);
    await h.tick(500); assert.equal(h.calls.length, 1);
    h.controller.visibility(false); await h.flush();
    assert.equal(h.calls.length, 2); assert.equal(h.calls[1].options.method, 'GET');
});

test('lost admission record survives reload without a POST', async () => {
    const storage = {};
    const first = harness([new Error('offline')], storage);
    first.controller.play('luca'); await first.flush();
    assert.equal(storage.pending.movie_key, 'luca'); assert.equal(storage.pending.idempotency_key, 'tablet-test-001');
    const next = harness([], storage); next.controller.recover(storage.pending); next.controller.check();
    assert.equal(next.calls.length, 0); assert.equal(next.controller.needsConfirmation(), true);
});

test('unexpected admission schemas never report delivery or follow server URLs', async () => {
    for (const body of [null, [], { request_id: requestId }, { ...accepted().body, movie_key: 'moana' },
                        { ...accepted().body, request_id: 'bad', status_url: 'https://evil.example/' }]) {
        const h = harness([{ status: 202, body }]); h.controller.play('luca'); await h.flush();
        assert.equal(h.calls.length, 1); assert.match(h.messages.at(-1), /may have reached/);
    }
});

test('preferences validate fields, bound and deduplicate lists, and preserve valid fields', () => {
    const scope = {}; vm.runInNewContext(source, scope);
    const clean = scope.MovieTablet.sanitizePreferences({ version: 1, favorite_keys: ['luca', 'luca', 'Bad Key', 5, 'moana'],
        recent_requests: Array.from({ length: 20 }, (_, i) => ({ movie_key: 'movie-' + i, command_sent_at: new Date(1700000000000 + i * 1000).toISOString() })),
        settings: { confirm_before_play: 'true' } });
    assert.deepEqual(Array.from(clean.favorite_keys), ['luca', 'moana']); assert.equal(clean.recent_requests.length, 12);
    assert.equal(clean.recent_requests[0].movie_key, 'movie-19'); assert.equal(clean.settings.confirm_before_play, false);
    assert.equal(scope.MovieTablet.sanitizePreferences({ version: 99 }).favorite_keys.length, 0);
    assert.equal(scope.MovieTablet.sanitizePreferences({ version: 1, favorite_keys: Array.from({ length: 250 }, (_, i) => 'key-' + i) }).favorite_keys.length, 200);
});

test('denied or corrupt preference storage falls back to memory with one notice', () => {
    const scope = {}; vm.runInNewContext(source, scope);
    for (const read of [() => '{broken', () => { throw new Error('denied'); }]) {
        let notices = 0;
        const preferences = scope.MovieTablet.createPreferences({ read, write() { throw new Error('quota'); }, notice() { notices++; } });
        preferences.toggle('luca'); preferences.confirm(true); preferences.delivered('luca', '2026-11-07T15:00:00Z');
        assert.equal(notices, 1); assert.equal(preferences.get().favorite_keys[0], 'luca');
        assert.equal(preferences.get().recent_requests.length, 1); preferences.reset(); assert.equal(preferences.get().favorite_keys.length, 0);
    }
});
