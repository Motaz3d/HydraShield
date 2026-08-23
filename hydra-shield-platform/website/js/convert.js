/* Talaix — conversion engine (privacy-conscious, first-party).
 *
 * One central conversion policy (CONVERSION_CONFIG) — thresholds and
 * messages are NOT scattered across pages. Usage counters live only in
 * the visitor's browser (localStorage, keyed by the pseudonymous session
 * id from analytics.js) — no fingerprinting, no server-side identity,
 * DNT respected. Analytics events (cta_viewed/cta_clicked/…) go through
 * the whitelisted first-party beacon.
 *
 * Principles (docs/CONVERSION_STRATEGY.md): value first — the first
 * analysis is never gated; prompts escalate gently with demonstrated
 * repeated use; one quiet strip per surface; dismissal persists.
 */
(function () {
    'use strict';

    /* Central conversion policy — the single place thresholds live. */
    var CONVERSION_CONFIG = {
        thresholds: {
            account_nudge: 2,   // 2nd high-value analysis → account CTA
            monitor_nudge: 3,   // 3rd+ → save & monitor CTA
            strong_nudge: 5,    // 5th+ → professional capabilities CTA
            business_nudge: 8   // 8th+ → business/organization CTA
        },
        // high-value actions counted toward the thresholds
        high_value_actions: ['location_analyzed', 'solution_viewed',
                             'report_generated', 'funding_viewed'],
        messages: {
            account: 'You are getting real value from Talaix. Create a free account to save analyses, monitor locations and receive updates.',
            monitor: 'Save this and monitor it — Talaix watches so you don\'t have to.',
            professional: 'Heavy use detected — professional capabilities (more monitoring, SMS alerts, API) may fit you. Subscription required; contact us for business.',
            business: 'This looks like organizational use — business/government arrangements offer many monitored locations, teams, API and support. Contact us.'
        }
    };

    var DISMISS_KEY = 'hs_convert_dismissed';
    var USAGE_KEY = 'hs_usage';

    function readJSON(key) {
        try { return JSON.parse(localStorage.getItem(key) || '{}'); }
        catch (e) { return {}; }
    }

    function writeJSON(key, obj) {
        try { localStorage.setItem(key, JSON.stringify(obj)); } catch (e) { /* ignore */ }
    }

    function dismissed(context) { return !!readJSON(DISMISS_KEY)[context]; }
    function dismiss(context) {
        var d = readJSON(DISMISS_KEY);
        d[context] = true;
        writeJSON(DISMISS_KEY, d);
    }

    /* Record a high-value usage action (local counter + analytics event). */
    function trackAction(action, props) {
        var usage = readJSON(USAGE_KEY);
        usage[action] = (usage[action] || 0) + 1;
        writeJSON(USAGE_KEY, usage);
        if (window.HS && HS.track) HS.track(action, props || {});
        return usage[action];
    }

    /* Total high-value actions across surfaces. */
    function highValueCount() {
        var usage = readJSON(USAGE_KEY);
        return CONVERSION_CONFIG.high_value_actions.reduce(function (n, a) {
            return n + (usage[a] || 0);
        }, 0);
    }

    /* Which escalation tier applies right now (or null). */
    function currentTier() {
        var n = highValueCount();
        var t = CONVERSION_CONFIG.thresholds;
        if (n >= t.business_nudge) return 'business';
        if (n >= t.strong_nudge) return 'professional';
        if (n >= t.monitor_nudge) return 'monitor';
        if (n >= t.account_nudge) return 'account';
        return null;
    }

    /* HSConvert.show({mount, context, text, cta, href}) — one quiet strip. */
    function show(opts) {
        var mount = document.getElementById(opts.mount);
        if (!mount || dismissed(opts.context)) return;
        if (mount.querySelector('.convert-strip')) return;

        var strip = document.createElement('div');
        strip.className = 'convert-strip notice notice-info';
        strip.style.cssText = 'display:flex;align-items:center;gap:12px;' +
            'justify-content:space-between;flex-wrap:wrap;margin-top:14px;';

        var text = document.createElement('span');
        text.textContent = opts.text + ' ';
        var link = document.createElement('a');
        link.className = 'text-link';
        link.href = opts.href;
        link.textContent = opts.cta + ' →';
        link.addEventListener('click', function () {
            if (window.HS && HS.track) HS.track('cta_clicked',
                { feature: opts.context });
        });
        text.appendChild(link);

        var close = document.createElement('button');
        close.type = 'button';
        close.className = 'btn-action btn-quiet';
        close.style.padding = '2px 10px';
        close.textContent = 'Not now';
        close.addEventListener('click', function () {
            dismiss(opts.context);
            strip.remove();
        });

        strip.appendChild(text);
        strip.appendChild(close);
        mount.appendChild(strip);
        if (window.HS && HS.track) HS.track('cta_viewed', { feature: opts.context });
    }

    /* HSConvert.evaluate(mountId) — threshold-driven nudge for heavy use. */
    function evaluate(mountId) {
        var tier = currentTier();
        if (!tier) return;
        show({
            mount: mountId,
            context: 'tier_' + tier,
            text: CONVERSION_CONFIG.messages[tier],
            cta: tier === 'business' ? 'Contact us'
                : (tier === 'professional' ? 'Explore professional capabilities'
                : (tier === 'monitor' ? 'Save and monitor' : 'Create a free account')),
            href: tier === 'business' ? 'contact.html' : 'account.html'
        });
    }

    window.HSConvert = {
        show: show,
        evaluate: evaluate,
        trackAction: trackAction,
        _config: CONVERSION_CONFIG   // exposed for tests/inspection
    };
})();
