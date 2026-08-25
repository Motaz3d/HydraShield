/* Talaix — operator tab switcher for admin.html.
 *
 * Bridges the Commercial Center (admin.js), Targets and Site statistics
 * (marketing.js) tabs. Lazy-mounts marketing panels on first open and
 * supports #targets / #stats deep-linking.
 */
(function () {
    'use strict';

    var mounted = { overview: true, targets: false, stats: false, users: false };

    function el(id) { return document.getElementById(id); }

    function activateTab(id) {
        var valid = id === 'overview' || id === 'targets' || id === 'stats' || id === 'users';
        if (!valid) id = 'overview';

        Array.prototype.forEach.call(document.querySelectorAll('.mkt-tab'), function (tab) {
            var active = tab.getAttribute('aria-controls') === id;
            tab.setAttribute('aria-selected', active ? 'true' : 'false');
            tab.setAttribute('tabindex', active ? '0' : '-1');
        });

        Array.prototype.forEach.call(document.querySelectorAll('.mkt-tabpanel'), function (panel) {
            panel.classList.toggle('active', panel.id === id);
        });

        if (id === 'targets' && !mounted.targets && window.HSMarketing) {
            HSMarketing.mountTargets(el('targets'));
            mounted.targets = true;
        }
        if (id === 'stats' && !mounted.stats && window.HSMarketing) {
            HSMarketing.mountStats(el('stats'));
            mounted.stats = true;
        }
        if (id === 'users' && !mounted.users && window.HSAdmin && HSAdmin.mountUsers) {
            HSAdmin.mountUsers(el('users'));
            mounted.users = true;
        }
        if (id === 'overview' && window.HSAdmin && HSAdmin.onShow) {
            HSAdmin.onShow('overview');
        }

        if (history.replaceState) {
            history.replaceState(null, '', '#' + id);
        }
    }

    function handleHash() {
        var hash = location.hash.replace('#', '');
        if (hash === 'targets' || hash === 'stats' || hash === 'users') {
            activateTab(hash);
        }
    }

    Array.prototype.forEach.call(document.querySelectorAll('.mkt-tab'), function (tab) {
        tab.addEventListener('click', function () {
            activateTab(tab.getAttribute('aria-controls'));
        });
    });

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', handleHash);
    } else {
        handleHash();
    }
})();
