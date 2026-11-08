(function (global) {
    'use strict';
    var uncertain = 'The request may have reached the TV. Check the screen before trying again.';
    var requestPattern = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/;
    function validKey(key) { return typeof key === 'string' && key.length <= 80 && /^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(key); }
    function sanitizePreferences(raw) {
        var result = { version: 1, favorite_keys: [], recent_requests: [], settings: { confirm_before_play: false } };
        if (!raw || raw.version !== 1) { return result; }
        if (Array.isArray(raw.favorite_keys)) {
            raw.favorite_keys.forEach(function (key) {
                if (validKey(key) && result.favorite_keys.indexOf(key) < 0 && result.favorite_keys.length < 200) { result.favorite_keys.push(key); }
            });
        }
        if (Array.isArray(raw.recent_requests)) {
            raw.recent_requests.filter(function (entry) {
                return entry && validKey(entry.movie_key) && typeof entry.command_sent_at === 'string' &&
                    /^\d{4}-\d{2}-\d{2}T/.test(entry.command_sent_at) && isFinite(Date.parse(entry.command_sent_at));
            }).sort(function (a, b) { return Date.parse(b.command_sent_at) - Date.parse(a.command_sent_at); }).forEach(function (entry) {
                if (result.recent_requests.length < 12 && !result.recent_requests.some(function (old) { return old.movie_key === entry.movie_key; })) {
                    result.recent_requests.push({ movie_key: entry.movie_key, command_sent_at: entry.command_sent_at });
                }
            });
        }
        result.settings.confirm_before_play = !!(raw.settings && raw.settings.confirm_before_play === true);
        return result;
    }
    function createPreferences(options) {
        var value, warned = false;
        function notice() { if (!warned) { warned = true; options.notice('Some preferences could not be saved or read. Changes will work for this visit.'); } }
        try { value = sanitizePreferences(JSON.parse(options.read() || 'null')); } catch (error) { value = sanitizePreferences(null); notice(); }
        function save() { try { options.write(JSON.stringify(value)); } catch (error) { notice(); } }
        return {
            get: function () { return JSON.parse(JSON.stringify(value)); },
            toggle: function (key) {
                if (!validKey(key)) { return; }
                var index = value.favorite_keys.indexOf(key);
                if (index >= 0) { value.favorite_keys.splice(index, 1); }
                else if (value.favorite_keys.length < 200) { value.favorite_keys.push(key); }
                save();
            },
            delivered: function (key, timestamp) {
                if (!validKey(key) || typeof timestamp !== 'string' || !isFinite(Date.parse(timestamp))) { return; }
                value.recent_requests = value.recent_requests.filter(function (entry) { return entry.movie_key !== key; });
                value.recent_requests.push({ movie_key: key, command_sent_at: timestamp });
                value = sanitizePreferences(value); save();
            },
            confirm: function (enabled) { value.settings.confirm_before_play = enabled === true; save(); },
            reset: function () { value = sanitizePreferences(null); save(); }
        };
    }
    // Recovery only queries status. A reload, timeout or network error never repeats POST.
    function createController(options) {
        var active = false, pending = null, needsConfirmation = false, current = null, hidden = false, run = null;
        function emit(state) { if (options.onState) { options.onState(state, pending); } }
        function remember() { if (options.savePending) { try { options.savePending(pending); } catch (error) { /* Optional storage. */ } } }
        function begin(key, title, recovered) {
            if (active) { return; }
            active = true; options.onBusy(true);
            var finished = false, deadline = options.now() + 20000, pollTimer, timeoutTimer, abort, polling = false;
            function finish(message, state, clearPending) {
                if (finished) { return; }
                finished = true; options.clearTimeout(timeoutTimer); options.clearTimeout(pollTimer);
                if (abort) { abort.abort(); }
                if (clearPending) {
                    pending = null;
                    if (options.clearPending) { try { options.clearPending(); } catch (error) { /* Optional storage. */ } }
                }
                needsConfirmation = state === 'unknown'; options.onMessage(message); emit(state);
                active = false; options.onBusy(false); run = null;
            }
            function readJSON(response) {
                return response.json().then(function (body) {
                    if (!body || typeof body !== 'object' || Array.isArray(body)) { throw new Error('Invalid response'); }
                    return { ok: response.ok, status: response.status, body: body, retryAfter: response.headers && response.headers.get('Retry-After') };
                });
            }
            function poll() {
                if (finished || polling) { return; }
                if (options.now() >= deadline) { finish(uncertain, 'unknown'); return; }
                if (hidden) { return; }
                options.clearTimeout(pollTimer);
                var requestedId = pending && pending.request_id;
                if (!requestedId) { return; }
                polling = true;
                var fetchOptions = { method: 'GET', cache: 'no-store', credentials: 'same-origin' };
                if (abort) { fetchOptions.signal = abort.signal; }
                options.fetch('/api/status?request_id=' + encodeURIComponent(requestedId), fetchOptions).then(readJSON).then(function (result) {
                    polling = false;
                    if (finished) { return; }
                    if (!result.ok || !result.body.request) { finish(uncertain, 'unknown'); return; }
                    var request = result.body.request;
                    if (request.request_id !== requestedId || (pending.movie_key && request.movie_key !== pending.movie_key)) { finish(uncertain, 'unknown'); return; }
                    if (request.command_state === 'command_sent') {
                        if (options.onDelivered && pending.movie_key) { options.onDelivered(pending.movie_key, request.completed_at); }
                        finish('Request sent to Fire TV. Check the screen.', 'command_sent', true);
                    } else if (request.command_state === 'failed') {
                        finish(request.error && request.error.code === 'device_unauthorized' ?
                            'Fire TV needs help connecting. Ask a caregiver to check its ADB authorization.' : 'The launch command failed. Ask a caregiver to check Fire TV.', 'failed', true);
                    } else if (request.command_state === 'queued' || request.command_state === 'dispatching') {
                        emit('queued'); pollTimer = options.setTimeout(poll, 1000);
                    } else { finish(uncertain, 'unknown'); }
                }).catch(function () { polling = false; finish(uncertain, 'unknown'); });
            }
            run = { poll: poll };
            if (options.makeAbortController) { abort = options.makeAbortController(); }
            timeoutTimer = options.setTimeout(function () { finish(uncertain, 'unknown'); }, 20000);
            if (recovered) { options.onMessage('Checking the previous movie request. No new launch was sent.'); emit('queued'); poll(); return; }
            options.onMessage('Sending ' + (title || 'movie request') + ' to Fire TV…'); emit('submitting');
            var idempotencyKey;
            try { idempotencyKey = options.makeKey(); } catch (error) { finish('This browser could not prepare a request. Please ask a caregiver.', 'failed', true); return; }
            current = { movie_key: key, title: title || key };
            pending = { movie_key: key, title: title || key, idempotency_key: idempotencyKey, accepted_at: options.now() }; remember();
            var postOptions = { method: 'POST', credentials: 'same-origin', cache: 'no-store',
                headers: { 'Content-Type': 'application/json', 'Idempotency-Key': idempotencyKey }, body: JSON.stringify({ movie_key: key }) };
            if (abort) { postOptions.signal = abort.signal; }
            options.fetch('/api/play', postOptions).then(readJSON).then(function (result) {
                if (finished) { return; }
                if (result.status === 429) {
                    var seconds = Number(result.retryAfter || (result.body.error && result.body.error.retry_after_seconds) || 1);
                    seconds = isFinite(seconds) ? Math.max(1, Math.min(900, seconds)) : 1;
                    options.clearTimeout(timeoutTimer); options.onMessage('Please wait. The TV is handling another request.'); emit('cooldown');
                    timeoutTimer = options.setTimeout(function () { finish('You can choose a movie again.', 'idle', true); }, seconds * 1000); return;
                }
                if (result.status !== 202) {
                    if (result.status === 404 || result.status === 409) {
                        finish('This movie is unavailable. Refresh movies to check the catalog.', 'failed', true);
                        if (options.onUnavailable) { options.onUnavailable(); }
                    } else if (result.status === 401 || result.status === 403) {
                        finish('Your connection needs refreshing. Use Refresh movies or ask a caregiver. No automatic retry will be sent.', 'failed', true);
                    } else if ((result.status >= 400 && result.status < 500) || result.status === 503) {
                        finish('The movie request was not accepted. Check the connection and try again.', 'failed', true);
                    } else { finish(uncertain, 'unknown'); }
                    return;
                }
                var requestId = result.body.request_id;
                // Build the local status URL from a validated ID; never follow server URLs.
                if (typeof requestId !== 'string' || !requestPattern.test(requestId) || result.body.movie_key !== key ||
                        result.body.command_state !== 'queued' || !result.body.playback || result.body.playback.state !== 'unknown') { finish(uncertain, 'unknown'); return; }
                pending.request_id = requestId; remember();
                options.onMessage('Request accepted. Waiting for command delivery…'); emit('queued'); pollTimer = options.setTimeout(poll, 500);
            }).catch(function () { finish(uncertain, 'unknown'); });
        }
        function recover(record) {
            if (active) { return; }
            if (!record || typeof record.accepted_at !== 'number' || !isFinite(record.accepted_at) || record.accepted_at > options.now() ||
                    options.now() - record.accepted_at >= 900000 || (record.request_id && (typeof record.request_id !== 'string' || !requestPattern.test(record.request_id))) ||
                    (record.movie_key && !validKey(record.movie_key))) {
                if (record) {
                    needsConfirmation = true;
                    if (options.clearPending) { try { options.clearPending(); } catch (error) { /* Optional storage. */ } }
                    options.onMessage(uncertain); emit('unknown');
                }
                return;
            }
            pending = record; current = record.movie_key ? { movie_key: record.movie_key, title: record.title || record.movie_key } : null;
            if (record.request_id) { begin(null, null, true); }
            else { needsConfirmation = true; options.onMessage(uncertain); emit('unknown'); }
        }
        return {
            play: function (key, title, confirmed) { if (validKey(key) && !active && (!needsConfirmation || confirmed)) { begin(key, title, false); } },
            recover: recover, isBusy: function () { return active; }, needsConfirmation: function () { return needsConfirmation; },
            current: function () { return current; }, check: function () { if (!active && pending) { recover(pending); } },
            visibility: function (isHidden) { hidden = isHidden; if (!hidden && run) { run.poll(); } }
        };
    }
    function sanitizeCatalog(rows) {
        if (!Array.isArray(rows) || rows.length > 1000) { throw new Error('Invalid catalog'); }
        var seen = Object.create(null);
        return rows.map(function (movie) {
            if (!movie || !validKey(movie.key) || seen[movie.key] || typeof movie.title !== 'string' || !movie.title.trim() || typeof movie.available !== 'boolean') { throw new Error('Invalid movie'); }
            seen[movie.key] = true;
            var poster = '/static/poster-fallback.svg';
            if (typeof movie.poster === 'string' && !/[\s\\]/.test(movie.poster)) {
                if (/^\/static\//.test(movie.poster) && movie.poster.indexOf('..') < 0 && movie.poster.indexOf('%') < 0) { poster = movie.poster; }
                else if (/^https:\/\//.test(movie.poster)) {
                    var link = global.document.createElement('a'); link.href = movie.poster;
                    if (link.hostname && !link.username && !link.password) { poster = movie.poster; }
                }
            }
            return { key: movie.key, title: movie.title, available: movie.available, poster: poster };
        });
    }
    function initialize() {
        var doc = global.document, status = doc.getElementById('request-status');
        if (!status) { return; }
        if (!global.fetch || !global.Promise) { status.textContent = 'This browser needs an update. Please ask a caregiver.'; return; }
        var grid = doc.getElementById('movie-grid'), section = 'all', selected = null, busy = false, confirmation = null, refreshActive = false;
        var movies = [], sequence = 0;
        var prefs = createPreferences({
            read: function () { return global.localStorage.getItem('zmm.tablet.v1'); },
            write: function (value) { global.localStorage.setItem('zmm.tablet.v1', value); },
            notice: function (message) { doc.getElementById('storage-notice').textContent = message; }
        });
        function el(tag, text, className) {
            var element = doc.createElement(tag); if (text) { element.textContent = text; } if (className) { element.className = className; } return element;
        }
        function find(key) { return movies.filter(function (movie) { return movie.key === key; })[0]; }
        function showSelection(movie) {
            selected = movie;
            doc.getElementById('selection').textContent = 'Selected: ' + movie.title;
            var cards = grid.querySelectorAll('.movie-card');
            for (var i = 0; i < cards.length; i += 1) {
                cards[i].className = 'movie-card' + (cards[i].querySelector('[data-movie-key]').getAttribute('data-movie-key') === movie.key ? ' selected' : '');
            }
        }
        function updateBusy(value) {
            busy = value;
            var buttons = grid.querySelectorAll('[data-movie-key]');
            for (var i = 0; i < buttons.length; i += 1) { buttons[i].setAttribute('aria-disabled', String(busy || buttons[i].getAttribute('data-available') !== 'true')); }
        }
        function closeConfirmation() {
            var previous = confirmation; confirmation = null; doc.getElementById('confirmation').hidden = true;
            if (previous && previous.focus && doc.documentElement.contains(previous.focus)) { previous.focus.focus(); }
        }
        function ask(movie, focus, reset) {
            confirmation = { movie: movie, focus: focus, reset: reset };
            doc.getElementById('confirmation-title').textContent = reset ? 'Reset preferences for this browser?' : 'Play ' + movie.title + ' on Fire TV?';
            doc.getElementById('confirmation-message').textContent = reset ? 'This removes local favorites, recent requests and the confirmation setting.' :
                (controller.needsConfirmation() ? 'The earlier request may have reached the TV. A new request can restart the movie.' : 'Choose Play to send this request.');
            doc.getElementById('confirm-play').textContent = reset ? 'Reset preferences' : 'Play';
            doc.getElementById('confirmation').hidden = false; doc.getElementById('cancel-confirmation').focus();
        }
        function choose(movie, button) {
            if (busy || !movie.available) { return; }
            showSelection(movie);
            if (prefs.get().settings.confirm_before_play || controller.needsConfirmation()) { ask(movie, button, false); }
            else { controller.play(movie.key, movie.title); }
        }
        function render() {
            var preferences = prefs.get(), favorites = preferences.favorite_keys;
            var favoriteMovies = movies.filter(function (movie) { return favorites.indexOf(movie.key) >= 0; });
            var recentMovies = preferences.recent_requests.map(function (entry) { return find(entry.movie_key); }).filter(Boolean);
            if ((section === 'favorites' && !favoriteMovies.length) || (section === 'recent' && !recentMovies.length)) { section = 'all'; }
            var visible = section === 'favorites' ? favoriteMovies : section === 'recent' ? recentMovies : movies;
            var nav = doc.querySelectorAll('[data-section]');
            for (var n = 0; n < nav.length; n += 1) {
                var name = nav[n].getAttribute('data-section');
                nav[n].hidden = (name === 'favorites' && !favoriteMovies.length) || (name === 'recent' && !recentMovies.length); nav[n].setAttribute('aria-pressed', String(name === section));
            }
            doc.getElementById('section-title').textContent = section === 'favorites' ? 'Favorites' : section === 'recent' ? 'Recent requests' : 'All movies';
            var focused = doc.activeElement, focusKey = focused && focused.getAttribute('data-focus-key');
            while (grid.firstChild) { grid.removeChild(grid.firstChild); }
            visible.forEach(function (movie) {
                var card = el('article', null, 'movie-card' + (selected && selected.key === movie.key ? ' selected' : ''));
                var play = el('button', null, 'play-button'); play.type = 'button';
                play.setAttribute('data-movie-key', movie.key); play.setAttribute('data-available', String(movie.available)); play.setAttribute('data-focus-key', 'play-' + movie.key);
                play.setAttribute('aria-label', 'Play ' + movie.title + ' on Fire TV' + (movie.available ? '' : ' — unavailable')); play.setAttribute('aria-disabled', String(busy || !movie.available));
                var image = el('img'); image.alt = ''; image.width = 500; image.height = 750;
                image.onerror = function () { this.onerror = null; this.src = '/static/poster-fallback.svg'; }; image.src = movie.poster;
                play.appendChild(image); play.appendChild(el('span', movie.title, 'movie-title'));
                if (!movie.available) { play.appendChild(el('span', 'Unavailable', 'movie-title')); }
                play.addEventListener('click', function () { choose(movie, play); });
                var favorite = el('button', favorites.indexOf(movie.key) >= 0 ? '★ Favorite' : '☆ Favorite', 'favorite-button'); favorite.type = 'button';
                favorite.setAttribute('data-focus-key', 'favorite-' + movie.key); favorite.setAttribute('aria-label', 'Favorite ' + movie.title); favorite.setAttribute('aria-pressed', String(favorites.indexOf(movie.key) >= 0));
                favorite.addEventListener('click', function () { prefs.toggle(movie.key); render(); });
                card.appendChild(play); card.appendChild(favorite); grid.appendChild(card);
            });
            if (focusKey) {
                var candidates = grid.querySelectorAll('[data-focus-key]'), restored = false;
                for (var f = 0; f < candidates.length; f += 1) { if (candidates[f].getAttribute('data-focus-key') === focusKey) { candidates[f].focus(); restored = true; break; } }
                if (!restored) { doc.getElementById('section-title').setAttribute('tabindex', '-1'); doc.getElementById('section-title').focus(); }
            }
            doc.getElementById('confirm-before-play').checked = preferences.settings.confirm_before_play;
        }
        function refreshCatalog() {
            if (refreshActive) { return; }
            refreshActive = true;
            var done = false, timer, abort = global.AbortController ? new global.AbortController() : null;
            function complete(message) {
                if (done) { return; } done = true; refreshActive = false; global.clearTimeout(timer); doc.getElementById('connection-notice').textContent = message; if (abort) { abort.abort(); }
            }
            timer = global.setTimeout(function () { complete('Could not refresh movies. Your loaded movies and preferences are still here.'); }, 10000);
            var request = { method: 'GET', credentials: 'same-origin', cache: 'no-store' }; if (abort) { request.signal = abort.signal; }
            global.fetch('/api/movies', request).then(function (response) {
                if (!response.ok) { throw new Error('Catalog unavailable'); } return response.json();
            }).then(function (body) {
                if (done) { return; } if (!body || body.schema_version !== 2) { throw new Error('Invalid catalog'); }
                movies = sanitizeCatalog(body.movies); doc.getElementById('catalog-notice').textContent = movies.length ? '' : 'No movies are available. Try Refresh movies or ask a caregiver.';
                render(); complete('Movies refreshed.');
            }).catch(function () { complete('Could not refresh movies. Your loaded movies and preferences are still here.'); });
        }
        var controller = createController({
            fetch: global.fetch.bind(global), now: Date.now, setTimeout: global.setTimeout.bind(global), clearTimeout: global.clearTimeout.bind(global),
            makeAbortController: global.AbortController ? function () { return new global.AbortController(); } : null,
            makeKey: function () {
                if (global.crypto && global.crypto.getRandomValues) {
                    var words = new Uint32Array(4); global.crypto.getRandomValues(words); return 'tablet-' + Array.prototype.map.call(words, function (word) { return word.toString(16); }).join('-');
                }
                // LAN Safari may not expose Web Crypto. Uniqueness, not secrecy, is required.
                sequence += 1; return 'tablet-' + Date.now().toString(36) + '-' + sequence + '-' + Math.random().toString(36).slice(2) + Math.random().toString(36).slice(2);
            },
            onMessage: function (message) { if (status.textContent !== message) { status.textContent = message; } }, onBusy: updateBusy,
            onState: function (state, pending) {
                doc.getElementById('check-request').hidden = state !== 'unknown' || !pending || !pending.request_id;
                doc.getElementById('try-again').hidden = state !== 'unknown' || !controller.current();
            },
            onDelivered: function (key, timestamp) { prefs.delivered(key, timestamp); render(); }, onUnavailable: refreshCatalog,
            savePending: function (record) { global.sessionStorage.setItem('zmoviemagic.pending-request.v2', JSON.stringify(record)); },
            clearPending: function () { global.sessionStorage.removeItem('zmoviemagic.pending-request.v2'); }
        });
        try { movies = sanitizeCatalog(JSON.parse(doc.getElementById('initial-catalog').textContent)); }
        catch (error) { status.textContent = 'The movie catalog could not be read. Use Refresh movies or ask a caregiver.'; }
        var initial = prefs.get();
        if (movies.some(function (movie) { return initial.favorite_keys.indexOf(movie.key) >= 0; })) { section = 'favorites'; }
        else if (initial.recent_requests.some(function (entry) { return !!find(entry.movie_key); })) { section = 'recent'; }
        render();
        var navigation = doc.querySelectorAll('[data-section]');
        for (var i = 0; i < navigation.length; i += 1) { navigation[i].addEventListener('click', function () { section = this.getAttribute('data-section'); render(); }); }
        doc.getElementById('cancel-confirmation').addEventListener('click', closeConfirmation);
        doc.getElementById('confirm-play').addEventListener('click', function () {
            if (!confirmation) { return; } var choice = confirmation; closeConfirmation();
            if (choice.reset) { prefs.reset(); render(); } else if (!busy) { controller.play(choice.movie.key, choice.movie.title, true); }
        });
        doc.getElementById('confirm-before-play').addEventListener('change', function () { prefs.confirm(this.checked); });
        doc.getElementById('reset-preferences').addEventListener('click', function () { ask(null, this, true); });
        doc.getElementById('refresh-catalog').addEventListener('click', refreshCatalog);
        doc.getElementById('check-request').addEventListener('click', controller.check);
        doc.getElementById('try-again').addEventListener('click', function () {
            var previous = controller.current(), movie = previous && find(previous.movie_key);
            if (movie && movie.available) { showSelection(movie); ask(movie, this, false); } else { status.textContent = 'This movie is unavailable. Refresh movies to check the catalog.'; }
        });
        function resume() { controller.visibility(doc.hidden === true); if (!doc.hidden) { refreshCatalog(); if (!controller.isBusy()) { controller.check(); } } }
        doc.addEventListener('visibilitychange', resume);
        global.addEventListener('pageshow', function (event) { if (event.persisted) { resume(); } });
        global.addEventListener('online', function () { doc.getElementById('connection-notice').textContent = 'Connection restored. You can refresh movies or check the previous request.'; });
        global.addEventListener('offline', function () { doc.getElementById('connection-notice').textContent = 'Connection lost. A request may still reach Fire TV. Check the screen.'; });
        doc.addEventListener('keydown', function (event) { if (event.key === 'Escape' && confirmation) { closeConfirmation(); } });
        try {
            var record = global.sessionStorage.getItem('zmoviemagic.pending-request.v2');
            if (record) { var saved = JSON.parse(record); if (saved.movie_key && find(saved.movie_key)) { showSelection(find(saved.movie_key)); } controller.recover(saved); }
        } catch (error) { /* Denied or corrupt session storage never sends a command. */ }
    }
    global.MovieTablet = { createController: createController, createPreferences: createPreferences, sanitizePreferences: sanitizePreferences, sanitizeCatalog: sanitizeCatalog };
    if (global.document) { initialize(); }
}(typeof window === 'undefined' ? globalThis : window));
