/* Talaix — declarative data visualizations (no build step, no dependencies).
 *
 * Turns plain data-attributes into SVG/CSS graphics, so page authors can drop
 * a parameter straight into a visual without writing chart code:
 *
 *   Meter   <div class="viz-meter" data-viz="meter" data-label="Flood risk"
 *           data-level="Moderate" data-scale="Low,Moderate,High,Severe,Extreme"></div>
 *   Ring    <div class="viz-ring" data-viz="ring" data-value="72"
 *           data-title="ESRS E1 coverage" data-sub="of required datapoints"></div>
 *   Bars    <div class="viz-bars" data-viz="bars" data-values="3,4,2,5"
 *           data-labels="Fire,Flood,Heat,Drought" data-height="120"></div>
 *   Stat    <div class="viz-stat" data-viz="stat" data-value="10" data-label="hazards screened"></div>
 *   Legend  <div class="viz-legend" data-viz="legend"
 *           data-items="Observed:#10B981,Modelled:#0EA5E9,Unknown:#94A3B8"></div>
 *
 * Timeline and process-steps are pure HTML/CSS (see css/viz.css); no JS needed.
 * Auto-loaded on every page by chrome.js.
 */
(function () {
    'use strict';

    var LEVEL_COLORS = ['#10B981', '#84CC16', '#F59E0B', '#F97316', '#EF4444'];
    var DEFAULT_LEVELS = ['Low', 'Moderate', 'High', 'Severe', 'Extreme'];

    function el(tag, cls, text) {
        var e = document.createElement(tag);
        if (cls) e.className = cls;
        if (text !== undefined) e.textContent = text;
        return e;
    }

    function escapeHtml(s) {
        return String(s).replace(/[&<>"']/g, function (c) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
        });
    }

    /* ---- Meter -------------------------------------------------- */
    function levelIndex(value, levels) {
        if (typeof value === 'number' || /^\d+$/.test(String(value).trim())) {
            var n = parseInt(value, 10);
            return Math.max(0, Math.min(levels.length - 1, n));
        }
        var s = String(value).trim().toLowerCase();
        for (var i = 0; i < levels.length; i++) {
            if (levels[i].toLowerCase() === s) return i;
        }
        // Fuzzy: accept "severe"->"high-ish" fallbacks by first word match.
        return 0;
    }

    function renderMeter(node) {
        var label = node.getAttribute('data-label') || '';
        var levels = (node.getAttribute('data-scale') || DEFAULT_LEVELS.join(','))
            .split(',').map(function (s) { return s.trim(); }).filter(Boolean);
        if (!levels.length) levels = DEFAULT_LEVELS;
        var idx = levelIndex(node.getAttribute('data-level'), levels);
        var valueText = node.getAttribute('data-value') || levels[idx];
        var color = LEVEL_COLORS[Math.min(idx, LEVEL_COLORS.length - 1)];

        var head = el('div', 'viz-meter-head');
        head.appendChild(el('span', 'viz-meter-label', label));
        head.appendChild(el('span', 'viz-meter-value', valueText));

        var track = el('div', 'viz-meter-track');
        for (var i = 0; i < levels.length; i++) {
            var seg = el('span', 'viz-meter-seg');
            if (i <= idx) seg.style.background = LEVEL_COLORS[Math.min(i, LEVEL_COLORS.length - 1)];
            track.appendChild(seg);
        }

        var scale = el('div', 'viz-meter-scale');
        levels.forEach(function (l) { scale.appendChild(el('span', '', l)); });

        node.appendChild(head);
        node.appendChild(track);
        node.appendChild(scale);
    }

    /* ---- Ring (SVG donut) -------------------------------------- */
    var ringCounter = 0;
    function renderRing(node) {
        var value = Math.max(0, Math.min(100, parseInt(node.getAttribute('data-value') || '0', 10)));
        var title = node.getAttribute('data-title') || '';
        var sub = node.getAttribute('data-sub') || '';
        var id = 'vizRingGrad' + (++ringCounter);
        var r = 36, c = 2 * Math.PI * r;
        var offset = c * (1 - value / 100);

        var fig = el('div', 'viz-ring-fig');
        fig.innerHTML =
            '<svg viewBox="0 0 84 84" role="img" aria-label="' + escapeHtml(title + ': ' + value + '%') + '">' +
            '<defs><linearGradient id="' + id + '" x1="0" y1="0" x2="1" y2="1">' +
            '<stop offset="0%" stop-color="#0EA5E9"/><stop offset="100%" stop-color="#10B981"/>' +
            '</linearGradient></defs>' +
            '<circle class="viz-ring-bg" cx="42" cy="42" r="' + r + '"></circle>' +
            '<circle class="viz-ring-val" cx="42" cy="42" r="' + r + '" stroke="url(#' + id + ')" ' +
            'stroke-dasharray="' + c + '" stroke-dashoffset="' + offset + '"></circle></svg>' +
            '<div class="viz-ring-num">' + value + '%</div>';

        var body = el('div', 'viz-ring-body');
        body.appendChild(el('div', 'viz-ring-title', title));
        if (sub) body.appendChild(el('div', 'viz-ring-sub', sub));

        node.appendChild(fig);
        node.appendChild(body);
    }

    /* ---- Bars --------------------------------------------------- */
    function renderBars(node) {
        var values = (node.getAttribute('data-values') || '')
            .split(',').map(function (v) { return parseFloat(v) || 0; });
        var labels = (node.getAttribute('data-labels') || '')
            .split(',').map(function (s) { return s.trim(); });
        var max = Math.max.apply(null, values.concat([1]));
        var height = parseInt(node.getAttribute('data-height') || '120', 10);

        values.forEach(function (v, i) {
            var bar = el('div', 'viz-bar');
            var col = el('div', 'viz-bar-col');
            col.style.height = Math.max(4, Math.round((v / max) * height)) + 'px';
            if (v === 0) col.style.background = '#E2E8F0';
            bar.appendChild(el('span', 'viz-bar-value', String(v)));
            bar.appendChild(col);
            bar.appendChild(el('span', 'viz-bar-label', labels[i] || ''));
            node.appendChild(bar);
        });
    }

    /* ---- Stat (big number) -------------------------------------- */
    function renderStat(node) {
        var value = node.getAttribute('data-value') || '';
        var label = node.getAttribute('data-label') || '';
        node.appendChild(el('span', 'viz-stat-num' + (node.hasAttribute('data-grad') ? ' grad' : ''), value));
        if (label) node.appendChild(el('span', 'viz-stat-label', label));
    }

    /* ---- Legend ------------------------------------------------- */
    function renderLegend(node) {
        var items = (node.getAttribute('data-items') || '').split(',').map(function (s) { return s.trim(); }).filter(Boolean);
        items.forEach(function (item) {
            var parts = item.split(':');
            var label = parts[0] || '';
            var color = parts[1] || '#94A3B8';
            var li = el('span', 'viz-legend-item');
            var swatch = el('span', 'viz-legend-swatch');
            swatch.style.background = color;
            li.appendChild(swatch);
            li.appendChild(document.createTextNode(label));
            node.appendChild(li);
        });
    }

    function init() {
        var renderers = {
            meter: renderMeter,
            ring: renderRing,
            bars: renderBars,
            stat: renderStat,
            legend: renderLegend
        };
        document.querySelectorAll('[data-viz]').forEach(function (node) {
            var type = node.getAttribute('data-viz');
            if (renderers[type]) renderers[type](node);
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
