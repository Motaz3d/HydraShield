/* Talaix Academy page (academy.html).
 *
 * Loads course + glossary, renders modules, quizzes, progress and certificates.
 */
(function () {
    'use strict';

    var esc = HS.esc, fetchJSON = HS.fetchJSON, API = HS.API;

    function el(id) { return document.getElementById(id); }

    var COURSE_ID = 'climate-risk-finance';
    var course = null;
    var glossary = {};
    var progress = {};
    var currentModuleId = null;

    function renderStatus(mountId, kind, html) {
        el(mountId).innerHTML = '<div class="notice notice-' + esc(kind) + '">' + html + '</div>';
    }

    function clearStatus(mountId) {
        el(mountId).innerHTML = '';
    }

    function authPrompt(action) {
        return 'Please <a class="text-link" href="account.html">sign in</a> to ' + esc(action) + '.';
    }

    function loadCourse() {
        return fetchJSON(API + '/v2/academy/courses/' + COURSE_ID).then(function (res) {
            if (!res.ok || !res.body || !res.body.course) return null;
            course = res.body.course;
            return course;
        });
    }

    function loadGlossary() {
        return fetchJSON(API + '/v2/academy/glossary').then(function (res) {
            if (!res.ok || !res.body || !res.body.terms) return;
            glossary = {};
            res.body.terms.forEach(function (t) { glossary[t.id] = t; });
        });
    }

    function loadProgress() {
        return fetchJSON(API + '/v2/academy/progress?course_id=' + COURSE_ID, {
            credentials: 'same-origin',
        }).then(function (res) {
            if (!res.ok) return;
            progress = {};
            (res.body.progress || []).forEach(function (r) {
                progress[r.module_id] = r;
            });
        });
    }

    function moduleState(moduleId) {
        var p = progress[moduleId];
        if (!p) return { label: 'Not started', className: 'chip-unknown' };
        if (p.passed) return { label: 'Passed (' + p.best_correct + '/' + p.best_total + ')', className: 'chip-observed' };
        return { label: 'Best: ' + p.best_correct + '/' + p.best_total, className: 'chip-error' };
    }

    function renderModuleList() {
        if (!course) return;
        el('courseMeta').textContent = course.audience + ' · ' + course.modules.length + ' modules';
        var html = '<div class="table-scroll"><table class="data-table"><thead><tr>' +
            '<th>#</th><th>Module</th><th>Minutes</th><th>Status</th><th></th>' +
            '</tr></thead><tbody>';
        course.modules.forEach(function (m, idx) {
            var state = moduleState(m.id);
            html += '<tr>' +
                '<td>' + (idx + 1) + '</td>' +
                '<td><strong>' + esc(m.title) + '</strong><br><span class="muted small">' + esc(m.summary) + '</span></td>' +
                '<td>' + esc(m.minutes) + '</td>' +
                '<td><span class="chip ' + state.className + '">' + esc(state.label) + '</span></td>' +
                '<td><button class="btn-action btn-sm" data-module="' + esc(m.id) + '">Open</button></td>' +
                '</tr>';
        });
        html += '</tbody></table></div>';
        el('moduleList').innerHTML = html;
        el('moduleList').querySelectorAll('button[data-module]').forEach(function (btn) {
            btn.addEventListener('click', function () { openModule(btn.getAttribute('data-module')); });
        });
    }

    function termChip(termId) {
        var t = glossary[termId];
        if (!t) return '';
        return '<button class="chip chip-documented term-chip" data-term="' + esc(termId) + '">' + esc(t.term) + '</button>';
    }

    function showTerm(termId) {
        var t = glossary[termId];
        if (!t) return;
        var html = '<div class="notice notice-info">' +
            '<strong>' + esc(t.term) + '</strong> — ' + esc(t.short) +
            '<p class="muted small">' + esc(t.long) + '</p>';
        if (t.platform_link) {
            html += '<p><a class="text-link" href="' + esc(t.platform_link) + '">See on the platform →</a></p>';
        }
        html += '</div>';
        el('moduleQuizStatus').innerHTML = html;
    }

    function openModule(moduleId) {
        var m = null;
        course.modules.forEach(function (mod) { if (mod.id === moduleId) m = mod; });
        if (!m) return;
        currentModuleId = moduleId;
        el('moduleReaderPanel').style.display = 'block';
        el('moduleReaderPanel').scrollIntoView({ behavior: 'smooth' });
        el('moduleReaderTitle').textContent = m.title;
        el('moduleReaderMeta').textContent = m.minutes + ' minutes · ' + m.sections.length + ' sections';

        var html = '';
        (m.sections || []).forEach(function (s) {
            html += '<h3>' + esc(s.heading) + '</h3>';
            html += '<p>' + esc(s.body).replace(/\n/g, '<br>') + '</p>';
        });

        if (m.key_terms && m.key_terms.length) {
            html += '<p><strong>Key terms:</strong> ' + m.key_terms.map(termChip).join(' ') + '</p>';
        }
        if (m.try_it && m.try_it.href) {
            html += '<p><a class="btn-secondary" href="' + esc(m.try_it.href) + '" target="_blank" rel="noopener">' + esc(m.try_it.label) + '</a></p>';
        }
        el('moduleReaderContent').innerHTML = html;
        el('moduleReaderContent').querySelectorAll('.term-chip').forEach(function (btn) {
            btn.addEventListener('click', function () { showTerm(btn.getAttribute('data-term')); });
        });

        renderQuiz(m);
        clearStatus('moduleQuizStatus');
        el('moduleQuizResult').innerHTML = '';
    }

    function renderQuiz(m) {
        if (!m.quiz || !m.quiz.length) {
            el('moduleQuiz').innerHTML = '<p class="muted small">No quiz for this module.</p>';
            return;
        }
        var html = '<h3>Module quiz</h3>';
        m.quiz.forEach(function (q, idx) {
            html += '<div class="form-group quiz-question" data-idx="' + idx + '">';
            html += '<label>' + (idx + 1) + '. ' + esc(q.question) + '</label>';
            (q.options || []).forEach(function (opt, optIdx) {
                var name = 'q_' + idx;
                var id = name + '_' + optIdx;
                html += '<div class="radio-option">' +
                    '<input type="radio" name="' + name + '" id="' + id + '" value="' + optIdx + '">' +
                    '<label for="' + id + '">' + esc(opt) + '</label></div>';
            });
            html += '</div>';
        });
        html += '<button class="btn-action" id="submitQuizBtn">Submit answers</button>';
        el('moduleQuiz').innerHTML = html;
        el('submitQuizBtn').addEventListener('click', submitQuiz);
    }

    function submitQuiz() {
        var m = null;
        course.modules.forEach(function (mod) { if (mod.id === currentModuleId) m = mod; });
        if (!m || !m.quiz) return;

        var answers = [];
        var complete = true;
        m.quiz.forEach(function (_, idx) {
            var selected = document.querySelector('input[name="q_' + idx + '"]:checked');
            if (selected) {
                answers.push(parseInt(selected.value, 10));
            } else {
                complete = false;
                answers.push(-1);
            }
        });
        if (!complete) {
            renderStatus('moduleQuizStatus', 'warn', 'Answer all questions before submitting.');
            return;
        }

        clearStatus('moduleQuizStatus');
        el('submitQuizBtn').disabled = true;

        fetchJSON(API + '/v2/academy/progress', {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ course_id: COURSE_ID, module_id: currentModuleId, answers: answers }),
        }).then(function (res) {
            el('submitQuizBtn').disabled = false;
            if (res.status === 401 || res.status === 403) {
                renderStatus('moduleQuizStatus', 'warn', authPrompt('submit quiz answers'));
                return;
            }
            if (!res.ok || res.body.error) {
                renderStatus('moduleQuizStatus', 'error', esc(res.body.error || 'Grading failed'));
                return;
            }
            showQuizResult(res.body);
            loadProgress().then(function () {
                renderModuleList();
                renderCertificatePanel();
            });
        }).catch(function () {
            el('submitQuizBtn').disabled = false;
            renderStatus('moduleQuizStatus', 'error', 'The service could not be reached.');
        });
    }

    function showQuizResult(result) {
        var html = '<div class="panel">';
        html += '<h3>Result: ' + (result.passed ? '<span class="chip chip-observed">PASSED</span>' : '<span class="chip chip-error">NOT PASSED</span>') + '</h3>';
        html += '<p class="muted small">Score: ' + result.score_correct + '/' + result.score_total + ' (need ' + result.pass_threshold + ' to pass)</p>';
        html += '<div class="table-scroll"><table class="data-table"><thead><tr>' +
            '<th>#</th><th>Your answer</th><th>Correct</th><th>Explanation</th>' +
            '</tr></thead><tbody>';
        (result.results || []).forEach(function (r, idx) {
            html += '<tr>' +
                '<td>' + (idx + 1) + '</td>' +
                '<td>' + (r.correct ? '<span class="chip chip-observed">Yes</span>' : '<span class="chip chip-error">No</span>') + '</td>' +
                '<td>' + esc(r.options ? r.options[r.correct_index] : r.correct_index) + '</td>' +
                '<td>' + esc(r.explanation) + '</td>' +
                '</tr>';
        });
        html += '</tbody></table></div></div>';
        el('moduleQuizResult').innerHTML = html;
    }

    function renderGlossary() {
        var termIds = Object.keys(glossary).sort();
        renderGlossaryCards(termIds);
        el('glossarySearch').addEventListener('input', function () {
            var q = this.value.trim().toLowerCase();
            var filtered = termIds.filter(function (id) {
                var t = glossary[id];
                return t.term.toLowerCase().indexOf(q) >= 0 ||
                    t.short.toLowerCase().indexOf(q) >= 0 ||
                    t.long.toLowerCase().indexOf(q) >= 0;
            });
            renderGlossaryCards(filtered);
        });
    }

    function renderGlossaryCards(termIds) {
        var html = '';
        termIds.forEach(function (id) {
            var t = glossary[id];
            html += '<div class="item-card">' +
                '<h3>' + esc(t.term) + '</h3>' +
                '<span class="chip chip-documented">' + esc(t.module) + '</span>' +
                '<p class="muted">' + esc(t.short) + '</p>' +
                '<details class="expander"><summary>More</summary>' +
                '<p class="muted small">' + esc(t.long) + '</p>';
            if (t.platform_link) {
                html += '<p><a class="text-link" href="' + esc(t.platform_link) + '">See on platform →</a></p>';
            }
            html += '</details></div>';
        });
        el('glossaryGrid').innerHTML = html || '<p class="muted small">No matching terms.</p>';
    }

    function allModulesPassed() {
        if (!course) return false;
        return course.modules.every(function (m) {
            return progress[m.id] && progress[m.id].passed;
        });
    }

    function missingModules() {
        if (!course) return [];
        return course.modules.filter(function (m) {
            return !progress[m.id] || !progress[m.id].passed;
        }).map(function (m) { return m.title; });
    }

    function renderCertificatePanel() {
        if (!course) return;
        if (allModulesPassed()) {
            el('certificateStatus').innerHTML = '<div class="notice notice-info">All modules passed. You can issue your Certificate of Completion.</div>';
            el('certificateActions').innerHTML = '<button class="btn-action" id="issueCertBtn">Issue certificate</button>';
            el('issueCertBtn').addEventListener('click', issueCertificate);
        } else {
            var missing = missingModules();
            el('certificateStatus').innerHTML = '<div class="notice notice-warn">Not yet eligible. Missing modules:<br>' + missing.map(esc).join('<br>') + '</div>';
            el('certificateActions').innerHTML = '';
        }
    }

    function issueCertificate() {
        el('issueCertBtn').disabled = true;
        fetchJSON(API + '/v2/academy/certificate', {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ course_id: COURSE_ID }),
        }).then(function (res) {
            el('issueCertBtn').disabled = false;
            if (res.status === 401 || res.status === 403) {
                renderStatus('certificateStatus', 'warn', authPrompt('issue a certificate'));
                return;
            }
            if (!res.ok || res.body.error) {
                renderStatus('certificateStatus', 'error', esc(res.body.error || 'Certificate request failed'));
                return;
            }
            showCertificate(res.body.certificate);
        }).catch(function () {
            el('issueCertBtn').disabled = false;
            renderStatus('certificateStatus', 'error', 'The service could not be reached.');
        });
    }

    function showCertificate(cert) {
        if (!cert) return;
        var html = '<div class="notice notice-info">' +
            '<strong>Certificate issued</strong><br>' +
            'ID: <code>' + esc(cert.certificate_id) + '</code><br>' +
            'Score: ' + cert.score_correct + '/' + cert.score_total + '<br>' +
            'Issued: ' + esc(cert.issued_at) +
            '</div>';
        html += '<a class="btn-action" href="' + esc(API + '/v2/academy/certificate/pdf?course_id=' + COURSE_ID) + '" target="_blank" rel="noopener">Download PDF</a>';
        el('certificateActions').innerHTML = html;
    }

    function verifyCertificate() {
        var id = el('verifyCertId').value.trim();
        if (!id) {
            renderStatus('verifyCertResult', 'warn', 'Enter a certificate ID.');
            return;
        }
        fetchJSON(API + '/v2/academy/certificates/' + encodeURIComponent(id) + '/verify').then(function (res) {
            if (!res.ok || !res.body.valid) {
                renderStatus('verifyCertResult', 'error', 'Certificate not found or invalid.');
                return;
            }
            var d = res.body;
            var html = '<div class="notice notice-info">' +
                '<strong>Valid certificate</strong><br>' +
                'Name: ' + esc(d.display_name) + '<br>' +
                'Course: ' + esc(d.course_title) + '<br>' +
                'Score: ' + d.score_correct + '/' + d.score_total + '<br>' +
                'Issued: ' + esc(d.issued_at) +
                '</div>';
            el('verifyCertResult').innerHTML = html;
        }).catch(function () {
            renderStatus('verifyCertResult', 'error', 'Verification service unreachable.');
        });
    }

    function setMode(mode) {
        var briefs = mode === 'briefs';
        el('coursePanel').classList.toggle('hidden', briefs);
        el('briefsPanel').classList.toggle('hidden', !briefs);
        el('modeCourseBtn').classList.toggle('active', !briefs);
        el('modeBriefsBtn').classList.toggle('active', briefs);
        if (window.HS && HS.track) HS.track('learn_mode', { mode: briefs ? 'briefs' : 'course' });
        if (history.replaceState) {
            var params = new URLSearchParams(location.search);
            if (briefs) params.set('mode', 'briefs'); else params.delete('mode');
            var qs = params.toString();
            history.replaceState(null, '', location.pathname + (qs ? '?' + qs : ''));
        }
    }

    function init() {
        el('modeCourseBtn').addEventListener('click', function () { setMode('course'); });
        el('modeBriefsBtn').addEventListener('click', function () { setMode('briefs'); });
        if (new URLSearchParams(location.search).get('mode') === 'briefs') setMode('briefs');
        Promise.all([loadCourse(), loadGlossary()]).then(function () {
            if (!course) {
                el('moduleList').innerHTML = '<div class="notice notice-error">Course could not be loaded.</div>';
                return;
            }
            renderModuleList();
            renderGlossary();
            loadProgress().then(function () {
                renderModuleList();
                renderCertificatePanel();
            });
        });
        el('verifyCertBtn').addEventListener('click', verifyCertificate);
    }

    init();
})();
