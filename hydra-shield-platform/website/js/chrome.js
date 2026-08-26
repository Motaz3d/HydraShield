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
 * Primary nav — grouped so the bar stays readable (single source of truth):
 * Intelligence · Map · Solutions ▾ · Learn ▾ · Explore ▾ + Account.
 * The legacy marketing pages stay reachable from the footer.
 */
(function () {
    'use strict';

    var PAGE = (document.body && document.body.getAttribute('data-page')) || '';

    /* Same base sniffing as js/api.js (duplicated on purpose: chrome.js must
     * stay self-contained — index.html loads it without api.js). */
    var API = (location.hostname === 'localhost' || location.hostname === '127.0.0.1')
        ? 'http://localhost:8051/api'
        : '/api';

    /* Top level: single links + groups (dropdowns on desktop, expanded
     * sections inside the mobile menu). IA: one Solutions mega-menu holds
     * the portals BY SOLUTION and BY SECTOR side by side — the same tool
     * may appear under several paths on purpose; repetition across entry
     * portals is a feature of the information architecture, not a bug. */
    var PRIMARY = [
        { id: 'intelligence', href: 'intelligence.html', label: 'Intelligence' },
        { id: 'map', href: 'map.html', label: 'Map' },
        {
            id: 'solutions', label: 'Solutions', mega: true, columns: [
                {
                    heading: 'By solution', children: [
                        { id: 'greenfinance', href: 'green-finance.html', label: 'Green Finance' },
                        { id: 'sustainability', href: 'sustainability.html', label: 'Sustainability & CSRD' },
                        { id: 'insurance', href: 'insurance.html', label: 'Insurance Risk' },
                        { id: 'supplychain', href: 'supplychain.html', label: 'Supply Chain & EUDR' },
                        { id: 'forensics', href: 'forensics.html', label: 'Forensics' },
                        { id: 'reports', href: 'reports.html', label: 'Reports & Builder' }
                    ]
                },
                {
                    heading: 'By sector', children: [
                        { id: 'for-banks', href: 'for-banks.html', label: 'Banks & lenders' },
                        { id: 'for-insurance', href: 'for-insurance.html', label: 'Insurance' },
                        { id: 'for-investors', href: 'for-investors.html', label: 'Investors' },
                        { id: 'for-real-estate', href: 'for-real-estate.html', label: 'Real estate' },
                        { id: 'for-consulting', href: 'for-consulting.html', label: 'Consultants & auditors' },
                        { id: 'for-government', href: 'for-government.html', label: 'Government' }
                    ]
                }
            ]
        },
        {
            id: 'learn', label: 'Learn', children: [
                { id: 'academy', href: 'academy.html', label: 'Academy' },
                { id: 'briefs', href: 'briefs.html', label: 'Briefs' }
            ]
        },
        {
            id: 'explore', label: 'Explore', children: [
                { id: 'mapcheck', href: 'mapcheck.html', label: 'Map Check' },
                { id: 'events', href: 'events.html', label: 'Events' },
                { id: 'solutions-hub', href: 'solutions.html', label: 'Hazard solutions' },
                { id: 'funding', href: 'funding.html', label: 'Funding' },
                { id: 'economy', href: 'economy.html', label: 'Economy' }
            ]
        }
    ];

    /* Flat list of every linkable item (footer + anywhere a full map is needed). */
    var ALL_LINKS = [];
    PRIMARY.forEach(function (item) {
        if (item.columns) {
            item.columns.forEach(function (col) {
                col.children.forEach(function (c) { ALL_LINKS.push(c); });
            });
        } else if (item.children) {
            item.children.forEach(function (c) { ALL_LINKS.push(c); });
        } else {
            ALL_LINKS.push(item);
        }
    });

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

    function navGroup(item) {
        if (item.mega) {
            var megaActive = item.columns.some(function (col) {
                return col.children.some(function (c) { return c.id === PAGE; });
            });
            var cols = item.columns.map(function (col) {
                var links = col.children.map(function (c) {
                    var active = c.id === PAGE ? ' class="active" aria-current="page"' : '';
                    return '<li><a href="' + c.href + '"' + active + '>' + c.label + '</a></li>';
                }).join('');
                return '<div class="nav-mega-col"><h4>' + col.heading + '</h4><ul>' + links + '</ul></div>';
            }).join('');
            return '<li class="nav-group nav-mega">' +
                '<button type="button" class="nav-group-toggle' + (megaActive ? ' active' : '') + '"' +
                ' aria-haspopup="true" aria-expanded="false">' +
                item.label + ' <span class="chevron" aria-hidden="true">▾</span></button>' +
                '<div class="nav-dropdown nav-dropdown-mega">' + cols + '</div></li>';
        }
        var groupActive = item.children.some(function (c) { return c.id === PAGE; });
        var links = item.children.map(function (c) {
            var active = c.id === PAGE ? ' class="active" aria-current="page"' : '';
            return '<li><a href="' + c.href + '"' + active + '>' + c.label + '</a></li>';
        }).join('');
        return '<li class="nav-group">' +
            '<button type="button" class="nav-group-toggle' + (groupActive ? ' active' : '') + '"' +
            ' aria-haspopup="true" aria-expanded="false">' +
            item.label + ' <span class="chevron" aria-hidden="true">▾</span></button>' +
            '<ul class="nav-dropdown">' + links + '</ul></li>';
    }

    function renderHeader(mount) {
        var links = PRIMARY.map(function (i) {
            return (i.children || i.columns) ? navGroup(i) : navLink(i);
        }).join('');
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
            ALL_LINKS.map(function (i) { return '<li><a href="' + i.href + '">' + i.label + '</a></li>'; }).join('') +
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

    /* Nav dropdown groups: click toggles (touch/keyboard), outside click and
     * Escape close; desktop also opens on :hover via CSS. */
    function closeNavGroups(except) {
        document.querySelectorAll('.nav-group.open').forEach(function (li) {
            if (except && li === except) return;
            li.classList.remove('open');
            li.querySelector('.nav-group-toggle').setAttribute('aria-expanded', 'false');
        });
    }

    function wireNavGroups() {
        document.querySelectorAll('.nav-group-toggle').forEach(function (btn) {
            btn.addEventListener('click', function (ev) {
                ev.stopPropagation();
                var li = btn.parentElement;
                var willOpen = !li.classList.contains('open');
                closeNavGroups(null);
                li.classList.toggle('open', willOpen);
                btn.setAttribute('aria-expanded', willOpen ? 'true' : 'false');
            });
        });
        document.addEventListener('click', function () { closeNavGroups(null); });
        document.addEventListener('keydown', function (ev) {
            if (ev.key === 'Escape') closeNavGroups(null);
        });
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

    /* Session-aware CTA visibility (site-wide design rule):
     * elements marked .guest-only (create-account / subscribe invitations)
     * are shown ONLY to guests; elements marked .user-only start hidden
     * (inline display:none) and are revealed only for a signed-in session.
     * A signed-in user never sees a register/subscribe prompt. */
    function reflectCta(signedIn) {
        var guests = document.querySelectorAll('.guest-only');
        var users = document.querySelectorAll('.user-only');
        Array.prototype.forEach.call(guests, function (el) {
            el.style.display = signedIn ? 'none' : '';
        });
        Array.prototype.forEach.call(users, function (el) {
            el.style.display = signedIn ? '' : 'none';
        });
    }

    /* Auth-aware nav: when a session cookie is present, append a "Sign out"
     * action next to the Account link so visitors can leave their session
     * from any page. Guests keep the plain Account link. */
    function reflectSession() {
        function go() { location.href = 'account.html'; }
        fetch(API + '/v2/account', { credentials: 'same-origin' })
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (account) {
                reflectCta(!!account);
                if (!account) return;
                var navLinks = document.getElementById('navLinks');
                if (!navLinks || document.getElementById('navSignOut')) return;
                var li = document.createElement('li');
                li.className = 'nav-signout';
                var a = document.createElement('a');
                a.href = 'account.html';
                a.id = 'navSignOut';
                a.textContent = 'Sign out';
                a.addEventListener('click', function (ev) {
                    ev.preventDefault();
                    fetch(API + '/v2/auth/logout', {
                        method: 'POST',
                        credentials: 'same-origin',
                        headers: { 'Content-Type': 'application/json' },
                        body: '{}'
                    }).then(go, go);
                });
                li.appendChild(a);
                navLinks.appendChild(li);
            })
            .catch(function () { /* guest or API unreachable — keep default nav */ });
    }

    function init() {
        var header = document.getElementById('site-header');
        var footer = document.getElementById('site-footer');
        if (header) renderHeader(header);
        if (footer) renderFooter(footer);
        wire();
        wireNavGroups();
        reflectSession();
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
