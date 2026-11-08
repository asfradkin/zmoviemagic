(function (global) {
    'use strict';

    var uncertain = 'The request may have reached the TV. Check the screen before trying again.';

    // Dependencies are injectable for fetch/timer tests; no server credentials enter the page.
    function createController(options) {
        var active = false;

        function begin(key, recoveredRequestId) {
            if (active) { return; }
            active = true;
            options.onBusy(true);
            var finished = false;
            var deadline = options.now() + 20000;
            var pollTimer;
            var timeoutTimer;

            function finish(message, clearPending) {
                if (finished) { return; }
                finished = true;
                options.clearTimeout(timeoutTimer);
                options.clearTimeout(pollTimer);
                if (clearPending && options.clearPending) {
                    try { options.clearPending(); } catch (error) { /* Storage is optional. */ }
                }
                options.onMessage(message);
                active = false;
                options.onBusy(false);
            }

            function readJSON(response) {
                return response.json().then(function (body) {
                    return { ok: response.ok, status: response.status, body: body };
                });
            }

            function poll(url) {
                if (finished || options.now() >= deadline) { finish(uncertain); return; }
                options.fetch(url, { method: 'GET', cache: 'no-store', credentials: 'same-origin' })
                    .then(readJSON)
                    .then(function (result) {
                        if (finished) { return; }
                        if (!result.ok || !result.body.request) { finish(uncertain); return; }
                        var request = result.body.request;
                        if (request.command_state === 'command_sent') {
                            finish('Launch command sent to Fire TV. Check the TV screen.', true);
                        } else if (request.command_state === 'failed') {
                            finish(request.error && request.error.message ? request.error.message : 'The launch command failed.', true);
                        } else if (request.command_state === 'unknown') {
                            finish(uncertain);
                        } else if (request.command_state === 'queued' || request.command_state === 'dispatching') {
                            pollTimer = options.setTimeout(function () { poll(url); }, 1000);
                        } else {
                            finish(uncertain);
                        }
                    }).catch(function () { finish(uncertain); });
            }

            timeoutTimer = options.setTimeout(function () { finish(uncertain); }, 20000);
            if (recoveredRequestId) {
                options.onMessage('Checking the previous movie request. No new launch was sent.');
                poll('/api/status?request_id=' + encodeURIComponent(recoveredRequestId));
                return;
            }
            options.onMessage('Sending movie request…');
            var idempotencyKey;
            try {
                idempotencyKey = options.makeKey();
            } catch (error) {
                finish('This browser could not prepare a request. Please ask a caregiver.');
                return;
            }
            options.fetch('/api/play', {
                method: 'POST', credentials: 'same-origin', cache: 'no-store',
                headers: { 'Content-Type': 'application/json', 'Idempotency-Key': idempotencyKey },
                body: JSON.stringify({ movie_key: key })
            }).then(readJSON).then(function (result) {
                if (finished) { return; }
                if (result.status !== 202) {
                    if ((result.status >= 400 && result.status < 500) || result.status === 503) {
                        finish(result.body.error && result.body.error.message ? result.body.error.message : 'The movie request was not accepted.');
                    } else {
                        finish(uncertain);
                    }
                    return;
                }
                // Construct a local URL from a validated ID, never follow arbitrary server URLs.
                var requestId = result.body.request_id;
                if (typeof requestId !== 'string' || !/^[a-f0-9-]{36}$/.test(requestId)) {
                    finish(uncertain);
                    return;
                }
                if (options.savePending) {
                    try { options.savePending({ request_id: requestId, accepted_at: options.now() }); }
                    catch (error) { /* Storage denial never causes another POST. */ }
                }
                options.onMessage('Request accepted. Waiting for command delivery…');
                pollTimer = options.setTimeout(function () {
                    poll('/api/status?request_id=' + encodeURIComponent(requestId));
                }, 500);
            }).catch(function () { finish(uncertain); });
        }

        function recover(record) {
            if (!record || typeof record.request_id !== 'string' || !/^[a-f0-9-]{36}$/.test(record.request_id)
                    || typeof record.accepted_at !== 'number' || !isFinite(record.accepted_at)
                    || record.accepted_at > options.now() || options.now() - record.accepted_at >= 900000) {
                if (record) {
                    if (options.clearPending) {
                        try { options.clearPending(); } catch (error) { /* Optional storage. */ }
                    }
                    options.onMessage(uncertain);
                }
                return;
            }
            begin(null, record.request_id);
        }

        return { play: function (key) { begin(key, null); }, recover: recover,
            isBusy: function () { return active; } };
    }

    global.MovieTablet = { createController: createController };

    if (!global.document) { return; }
    var status = global.document.getElementById('request-status');
    if (!status) { return; }
    if (!global.fetch || !global.Promise || !global.crypto || !global.crypto.getRandomValues) {
        status.textContent = 'This browser needs an update before it can request movies. Please ask a caregiver.';
        return;
    }
    var buttons = global.document.querySelectorAll('[data-movie-key]');
    var storageKey = 'zmoviemagic.pending-request.v2';
    var controller = createController({
        fetch: global.fetch.bind(global), now: Date.now,
        setTimeout: global.setTimeout.bind(global), clearTimeout: global.clearTimeout.bind(global),
        makeKey: function () {
            var words = new Uint32Array(4);
            global.crypto.getRandomValues(words);
            return 'tablet-' + Array.prototype.map.call(words, function (word) { return word.toString(16); }).join('-');
        },
        onMessage: function (message) { status.textContent = message; },
        savePending: function (record) { global.sessionStorage.setItem(storageKey, JSON.stringify(record)); },
        clearPending: function () { global.sessionStorage.removeItem(storageKey); },
        onBusy: function (busy) {
            for (var i = 0; i < buttons.length; i += 1) {
                buttons[i].disabled = busy || buttons[i].getAttribute('data-available') !== 'true';
            }
        }
    });
    for (var i = 0; i < buttons.length; i += 1) {
        buttons[i].disabled = buttons[i].getAttribute('data-available') !== 'true';
        buttons[i].addEventListener('click', function () { controller.play(this.getAttribute('data-movie-key')); });
    }
    try {
        var pending = global.sessionStorage.getItem(storageKey);
        if (pending) { controller.recover(JSON.parse(pending)); }
    } catch (error) {
        // Corrupt/denied storage cannot create a command or disable the catalog.
        try { global.sessionStorage.removeItem(storageKey); } catch (ignored) { /* Optional storage. */ }
    }
}(typeof window === 'undefined' ? globalThis : window));
