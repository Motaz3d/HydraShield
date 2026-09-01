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
    var knowledge = null;
    var learnerModel = null;
    var reviewDue = [];
    var selectedTrack = 'all';

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
            refreshLearnerModel();
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

    function loadKnowledge() {
        return fetchJSON(API + '/v2/academy/knowledge?course_id=' + COURSE_ID).then(function (res) {
            if (!res.ok || !res.body || !res.body.knowledge) return null;
            knowledge = res.body.knowledge;
            return knowledge;
        });
    }

    function loadLearnerModel() {
        return fetchJSON(API + '/v2/academy/learner-model?course_id=' + COURSE_ID, {
            credentials: 'same-origin',
        }).then(function (res) {
            if (res.status === 401 || res.status === 403) {
                learnerModel = null;
                reviewDue = [];
                return { authRequired: true };
            }
            if (!res.ok) return null;
            learnerModel = res.body.model || null;
            reviewDue = res.body.due_reviews || [];
            return learnerModel;
        });
    }

    function setAcademyView(view) {
        var isMap = view === 'map';
        el('mapPanel').classList.toggle('hidden', !isMap);
        el('listPanel').classList.toggle('hidden', isMap);
        el('viewMapBtn').classList.toggle('active', isMap);
        el('viewListBtn').classList.toggle('active', !isMap);
        if (window.HS && HS.track) HS.track('academy_view', { view: view });
    }

    function nodeLevelClass(level) {
        return 'km-' + (level || 'not_started');
    }

    function levelLabel(level) {
        var map = {
            mastered: 'Mastered',
            proficient: 'Proficient',
            developing: 'Developing',
            needs_attention: 'Needs attention',
            not_started: 'Not started'
        };
        return map[level] || level;
    }

    function wrapText(text, maxLen) {
        if (!text) return [''];
        if (text.length <= maxLen) return [text];
        var words = text.split(' ');
        var lines = [''];
        words.forEach(function (w) {
            var last = lines[lines.length - 1];
            if (!last || (last + ' ' + w).length <= maxLen) {
                lines[lines.length - 1] = last ? last + ' ' + w : w;
            } else if (lines.length < 2) {
                lines.push(w);
            } else {
                lines[lines.length - 1] = last + '…';
            }
        });
        return lines;
    }

    function renderTrackChips() {
        if (!knowledge || !knowledge.tracks) return;
        var html = '<button class="hazard-tab ' + (selectedTrack === 'all' ? 'active' : '') + '" data-track="all">All tracks</button>';
        knowledge.tracks.forEach(function (t) {
            html += '<button class="hazard-tab ' + (selectedTrack === t.id ? 'active' : '') + '" data-track="' + esc(t.id) + '">' + esc(t.label) + '</button>';
        });
        el('trackChips').innerHTML = html;
        el('trackChips').querySelectorAll('button[data-track]').forEach(function (btn) {
            btn.addEventListener('click', function () {
                selectedTrack = btn.getAttribute('data-track');
                renderTrackChips();
                renderMap();
                if (window.HS && HS.track) HS.track('academy_track_filter', { track: selectedTrack });
            });
        });
    }

    function computeDepths(nodes) {
        var byId = {};
        nodes.forEach(function (n) { byId[n.id] = n; });
        var depth = {};
        function getDepth(id) {
            if (depth[id] !== undefined) return depth[id];
            var node = byId[id];
            if (!node) return 0;
            var prereqs = node.prerequisites || [];
            if (!prereqs.length) {
                depth[id] = 0;
                return 0;
            }
            var max = 0;
            prereqs.forEach(function (p) {
                var d = getDepth(p);
                if (d + 1 > max) max = d + 1;
            });
            depth[id] = max;
            return max;
        }
        nodes.forEach(function (n) { getDepth(n.id); });
        return depth;
    }

    function renderMap() {
        if (!knowledge) return;
        var nodes = knowledge.nodes || [];
        var conceptsById = {};
        if (learnerModel && learnerModel.concepts) {
            learnerModel.concepts.forEach(function (c) { conceptsById[c.id] = c; });
        }
        var recommendedId = learnerModel && learnerModel.recommended_next ? learnerModel.recommended_next.concept_id : null;
        var depths = computeDepths(nodes);
        var layers = {};
        nodes.forEach(function (n) {
            var d = depths[n.id] || 0;
            layers[d] = layers[d] || [];
            layers[d].push(n);
        });
        var colWidth = 220;
        var rowHeight = 74;
        var nodeW = 190;
        var nodeH = 46;
        var maxLayer = Object.keys(layers).length ? Math.max.apply(null, Object.keys(layers).map(Number)) : 0;
        var svgW = (maxLayer + 1) * colWidth + 20;
        var maxRows = 0;
        Object.keys(layers).forEach(function (d) {
            if (layers[d].length > maxRows) maxRows = layers[d].length;
        });
        var svgH = Math.max(maxRows * rowHeight + 40, 200);

        var svg = '<svg width="' + svgW + '" height="' + svgH + '" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Knowledge map">';
        svg += '<defs><marker id="km-arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 L2,4 z" fill="#94a3b8"/></marker></defs>';

        var positions = {};
        Object.keys(layers).forEach(function (d) {
            var x = parseInt(d, 10) * colWidth + 20;
            var startY = (svgH - layers[d].length * rowHeight) / 2 + rowHeight / 2;
            layers[d].forEach(function (n, i) {
                positions[n.id] = { x: x, y: startY + i * rowHeight };
            });
        });

        // edges
        nodes.forEach(function (n) {
            var target = positions[n.id];
            if (!target) return;
            (n.prerequisites || []).forEach(function (pid) {
                var source = positions[pid];
                if (!source) return;
                svg += '<line x1="' + (source.x + nodeW) + '" y1="' + source.y + '" x2="' + target.x + '" y2="' + target.y + '" class="km-edge" marker-end="url(#km-arrow)"/>';
            });
        });

        // nodes
        nodes.forEach(function (n) {
            var pos = positions[n.id];
            if (!pos) return;
            var concept = conceptsById[n.id];
            var level = concept ? concept.level : 'not_started';
            var isRecommended = n.id === recommendedId;
            var isDimmed = selectedTrack !== 'all' && (n.tracks || []).indexOf(selectedTrack) < 0;
            var gClass = 'km-node ' + nodeLevelClass(level) + (isRecommended ? ' km-recommended' : '') + (isDimmed ? ' km-dimmed' : '');
            var aria = esc(n.label) + ' — ' + levelLabel(level);
            var lines = wrapText(n.label, 22);
            var textY = pos.y - ((lines.length - 1) * 8) + 4;
            var textHtml = '';
            lines.forEach(function (line, i) {
                textHtml += '<tspan x="' + (pos.x + nodeW / 2) + '" dy="' + (i === 0 ? 0 : 16) + '">' + esc(line) + '</tspan>';
            });
            if (isRecommended) {
                svg += '<text x="' + (pos.x + nodeW / 2) + '" y="' + (pos.y - nodeH / 2 - 8) + '" text-anchor="middle" class="km-here-label">YOU ARE HERE</text>';
            }
            svg += '<g tabindex="0" role="button" class="' + gClass + '" data-node="' + esc(n.id) + '" aria-label="' + aria + '">';
            svg += '<title>' + esc(n.label) + ' — ' + levelLabel(level) + (n.summary ? '\n' + n.summary : '') + '</title>';
            svg += '<rect x="' + pos.x + '" y="' + (pos.y - nodeH / 2) + '" width="' + nodeW + '" height="' + nodeH + '" rx="10" ry="10"/>';
            svg += '<circle cx="' + (pos.x + 12) + '" cy="' + pos.y + '" r="4" class="km-status-dot"/>';
            svg += '<text x="' + (pos.x + nodeW / 2) + '" y="' + textY + '" text-anchor="middle" class="km-label">' + textHtml + '</text>';
            svg += '</g>';
        });

        svg += '</svg>';
        el('knowledgeMap').innerHTML = svg;
        el('knowledgeMap').querySelectorAll('g[data-node]').forEach(function (g) {
            function activate() {
                var nodeId = g.getAttribute('data-node');
                var node = nodes.find(function (n) { return n.id === nodeId; });
                if (!node) return;
                var moduleId = node.module_id;
                if (!moduleId && node.kind === 'module') moduleId = node.module_id;
                if (moduleId) {
                    openModule(moduleId);
                    if (window.HS && HS.track) HS.track('academy_node_open', { node_id: nodeId, module_id: moduleId });
                }
            }
            g.addEventListener('click', activate);
            g.addEventListener('keydown', function (e) {
                if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    activate();
                }
            });
        });
    }

    function renderCompetencyBars() {
        if (!learnerModel || !learnerModel.competencies) {
            el('competencyBars').innerHTML = '<p class="muted small">Sign in to see competency progress.</p>';
            return;
        }
        var html = '';
        learnerModel.competencies.forEach(function (c) {
            var pct = Math.round((c.mastery || 0) * 100);
            html += '<div class="km-competency">' +
                '<div class="km-competency-meta"><span>' + esc(c.label) + '</span>' + HS.chip(c.level, levelLabel(c.level)) + '</div>' +
                '<div class="km-meter"><div class="km-meter-fill ' + nodeLevelClass(c.level) + '" style="width:' + pct + '%;"></div></div>' +
                '<div class="km-competency-pct">' + pct + '%</div>' +
                '</div>';
        });
        el('competencyBars').innerHTML = html;
    }

    function renderOverallMastery() {
        if (!learnerModel || !learnerModel.overall) {
            el('overallMastery').innerHTML = '<p class="muted small">Sign in to track your overall mastery.</p>';
            return;
        }
        var o = learnerModel.overall;
        var pct = Math.round((o.mastery || 0) * 100);
        el('overallMastery').innerHTML = '<div class="km-competency">' +
            '<div class="km-competency-meta"><span>Overall mastery</span>' + HS.chip(o.level, levelLabel(o.level)) + '</div>' +
            '<div class="km-meter"><div class="km-meter-fill ' + nodeLevelClass(o.level) + '" style="width:' + pct + '%;"></div></div>' +
            '<div class="km-competency-pct">' + pct + '%</div>' +
            '</div>';
    }

    function renderWeakAreas() {
        if (!knowledge) return;
        if (!learnerModel || !learnerModel.weak_areas || !learnerModel.weak_areas.length) {
            el('weakAreas').innerHTML = '<p class="muted small">No weak areas right now.</p>';
            return;
        }
        var byId = {};
        knowledge.nodes.forEach(function (n) { byId[n.id] = n; });
        var html = '<div class="badge-row">';
        learnerModel.weak_areas.forEach(function (id) {
            var n = byId[id];
            if (!n) return;
            html += '<button class="chip chip-error km-weak-chip" data-module="' + esc(n.module_id || '') + '">' + esc(n.label) + '</button>';
        });
        html += '</div>';
        el('weakAreas').innerHTML = html;
        el('weakAreas').querySelectorAll('.km-weak-chip').forEach(function (btn) {
            btn.addEventListener('click', function () {
                var moduleId = btn.getAttribute('data-module');
                if (moduleId) openModule(moduleId);
            });
        });
    }

    function renderRecommendedNext() {
        if (!learnerModel || !learnerModel.recommended_next) {
            el('recommendedNext').innerHTML = '<p class="muted small">Complete more concepts to get a recommendation.</p>';
            return;
        }
        var rec = learnerModel.recommended_next;
        var byId = {};
        if (knowledge) knowledge.nodes.forEach(function (n) { byId[n.id] = n; });
        var moduleId = byId[rec.concept_id] ? byId[rec.concept_id].module_id : null;
        el('recommendedNext').innerHTML = '<p><strong>' + esc(rec.label) + '</strong><br><span class="muted small">' + esc(rec.reason) + '</span></p>' +
            (moduleId ? '<button class="btn-action btn-sm" id="recOpenBtn">Open</button>' : '');
        var openBtn = el('recOpenBtn');
        if (openBtn) {
            openBtn.addEventListener('click', function () {
                openModule(moduleId);
                if (window.HS && HS.track) HS.track('academy_recommended_open', { concept_id: rec.concept_id });
            });
        }
    }

    function renderDueReviews() {
        if (!knowledge) return;
        if (!reviewDue || !reviewDue.length) {
            el('dueReviews').innerHTML = '<p class="muted small">No reviews due right now.</p>';
            return;
        }
        var byId = {};
        knowledge.nodes.forEach(function (n) { byId[n.id] = n; });
        var html = '<div class="km-review-list">';
        reviewDue.forEach(function (id) {
            var n = byId[id];
            if (!n) return;
            html += '<div class="km-review-item"><span>' + esc(n.label) + '</span><button class="btn-action btn-sm" data-review="' + esc(id) + '">Start review</button></div>';
        });
        html += '</div>';
        el('dueReviews').innerHTML = html;
        el('dueReviews').querySelectorAll('button[data-review]').forEach(function (btn) {
            btn.addEventListener('click', function () {
                startReview(btn.getAttribute('data-review'));
            });
        });
    }

    function renderPositionPanel() {
        renderOverallMastery();
        renderCompetencyBars();
        renderWeakAreas();
        renderRecommendedNext();
        renderDueReviews();
    }

    function renderMapView() {
        renderTrackChips();
        renderMap();
        renderPositionPanel();
    }

    function startReview(conceptId) {
        if (!knowledge) return;
        var concept = knowledge.nodes.find(function (n) { return n.id === conceptId; });
        if (!concept) return;
        fetchJSON(API + '/v2/academy/reviews/due?course_id=' + COURSE_ID, {
            credentials: 'same-origin',
        }).then(function (res) {
            if (res.status === 401 || res.status === 403) {
                el('dueReviews').innerHTML = '<div class="notice notice-warn">' + authPrompt('review concepts') + '</div>';
                return;
            }
            if (!res.ok) {
                el('dueReviews').innerHTML = '<div class="notice notice-error">Could not load review questions.</div>';
                return;
            }
            var item = (res.body.due || []).find(function (d) { return d.concept_id === conceptId; });
            if (!item) {
                el('dueReviews').innerHTML = '<div class="notice notice-info">This review is no longer due.</div>';
                return;
            }
            renderReviewForm(conceptId, item.label, item.questions);
        });
    }

    function renderReviewForm(conceptId, label, questions) {
        var html = '<div class="panel km-review-panel"><h3>Review: ' + esc(label) + '</h3>';
        questions.forEach(function (q, idx) {
            html += '<div class="form-group quiz-question" data-idx="' + idx + '">';
            html += '<label>' + (idx + 1) + '. ' + esc(q.question) + '</label>';
            (q.options || []).forEach(function (opt, optIdx) {
                var name = 'review_q_' + idx;
                var id = name + '_' + optIdx;
                html += '<div class="radio-option">' +
                    '<input type="radio" name="' + name + '" id="' + id + '" value="' + optIdx + '">' +
                    '<label for="' + id + '">' + esc(opt) + '</label></div>';
            });
            html += '</div>';
        });
        html += '<button class="btn-action" id="submitReviewBtn">Submit review</button>';
        html += '<div id="reviewResult"></div></div>';
        el('dueReviews').innerHTML = html;
        el('submitReviewBtn').addEventListener('click', function () {
            submitReview(conceptId, questions);
        });
    }

    function submitReview(conceptId, questions) {
        var answers = [];
        var complete = true;
        questions.forEach(function (_, idx) {
            var selected = document.querySelector('input[name="review_q_' + idx + '"]:checked');
            if (selected) {
                answers.push(parseInt(selected.value, 10));
            } else {
                complete = false;
                answers.push(-1);
            }
        });
        if (!complete) {
            el('reviewResult').innerHTML = '<div class="notice notice-warn">Answer all questions before submitting.</div>';
            return;
        }
        el('submitReviewBtn').disabled = true;
        fetchJSON(API + '/v2/academy/reviews', {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ course_id: COURSE_ID, concept_id: conceptId, answers: answers }),
        }).then(function (res) {
            el('submitReviewBtn').disabled = false;
            if (res.status === 401 || res.status === 403) {
                el('reviewResult').innerHTML = '<div class="notice notice-warn">' + authPrompt('submit reviews') + '</div>';
                return;
            }
            if (!res.ok || res.body.error) {
                el('reviewResult').innerHTML = '<div class="notice notice-error">' + esc(res.body.error || 'Review submission failed') + '</div>';
                return;
            }
            var d = res.body;
            el('reviewResult').innerHTML = '<div class="notice notice-info">' +
                'Score: ' + d.score_correct + '/' + d.score_total + ' ' +
                (d.passed ? '<span class="chip chip-observed">PASSED</span>' : '<span class="chip chip-error">KEEP PRACTISING</span>') +
                '<br><span class="muted small">Next review in ' + d.schedule.interval_days + ' day(s).</span>' +
                '</div>';
            refreshLearnerModel();
        }).catch(function () {
            el('submitReviewBtn').disabled = false;
            el('reviewResult').innerHTML = '<div class="notice notice-error">The service could not be reached.</div>';
        });
    }

    function refreshLearnerModel() {
        return loadLearnerModel().then(function (res) {
            if (res && res.authRequired) {
                el('overallMastery').innerHTML = '<div class="notice notice-info">' + authPrompt('track your position') + '</div>';
                el('competencyBars').innerHTML = '';
                el('weakAreas').innerHTML = '';
                el('recommendedNext').innerHTML = '';
                el('dueReviews').innerHTML = '';
                renderMap();
                return;
            }
            renderMapView();
        });
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
        el('viewMapBtn').addEventListener('click', function () { setAcademyView('map'); });
        el('viewListBtn').addEventListener('click', function () { setAcademyView('list'); });
        if (new URLSearchParams(location.search).get('mode') === 'briefs') setMode('briefs');
        Promise.all([loadCourse(), loadGlossary(), loadKnowledge()]).then(function () {
            if (!course) {
                el('moduleList').innerHTML = '<div class="notice notice-error">Course could not be loaded.</div>';
                return;
            }
            renderModuleList();
            renderGlossary();
            renderTrackChips();
            renderMap();
            loadProgress().then(function () {
                renderModuleList();
                renderCertificatePanel();
            });
            loadLearnerModel().then(function (res) {
                if (res && res.authRequired) {
                    el('overallMastery').innerHTML = '<div class="notice notice-info">' + authPrompt('track your position') + '</div>';
                    el('competencyBars').innerHTML = '';
                    el('weakAreas').innerHTML = '';
                    el('recommendedNext').innerHTML = '';
                    el('dueReviews').innerHTML = '';
                    renderMap();
                    return;
                }
                renderMapView();
            });
        });
        el('verifyCertBtn').addEventListener('click', verifyCertificate);
    }

    init();
})();
