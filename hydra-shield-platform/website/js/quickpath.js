/* Talaix QuickPath — short guided path (stepper) for service pages.
 *
 * Adds a compact, sticky stepper above a page's key sections so the path to
 * the goal is short and obvious, while the full page stays below (nothing lost).
 *
 * Usage — add a mount div anywhere on the page:
 *     <div class="quickpath" data-steps="applicability:Check your scope,build:Build the pack"></div>
 *   Each entry is `sectionId:Label` (label optional; falls back to the id).
 *
 * Self-contained: injects its own styles only when a mount is present, and is
 * a no-op on pages without one. Loaded lazily from chrome.js so every service
 * page can opt in without extra wiring.
 */
(function () {
    'use strict';

    var CSS = [
        '.qp{position:sticky;top:64px;z-index:40;background:rgba(255,255,255,.94);backdrop-filter:blur(10px);border:1px solid rgba(15,23,42,.08);border-radius:14px;box-shadow:0 8px 24px -16px rgba(15,23,42,.18);margin:16px 0 28px;padding:12px 16px}',
        '.qp-inner{display:flex;align-items:center;justify-content:space-between;gap:14px;flex-wrap:wrap}',
        '.qp-chips{display:flex;align-items:center;flex-wrap:wrap;gap:2px}',
        '.qp-step{display:inline-flex;align-items:center;gap:9px;background:none;border:none;cursor:pointer;padding:8px 12px;border-radius:11px;font-family:"Space Grotesk",sans-serif;font-weight:600;font-size:.9rem;color:var(--text-light);transition:color .15s ease,background .15s ease}',
        '.qp-step:hover{color:var(--primary)}',
        '.qp-num{width:26px;height:26px;flex:0 0 auto;border-radius:50%;display:grid;place-items:center;font-size:.82rem;background:#EEF2F7;color:var(--text-light);transition:background .15s ease,color .15s ease}',
        '.qp-label{line-height:1.2}',
        '.qp-step.active{color:var(--text);background:rgba(14,165,233,.10)}',
        '.qp-step.active .qp-num{background:var(--primary);color:#fff}',
        '.qp-step.done .qp-num{background:var(--brand-teal);color:#fff}',
        '.qp-sep{width:18px;height:2px;background:rgba(15,23,42,.12);border-radius:2px;margin:0 6px}',
        '.qp-nav{display:flex;gap:8px}',
        '.qp-prev,.qp-next{font-family:"Space Grotesk",sans-serif;font-weight:600;font-size:.9rem;padding:9px 16px;border-radius:10px;border:1px solid transparent;cursor:pointer;transition:background .15s ease,color .15s ease,border-color .15s ease}',
        '.qp-next{background:var(--primary);color:#fff}',
        '.qp-next:hover{background:var(--primary-dark)}',
        '.qp-prev{background:transparent;color:var(--text-light);border-color:rgba(15,23,42,.15)}',
        '.qp-prev:disabled{opacity:.4;cursor:not-allowed}',
        '.qp-prev:not(:disabled):hover{color:var(--primary);border-color:var(--primary)}',
        '@media(max-width:640px){.qp{position:relative;top:auto}.qp-inner{flex-direction:column;align-items:stretch}.qp-nav{justify-content:space-between}}'
    ].join('\n');

    function parseSteps(raw) {
        return (raw || '').split(',').map(function (s) {
            var parts = s.split(':');
            var id = parts[0].trim();
            var label = (parts[1] || parts[0]).trim();
            return id ? { id: id, label: label } : null;
        }).filter(Boolean);
    }

    function mountOne(el) {
        var targets = parseSteps(el.getAttribute('data-steps')).map(function (s) {
            return { label: s.label, el: document.getElementById(s.id) };
        }).filter(function (t) { return t.el; });
        if (targets.length < 2) return;

        var bar = document.createElement('div');
        bar.className = 'qp';
        var chips = targets.map(function (t, i) {
            return '<button type="button" class="qp-step' + (i === 0 ? ' active' : '') + '" data-i="' + i + '">' +
                '<span class="qp-num">' + (i + 1) + '</span><span class="qp-label">' + t.label + '</span></button>';
        }).join('<span class="qp-sep" aria-hidden="true"></span>');
        bar.innerHTML = '<div class="qp-inner"><div class="qp-chips">' + chips + '</div>' +
            '<div class="qp-nav"><button type="button" class="qp-prev" disabled>← Back</button>' +
            '<button type="button" class="qp-next">Continue →</button></div></div>';
        el.appendChild(bar);

        var stepBtns = bar.querySelectorAll('.qp-step');
        var prevBtn = bar.querySelector('.qp-prev');
        var nextBtn = bar.querySelector('.qp-next');
        var current = 0;

        function setActive(i) {
            current = i;
            stepBtns.forEach(function (b, j) {
                b.classList.toggle('active', j === i);
                b.classList.toggle('done', j < i);
            });
            prevBtn.disabled = i === 0;
            nextBtn.textContent = i === targets.length - 1 ? 'Done ✓' : 'Continue →';
        }

        function go(i) {
            setActive(i);
            var y = targets[i].el.getBoundingClientRect().top + window.pageYOffset - 130;
            window.scrollTo({ top: y, behavior: 'smooth' });
        }

        stepBtns.forEach(function (b, i) {
            b.addEventListener('click', function () { go(i); });
        });
        nextBtn.addEventListener('click', function () { go(Math.min(current + 1, targets.length - 1)); });
        prevBtn.addEventListener('click', function () { go(Math.max(current - 1, 0)); });

        var ticking = false;
        window.addEventListener('scroll', function () {
            if (ticking) return;
            ticking = true;
            requestAnimationFrame(function () {
                var idx = current;
                targets.forEach(function (t, i) {
                    if (t.el.getBoundingClientRect().top < window.innerHeight * 0.4) idx = i;
                });
                if (idx !== current) setActive(idx);
                ticking = false;
            });
        }, { passive: true });
    }

    function init() {
        var mounts = document.querySelectorAll('.quickpath');
        if (!mounts.length) return;
        var style = document.createElement('style');
        style.textContent = CSS;
        document.head.appendChild(style);
        mounts.forEach(mountOne);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
