/* HydraShield — contextual conversion prompts (Phase F).
 *
 * One quiet, contextual invitation per surface — "save this analysis",
 * "monitor this area" — shown once, dismissible, never a modal, never
 * repeated after dismissal. The free core stays fully usable without an
 * account; the prompt appears only after a real result exists.
 *
 * Usage: <script src="js/convert.js" defer></script> + HSConvert.show({
 *   mount: 'elementId', text: '…', cta: '…', href: 'account.html' })
 */
(function () {
    'use strict';

    var DISMISS_KEY = 'hs_convert_dismissed';

    function dismissed(context) {
        try {
            var d = JSON.parse(localStorage.getItem(DISMISS_KEY) || '{}');
            return !!d[context];
        } catch (e) { return false; }
    }

    function dismiss(context) {
        try {
            var d = JSON.parse(localStorage.getItem(DISMISS_KEY) || '{}');
            d[context] = true;
            localStorage.setItem(DISMISS_KEY, JSON.stringify(d));
        } catch (e) { /* ignore */ }
    }

    /* HSConvert.show({mount, context, text, cta, href}) */
    function show(opts) {
        var mount = document.getElementById(opts.mount);
        if (!mount || dismissed(opts.context)) return;
        if (mount.querySelector('.convert-strip')) return; // one per mount

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
    }

    window.HSConvert = { show: show };
})();
