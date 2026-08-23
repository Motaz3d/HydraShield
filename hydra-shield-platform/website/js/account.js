/* HydraShield — Account (account.html).
 *
 * Cookie-session auth against the Stage 6 API:
 *   POST /api/v2/auth/register · POST /api/v2/auth/login · POST /api/v2/auth/logout
 *   GET  /api/v2/account
 *   GET/POST /api/v2/account/locations · DELETE /api/v2/account/locations/<id>
 *   GET  /api/v2/account/history
 *   GET/POST /api/v2/account/alerts · DELETE /api/v2/account/alerts/<id>
 *   POST /api/v2/alerts/phone · POST /api/v2/alerts/phone/verify
 *   DELETE /api/v2/alerts/phone
 *   GET/PATCH /api/v2/alerts/preferences
 *   GET/POST /api/v2/alerts/rules · DELETE /api/v2/alerts/rules/<id>
 *   GET  /api/v2/alerts/history · POST /api/v2/alerts/unsubscribe
 *
 * Any 401 shows the login/register view; 403 tier responses show their
 * upgrade message. Nothing is rendered from assumed state — every list is
 * fetched.
 */
(function () {
    'use strict';

    var esc = HS.esc, chip = HS.chip, fetchJSON = HS.fetchJSON, API = HS.API;

    function el(id) { return document.getElementById(id); }

    function status(kind, msg) {
        el('statusArea').innerHTML = msg
            ? '<div class="notice notice-' + kind + '">' + esc(msg) + '</div>'
            : '';
    }

    function showView(loggedIn) {
        el('authView').classList.toggle('hidden', loggedIn);
        el('accountView').classList.toggle('hidden', !loggedIn);
    }

    function postJSON(url, payload) {
        return fetchJSON(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
    }

    // ------------------------------------------------------------------
    // Session bootstrap
    // ------------------------------------------------------------------

    // After the email-verification link redirects back here
    // (/account.html?verified=1 / ?verify_error=1), surface the outcome,
    // then strip the parameter from the URL.
    function notifyVerifyResult() {
        var params = new URLSearchParams(location.search);
        if (params.get('verified') === '1') {
            status('info', 'Your email address is verified — welcome to HydraShield.');
        } else if (params.get('verify_error') === '1') {
            status('error', 'This verification link is invalid or has expired.');
        } else {
            return;
        }
        history.replaceState(null, '', location.pathname);
    }

    function boot() {
        fetchJSON(API + '/v2/account').then(function (res) {
            if (res.status === 401) {
                showView(false);
                notifyVerifyResult();
                return;
            }
            if (!res.ok) {
                showView(false);
                status('error', res.body.error || 'Account service unavailable.');
                return;
            }
            status('', '');
            showView(true);
            notifyVerifyResult();
            renderProfile(res.body);
            loadSubscription();
            loadApiKeys();
            loadLocations();
            loadAlerts();
            loadHistory();
            loadHazards();
            loadSmsPrefs();
            loadRules();
            loadAlertHistory();
        }).catch(function () {
            showView(false);
            status('error', 'The account service could not be reached.');
        });
    }

    // ------------------------------------------------------------------
    // Auth forms
    // ------------------------------------------------------------------

    function wireAuth() {
        el('loginForm').addEventListener('submit', function (e) {
            e.preventDefault();
            status('info', 'Signing in…');
            postJSON(API + '/v2/auth/login', {
                email: el('loginEmail').value,
                password: el('loginPassword').value
            }).then(function (res) {
                if (!res.ok) {
                    status(res.status === 403 ? 'warn' : 'error',
                        res.body.error || 'Sign-in failed.');
                    return;
                }
                status('', '');
                boot();
            }).catch(function () { status('error', 'Sign-in request failed.'); });
        });

        el('registerForm').addEventListener('submit', function (e) {
            e.preventDefault();
            if (!el('regConsent').checked) {
                status('error', 'Please tick the consent box — it is required to create an account.');
                return;
            }
            if (window.HS && HS.track) HS.track('account_started');
            status('info', 'Registering…');
            postJSON(API + '/v2/auth/register', {
                email: el('regEmail').value,
                password: el('regPassword').value,
                display_name: el('regName').value || undefined,
                consent: el('regConsent').checked
            }).then(function (res) {
                if (!res.ok) {
                    status('error', res.body.error || 'Registration failed.');
                    return;
                }
                status('info', res.body.message ||
                    'Check your inbox for the verification link.');
            }).catch(function () { status('error', 'Registration request failed.'); });
        });

        // ---- Password reset (forgot → email link → reset form) ----------
        el('forgotLink').addEventListener('click', function (e) {
            e.preventDefault();
            el('forgotForm').classList.toggle('hidden');
        });

        el('forgotForm').addEventListener('submit', function (e) {
            e.preventDefault();
            status('info', 'Sending reset link…');
            postJSON(API + '/v2/auth/forgot-password', {
                email: el('forgotEmail').value
            }).then(function (res) {
                // The API answer is intentionally indistinguishable.
                status('info', (res.body && res.body.message) ||
                    'If the address is registered, a reset link is on its way.');
            }).catch(function () { status('error', 'Reset request failed.'); });
        });

        var resetToken = new URLSearchParams(location.search).get('reset_token');
        if (resetToken) {
            showView(false);
            el('resetForm').classList.remove('hidden');
            status('info', 'Enter a new password to complete the reset.');
        }
        el('resetForm').addEventListener('submit', function (e) {
            e.preventDefault();
            status('info', 'Updating password…');
            postJSON(API + '/v2/auth/reset-password', {
                token: resetToken,
                password: el('resetPassword').value
            }).then(function (res) {
                if (!res.ok) {
                    status('error', res.body.error || 'Reset failed.');
                    return;
                }
                status('info', res.body.message || 'Password updated. Please sign in.');
                el('resetForm').classList.add('hidden');
                history.replaceState(null, '', location.pathname);
            }).catch(function () { status('error', 'Reset request failed.'); });
        });

        el('logoutBtn').addEventListener('click', function () {
            postJSON(API + '/v2/auth/logout', {}).then(function () {
                status('info', 'Signed out.');
                showView(false);
            }).catch(function () {
                showView(false);
            });
        });

        // Show/hide password toggles (login, register, reset forms)
        Array.prototype.forEach.call(document.querySelectorAll('.pw-toggle'), function (btn) {
            btn.addEventListener('click', function () {
                var input = el(btn.getAttribute('data-target'));
                var show = input.type === 'password';
                input.type = show ? 'text' : 'password';
                btn.textContent = show ? 'Hide' : 'Show';
                btn.setAttribute('aria-label', show ? 'Hide password' : 'Show password');
            });
        });
    }

    // ------------------------------------------------------------------
    // Profile
    // ------------------------------------------------------------------

    function renderProfile(body) {
        var u = body.user || {};
        el('profileBlock').innerHTML =
            '<div class="table-scroll"><table class="kv-table">' +
            '<tr><th>Email</th><td>' + esc(u.email) + '</td></tr>' +
            (u.display_name ? '<tr><th>Name</th><td>' + esc(u.display_name) + '</td></tr>' : '') +
            '<tr><th>Tier</th><td>' + esc(u.role || 'registered') + '</td></tr>' +
            '<tr><th>Status</th><td>' + esc(u.status || '') + '</td></tr>' +
            '<tr><th>Saved locations</th><td>' + esc(body.locations != null ? body.locations : '—') + '</td></tr>' +
            '<tr><th>Alerts</th><td>' + esc(body.alerts != null ? body.alerts : '—') + '</td></tr>' +
            '</table></div>';
    }

    // ------------------------------------------------------------------
    // Subscription (self-service; recorded, never charged)
    // ------------------------------------------------------------------

    function loadSubscription() {
        fetchJSON(API + '/v2/account/subscription').then(function (res) {
            if (res.status === 401) { showView(false); return; }
            if (!res.ok) {
                el('subscriptionBlock').innerHTML =
                    '<div class="notice notice-error">Subscription state unavailable: ' +
                    esc(res.body.error || '') + '</div>';
                return;
            }
            renderSubscription(res.body || {});
        }).catch(function () {
            el('subscriptionBlock').innerHTML =
                '<div class="notice notice-error">Subscription state could not be loaded.</div>';
        });
    }

    function renderSubscription(body) {
        var sub = body.subscription;
        var rows = '<tr><th>Your tier</th><td>' + esc(body.role || 'registered') + '</td></tr>';
        if (sub) {
            rows += '<tr><th>Subscription</th><td>' + chip('OBSERVED', 'ACTIVE') + '</td></tr>' +
                '<tr><th>Tier</th><td>' + esc(sub.tier) + '</td></tr>' +
                '<tr><th>Started</th><td>' + esc((sub.started_at || '').slice(0, 10)) + '</td></tr>';
        } else {
            rows += '<tr><th>Subscription</th><td>' + chip('UNAVAILABLE', 'NOT SUBSCRIBED') + '</td></tr>';
        }
        var unlocks = (body.subscriber_unlocks || []).map(function (u) {
            return '<li>' + esc(u) + '</li>';
        }).join('');
        el('subscriptionBlock').innerHTML =
            '<div class="table-scroll"><table class="kv-table">' + rows + '</table></div>' +
            (sub
                ? ''
                : '<p class="muted small" style="margin-top:10px;">Subscribing unlocks:</p>' +
                  '<ul class="muted small" style="margin:4px 0 0 18px;">' + unlocks + '</ul>');
        el('subscribeBtn').classList.toggle('hidden', !!sub);
        el('unsubscribeBtn').classList.toggle('hidden', !sub);
    }

    function wireSubscription() {
        el('subscribeBtn').addEventListener('click', function () {
            status('info', 'Activating your subscription…');
            postJSON(API + '/v2/account/subscribe', {}).then(function (res) {
                if (res.status === 401) { showView(false); return; }
                if (!res.ok) {
                    status('error', (res.body && res.body.error) || 'Subscription failed.');
                    return;
                }
                status('info', (res.body && res.body.already_active)
                    ? 'Your subscription is already active.'
                    : 'Subscription active — a confirmation email is on its way.');
                boot();
            }).catch(function () { status('error', 'Subscription request failed.'); });
        });

        el('unsubscribeBtn').addEventListener('click', function () {
            if (!window.confirm('Cancel your subscription? Your account, saved locations ' +
                    'and alert rules are kept; the tier returns to the free level.')) return;
            postJSON(API + '/v2/account/unsubscribe', {}).then(function (res) {
                if (res.status === 401) { showView(false); return; }
                if (!res.ok) {
                    status('error', (res.body && res.body.error) || 'Cancellation failed.');
                    return;
                }
                status('info', 'Subscription cancelled.');
                boot();
            }).catch(function () { status('error', 'Cancellation request failed.'); });
        });
    }

    // ------------------------------------------------------------------
    // API keys (subscriber tier; read-only programmatic access)
    // ------------------------------------------------------------------

    function loadApiKeys() {
        fetchJSON(API + '/v2/account/api-keys').then(function (res) {
            if (res.status === 401) { showView(false); return; }
            if (!res.ok) {
                el('apiKeysBlock').innerHTML =
                    '<div class="notice notice-error">API keys unavailable: ' +
                    esc(res.body.error || '') + '</div>';
                return;
            }
            renderApiKeys(res.body.api_keys || []);
        }).catch(function () {
            el('apiKeysBlock').innerHTML =
                '<div class="notice notice-error">API keys could not be loaded.</div>';
        });
    }

    function renderApiKeys(list) {
        if (!list.length) {
            el('apiKeysBlock').innerHTML =
                '<div class="notice notice-empty">No API keys yet.</div>';
            return;
        }
        el('apiKeysBlock').innerHTML =
            '<div class="table-scroll"><table class="data-table"><thead><tr>' +
            '<th>Label</th><th>Created</th><th>State</th><th></th></tr></thead><tbody>' +
            list.map(function (k) {
                return '<tr><td>' + esc(k.label || '—') + '</td>' +
                    '<td>' + esc((k.created_at || '').slice(0, 10)) + '</td>' +
                    '<td>' + (k.revoked ? chip('UNAVAILABLE', 'REVOKED') : chip('OBSERVED', 'ACTIVE')) + '</td>' +
                    '<td>' + (k.revoked ? '' :
                        '<button class="btn-action btn-quiet" data-revoke-key="' + k.id + '">Revoke</button>') +
                    '</td></tr>';
            }).join('') + '</tbody></table></div>';
        Array.prototype.forEach.call(
            document.querySelectorAll('[data-revoke-key]'), function (btn) {
                btn.addEventListener('click', function () {
                    fetchJSON(API + '/v2/account/api-keys/' + btn.getAttribute('data-revoke-key'),
                        { method: 'DELETE' }).then(function (res) {
                            if (res.status === 401) { showView(false); return; }
                            loadApiKeys();
                        });
                });
            });
    }

    function wireApiKeys() {
        el('apiKeyCreateBtn').addEventListener('click', function () {
            el('apiKeyNewBlock').innerHTML = '';
            postJSON(API + '/v2/account/api-keys', {
                label: el('apiKeyLabel').value || undefined
            }).then(function (res) {
                if (res.status === 401) { showView(false); return; }
                if (res.status === 403 && res.body && res.body.upgrade) {
                    el('apiKeyNewBlock').innerHTML =
                        '<div class="notice notice-warn" style="margin-top:12px;">' +
                        esc(res.body.error || 'API keys require a subscription.') +
                        ' Use the Subscribe button in the Subscription panel above.</div>';
                    return;
                }
                if (!res.ok) {
                    el('apiKeyNewBlock').innerHTML =
                        '<div class="notice notice-error" style="margin-top:12px;">' +
                        esc((res.body && res.body.error) || 'Could not create the key.') + '</div>';
                    return;
                }
                var key = res.body.api_key || {};
                el('apiKeyNewBlock').innerHTML =
                    '<div class="notice notice-info" style="margin-top:12px;">' +
                    '<strong>Your new API key (shown once — store it now):</strong><br>' +
                    '<code style="word-break:break-all;">' + esc(key.key || '') + '</code><br>' +
                    '<span class="muted small">Send it as the X-API-Key header on GET ' +
                    'requests; keys are read-only.</span></div>';
                el('apiKeyLabel').value = '';
                loadApiKeys();
            }).catch(function () {
                el('apiKeyNewBlock').innerHTML =
                    '<div class="notice notice-error" style="margin-top:12px;">Key creation request failed.</div>';
            });
        });
    }

    // ------------------------------------------------------------------
    // Saved locations
    // ------------------------------------------------------------------

    function loadLocations() {
        fetchJSON(API + '/v2/account/locations').then(function (res) {
            if (res.status === 401) { showView(false); return; }
            if (!res.ok) {
                el('locationsList').innerHTML =
                    '<div class="notice notice-error">Saved locations unavailable: ' +
                    esc(res.body.error || '') + '</div>';
                return;
            }
            renderLocations(res.body.locations || []);
        }).catch(function () {
            el('locationsList').innerHTML =
                '<div class="notice notice-error">Saved locations could not be loaded.</div>';
        });
    }

    function renderLocations(list) {
        if (!list.length) {
            el('locationsList').innerHTML =
                '<div class="notice notice-empty">No saved locations yet.</div>';
            return;
        }
        el('locationsList').innerHTML =
            '<div class="table-scroll"><table class="data-table"><thead><tr>' +
            '<th>Name</th><th>Coordinates</th><th></th></tr></thead><tbody>' +
            list.map(function (l) {
                return '<tr><td>' + esc(l.name || 'Location') + '</td>' +
                    '<td><a class="text-link" href="map.html?location=' +
                    encodeURIComponent(l.lat + ',' + l.lon) + '">' +
                    esc(Number(l.lat).toFixed(4)) + ', ' + esc(Number(l.lon).toFixed(4)) + '</a></td>' +
                    '<td><button class="btn-action btn-quiet" data-del-location="' + l.id + '">Delete</button></td></tr>';
            }).join('') + '</tbody></table></div>';
        Array.prototype.forEach.call(
            document.querySelectorAll('[data-del-location]'), function (btn) {
                btn.addEventListener('click', function () {
                    fetchJSON(API + '/v2/account/locations/' + btn.getAttribute('data-del-location'),
                        { method: 'DELETE' }).then(loadLocations);
                });
            });
    }

    function wireLocations() {
        var last = HS.lastLocation();
        if (last && last.lat != null && last.lon != null) {
            var btn = el('useMapLocBtn');
            btn.classList.remove('hidden');
            btn.textContent = 'Use last map location (' +
                (last.name || (last.lat + ', ' + last.lon)) + ')';
            btn.addEventListener('click', function () {
                el('locLat').value = last.lat;
                el('locLon').value = last.lon;
                if (!el('locName').value && last.name) el('locName').value = last.name;
            });
        }
        el('addLocBtn').addEventListener('click', function () {
            var lat = parseFloat(el('locLat').value);
            var lon = parseFloat(el('locLon').value);
            if (isNaN(lat) || isNaN(lon)) {
                status('error', 'Latitude and longitude must be numbers.');
                return;
            }
            postJSON(API + '/v2/account/locations', {
                name: el('locName').value || undefined,
                lat: lat, lon: lon
            }).then(function (res) {
                if (!res.ok) {
                    status('error', (res.body && res.body.error) || 'Could not save the location.');
                    if (res.body && res.body.upgrade) status('warn', res.body.error + ' ' + res.body.upgrade.unlocks);
                    return;
                }
                status('', '');
                el('locName').value = ''; el('locLat').value = ''; el('locLon').value = '';
                loadLocations();
            });
        });
    }

    // ------------------------------------------------------------------
    // Alerts
    // ------------------------------------------------------------------

    function loadHazards() {
        fetchJSON(API + '/v2/hazards').then(function (res) {
            if (!res.ok || !res.body.hazards) return;
            var options = res.body.hazards.map(function (h) {
                return '<option value="' + esc(h.id) + '">' + esc(h.name) + '</option>';
            }).join('');
            el('alertHazard').innerHTML = options;
            // The SMS alert-rule form reuses the same already-loaded registry.
            var ruleHazard = el('ruleHazard');
            if (ruleHazard) ruleHazard.innerHTML = options;
            // Apply a hazard carried by a deep link (?hazard=…#sms).
            if (pendingRuleHazard && ruleHazard) {
                for (var i = 0; i < ruleHazard.options.length; i++) {
                    if (ruleHazard.options[i].value === pendingRuleHazard) {
                        ruleHazard.value = pendingRuleHazard;
                        break;
                    }
                }
            }
        }).catch(function () {
            el('alertHazard').innerHTML = '<option value="wildfire">Wildfire</option>';
            var ruleHazard = el('ruleHazard');
            if (ruleHazard) ruleHazard.innerHTML = '<option value="wildfire">Wildfire</option>';
        });
    }

    function loadAlerts() {
        fetchJSON(API + '/v2/account/alerts').then(function (res) {
            if (res.status === 401) { showView(false); return; }
            if (!res.ok) {
                el('alertsList').innerHTML =
                    '<div class="notice notice-error">Alerts unavailable: ' +
                    esc(res.body.error || '') + '</div>';
                return;
            }
            renderAlerts(res.body.alerts || []);
        }).catch(function () {
            el('alertsList').innerHTML =
                '<div class="notice notice-error">Alerts could not be loaded.</div>';
        });
    }

    function renderAlerts(list) {
        if (!list.length) {
            el('alertsList').innerHTML =
                '<div class="notice notice-empty">No alerts configured.</div>';
            return;
        }
        el('alertsList').innerHTML =
            '<div class="table-scroll"><table class="data-table"><thead><tr>' +
            '<th>Hazard</th><th>Location</th><th>Threshold</th><th>Channel</th><th>State</th><th></th>' +
            '</tr></thead><tbody>' +
            list.map(function (a) {
                var thr = a.threshold || {};
                var thrText = Object.keys(thr).length
                    ? Object.keys(thr).map(function (k) { return k.replace(/_/g, ' ') + ' ' + thr[k]; }).join(', ')
                    : '—';
                return '<tr><td>' + esc(a.hazard) + '</td>' +
                    '<td>' + esc(Number(a.lat).toFixed(4)) + ', ' + esc(Number(a.lon).toFixed(4)) + '</td>' +
                    '<td>' + esc(thrText) + '</td>' +
                    '<td>' + esc(a.channel || 'email') + '</td>' +
                    '<td>' + (a.active ? chip('OBSERVED', 'ACTIVE') : chip('UNAVAILABLE', 'INACTIVE')) + '</td>' +
                    '<td><button class="btn-action btn-quiet" data-del-alert="' + a.id + '">Delete</button></td></tr>';
            }).join('') + '</tbody></table></div>';
        Array.prototype.forEach.call(
            document.querySelectorAll('[data-del-alert]'), function (btn) {
                btn.addEventListener('click', function () {
                    fetchJSON(API + '/v2/account/alerts/' + btn.getAttribute('data-del-alert'),
                        { method: 'DELETE' }).then(loadAlerts);
                });
            });
    }

    function wireAlerts() {
        el('addAlertBtn').addEventListener('click', function () {
            var lat = parseFloat(el('alertLat').value);
            var lon = parseFloat(el('alertLon').value);
            if (isNaN(lat) || isNaN(lon)) {
                status('error', 'Alert latitude and longitude must be numbers.');
                return;
            }
            postJSON(API + '/v2/account/alerts', {
                hazard: el('alertHazard').value || 'wildfire',
                lat: lat, lon: lon,
                threshold: { risk_gte: parseInt(el('alertThreshold').value, 10) },
                channel: 'email'
            }).then(function (res) {
                if (!res.ok) {
                    status('error', (res.body && res.body.error) || 'Could not create the alert.');
                    return;
                }
                status('', '');
                loadAlerts();
            });
        });
    }

    // ------------------------------------------------------------------
    // SMS alerts (Climate Alert Subscription — /api/v2/alerts/…)
    // ------------------------------------------------------------------
    //
    // Phone verification → preferences → rules → history → unsubscribe.
    // Consent model: nothing is subscribed silently — SMS starts only after
    // the user verifies their phone and creates a rule themselves. The panel
    // stays collapsed (one-line intro + expand) while there is no phone and
    // no rules. Verification codes are delivered by SMS only (dev: server
    // outbox) and never appear in API responses.

    var smsState = { phone: null, prefs: null, rules: [], expanded: false, delivery: null };
    var pendingRuleHazard = null;  // hazard from a deep link, applied on registry load

    function smsStatus(kind, msg) {
        el('smsStatus').innerHTML = msg
            ? '<div class="notice notice-' + kind + '">' + esc(msg) + '</div>'
            : '';
    }

    function severityChip(sev) {
        var s = String(sev || '').toUpperCase();
        if (s === 'EXTREME') return chip('error', 'EXTREME');
        if (s === 'HIGH') return chip('reported', 'HIGH');
        return chip('unknown', s || '—');
    }

    function deliveryChip(statusText) {
        var s = String(statusText || 'unknown').toLowerCase();
        var token = { sent: 'observed', failed: 'error', error: 'error',
                      outbox: 'modelled', held_quiet_hours: 'forecast' }[s] || 'unknown';
        return chip(token, statusText);
    }

    function renderSmsVisibility() {
        var expand = smsState.expanded || !!smsState.phone ||
            smsState.rules.length > 0 || location.hash === '#sms';
        el('smsCollapsed').classList.toggle('hidden', expand);
        el('smsBody').classList.toggle('hidden', !expand);
    }

    /* Pre-fill the alert-rule form from a deep link
     * (account.html?location=…&hazard=…#sms) — the "get alerts for this
     * place" flow carries the analyzed location + hazard here. */
    function prefillRuleFromUrl() {
        var params = new URLSearchParams(location.search);
        var loc = params.get('location');
        var hazard = params.get('hazard');
        if (!loc && !hazard) return;
        smsState.expanded = true;
        renderSmsVisibility();
        if (loc && el('ruleLocation')) el('ruleLocation').value = loc;
        if (hazard && el('ruleHazard')) {
            pendingRuleHazard = hazard;   // applied once the registry options load
            var sel = el('ruleHazard');
            for (var i = 0; i < sel.options.length; i++) {
                if (sel.options[i].value === hazard) { sel.value = hazard; break; }
            }
        }
        if (loc || hazard) {
            smsStatus('info', 'Alert context loaded for ' + (loc || '') +
                (hazard ? ' (' + hazard + ')' : '') +
                ' — verify your phone, then create the rule.');
        }
    }

    // ---- Phone ---------------------------------------------------------

    function loadSmsPrefs() {
        fetchJSON(API + '/v2/alerts/preferences').then(function (res) {
            if (res.status === 401) { showView(false); return; }
            if (!res.ok) {
                el('smsPhoneBlock').innerHTML =
                    '<div class="notice notice-error">SMS alert settings unavailable: ' +
                    esc(res.body.error || '') + '</div>';
                return;
            }
            smsState.phone = res.body.phone || null;
            smsState.prefs = res.body.prefs || null;
            smsState.delivery = res.body.sms_delivery || null;
            renderPhone();
            renderPrefs();
            renderSmsVisibility();
        }).catch(function () {
            el('smsPhoneBlock').innerHTML =
                '<div class="notice notice-error">SMS alert settings could not be loaded.</div>';
        });
    }

    function renderPhone() {
        var p = smsState.phone;
        var block = el('smsPhoneBlock');
        if (!p) {
            block.innerHTML =
                '<div class="notice notice-empty">No phone number registered.</div>';
            el('smsPhoneForm').classList.remove('hidden');
            el('smsVerifyForm').classList.add('hidden');
            return;
        }
        block.innerHTML =
            '<div class="table-scroll"><table class="kv-table">' +
            '<tr><th>Phone</th><td>' + esc(p.e164) + '</td></tr>' +
            '<tr><th>Status</th><td>' + (p.verified
                ? chip('OBSERVED', 'PHONE VERIFIED')
                : chip('REPORTED', 'AWAITING VERIFICATION')) + '</td></tr>' +
            '</table></div>' +
            '<div class="card-actions" style="margin-top:8px;">' +
            '<button class="btn-action btn-quiet" id="smsPhoneDeleteBtn" type="button">Delete phone</button>' +
            '</div>';
        // Unverified: keep both forms visible so the code can be re-sent or corrected.
        el('smsPhoneForm').classList.toggle('hidden', !!p.verified);
        el('smsVerifyForm').classList.toggle('hidden', !!p.verified);
        el('smsPhoneDeleteBtn').addEventListener('click', function () {
            fetchJSON(API + '/v2/alerts/phone', { method: 'DELETE' }).then(function (res) {
                if (res.status === 401) { showView(false); return; }
                if (!res.ok) {
                    smsStatus('error', (res.body && res.body.error) ||
                        'Could not delete the phone number.');
                    return;
                }
                smsStatus('info', 'Phone number deleted.');
                smsState.phone = null;
                renderPhone();
                renderSmsVisibility();
            }).catch(function () { smsStatus('error', 'Delete request failed.'); });
        });
    }

    function renderPrefs() {
        var p = smsState.prefs;
        if (!p) return;
        el('prefSms').checked = !!p.sms_enabled;
        el('prefEmail').checked = !!p.email_enabled;
        el('prefQuietStart').value = (p.quiet_hours && p.quiet_hours.start) || '';
        el('prefQuietEnd').value = (p.quiet_hours && p.quiet_hours.end) || '';
        el('prefLang').value = p.language || 'en';
        el('prefMaxPerDay').value = p.max_per_day != null ? p.max_per_day : 10;
        var d = smsState.delivery;
        if (d) {
            el('smsDeliveryNote').textContent = d.provider_configured
                ? 'SMS delivery: a provider is configured — alerts are delivered as real SMS.'
                : 'SMS delivery: no provider is configured yet — alerts and verification ' +
                  'codes are written to the operator outbox, not delivered as SMS.';
        }
    }

    // ---- Rules -----------------------------------------------------------

    function loadRules() {
        fetchJSON(API + '/v2/alerts/rules').then(function (res) {
            if (res.status === 401) { showView(false); return; }
            if (!res.ok) {
                el('rulesList').innerHTML =
                    '<div class="notice notice-error">Alert rules unavailable: ' +
                    esc(res.body.error || '') + '</div>';
                return;
            }
            smsState.rules = res.body.rules || [];
            renderRules();
            renderSmsVisibility();
        }).catch(function () {
            el('rulesList').innerHTML =
                '<div class="notice notice-error">Alert rules could not be loaded.</div>';
        });
    }

    function renderRules() {
        var list = smsState.rules;
        if (!list.length) {
            el('rulesList').innerHTML =
                '<div class="notice notice-empty">No alert rules yet. Add one below — ' +
                'alerts are generated only for rules you create yourself.</div>';
            return;
        }
        el('rulesList').innerHTML =
            '<div class="table-scroll"><table class="data-table"><thead><tr>' +
            '<th>Name</th><th>Location</th><th>Hazard</th><th>Threshold</th><th>State</th><th></th>' +
            '</tr></thead><tbody>' +
            list.map(function (r) {
                return '<tr><td>' + esc(r.name || '—') + '</td>' +
                    '<td>' + esc(Number(r.lat).toFixed(4)) + ', ' + esc(Number(r.lon).toFixed(4)) + '</td>' +
                    '<td>' + esc(r.hazard) + '</td>' +
                    '<td>' + severityChip(r.severity_threshold) + '</td>' +
                    '<td>' + (r.active ? chip('OBSERVED', 'ACTIVE') : chip('UNAVAILABLE', 'INACTIVE')) + '</td>' +
                    '<td><button class="btn-action btn-quiet" data-del-rule="' + r.id + '">Delete</button></td></tr>';
            }).join('') + '</tbody></table></div>';
        Array.prototype.forEach.call(
            document.querySelectorAll('[data-del-rule]'), function (btn) {
                btn.addEventListener('click', function () {
                    fetchJSON(API + '/v2/alerts/rules/' + btn.getAttribute('data-del-rule'),
                        { method: 'DELETE' }).then(function (res) {
                            if (res.status === 401) { showView(false); return; }
                            loadRules();
                        });
                });
            });
    }

    // ---- Alert history ---------------------------------------------------

    function loadAlertHistory() {
        fetchJSON(API + '/v2/alerts/history').then(function (res) {
            if (res.status === 401) { showView(false); return; }
            if (!res.ok) {
                el('alertHistoryBlock').innerHTML =
                    '<div class="notice notice-error">Alert history unavailable: ' +
                    esc(res.body.error || '') + '</div>';
                return;
            }
            renderAlertHistory(res.body.alerts || []);
        }).catch(function () {
            el('alertHistoryBlock').innerHTML =
                '<div class="notice notice-error">Alert history could not be loaded.</div>';
        });
    }

    function renderAlertHistory(list) {
        if (!list.length) {
            el('alertHistoryBlock').innerHTML =
                '<div class="notice notice-empty">No alerts sent yet. When a rule\'s ' +
                'threshold is crossed, the generated message and its delivery status appear here.</div>';
            return;
        }
        el('alertHistoryBlock').innerHTML =
            '<div class="table-scroll"><table class="data-table"><thead><tr>' +
            '<th>When</th><th>Hazard</th><th>Severity</th><th>Trigger</th><th>Deliveries</th>' +
            '</tr></thead><tbody>' +
            list.map(function (a) {
                var deliveries = (a.deliveries || []).map(function (d) {
                    return esc(d.channel) + ': ' + deliveryChip(d.status);
                }).join('<br>') || '<span class="muted">—</span>';
                return '<tr><td>' + esc((a.created_at || '').slice(0, 16).replace('T', ' ')) + '</td>' +
                    '<td>' + esc(a.hazard) + '</td>' +
                    '<td>' + severityChip(a.severity) +
                        (a.suppressed ? ' <span class="muted small">(suppressed)</span>' : '') + '</td>' +
                    '<td>' + esc(a.trigger || '—') + '</td>' +
                    '<td>' + deliveries + '</td></tr>';
            }).join('') + '</tbody></table></div>';
    }

    // ---- Wiring ------------------------------------------------------------

    function wireSms() {
        el('smsExpandBtn').addEventListener('click', function () {
            if (window.HS && HS.track) HS.track('sms_interest');
            smsState.expanded = true;
            renderSmsVisibility();
        });

        el('smsPhoneForm').addEventListener('submit', function (e) {
            e.preventDefault();
            var phone = el('smsPhone').value.trim();
            if (!phone) {
                smsStatus('error', 'Enter a phone number in E.164 format (e.g. +352691234567).');
                return;
            }
            smsStatus('info', 'Sending verification code…');
            postJSON(API + '/v2/alerts/phone', { phone: phone }).then(function (res) {
                if (res.status === 401) { showView(false); return; }
                if (!res.ok) {
                    smsStatus('error', (res.body && res.body.error) ||
                        'Could not register the phone number.');
                    return;
                }
                smsState.phone = res.body.phone || smsState.phone;
                renderPhone();
                renderSmsVisibility();
                var target = (res.body.phone && res.body.phone.e164) || phone;
                smsStatus('info', 'Verification code sent to ' + target + '.' +
                    (res.body.delivery_backend === 'outbox'
                        ? ' No SMS provider is configured — the code was written to the server outbox.'
                        : ''));
                el('smsCode').focus();
            }).catch(function () { smsStatus('error', 'Phone registration request failed.'); });
        });

        el('smsVerifyForm').addEventListener('submit', function (e) {
            e.preventDefault();
            var code = el('smsCode').value.trim();
            if (!/^\d{6}$/.test(code)) {
                smsStatus('error', 'Enter the 6-digit code from the SMS.');
                return;
            }
            smsStatus('info', 'Verifying…');
            postJSON(API + '/v2/alerts/phone/verify', { code: code }).then(function (res) {
                if (res.status === 401) { showView(false); return; }
                if (!res.ok) {
                    smsStatus('error', (res.body && res.body.error) || 'Verification failed.');
                    return;
                }
                smsState.phone = res.body.phone || smsState.phone;
                if (res.body.prefs) smsState.prefs = res.body.prefs;
                renderPhone();
                renderPrefs();
                el('smsCode').value = '';
                smsStatus('info', 'Phone verified. SMS is enabled — add an alert rule ' +
                    'below to start watching a place.');
            }).catch(function () { smsStatus('error', 'Verification request failed.'); });
        });

        el('prefSaveBtn').addEventListener('click', function () {
            var qs = el('prefQuietStart').value;
            var qe = el('prefQuietEnd').value;
            if ((qs && !qe) || (!qs && qe)) {
                smsStatus('error', 'Quiet hours need both a start and an end, or neither.');
                return;
            }
            var maxPerDay = parseInt(el('prefMaxPerDay').value, 10);
            if (isNaN(maxPerDay) || maxPerDay < 1 || maxPerDay > 50) {
                smsStatus('error', 'Max alerts per day must be between 1 and 50.');
                return;
            }
            smsStatus('info', 'Saving preferences…');
            fetchJSON(API + '/v2/alerts/preferences', {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    sms_enabled: el('prefSms').checked,
                    email_enabled: el('prefEmail').checked,
                    quiet_hours: qs ? { start: qs, end: qe } : null,
                    language: el('prefLang').value,
                    max_per_day: maxPerDay
                })
            }).then(function (res) {
                if (res.status === 401) { showView(false); return; }
                if (!res.ok) {
                    smsStatus('error', (res.body && res.body.error) ||
                        'Could not save the preferences.');
                    return;
                }
                smsState.prefs = (res.body && res.body.prefs) || smsState.prefs;
                renderPrefs();
                smsStatus('info', 'Preferences saved.');
            }).catch(function () { smsStatus('error', 'Save request failed.'); });
        });

        el('ruleAddBtn').addEventListener('click', function () {
            var q = el('ruleLocation').value.trim();
            if (!q) {
                smsStatus('error', 'Enter a location — a place name or lat,lon coordinates.');
                return;
            }
            smsStatus('info', 'Resolving location…');
            HS.resolveLocation(q).then(function (loc) {
                if (!loc.ok) {
                    smsStatus('error', loc.error || 'Location could not be resolved.');
                    return;
                }
                postJSON(API + '/v2/alerts/rules', {
                    hazard: el('ruleHazard').value,
                    lat: loc.lat,
                    lon: loc.lon,
                    name: loc.name,
                    severity_threshold: el('ruleThreshold').value
                }).then(function (res) {
                    if (res.status === 401) { showView(false); return; }
                    if (res.status === 403 && res.body && res.body.upgrade) {
                        smsStatus('warn', (res.body.error || 'Alert-rule limit reached.') +
                            ' ' + res.body.upgrade.unlocks);
                        return;
                    }
                    if (!res.ok) {
                        smsStatus('error', (res.body && res.body.error) ||
                            'Could not create the rule.');
                        return;
                    }
                    smsStatus('', '');
                    el('ruleLocation').value = '';
                    loadRules();
                });
            }).catch(function () {
                smsStatus('error', 'The location could not be resolved.');
            });
        });

        el('smsUnsubBtn').addEventListener('click', function () { unsubscribeSms(false); });
        el('smsUnsubRulesBtn').addEventListener('click', function () { unsubscribeSms(true); });
    }

    function unsubscribeSms(withRules) {
        var question = withRules
            ? 'Stop all SMS alerts AND permanently delete your alert rules?'
            : 'Stop all SMS alerts? Your rules stay in place and you can re-enable SMS at any time.';
        if (!window.confirm(question)) return;
        postJSON(API + '/v2/alerts/unsubscribe' + (withRules ? '?rules=1' : ''), {})
            .then(function (res) {
                if (res.status === 401) { showView(false); return; }
                if (!res.ok) {
                    smsStatus('error', (res.body && res.body.error) || 'Unsubscribe failed.');
                    return;
                }
                smsStatus('info', 'SMS alerts stopped.' +
                    (res.body.rules_deleted
                        ? ' ' + res.body.rules_deleted + ' rule(s) deleted.'
                        : ''));
                loadSmsPrefs();
                if (withRules) loadRules();
            }).catch(function () { smsStatus('error', 'Unsubscribe request failed.'); });
    }

    // ------------------------------------------------------------------
    // History
    // ------------------------------------------------------------------

    function loadHistory() {
        fetchJSON(API + '/v2/account/history').then(function (res) {
            if (res.status === 401) { showView(false); return; }
            if (!res.ok) {
                el('historyBlock').innerHTML =
                    '<div class="notice notice-error">History unavailable: ' +
                    esc(res.body.error || '') + '</div>';
                return;
            }
            renderHistory(res.body || {});
        }).catch(function () {
            el('historyBlock').innerHTML =
                '<div class="notice notice-error">History could not be loaded.</div>';
        });
    }

    function renderHistory(h) {
        var analyses = h.analyses || [];
        var reports = h.reports || [];
        var html = '';
        if (!analyses.length && !reports.length) {
            el('historyBlock').innerHTML =
                '<div class="notice notice-empty">No analyses or reports recorded yet. ' +
                'Analyses you run while signed in appear here.</div>';
            return;
        }
        if (analyses.length) {
            html += '<h3>Analyses</h3><div class="table-scroll"><table class="data-table">' +
                '<thead><tr><th>When</th><th>Hazard</th><th>Location</th><th>Summary</th></tr></thead><tbody>' +
                analyses.map(function (a) {
                    var s = a.summary || {};
                    return '<tr><td>' + esc((a.created_at || '').slice(0, 16).replace('T', ' ')) + '</td>' +
                        '<td>' + esc(a.hazard) + '</td>' +
                        '<td><a class="text-link" href="map.html?location=' +
                        encodeURIComponent(a.lat + ',' + a.lon) + '">' +
                        esc(Number(a.lat).toFixed(3)) + ', ' + esc(Number(a.lon).toFixed(3)) + '</a></td>' +
                        '<td class="muted small">' + esc(s.summary || s.text || '') + '</td></tr>';
                }).join('') + '</tbody></table></div>';
        }
        if (reports.length) {
            html += '<h3>Reports</h3><div class="table-scroll"><table class="data-table">' +
                '<thead><tr><th>When</th><th>Type</th><th>Hazard</th><th>Location</th><th>Report ID</th></tr></thead><tbody>' +
                reports.map(function (r) {
                    var meta = r.report_meta || {};
                    return '<tr><td>' + esc((r.created_at || '').slice(0, 16).replace('T', ' ')) + '</td>' +
                        '<td>' + esc(r.report_type) + '</td><td>' + esc(r.hazard || '') + '</td>' +
                        '<td>' + esc(Number(r.lat).toFixed(3)) + ', ' + esc(Number(r.lon).toFixed(3)) + '</td>' +
                        '<td class="muted small">' + esc(meta.report_id || '—') + '</td></tr>';
                }).join('') + '</tbody></table></div>';
        }
        el('historyBlock').innerHTML = html;
    }

    // ------------------------------------------------------------------

    function init() {
        wireAuth();
        wireSubscription();
        wireApiKeys();
        wireLocations();
        wireAlerts();
        wireSms();
        prefillRuleFromUrl();
        boot();
    }

    init();
})();
