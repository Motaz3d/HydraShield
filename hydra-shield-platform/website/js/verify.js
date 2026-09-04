/* Talaix — public TX seal verification page. */
(function () {
    'use strict';

    function id(s) { return document.getElementById(s); }
    function show(el, html) { el.innerHTML = html; el.classList.remove('hidden'); }
    function hide(el) { el.innerHTML = ''; el.classList.add('hidden'); }

    function renderRegistryResult(body) {
        var el = id('registryResult');
        if (!body.valid) {
            show(el,
                '<div class="notice notice-error">' +
                '<strong>Not recognised.</strong> This code is not in the Talaix document registry. ' +
                'If you are checking a JSON analysis result, use the stateless verifier below.' +
                '</div>'
            );
            return;
        }
        var rows = [
            ['Seal code', body.code],
            ['Engine', body.engine],
            ['Kind', body.kind || '—'],
            ['Reference ID', body.ref_id || '—'],
            ['Issued at', body.issued_at || '—']
        ];
        var html = '<div class="notice notice-success"><strong>Genuine — issued by the Talaix TX engine.</strong></div>' +
            '<table class="kv-table"><tbody>' +
            rows.map(function (r) {
                return '<tr><th>' + HS.esc(r[0]) + '</th><td>' + HS.esc(r[1]) + '</td></tr>';
            }).join('') +
            '</tbody></table>';
        show(el, html);
    }

    function renderRecomputeResult(body, payload, code) {
        var el = id('recomputeResult');
        if (body.valid) {
            show(el,
                '<div class="notice notice-success"><strong>Valid seal.</strong> The payload matches <code>' +
                HS.esc(body.code) + '</code>.</div>'
            );
        } else {
            show(el,
                '<div class="notice notice-error"><strong>Invalid seal.</strong> The payload does not match <code>' +
                HS.esc(body.code) + '</code>.</div>'
            );
        }
    }

    function renderError(el, msg) {
        show(el, '<div class="notice notice-error">' + HS.esc(msg) + '</div>');
    }

    function initRegistryForm() {
        var form = id('registryForm');
        if (!form) return;
        form.addEventListener('submit', function (e) {
            e.preventDefault();
            var code = (id('registryCode').value || '').trim();
            var resultEl = id('registryResult');
            hide(resultEl);
            if (!code) { renderError(resultEl, 'Enter a seal code.'); return; }
            HS.fetchJSON(HS.API + '/v2/verify/' + encodeURIComponent(code))
                .then(function (res) { renderRegistryResult(res.body); })
                .catch(function () { renderError(resultEl, 'Network error. Please try again.'); });
        });
    }

    function initRecomputeForm() {
        var form = id('recomputeForm');
        var toggle = id('recomputeToggle');
        var panel = id('recomputePanel');
        if (!form || !toggle || !panel) return;

        toggle.addEventListener('click', function (e) {
            e.preventDefault();
            panel.classList.toggle('hidden');
        });

        form.addEventListener('submit', function (e) {
            e.preventDefault();
            var code = (id('recomputeCode').value || '').trim();
            var text = (id('recomputePayload').value || '').trim();
            var resultEl = id('recomputeResult');
            hide(resultEl);
            if (!code) { renderError(resultEl, 'Enter a seal code.'); return; }
            var payload;
            try {
                payload = text ? JSON.parse(text) : {};
            } catch (err) {
                renderError(resultEl, 'JSON payload is invalid: ' + err.message);
                return;
            }
            HS.fetchJSON(HS.API + '/v2/verify', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ payload: payload, code: code })
            })
                .then(function (res) {
                    if (!res.ok && res.status === 400) {
                        renderError(resultEl, res.body.error || 'Bad request');
                        return;
                    }
                    renderRecomputeResult(res.body, payload, code);
                })
                .catch(function () { renderError(resultEl, 'Network error. Please try again.'); });
        });
    }

    function prefillFromHash() {
        var hash = (location.hash || '').replace(/^#/, '');
        if (!hash) return;
        var input = id('registryCode');
        if (input) input.value = hash.trim();
    }

    document.addEventListener('DOMContentLoaded', function () {
        initRegistryForm();
        initRecomputeForm();
        prefillFromHash();
    });
})();
