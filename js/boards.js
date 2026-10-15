// ============================================================
// Boards & Events (multi-board)
// ============================================================
// An EVENT is the container (name + dates); BOARDS live inside it. The original board is board "main" inside
// event "main". This file owns: which board is on screen (and the switcher), the leaderboard scopes (one board /
// an event's combined standings / a hand-picked set), the analytics scope, and the admin screen for managing
// events and boards.
//
// Loaded BEFORE app.js (app.js calls BoardsUI during init) and relies on its globals at call time:
// API_URL, isAdmin, bingoData, currentPlayer, refreshFromAPI, loadAnalyticsWithFilters.

const BoardsUI = (() => {
    const MAIN = 'main';
    const MANY_BOARDS = 6;      // above this many boards in one event, switch from buttons to a dropdown
    const LS_BOARD = 'currentBoardId';

    let events = [];            // [{event_id, eventName, enabled, startDate, endDate, boards: [...]}]
    let boards = [];            // flat board summaries, each with .event attached
    let currentId = MAIN;
    let lbScope = 'board';      // 'board' | 'event:<id>' | 'boards:<id>,<id>'
    let lbCustom = [];          // ids ticked for a custom combination
    let analyticsScope = '';    // '' = original behaviour; otherwise a scope string for the server
    let statsScope = '';        // shared by the KC gained / luck / personal bests screens, same idea
    let lbTimer = null;

    const esc = v => String(v ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    const jsq = v => String(v ?? '').replace(/\\/g, '\\\\').replace(/'/g, "\\'");
    const adminPw = () => sessionStorage.getItem('adminPassword');

    // ---- index --------------------------------------------------------------------------------
    async function loadIndex() {
        try {
            const response = await fetch(`${API_URL}/events`);
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const data = await response.json();
            events = data.events || [];
            boards = events.flatMap(ev => (ev.boards || []).map(b => ({ ...b, event: ev })));
        } catch (e) {
            // Older API or offline: behave exactly like the single-board site.
            events = [];
            boards = [];
        }
        if (!boards.some(b => b.meta.board_id === currentId)) currentId = MAIN;
    }

    function windowOf(b) {
        const start = b.meta.startDate || b.event.startDate;
        const end = b.meta.endDate || b.event.endDate;
        return [start ? new Date(start) : null, end ? new Date(end) : null];
    }

    function statusOf(b) {
        const [start, end] = windowOf(b);
        const now = new Date();
        if (!b.meta.enabled || !b.event.enabled) return 'off';
        if (start && now < start) return 'upcoming';
        if (end && now > end) return 'ended';
        return 'live';
    }

    function pickDefaultBoard() {
        try {
            const saved = localStorage.getItem(LS_BOARD);
            if (saved && boards.some(b => b.meta.board_id === saved)) return saved;
        } catch (e) { /* storage unavailable */ }
        // First visit: the most recently started board that is running right now (falls back to the original).
        const live = boards.filter(b => statusOf(b) === 'live' && b.meta.board_id !== MAIN);
        if (live.length) {
            live.sort((a, b) => (windowOf(b)[0] || 0) - (windowOf(a)[0] || 0));
            return live[0].meta.board_id;
        }
        return MAIN;
    }

    async function init() {
        await loadIndex();
        currentId = pickDefaultBoard();
        renderAll();
        if (!lbTimer) lbTimer = setInterval(() => { if (needsServerLeaderboard()) renderServerLeaderboard(); }, 15000);
    }

    async function refreshIndex() {
        await loadIndex();
        renderAll();
    }

    const currentBoardId = () => currentId;
    const current = () => boards.find(b => b.meta.board_id === currentId) || null;
    const isMain = () => currentId === MAIN;
    // "?board=x" / "&board=x" fragment for APIs, empty for the original board so its URLs stay exactly as they were
    const boardQuery = (prefix = '?') => (currentId === MAIN ? '' : `${prefix}board=${encodeURIComponent(currentId)}`);

    // ---- switcher -----------------------------------------------------------------------------
    function renderSwitcher() {
        const bar = document.getElementById('boardSwitcher');
        if (!bar) return;
        if (boards.length <= 1) { bar.style.display = 'none'; bar.innerHTML = ''; return; }
        bar.style.display = '';
        const groups = events.filter(ev => (ev.boards || []).length);
        const showEventNames = groups.length > 1;
        const pill = (b, ev) => {
            const id = b.meta.board_id;
            const st = statusOf({ ...b, event: ev });
            const tag = st === 'live' ? '' : `<small class="board-pill-tag board-pill-${st}">${st}</small>`;
            return `<button class="board-pill ${id === currentId ? 'active' : ''}" onclick="BoardsUI.switchBoard('${jsq(id)}')" title="${esc(b.meta.label || '')}">
                ${esc(b.meta.name)}${b.meta.label ? ` <small>${esc(b.meta.label)}</small>` : ''}${tag}</button>`;
        };
        bar.innerHTML = groups.map(ev => {
            const list = ev.boards || [];
            let inner;
            if (list.length <= MANY_BOARDS) {
                inner = list.map(b => pill(b, ev)).join('');
            } else {
                // Lots of boards (e.g. a year with 12 monthly boards): boards that span the whole event stay as
                // buttons; the dated ones go in a dropdown in date order with previous/next arrows.
                const whole = list.filter(b => !b.meta.startDate && !b.meta.endDate);
                const dated = list.filter(b => b.meta.startDate || b.meta.endDate)
                    .sort((a, b) => (windowOf({ ...a, event: ev })[0] || 0) - (windowOf({ ...b, event: ev })[0] || 0));
                const inDated = dated.some(b => b.meta.board_id === currentId);
                const fmt = d => (d ? d.toLocaleDateString(undefined, { day: 'numeric', month: 'short' }) : '…');
                inner = whole.map(b => pill(b, ev)).join('') + `
                    <span class="board-step ${inDated ? 'active' : ''}">
                        <button class="board-step-btn" onclick="BoardsUI.stepBoard(-1)" title="Previous board" ${inDated ? '' : 'disabled'}>◀</button>
                        <select class="board-step-select" onchange="BoardsUI.switchBoard(this.value)">
                            ${inDated ? '' : '<option value="">Pick a board…</option>'}
                            ${dated.map(b => {
                                const [s, e] = windowOf({ ...b, event: ev });
                                const st = statusOf({ ...b, event: ev });
                                return `<option value="${esc(b.meta.board_id)}" ${b.meta.board_id === currentId ? 'selected' : ''}>${esc(b.meta.name)} (${fmt(s)} – ${fmt(e)})${st === 'live' ? ' • live' : st === 'upcoming' ? ' • upcoming' : ''}</option>`;
                            }).join('')}
                        </select>
                        <button class="board-step-btn" onclick="BoardsUI.stepBoard(1)" title="Next board" ${inDated ? '' : 'disabled'}>▶</button>
                    </span>`;
            }
            return `<div class="board-switch-group">
                ${showEventNames ? `<span class="board-switch-event">${esc(ev.eventName)}</span>` : ''}${inner}</div>`;
        }).join('');
    }

    // Previous/next dated board within the current board's event (date order)
    function stepBoard(delta) {
        const b = current();
        if (!b) return;
        const dated = (b.event.boards || []).filter(x => x.meta.startDate || x.meta.endDate)
            .sort((x, y) => (windowOf({ ...x, event: b.event })[0] || 0) - (windowOf({ ...y, event: b.event })[0] || 0));
        const i = dated.findIndex(x => x.meta.board_id === currentId);
        const next = dated[i + delta];
        if (next) switchBoard(next.meta.board_id);
    }

    async function switchBoard(id) {
        if (id === currentId) return;
        currentId = id;
        lbScope = 'board';
        try { localStorage.setItem(LS_BOARD, id); } catch (e) { /* ignore */ }
        renderAll();
        if (typeof resetBoardView === 'function') resetBoardView();
        await refreshFromAPI(true);
        if (typeof loadTotalValueLooted === 'function') loadTotalValueLooted();
    }

    // ---- leaderboard --------------------------------------------------------------------------
    function combinableEvents() {
        return events.filter(ev => (ev.boards || []).filter(b => b.meta.inCombined).length >= 2);
    }

    function needsServerLeaderboard() {
        return lbScope !== 'board' || !!(typeof bingoData !== 'undefined' && bingoData && bingoData.teamMode);
    }

    function leaderboardTitle() {
        if (boards.length <= 1) return '🏆 Leaderboard 🏆';
        if (lbScope.startsWith('event:')) {
            const ev = events.find(e => e.event_id === lbScope.slice(6));
            return `🏆 ${esc(ev ? ev.eventName : 'Combined')} — Combined 🏆`;
        }
        if (lbScope.startsWith('boards:')) return '🏆 Combined (custom) 🏆';
        const b = current();
        return `🏆 ${esc(b ? b.meta.name : 'Leaderboard')} Leaderboard 🏆`;
    }

    function renderLeaderboardBar() {
        const title = document.getElementById('leaderboardTitle');
        if (title) title.innerHTML = leaderboardTitle();
        const bar = document.getElementById('leaderboardScopeBar');
        if (!bar) return;
        if (boards.length <= 1) { bar.innerHTML = ''; return; }
        const combos = combinableEvents();
        const b = current();
        const options = [`<option value="board" ${lbScope === 'board' ? 'selected' : ''}>${esc(b ? b.meta.name : 'This board')}</option>`]
            .concat(combos.map(ev => `<option value="event:${esc(ev.event_id)}" ${lbScope === 'event:' + ev.event_id ? 'selected' : ''}>${esc(ev.eventName)} — combined</option>`))
            .concat([`<option value="custom" ${lbScope.startsWith('boards:') ? 'selected' : ''}>Custom combination…</option>`]);
        const picker = (lbScope.startsWith('boards:') || lbScope === 'custom-open') ? `
            <div class="lb-custom">${boards.map(x => `
                <label><input type="checkbox" ${lbCustom.includes(x.meta.board_id) ? 'checked' : ''}
                    onchange="BoardsUI.toggleCustom('${jsq(x.meta.board_id)}', this.checked)"> ${esc(x.meta.name)}</label>`).join('')}
            </div>` : '';
        bar.innerHTML = `<select class="lb-scope-select" onchange="BoardsUI.setLeaderboardScope(this.value)">${options.join('')}</select>${picker}`;
    }

    function setLeaderboardScope(value) {
        if (value === 'custom') {
            if (!lbCustom.length) lbCustom = boards.map(x => x.meta.board_id).slice(0, 2);
            lbScope = `boards:${lbCustom.join(',')}`;
        } else {
            lbScope = value;
        }
        renderLeaderboardBar();
        refreshLeaderboard();
    }

    function toggleCustom(id, on) {
        lbCustom = on ? [...new Set([...lbCustom, id])] : lbCustom.filter(x => x !== id);
        lbScope = lbCustom.length ? `boards:${lbCustom.join(',')}` : 'board';
        renderLeaderboardBar();
        refreshLeaderboard();
    }

    function refreshLeaderboard() {
        if (typeof updatePlayerStats === 'function') updatePlayerStats();
    }

    function serverScopeParam() {
        return lbScope === 'board' ? `board:${currentId}` : lbScope;
    }

    async function renderServerLeaderboard() {
        const statsDiv = document.getElementById('playerStats');
        if (!statsDiv) return;
        const requested = serverScopeParam();
        try {
            const response = await fetch(`${API_URL}/leaderboard?scope=${encodeURIComponent(requested)}`);
            const data = await response.json();
            if (requested !== serverScopeParam()) return; // user changed scope while this was loading
            if (!response.ok) throw new Error(data.error || 'Could not load standings');
            const rows = data.rows || [];
            if (!rows.length) { statsDiv.innerHTML = '<div class="no-players">No drops recorded yet!</div>'; return; }
            const medals = ['🥇', '🥈', '🥉'];
            const multi = data.combined && (data.boards || []).length > 1;
            statsDiv.innerHTML = rows.map((r, i) => {
                const medal = r.rank <= 3 ? medals[r.rank - 1] : '';
                const rankClass = r.rank <= 3 ? `rank-${r.rank}` : '';
                const sub = data.teamMode && r.members ? `<div class="player-stats">👥 ${r.members.map(esc).join(', ')}</div>` : '';
                const breakdown = multi ? `<div class="player-stats lb-breakdown">${Object.values(r.breakdown || {}).map(x =>
                    `${esc(x.name)}: ${Number(x.points).toLocaleString()}${x.weighted !== x.points ? ` (×${(x.weighted / (x.points || 1)).toFixed(2).replace(/\.?0+$/, '')})` : ''}`).join(' · ')}</div>` : '';
                const clickable = !data.teamMode;
                return `
                    <div class="player-card ${rankClass}" data-player="${esc(r.name)}"
                        ${clickable ? `onclick="viewAsPlayer('${jsq(r.name)}')" style="cursor:pointer;"` : ''}>
                        ${medal ? `<div class="player-rank">${medal}</div>` : ''}
                        <div class="player-name">${esc(r.name)}</div>
                        <div class="player-score">${Number(r.points).toLocaleString()} points</div>
                        <div class="player-stats">${r.tiles} tile${r.tiles === 1 ? '' : 's'} completed
                            ${r.line_bonus > 0 ? `<span class="bonus-badge">+${r.line_bonus} bonus</span>` : ''}</div>
                        ${sub}${breakdown}
                    </div>`;
            }).join('');
        } catch (e) {
            statsDiv.innerHTML = `<div class="no-players">Could not load standings (${esc(e.message)})</div>`;
        }
    }

    // ---- analytics scope ----------------------------------------------------------------------
    function populateAnalyticsScope() {
        const select = document.getElementById('analyticsScopeSelect');
        if (!select) return;
        const wrap = document.getElementById('analyticsScopeWrap');
        if (wrap) wrap.style.display = boards.length > 1 || analyticsScope ? '' : 'none';
        const opts = ['<option value="">Default (current bingo / all time)</option>'];
        boards.forEach(b => opts.push(`<option value="board:${esc(b.meta.board_id)}">Board: ${esc(b.meta.name)}</option>`));
        combinableEvents().forEach(ev => opts.push(`<option value="event:${esc(ev.event_id)}">Combined: ${esc(ev.eventName)}</option>`));
        opts.push('<option value="range">Custom date range…</option>');
        select.innerHTML = opts.join('');
        select.value = analyticsScope.startsWith('range:') ? 'range' : analyticsScope;
    }

    function setAnalyticsScope(value) {
        const rangeBox = document.getElementById('analyticsRangeBox');
        if (rangeBox) rangeBox.style.display = value === 'range' ? '' : 'none';
        if (value === 'range') { applyAnalyticsRange(); return; }
        analyticsScope = value || '';
        afterAnalyticsScopeChange();
    }

    function applyAnalyticsRange() {
        const from = document.getElementById('analyticsRangeFrom')?.value;
        const to = document.getElementById('analyticsRangeTo')?.value;
        if (!from && !to) return;
        const iso = v => (v ? new Date(v).toISOString() : '');
        analyticsScope = `range:${iso(from)},${iso(to)}`;
        afterAnalyticsScopeChange();
    }

    async function afterAnalyticsScopeChange() {
        ['analyticsModeBingo', 'analyticsModeAlltime'].forEach(id => {
            const el = document.getElementById(id);
            if (el) el.classList.toggle('active', !analyticsScope && (id === 'analyticsModeBingo') === (_analyticsMode === 'bingo'));
        });
        const label = document.getElementById('analyticsModeLabel');
        if (label) {
            if (!analyticsScope) {
                if (typeof updateAnalyticsModeLabel === 'function') updateAnalyticsModeLabel();
            } else {
                label.textContent = 'Loading…';
                try {
                    const r = await fetch(`${API_URL}/scope/windows?scope=${encodeURIComponent(analyticsScope)}`);
                    const d = await r.json();
                    const parts = (d.windows || []).map(w => `${w.start ? new Date(w.start).toLocaleDateString() : '…'} – ${w.end ? new Date(w.end).toLocaleDateString() : 'now'}`);
                    label.textContent = `Showing ${d.label}${parts.length ? ` (${parts.join(', ')})` : ''}`;
                } catch (e) { label.textContent = 'Showing selected scope'; }
            }
        }
        if (typeof loadAnalyticsWithFilters === 'function') loadAnalyticsWithFilters();
    }

    function clearAnalyticsScope() {
        if (!analyticsScope) return;
        analyticsScope = '';
        const select = document.getElementById('analyticsScopeSelect');
        if (select) select.value = '';
        const rangeBox = document.getElementById('analyticsRangeBox');
        if (rangeBox) rangeBox.style.display = 'none';
    }

    const hasAnalyticsScope = () => !!analyticsScope;
    // Adds ?scope= to a URLSearchParams when an explicit scope is chosen; returns whether it did.
    function applyAnalyticsScope(params) {
        if (!analyticsScope) return false;
        params.delete('start_date');
        params.set('scope', analyticsScope);
        return true;
    }
    // "?scope=..." / "&scope=..." for URLs built as strings
    const analyticsScopeQuery = (prefix = '?') => (analyticsScope ? `${prefix}scope=${encodeURIComponent(analyticsScope)}` : '');

    // ---- stats scope (KC gained, luck, personal bests) -----------------------------------------
    function statsScopeOptions(selected) {
        const opts = [`<option value="">Default (current bingo)</option>`];
        boards.forEach(b => opts.push(`<option value="board:${esc(b.meta.board_id)}">Board: ${esc(b.meta.name)}</option>`));
        events.filter(ev => (ev.boards || []).length).forEach(ev =>
            opts.push(`<option value="event:${esc(ev.event_id)}">Whole event: ${esc(ev.eventName)}</option>`));
        opts.push('<option value="range">Custom date range…</option>');
        const html = opts.join('');
        const want = selected.startsWith('range:') ? 'range' : selected;
        return html.replace(`value="${want}"`, `value="${want}" selected`);
    }

    function mountStatsScope(hostId) {
        const host = document.getElementById(hostId);
        if (!host) return;
        if (boards.length <= 1 && !statsScope) { host.innerHTML = ''; return; }
        const isRange = statsScope.startsWith('range:');
        const [from, to] = isRange ? statsScope.slice(6).split(',') : ['', ''];
        host.innerHTML = `
            <label style="font-size:13px; color:#6b4423; font-weight:bold;">Scope:</label>
            <select onchange="BoardsUI.setStatsScope(this.value, '${hostId}')" style="margin-left:6px;">${statsScopeOptions(statsScope)}</select>
            <span id="${hostId}Range" style="${isRange ? '' : 'display:none;'} margin-left:8px;">
                <input type="datetime-local" id="${hostId}From" value="${toLocalInput(from)}" onchange="BoardsUI.applyStatsRange('${hostId}')">
                →
                <input type="datetime-local" id="${hostId}To" value="${toLocalInput(to)}" onchange="BoardsUI.applyStatsRange('${hostId}')">
            </span>`;
    }

    function remountStatsScopes(except) {
        ['kcScopeHost', 'pbScopeHost'].filter(h => h !== except).forEach(mountStatsScope);
    }

    function setStatsScope(value, hostId) {
        if (value === 'range') {
            const box = document.getElementById(`${hostId}Range`);
            if (box) box.style.display = '';
            applyStatsRange(hostId);
            return;
        }
        statsScope = value || '';
        remountStatsScopes(hostId);
        notifyStatsScopeChanged();
    }

    function applyStatsRange(hostId) {
        const from = document.getElementById(`${hostId}From`)?.value;
        const to = document.getElementById(`${hostId}To`)?.value;
        if (!from && !to) return;
        const iso = v => (v ? new Date(v).toISOString() : '');
        statsScope = `range:${iso(from)},${iso(to)}`;
        remountStatsScopes(hostId);
        notifyStatsScopeChanged();
    }

    function notifyStatsScopeChanged() {
        if (typeof kcScopeChanged === 'function') kcScopeChanged();
        if (typeof pbScopeChanged === 'function') pbScopeChanged();
    }

    const hasStatsScope = () => !!statsScope;
    const statsScopeQuery = (prefix = '?') => (statsScope ? `${prefix}scope=${encodeURIComponent(statsScope)}` : '');

    // ---- shared render ------------------------------------------------------------------------
    function renderAll() {
        renderSwitcher();
        renderLeaderboardBar();
    }

    // ---- admin: events & boards ---------------------------------------------------------------
    function toLocalInput(iso) {
        if (!iso) return '';
        const d = new Date(iso);
        if (isNaN(d)) return '';
        const p = n => String(n).padStart(2, '0');
        return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
    }
    const fromLocalInput = v => (v ? new Date(v).toISOString() : null);

    async function openAdmin() {
        if (typeof isAdmin !== 'undefined' && !isAdmin) { alert('⛔ Admin access required!'); return; }
        if (!document.getElementById('boardsAdminModal')) {
            document.body.insertAdjacentHTML('beforeend', `
                <div class="modal" id="boardsAdminModal">
                    <div class="modal-content" style="max-width: 860px;">
                        <button class="close-btn" onclick="BoardsUI.closeAdmin()">✕</button>
                        <div id="boardsAdminBody"></div>
                    </div>
                </div>`);
        }
        document.getElementById('boardsAdminModal').classList.add('active');
        await adminRender();
    }

    function closeAdmin() {
        const m = document.getElementById('boardsAdminModal');
        if (m) m.classList.remove('active');
    }

    async function adminRender(message) {
        await loadIndex();
        renderAll();
        const body = document.getElementById('boardsAdminBody');
        const row = (b, ev) => {
            const st = statusOf({ ...b, event: ev });
            const [s, e] = windowOf({ ...b, event: ev });
            const fmt = d => (d ? d.toLocaleDateString() : '…');
            return `<tr>
                <td><strong>${esc(b.meta.name)}</strong>${b.meta.label ? ` <small class="pb-muted">${esc(b.meta.label)}</small>` : ''}
                    ${b.meta.teamMode ? ' <span title="Team board">👥</span>' : ''}</td>
                <td>${fmt(s)} – ${fmt(e)}</td>
                <td>${st}</td>
                <td>${b.meta.inCombined ? '✓' : '–'} ×${b.meta.weight}</td>
                <td class="ba-actions">
                    <button class="btn-secondary" onclick="BoardsUI.adminBoardForm('${jsq(b.meta.board_id)}')">Edit</button>
                    ${b.meta.board_id === MAIN ? '' : `<button class="btn-secondary" onclick="BoardsUI.adminDeleteBoard('${jsq(b.meta.board_id)}')">Delete</button>`}
                </td></tr>`;
        };
        body.innerHTML = `
            <h2>🗂️ Events &amp; Boards</h2>
            <p class="pb-muted">An event holds boards (a year-long, a 6-month, monthly...). Drops score on every board that is live when they happen. The archive freezes the whole event with all its boards.</p>
            ${message ? `<div class="pb-note">${esc(message)}</div>` : ''}
            ${events.map(ev => `
                <div class="ba-event">
                    <div class="ba-event-head">
                        <div><strong>${esc(ev.eventName)}</strong>
                            <span class="pb-muted">${ev.startDate ? new Date(ev.startDate).toLocaleDateString() : '…'} – ${ev.endDate ? new Date(ev.endDate).toLocaleDateString() : '…'}
                            ${ev.enabled ? '' : ' · disabled'}</span></div>
                        <div class="ba-actions">
                            ${ev.event_id === MAIN
                                ? `<button class="btn-secondary" onclick="BoardsUI.closeAdmin(); openEventConfigModal()">Edit dates</button>`
                                : `<button class="btn-secondary" onclick="BoardsUI.adminEventForm('${jsq(ev.event_id)}')">Edit</button>
                                   <button class="btn-secondary" onclick="BoardsUI.adminDeleteEvent('${jsq(ev.event_id)}')">Delete</button>`}
                            <button class="btn-save" onclick="BoardsUI.adminBoardForm(null, '${jsq(ev.event_id)}')">+ Board</button>
                        </div>
                    </div>
                    <div class="pb-table-wrap"><table class="pb-table">
                        <thead><tr><th>Board</th><th>Dates</th><th>Status</th><th>Combined</th><th></th></tr></thead>
                        <tbody>${(ev.boards || []).map(b => row(b, ev)).join('') || '<tr><td colspan="5" class="pb-muted">No boards yet</td></tr>'}</tbody>
                    </table></div>
                </div>`).join('')}
            <div style="margin-top:14px;"><button class="btn-save" onclick="BoardsUI.adminEventForm()">+ New event</button></div>
            <div id="boardsAdminForm"></div>`;
    }

    function formShell(title, fields, onSave) {
        const host = document.getElementById('boardsAdminForm');
        host.innerHTML = `
            <div class="ba-form">
                <h3>${title}</h3>
                ${fields}
                <div class="modal-buttons">
                    <button class="btn-cancel" onclick="document.getElementById('boardsAdminForm').innerHTML=''">Cancel</button>
                    <button class="btn-save" onclick="${onSave}">Save</button>
                </div>
                <p id="baError" style="color:#8b1a1a; display:none;"></p>
            </div>`;
        host.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }

    function adminEventForm(eventId) {
        const ev = events.find(e => e.event_id === eventId) || {};
        formShell(eventId ? 'Edit event' : 'New event', `
            <label>Event name</label><input id="baEvName" value="${esc(ev.eventName || '')}" placeholder="e.g. 2027 Year">
            <label>Start</label><input type="datetime-local" id="baEvStart" value="${toLocalInput(ev.startDate)}">
            <label>End</label><input type="datetime-local" id="baEvEnd" value="${toLocalInput(ev.endDate)}">
            <label><input type="checkbox" id="baEvEnabled" ${ev.enabled === false ? '' : 'checked'}> Enabled</label>`,
            `BoardsUI.adminSaveEvent('${jsq(eventId || '')}')`);
    }

    async function adminPost(path, payload) {
        const response = await fetch(`${API_URL}${path}`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ password: adminPw(), ...payload }),
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.error || `Request failed (${response.status})`);
        return data;
    }

    function formError(msg) {
        const el = document.getElementById('baError');
        if (el) { el.textContent = msg; el.style.display = 'block'; }
    }

    async function adminSaveEvent(eventId) {
        try {
            await adminPost('/admin/events', { event: {
                event_id: eventId || undefined,
                eventName: document.getElementById('baEvName').value.trim(),
                startDate: fromLocalInput(document.getElementById('baEvStart').value),
                endDate: fromLocalInput(document.getElementById('baEvEnd').value),
                enabled: document.getElementById('baEvEnabled').checked,
            } });
            await adminRender('Event saved.');
        } catch (e) { formError(e.message); }
    }

    async function adminDeleteEvent(eventId) {
        const ev = events.find(e => e.event_id === eventId);
        const n = (ev?.boards || []).length;
        if (!confirm(`Delete "${ev?.eventName}"${n ? ` and its ${n} board(s)` : ''}? This cannot be undone.`)) return;
        try {
            await adminPost('/admin/events', { action: 'delete', event: { event_id: eventId }, force: true });
            if (!boards.some(b => b.meta.board_id === currentId)) currentId = MAIN;
            await adminRender('Event deleted.');
        } catch (e) { alert(e.message); }
    }

    function teamsToText(teams) {
        return Object.entries(teams || {}).map(([t, m]) => `${t}: ${m.join(', ')}`).join('\n');
    }
    function textToTeams(text) {
        const teams = {};
        text.split('\n').map(l => l.trim()).filter(Boolean).forEach(line => {
            const [name, ...rest] = line.split(':');
            teams[name.trim()] = rest.join(':').split(',').map(s => s.trim()).filter(Boolean);
        });
        return teams;
    }

    function adminBoardForm(boardId, defaultEventId) {
        const b = boards.find(x => x.meta.board_id === boardId);
        const m = b ? b.meta : { event_id: defaultEventId || MAIN, enabled: true, inCombined: true, weight: 1, teamMode: false, teams: {} };
        const creating = !b;
        formShell(creating ? 'New board' : `Edit board: ${esc(m.name)}`, `
            <label>Board name</label><input id="baName" value="${esc(m.name || '')}" placeholder="e.g. Year-Long, Seasonal, March">
            <label>Label <span class="pb-muted">(optional tag shown next to the name)</span></label><input id="baLabel" value="${esc(m.label || '')}">
            <label>Event</label>
            <select id="baEvent" ${creating ? '' : 'disabled'}>${events.map(ev => `<option value="${esc(ev.event_id)}" ${ev.event_id === m.event_id ? 'selected' : ''}>${esc(ev.eventName)}</option>`).join('')}</select>
            <label>Start <span class="pb-muted">(blank = event start)</span></label><input type="datetime-local" id="baStart" value="${toLocalInput(m.startDate)}">
            <label>End <span class="pb-muted">(blank = event end)</span></label><input type="datetime-local" id="baEnd" value="${toLocalInput(m.endDate)}">
            ${creating ? `
            <label>Start from</label>
            <select id="baCopy"><option value="">A blank board</option>${boards.map(x => `<option value="${esc(x.meta.board_id)}">Copy tiles from: ${esc(x.meta.name)}</option>`).join('')}</select>
            <label>Board size <span class="pb-muted">(blank boards only)</span></label><input type="number" id="baSize" min="2" max="12" value="5">` : ''}
            <label>Weight in combined standings</label><input type="number" id="baWeight" step="0.05" min="0" value="${m.weight}">
            <label><input type="checkbox" id="baInCombined" ${m.inCombined ? 'checked' : ''}> Counts toward the event's combined leaderboard</label>
            <label><input type="checkbox" id="baEnabled" ${m.enabled ? 'checked' : ''}> Enabled (receives drops)</label>
            <label><input type="checkbox" id="baTeamMode" ${m.teamMode ? 'checked' : ''} onchange="document.getElementById('baTeamsBox').style.display=this.checked?'':'none'"> Team board (score by team instead of individually)</label>
            <div id="baTeamsBox" style="${m.teamMode ? '' : 'display:none;'}">
                <label>Teams <span class="pb-muted">(one per line: <code>Team name: player, player</code>)</span></label>
                <textarea id="baTeams" rows="5" style="width:100%;">${esc(teamsToText(m.teams))}</textarea>
            </div>`, `BoardsUI.adminSaveBoard('${jsq(boardId || '')}')`);
    }

    async function adminSaveBoard(boardId) {
        const creating = !boardId;
        const board = {
            board_id: boardId || undefined,
            name: document.getElementById('baName').value.trim(),
            label: document.getElementById('baLabel').value.trim(),
            event_id: document.getElementById('baEvent').value,
            startDate: fromLocalInput(document.getElementById('baStart').value),
            endDate: fromLocalInput(document.getElementById('baEnd').value),
            weight: parseFloat(document.getElementById('baWeight').value),
            inCombined: document.getElementById('baInCombined').checked,
            enabled: document.getElementById('baEnabled').checked,
            teamMode: document.getElementById('baTeamMode').checked,
            teams: textToTeams(document.getElementById('baTeams').value || ''),
        };
        if (!creating) delete board.event_id;
        if (creating) board.boardSize = parseInt(document.getElementById('baSize').value, 10) || 5;
        try {
            const result = await adminPost('/admin/boards', { board, copyFrom: creating ? (document.getElementById('baCopy').value || undefined) : undefined });
            await adminRender(creating ? 'Board created. Switch to it above, then use Edit Mode to fill in its tiles.' : 'Board saved.');
            if (creating && result.board) await switchBoard(result.board.board_id);
            else if (boardId === currentId) await refreshFromAPI(true);
        } catch (e) { formError(e.message); }
    }

    async function adminDeleteBoard(boardId) {
        const b = boards.find(x => x.meta.board_id === boardId);
        if (!confirm(`Delete board "${b?.meta.name}"? Its tiles and completions are lost (past archives are unaffected).`)) return;
        try {
            await adminPost('/admin/boards', { action: 'delete', board: { board_id: boardId } });
            if (currentId === boardId) {
                currentId = MAIN;
                try { localStorage.setItem(LS_BOARD, MAIN); } catch (e) { /* ignore */ }
                await refreshFromAPI(true);
            }
            await adminRender('Board deleted.');
        } catch (e) { alert(e.message); }
    }

    return {
        init, refreshIndex, currentBoardId, current, isMain, boardQuery,
        switchBoard, stepBoard, setLeaderboardScope, toggleCustom,
        mountStatsScope, setStatsScope, applyStatsRange, hasStatsScope, statsScopeQuery,
        needsServerLeaderboard, renderServerLeaderboard, renderLeaderboardBar,
        populateAnalyticsScope, setAnalyticsScope, applyAnalyticsRange, clearAnalyticsScope,
        hasAnalyticsScope, applyAnalyticsScope, analyticsScopeQuery,
        openAdmin, closeAdmin, adminEventForm, adminSaveEvent, adminDeleteEvent,
        adminBoardForm, adminSaveBoard, adminDeleteBoard,
        get boards() { return boards; }, get events() { return events; },
    };
})();
