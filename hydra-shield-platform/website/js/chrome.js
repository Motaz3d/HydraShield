/* Talaix — shared site chrome (no build step).
 *
 * Every page carries:
 *     <body data-page="<page-id>">
 *     <div id="site-header"></div>
 *     … page content …
 *     <div id="site-footer"></div>
 *     <script src="js/chrome.js"></script>
 *
 * chrome.js injects the primary navigation + footer into those mounts and
 * highlights the active item from <body data-page>. This file is the single
 * source of truth for site navigation — an IA change is one edit here.
 *
 * Primary nav (docs/PLATFORM_ARCHITECTURE.md §3.8):
 * Intelligence · Map · Events · Solutions · Economy · Reports + Account.
 * The legacy marketing pages stay reachable from the footer.
 */
(function () {
    'use strict';

    var PAGE = (document.body && document.body.getAttribute('data-page')) || '';

    var PRIMARY = [
        { id: 'intelligence', href: 'intelligence.html', label: 'Intelligence' },
        { id: 'map', href: 'map.html', label: 'Map' },
        { id: 'events', href: 'events.html', label: 'Events' },
        { id: 'solutions', href: 'solutions.html', label: 'Solutions' },
        { id: 'funding', href: 'funding.html', label: 'Funding' },
        { id: 'economy', href: 'economy.html', label: 'Economy' },
        { id: 'reports', href: 'reports.html', label: 'Reports' }
    ];

    var LEGACY = [
        { href: 'problem.html', label: 'The Problem' },
        { href: 'solution.html', label: 'Our Solution' },
        { href: 'technology.html', label: 'Technology' },
        { href: 'applications.html', label: 'Applications' },
        { href: 'roadmap.html', label: 'Roadmap' },
        { href: 'story.html', label: 'Story' },
        { href: 'privacy.html', label: 'Privacy' },
        { href: 'contact.html', label: 'Contact' }
    ];

    var LOGO_SVG =
        '<svg class="logo-icon" viewBox="0 0 40 40" fill="none" xmlns="http://www.w3.org/2000/svg">' +
        '<path d="M20 2L36 10V20C36 29.5 29 37 20 39C11 37 4 29.5 4 20V10L20 2Z" fill="#0EA5E9" fill-opacity="0.2" stroke="#0EA5E9" stroke-width="2"/>' +
        '<path d="M20 8L30 13V20C30 25.5 25.5 30.5 20 32C14.5 30.5 10 25.5 10 20V13L20 8Z" fill="#0EA5E9" fill-opacity="0.4"/>' +
        '<path d="M20 14L25 17V21C25 23.5 22.5 25.5 20 26.5C17.5 25.5 15 23.5 15 21V17L20 14Z" fill="#7DD3FC"/>' +
        '</svg>';

    function navLink(item) {
        var active = item.id === PAGE ? ' class="active" aria-current="page"' : '';
        return '<li><a href="' + item.href + '"' + active + '>' + item.label + '</a></li>';
    }

    function renderHeader(mount) {
        var links = PRIMARY.map(navLink).join('');
        var accountActive = PAGE === 'account' ? ' class="active" aria-current="page"' : '';
        mount.innerHTML =
            '<nav class="navbar" id="navbar">' +
            '<div class="container nav-container">' +
            '<a href="index.html" class="logo">' + LOGO_SVG +
            '<span class="logo-text">Tal<span class="logo-accent">aix</span></span></a>' +
            '<button class="hamburger" id="hamburger" aria-label="Menu" aria-expanded="false">' +
            '<span></span><span></span><span></span></button>' +
            '<ul class="nav-links" id="navLinks">' +
            links +
            '<li class="nav-account"><a href="account.html"' + accountActive + '>Account</a></li>' +
            '</ul>' +
            '</div></nav>';
    }

    function renderFooter(mount) {
        mount.innerHTML =
            '<footer class="footer">' +
            '<div class="container">' +
            '<div class="footer-grid">' +
            '<div class="footer-brand">' +
            '<a href="index.html" class="logo">' + LOGO_SVG +
            '<span class="logo-text">Tal<span class="logo-accent">aix</span></span></a>' +
            '<p>Climate Extreme Intelligence: the best available evidence on environmental ' +
            'extremes, their consequences, their economic meaning, and the actions that ' +
            'reduce exposure. Real data only — unavailable is stated, never filled in.</p>' +
            '</div>' +
            '<div class="footer-links"><h4>Platform</h4><ul>' +
            PRIMARY.map(function (i) { return '<li><a href="' + i.href + '">' + i.label + '</a></li>'; }).join('') +
            '<li><a href="account.html">Account</a></li>' +
            '<li><a href="dashboard.html">Wildfire analysis (full)</a></li>' +
            '</ul></div>' +
            '<div class="footer-links"><h4>About</h4><ul>' +
            LEGACY.map(function (i) { return '<li><a href="' + i.href + '">' + i.label + '</a></li>'; }).join('') +
            '</ul></div>' +
            '<div class="footer-links"><h4>Solutions for</h4><ul>' +
            '<li><a href="for-banks.html">Banks &amp; lenders</a></li>' +
            '<li><a href="for-consulting.html">Consultants</a></li>' +
            '<li><a href="for-investors.html">Investors</a></li>' +
            '<li><a href="for-insurance.html">Insurance</a></li>' +
            '<li><a href="for-real-estate.html">Real estate</a></li>' +
            '<li><a href="for-government.html">Government</a></li>' +
            '</ul></div>' +
            '<div class="footer-contact"><h4>Evidence</h4>' +
            '<p><a href="/sources">Data sources</a></p>' +
            '<p><a href="/api/sources" target="_blank" rel="noopener">Data-source registry (API)</a></p>' +
            '<p><a href="/api/v2/hazards" target="_blank" rel="noopener">Hazard registry (API)</a></p>' +
            '<p><a href="mailto:info@talaix.com">info@talaix.com</a></p>' +
            '</div>' +
            '</div>' +
            '<div class="footer-bottom">' +
            '<p>© 2026 Talaix Earth Systems. All rights reserved.<br>' +
            'Founder &amp; CEO: Motaz Omarien · <a href="mailto:info@talaix.com" style="color:inherit;">info@talaix.com</a></p>' +
            '<p>Evidence: OBSERVED · DOCUMENTED · REPORTED · MODELLED · INFERRED · UNKNOWN<br>' +
            'Time: OBSERVED · HISTORICAL · FORECAST · PROJECTED · SCENARIO</p>' +
            '</div>' +
            '</div></footer>';
    }

    function wire() {
        var navbar = document.getElementById('navbar');
        var hamburger = document.getElementById('hamburger');
        var navLinks = document.getElementById('navLinks');

        if (navbar) {
            window.addEventListener('scroll', function () {
                if (window.scrollY > 50) navbar.classList.add('scrolled');
                else navbar.classList.remove('scrolled');
            });
        }
        if (hamburger && navLinks) {
            hamburger.addEventListener('click', function () {
                var open = navLinks.classList.toggle('active');
                hamburger.classList.toggle('active', open);
                hamburger.setAttribute('aria-expanded', open ? 'true' : 'false');
            });
            navLinks.querySelectorAll('a').forEach(function (link) {
                link.addEventListener('click', function () {
                    navLinks.classList.remove('active');
                    hamburger.classList.remove('active');
                    hamburger.setAttribute('aria-expanded', 'false');
                });
            });
        }
    }

    function init() {
        var header = document.getElementById('site-header');
        var footer = document.getElementById('site-footer');
        if (header) renderHeader(header);
        if (footer) renderFooter(footer);
        wire();
        // First-party product analytics beacon (privacy-conscious; see
        // js/analytics.js + docs/PRODUCT_ANALYTICS.md). Loaded here so every
        // page gets it; honours Do Not Track.
        var beacon = document.createElement('script');
        beacon.src = 'js/analytics.js';
        beacon.defer = true;
        document.head.appendChild(beacon);
    }

    // chrome.js is included after the mount divs, so the DOM is ready.
    init();
})();
