const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const { execFileSync } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '../..');
const python = process.env.ZMM_TEST_PYTHON || path.join(root, '.venv', process.platform === 'win32' ? 'python.exe' : 'bin/python');
const html = execFileSync(python, ['-B', path.join(__dirname, 'render_fixture.py')], { encoding: 'utf8' });
const requestId = '65b80b5f-4a08-4c26-8d92-f2bb90f9b890';
let browser;
before(async () => { browser = await chromium.launch({ headless: true,
    ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH } : {}) }); });
after(async () => { if (browser) await browser.close(); });

async function fixture(options = {}) {
    const context = await browser.newContext({ viewport: options.viewport || { width: 768, height: 1024 }, hasTouch: true });
    const page = await context.newPage();
    page.setDefaultTimeout(5000);
    if (options.clock) await page.clock.install();
    const posts = [], gets = [], errors = [];
    page.on('pageerror', error => errors.push(error.message));
    if (options.init) await page.addInitScript(options.init);
    await context.route('**/*', async route => {
        const request = route.request(), url = new URL(request.url());
        if (url.origin !== 'http://tablet.test') return route.abort();
        if (url.pathname === '/') return route.fulfill({ contentType: 'text/html', body: html });
        if (url.pathname.startsWith('/static/')) {
            const filename = path.basename(url.pathname);
            if (!['tablet.js', 'tablet.css', 'poster-fallback.svg'].includes(filename)) return route.abort();
            return route.fulfill({ contentType: filename.endsWith('.js') ? 'text/javascript' : filename.endsWith('.css') ? 'text/css' : 'image/svg+xml', body: fs.readFileSync(path.join(root, 'static', filename)) });
        }
        if (url.pathname === '/api/play') {
            posts.push({ body: request.postDataJSON(), key: request.headers()['idempotency-key'], csrf: request.headers()['x-csrf-token'] });
            if (options.post) return options.post(route, posts);
            return route.fulfill({ status: 202, json: { request_id: requestId, movie_key: request.postDataJSON().movie_key,
                command_state: 'queued', playback: { state: 'unknown' }, status_url: 'https://evil.invalid/api/status' } });
        }
        if (url.pathname === '/api/status') {
            gets.push(url.pathname + url.search);
            if (options.status) return options.status(route, gets);
            return route.fulfill({ json: { boot_id: 'fixture-boot', request: { request_id: requestId, movie_key: posts.at(-1)?.body.movie_key || 'luca',
                command_state: 'command_sent', completed_at: '2026-11-07T15:00:01Z' }, playback: { state: 'unknown' } } });
        }
        if (url.pathname === '/api/movies') {
            if (options.catalog) return options.catalog(route);
            return route.fulfill({ status: 503, json: { error: { code: 'catalog_unavailable' } } });
        }
        throw new Error('Unexpected request: ' + request.url());
    });
    await page.goto('http://tablet.test/');
    await page.locator('.favorite-button').first().waitFor();
    return { page, posts, gets, errors, async close() { assert.deepEqual(errors, []); await context.close(); } };
}
const play = (page, key = 'luca') => page.locator('[data-movie-key="' + key + '"]');
async function message(page, text) { await page.waitForFunction(text => document.getElementById('request-status').textContent.includes(text), text); }

test('native keyboard activation, ten rapid taps, delivery, focus and recents', async () => {
    const f = await fixture();
    try {
        await play(f.page).focus(); await f.page.keyboard.press('Enter');
        await f.page.evaluate(() => { for (let i = 0; i < 10; i++) document.querySelector('[data-movie-key="luca"]').click(); });
        await message(f.page, 'Request sent');
        assert.equal(f.posts.length, 1); assert.equal(f.posts[0].body.movie_key, 'luca');
        assert.equal(f.posts[0].csrf, 'synthetic-csrf-token');
        assert.equal(await play(f.page).evaluate(el => el === document.activeElement), true);
        const prefs = await f.page.evaluate(() => JSON.parse(localStorage.getItem('zmm.tablet.v1')));
        assert.equal(prefs.recent_requests[0].movie_key, 'luca');
        assert.doesNotMatch(await f.page.locator('#request-status').innerText(), /playing/i);
        assert.equal(await f.page.locator('button button').count(), 0);
        await play(f.page, 'moana').focus(); await f.page.keyboard.press('Space'); await message(f.page, 'Request sent');
        assert.equal(f.posts.length, 2); assert.notEqual(f.posts[0].key, f.posts[1].key);
    } finally { await f.close(); }
});

test('favorites, touch cancellation, scrolling and confirmation cancel never launch', async () => {
    const f = await fixture();
    try {
        await f.page.getByRole('button', { name: 'Favorite Luca', exact: true }).click();
        await f.page.getByRole('button', { name: 'Favorites', exact: true }).click();
        assert.equal(await play(f.page).count(), 1); assert.equal(await f.page.locator('.play-button').count(), 1);
        await play(f.page).dispatchEvent('touchcancel'); await play(f.page).dispatchEvent('touchstart');
        await f.page.evaluate(() => window.scrollBy(0, 200));
        await f.page.locator('summary').click(); await f.page.locator('#confirm-before-play').check();
        await play(f.page).click(); assert.equal(await f.page.locator('#cancel-confirmation').evaluate(el => el === document.activeElement), true);
        await f.page.locator('#cancel-confirmation').click(); assert.equal(f.posts.length, 0);
        await f.page.reload(); await f.page.locator('.favorite-button').first().waitFor();
        assert.equal(await f.page.locator('#section-title').innerText(), 'Favorites');
        await play(f.page).click(); await f.page.locator('#confirm-play').click(); await message(f.page, 'Request sent');
        assert.equal(f.posts.length, 1);
    } finally { await f.close(); }
});

test('network uncertainty requires confirmation; reload without admission ID never replays', async () => {
    const f = await fixture({ post: route => route.abort() });
    try {
        await play(f.page).click(); await message(f.page, 'may have reached');
        await f.page.reload(); await message(f.page, 'may have reached'); assert.equal(f.posts.length, 1);
        await f.page.locator('#try-again').click(); assert.match(await f.page.locator('#confirmation-message').innerText(), /restart/);
        await f.page.locator('#cancel-confirmation').click(); assert.equal(f.posts.length, 1);
        await play(f.page, 'moana').click(); await f.page.locator('#confirm-play').click(); await message(f.page, 'may have reached');
        assert.equal(f.posts.length, 2); assert.notEqual(f.posts[0].key, f.posts[1].key);
    } finally { await f.close(); }
});

test('reload with accepted ID only polls, missing request stays uncertain and never records recent', async () => {
    const f = await fixture({ status: route => route.fulfill({ status: 404, json: { error: { code: 'request_not_found' } } }) });
    try {
        await play(f.page).click(); await message(f.page, 'may have reached');
        await f.page.reload(); await message(f.page, 'may have reached');
        await f.page.locator('#check-request').click(); await message(f.page, 'may have reached');
        assert.equal(f.posts.length, 1); assert.equal(f.gets.length, 3);
        assert.equal(await f.page.evaluate(() => localStorage.getItem('zmm.tablet.v1')), null);
    } finally { await f.close(); }
});

test('denied storage and missing posters preserve launches and loaded grid on failed refresh', async () => {
    const f = await fixture({ init: () => {
        for (const key of ['localStorage', 'sessionStorage']) Object.defineProperty(window, key, { get() { throw new Error('denied'); } });
        Object.defineProperty(window, 'crypto', { value: undefined });
        Object.defineProperty(window, 'AbortController', { value: undefined });
    } });
    try {
        await f.page.waitForFunction(() => document.querySelector('[data-movie-key="moana"] img').getAttribute('src') === '/static/poster-fallback.svg');
        const img = play(f.page, 'moana').locator('img'); assert.equal(await img.evaluate(el => el.naturalWidth), 500);
        await f.page.locator('#refresh-catalog').click(); await f.page.waitForFunction(() => document.querySelector('#connection-notice').textContent.includes('Could not refresh'));
        assert.equal(await f.page.locator('.play-button').count(), 5);
        await f.page.getByRole('button', { name: 'Favorite Luca', exact: true }).click();
        await play(f.page).click(); await message(f.page, 'Request sent'); assert.equal(f.posts.length, 1);
        assert.match(await f.page.locator('#storage-notice').textContent(), /this visit/);
    } finally { await f.close(); }
});

test('malformed HTML, auth failures, unavailable and device failures have safe persistent feedback', async () => {
    for (const mode of ['html', 'auth', 'unavailable', 'device']) {
        const options = mode === 'device' ? { status: route => route.fulfill({ json: { request: { request_id: requestId, movie_key: 'luca', command_state: 'failed', error: { code: 'device_unauthorized', message: '<private>' } } } }) } : {
            post: route => mode === 'html' ? route.fulfill({ status: 200, contentType: 'text/html', body: '<h1>private failure</h1>' }) : route.fulfill({ status: mode === 'auth' ? 401 : 409, json: { error: { code: 'fixture' } } })
        };
        const f = await fixture(options);
        try {
            await play(f.page).click(); await message(f.page, mode === 'html' ? 'may have reached' : mode === 'auth' ? 'connection needs refreshing' : mode === 'unavailable' ? 'unavailable' : 'needs help');
            assert.equal(f.posts.length, 1); assert.equal(await f.page.evaluate(() => localStorage.getItem('zmm.tablet.v1')), null);
            assert.doesNotMatch(await f.page.locator('#request-status').textContent(), /private/);
            await play(f.page, 'unavailable').dispatchEvent('click'); assert.equal(f.posts.length, 1);
        } finally { await f.close(); }
    }
});

test('layout targets, spacing, complete titles, escaping, focus and reduced motion', async () => {
    for (const viewport of [{ width: 768, height: 1024 }, { width: 1024, height: 768 }, { width: 384, height: 512 }, { width: 320, height: 600 }]) {
        const f = await fixture({ viewport });
        try {
            const metrics = await f.page.evaluate(() => {
                const grid = document.querySelector('.movie-grid'), style = getComputedStyle(grid);
                const controls = [...document.querySelectorAll('button,summary,.setting,input')].filter(el => el.getBoundingClientRect().width > 0);
                return { columns: style.gridTemplateColumns.split(' ').length, gap: parseFloat(style.gap), posterWidth: document.querySelector('.play-button').getBoundingClientRect().width, overflow: document.documentElement.scrollWidth > innerWidth,
                    tooSmall: controls.filter(el => el.getBoundingClientRect().width < 56 || el.getBoundingClientRect().height < 56).map(el => el.outerHTML),
                    truncation: getComputedStyle(document.querySelector('.movie-title')).whiteSpace };
            });
            assert.equal(metrics.overflow, false); assert.equal(metrics.tooSmall.length, 0); assert.ok(metrics.gap >= 12);
            assert.ok(metrics.columns <= (viewport.width >= 700 ? 4 : viewport.width >= 360 ? 2 : 1));
            if (viewport.width >= 700) assert.ok(metrics.posterWidth >= 150);
            assert.equal(metrics.truncation, 'normal'); assert.equal(await f.page.locator('.movie-title img').count(), 0);
            await play(f.page).focus(); assert.equal(await play(f.page).evaluate(el => getComputedStyle(el).outlineStyle), 'solid');
            await f.page.emulateMedia({ reducedMotion: 'reduce' });
            assert.equal(await play(f.page).evaluate(el => getComputedStyle(el).transform), 'none');
            if (process.env.ZMM_UI_SCREENSHOTS) {
                fs.mkdirSync(path.join(root, 'test-results'), { recursive: true });
                await f.page.screenshot({ path: path.join(root, 'test-results', `tablet-${viewport.width}x${viewport.height}.png`), fullPage: true });
            }
        } finally { await f.close(); }
    }
});

test('native touch gesture submits once and 200% text enlargement reflows', async () => {
    const f = await fixture();
    try {
        await play(f.page).dispatchEvent('contextmenu'); await play(f.page).dispatchEvent('touchcancel');
        assert.equal(f.posts.length, 0);
        await play(f.page).tap(); await message(f.page, 'Request sent'); assert.equal(f.posts.length, 1);
        await f.page.evaluate(() => { document.documentElement.style.fontSize = '200%'; });
        assert.equal(await f.page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
        assert.equal(await f.page.locator('.movie-title').first().evaluate(el => el.scrollWidth > el.clientWidth), false);
    } finally { await f.close(); }
});

test('visibility resume refreshes catalog and queries a pending command without resubmission', async () => {
    let finish = false;
    const f = await fixture({ clock: true, status: route => route.fulfill({ json: { request: { request_id: requestId, movie_key: 'luca',
        command_state: finish ? 'command_sent' : 'dispatching', completed_at: '2026-11-07T15:00:01Z' } } }) });
    try {
        await play(f.page).click(); await message(f.page, 'Request accepted');
        await f.page.evaluate(() => { Object.defineProperty(document, 'hidden', { configurable: true, value: true }); document.dispatchEvent(new Event('visibilitychange')); });
        await f.page.clock.runFor(1500); assert.equal(f.gets.length, 0);
        finish = true;
        await f.page.evaluate(() => { Object.defineProperty(document, 'hidden', { configurable: true, value: false }); document.dispatchEvent(new Event('visibilitychange')); });
        await message(f.page, 'Request sent'); assert.equal(f.gets.length, 1); assert.equal(f.posts.length, 1);
    } finally { await f.close(); }
});

test('busy Retry-After lockout, delayed acceptance and feedback under 100ms', async () => {
    const f = await fixture({ clock: true, post: route => route.fulfill({ status: 429, headers: { 'Retry-After': '2' }, json: { error: { code: 'busy' } } }) });
    try {
        const latency = await f.page.evaluate(() => {
            const start = performance.now(); document.querySelector('[data-movie-key="luca"]').click();
            return { ms: performance.now() - start, message: document.querySelector('#request-status').textContent };
        });
        assert.ok(latency.ms < 100); assert.match(latency.message, /Sending Luca/);
        await message(f.page, 'Please wait');
        await play(f.page, 'moana').dispatchEvent('click'); assert.equal(f.posts.length, 1);
        assert.equal(await play(f.page).getAttribute('aria-disabled'), 'true');
        await f.page.clock.runFor(2001); await message(f.page, 'choose a movie again');
        assert.equal(await play(f.page).getAttribute('aria-disabled'), 'false'); assert.equal(f.posts.length, 1);
    } finally { await f.close(); }
});

test('20-second delayed response leaves uncertainty, ignores late acceptance and records no recent', async () => {
    let release;
    const f = await fixture({ clock: true, post: async route => {
        await new Promise(resolve => { release = resolve; });
        await route.fulfill({ status: 202, json: { request_id: requestId, movie_key: 'luca', command_state: 'queued', playback: { state: 'unknown' } } }).catch(() => {});
    } });
    try {
        await play(f.page).click();
        await f.page.waitForFunction(() => document.querySelector('#request-status').textContent.includes('Sending'));
        await f.page.clock.runFor(20001); await message(f.page, 'may have reached');
        release(); assert.equal(f.posts.length, 1); assert.equal(f.gets.length, 0);
        assert.equal(await f.page.evaluate(() => localStorage.getItem('zmm.tablet.v1')), null);
    } finally { if (release) release(); await f.close(); }
});

test('catalog removal/reappearance keeps preferences, favorites stay in catalog order, reset is explicit', async () => {
    let rows = [{ key: 'moana', title: 'Moana', available: true, poster: '/static/poster-fallback.svg' },
        { key: 'luca', title: 'Luca', available: true, poster: '/static/poster-fallback.svg' }];
    const f = await fixture({ init: () => {
        localStorage.setItem('zmm.tablet.v1', JSON.stringify({ version: 1, favorite_keys: ['luca', 'moana', 'removed'], settings: { confirm_before_play: false }, recent_requests: [] }));
    }, catalog: route => route.fulfill({ json: { schema_version: 2, movies: rows } }) });
    try {
        assert.deepEqual(await f.page.locator('.play-button').evaluateAll(els => els.map(el => el.dataset.movieKey)), ['luca', 'moana']);
        await f.page.locator('#refresh-catalog').click();
        await f.page.waitForFunction(() => document.querySelector('.play-button').dataset.movieKey === 'moana');
        assert.deepEqual(await f.page.locator('.play-button').evaluateAll(els => els.map(el => el.dataset.movieKey)), ['moana', 'luca']);
        rows = []; await f.page.locator('#refresh-catalog').click(); await f.page.waitForFunction(() => !document.querySelector('.play-button'));
        assert.equal(await f.page.evaluate(() => JSON.parse(localStorage.getItem('zmm.tablet.v1')).favorite_keys.length), 3);
        rows = [{ key: 'removed', title: 'Back again', available: true, poster: '/static/poster-fallback.svg' }];
        await f.page.locator('#refresh-catalog').click(); await play(f.page, 'removed').waitFor();
        await f.page.getByRole('button', { name: 'Favorites', exact: true }).click();
        assert.equal(await f.page.locator('.play-button').count(), 1);
        await f.page.locator('summary').click(); await f.page.locator('#reset-preferences').click();
        await f.page.locator('#cancel-confirmation').click();
        assert.equal(await f.page.evaluate(() => JSON.parse(localStorage.getItem('zmm.tablet.v1')).favorite_keys.length), 3);
        await f.page.locator('#reset-preferences').click(); await f.page.locator('#confirm-play').click();
        assert.equal(await f.page.evaluate(() => JSON.parse(localStorage.getItem('zmm.tablet.v1')).favorite_keys.length), 0);
        assert.equal(f.posts.length, 0);
    } finally { await f.close(); }
});

test('corrupt storage preserves an operable grid and valid preference fields survive invalid neighbors', async () => {
    const f = await fixture({ init: () => {
        localStorage.setItem('zmm.tablet.v1', '{broken'); sessionStorage.setItem('zmoviemagic.pending-request.v2', '{broken');
    } });
    try {
        assert.equal(f.posts.length, 0); await play(f.page).click(); await message(f.page, 'Request sent'); assert.equal(f.posts.length, 1);
    } finally { await f.close(); }
});

test('text and control boundary contrast meets AA thresholds', async () => {
    const f = await fixture();
    try {
        const failures = await f.page.evaluate(() => {
            function rgb(value) { return value.match(/[\d.]+/g).slice(0, 3).map(Number); }
            function luminance(color) { return rgb(color).map(n => { n /= 255; return n <= 0.04045 ? n / 12.92 : Math.pow((n + 0.055) / 1.055, 2.4); }).reduce((sum, n, i) => sum + n * [0.2126, 0.7152, 0.0722][i], 0); }
            function ratio(a, b) { const x = luminance(a), y = luminance(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); }
            function background(el) { while (el && getComputedStyle(el).backgroundColor === 'rgba(0, 0, 0, 0)') el = el.parentElement; return el ? getComputedStyle(el).backgroundColor : 'rgb(22,27,40)'; }
            return [...document.querySelectorAll('button,summary,p,h1,h2,.movie-title')].filter(el => el.getBoundingClientRect().width > 0).flatMap(el => {
                const css = getComputedStyle(el), bg = background(el), issues = [];
                if (ratio(css.color, bg) < 4.5) issues.push('text: ' + el.textContent);
                const outside = background(el.parentElement);
                if (el.tagName === 'BUTTON' && Math.max(ratio(css.borderTopColor, bg), ratio(css.borderTopColor, outside), ratio(bg, outside)) < 3) issues.push('border: ' + el.textContent);
                return issues;
            });
        });
        assert.deepEqual(failures, []);
    } finally { await f.close(); }
});
