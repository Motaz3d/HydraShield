/* Talaix — per-page tier badge + share bar.
 *
 * Injects a small classification bar under each page's H1 so visitors always
 * know how the current service is priced. The bar includes tier chip(s), a
 * short note, a Subscribe CTA (guests only) and a plain-text share widget.
 */
(function () {
    'use strict';

    if (window.HS_TIERS_INJECTED) return;
    window.HS_TIERS_INJECTED = true;

    var PAGE = (document.body && document.body.getAttribute('data-page')) || '';

    var CONFIG = {
        map: {
            chips: [{ cls: 'tier-free', label: 'Free' }],
            note: 'Full historical depth and API access with Professional.'
        },
        intelligence: {
            chips: [{ cls: 'tier-free', label: 'Free' }],
            note: 'Economic exposure and solutions sections in full with Professional.'
        },
        reports: {
            chips: [
                { cls: 'tier-free', label: 'Free · Simple' },
                { cls: 'tier-onetime', label: 'One-time €19–€39' }
            ],
            note: 'Simple report free forever. Decision €19 · Scientific €39 per location, no subscription needed.'
        },
        insurance: {
            chips: [
                { cls: 'tier-free', label: 'Free up to 25' },
                { cls: 'tier-sub', label: 'Subscription 100' }
            ],
            note: 'Batch checks up to 25 assets free, 100 with a subscription; portfolio scale via Enterprise.'
        },
        greenfinance: {
            chips: [
                { cls: 'tier-free', label: 'Free up to 25' },
                { cls: 'tier-sub', label: 'Subscription 100' }
            ],
            note: 'Batch checks up to 25 assets free, 100 with a subscription; portfolio scale via Enterprise.'
        },
        supplychain: {
            chips: [
                { cls: 'tier-free', label: 'Free up to 25' },
                { cls: 'tier-sub', label: 'Subscription 100' }
            ],
            note: 'Batch checks up to 25 assets free, 100 with a subscription; portfolio scale via Enterprise.'
        },
        sustainability: {
            chips: [
                { cls: 'tier-free', label: 'Free up to 25' },
                { cls: 'tier-sub', label: 'Subscription 100' }
            ],
            note: 'Batch checks up to 25 assets free, 100 with a subscription; portfolio scale via Enterprise.'
        },
        forensics: {
            chips: [{ cls: 'tier-enterprise', label: 'Enterprise' }],
            note: 'Forensic evidence packs are delivered at contract scope — contact us.'
        },
        licensing: {
            chips: [{ cls: 'tier-free', label: 'Free' }],
            note: 'Pre-draft dossiers are free at screening level.'
        },
        academy: {
            chips: [{ cls: 'tier-free', label: 'Free' }],
            note: 'The pilot course is free. Academic institutions get Professional free on application.'
        },
        press: {
            chips: [{ cls: 'tier-free', label: 'Free' }],
            note: 'English packs are public; other languages with a subscription.'
        }
    };

    function esc(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    function buildChips(chips) {
        return chips.map(function (c) {
            return '<span class="tier-chip ' + esc(c.cls) + '">' + esc(c.label) + '</span>';
        }).join(' ');
    }

    function shareUrl() {
        return encodeURIComponent(location.href);
    }

    function shareText() {
        return encodeURIComponent(document.title || 'Talaix climate-risk intelligence');
    }

    function renderBar(cfg) {
        var main = document.querySelector('main .container');
        var h1 = main ? main.querySelector('h1') : document.querySelector('h1');
        if (!h1) return;

        var chips = buildChips(cfg.chips);
        var bar = document.createElement('div');
        bar.className = 'tier-bar';
        bar.innerHTML =
            '<div class="tier-badges">' + chips + '</div>' +
            '<p class="tier-note">' + esc(cfg.note) + '</p>' +
            '<div class="tier-actions">' +
            '<a class="btn-action btn-sm guest-only" href="pricing.html">Subscribe</a>' +
            '<span class="tier-share">' +
            '<span class="tier-share-label">Share:</span>' +
            '<button type="button" class="btn-quiet btn-sm tier-share-copy" aria-label="Copy page link">Copy link</button>' +
            '<a class="btn-quiet btn-sm" href="https://twitter.com/intent/tweet?url=' + shareUrl() + '&text=' + shareText() + '" target="_blank" rel="noopener" aria-label="Share on X">X</a>' +
            '<a class="btn-quiet btn-sm" href="https://www.linkedin.com/sharing/share-offsite/?url=' + shareUrl() + '" target="_blank" rel="noopener" aria-label="Share on LinkedIn">in</a>' +
            '<a class="btn-quiet btn-sm" href="mailto:?subject=' + shareText() + '&body=' + shareUrl() + '" aria-label="Share by email">✉</a>' +
            '</span>' +
            '</div>';

        var lead = main ? main.querySelector('.page-lead') : null;
        if (lead && h1.compareDocumentPosition(lead) & Node.DOCUMENT_POSITION_FOLLOWING) {
            lead.parentNode.insertBefore(bar, lead.nextSibling);
        } else {
            h1.parentNode.insertBefore(bar, h1.nextSibling);
        }

        var copyBtn = bar.querySelector('.tier-share-copy');
        if (copyBtn) {
            copyBtn.addEventListener('click', function () {
                var original = copyBtn.textContent;
                function done() {
                    setTimeout(function () { copyBtn.textContent = original; }, 2000);
                }
                if (navigator.clipboard && navigator.clipboard.writeText) {
                    navigator.clipboard.writeText(location.href).then(function () {
                        copyBtn.textContent = 'Copied';
                        done();
                    }).catch(function () {
                        window.prompt('Copy this link:', location.href);
                    });
                } else {
                    window.prompt('Copy this link:', location.href);
                }
            });
        }

        if (window.HS_REFLECT_CTA && typeof window.HS_REFLECT_CTA === 'function') {
            // chrome.js calls this after the session fetch; re-apply for the
            // newly injected subscribe link. Infer signed-in state from the
            // visibility chrome.js already set on existing guest-only elements.
            try {
                var guestEl = document.querySelector('.guest-only');
                var signedIn = guestEl && window.getComputedStyle(guestEl).display === 'none';
                window.HS_REFLECT_CTA(signedIn);
            } catch (e) { /* ignore */ }
        }
    }

    function init() {
        var cfg = CONFIG[PAGE];
        if (!cfg) return;
        renderBar(cfg);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
