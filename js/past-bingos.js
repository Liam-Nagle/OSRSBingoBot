// ============================================================
// Past Bingos
// ============================================================
// Browse frozen snapshots of finished bingos: scores, the board, boss KC, luck, drops and PBs.
// Everything is read from the /event/archive/* endpoints; nothing here ever changes data.
//
// Loaded after app.js and relies on its globals: API_URL, isAdmin, currentPlayer, loadItemImage,
// formatRecapGp, RECAP_BADGE_INFO, renderRecapModalContent, renderLuckPlayerView/renderLuckBossView
// (also used by the live Luck tab) and _formatLuck/_luckDiffColor.

const PB = {
    events: [],      // archive list for the picker
    id: null,        // archive currently open
    detail: null,    // /event/archive/<id>
    cache: {},       // immutable archived data, so reopening a tab or event costs nothing
    tab: 'overview',
    kcView: 'player',
    luckView: 'player',
    drops: { skip: 0, total: 0, loaded: 0 },
};

const PB_TABS = [
    { key: 'overview', label: '🏆 Overview' },
    { key: 'board', label: '🎯 Board' },
    { key: 'kc', label: '💀 Boss KC' },
    { key: 'luck', label: '🍀 Luck' },
    { key: 'drops', label: '💎 Drops' },
    { key: 'extras', label: '🏆 Personal Bests' },
];
// Archives taken before detailed snapshots existed only have a leaderboard and a board
const PB_LEGACY_TABS = ['overview', 'board'];

// ---- helpers --------------------------------------------------------------
function pbEsc(value) {
    return String(value ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function pbDate(iso, withYear = true) {
    if (!iso) return '';
    const d = new Date(iso);
    if (isNaN(d)) return '';
    return d.toLocaleDateString(undefined, withYear ? { day: 'numeric', month: 'short', year: 'numeric' } : { day: 'numeric', month: 'short' });
}

function pbDateRange(start, end) {
    if (!start && !end) return '';
    return `${pbDate(start, false)} – ${pbDate(end)}`;
}

function pbBody() {
    return document.getElementById('pbBody');
}

function pbNumber(n) {
    return Number(n || 0).toLocaleString();
}

function pbLuckHtml(score) {
    if (typeof score !== 'number') return '<span style="color:#8b7355;">–</span>';
    return `<span style="color:${_luckDiffColor(score)}; font-weight:bold;">${_formatLuck(score)}</span>`;
}

function pbBadgesHtml(badges) {
    return (badges || []).map(key => {
        const info = RECAP_BADGE_INFO[key];
        return info ? `<span title="${pbEsc(info.label)}: ${pbEsc(info.desc)}">${info.emoji}</span>` : '';
    }).join(' ');
}

function pbRankHtml(rank) {
    const medals = { 1: '🥇', 2: '🥈', 3: '🥉' };
    return medals[rank] || `#${rank}`;
}

async function pbFetch(path) {
    const res = await fetch(`${API_URL}${path}`);
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
        const err = new Error(data.error || `Request failed (${res.status})`);
        err.code = data.code;
        throw err;
    }
    return data;
}

// Archived data never changes, so each fetch only ever happens once per page load
function pbCached(key, loader) {
    if (!PB.cache[key]) PB.cache[key] = loader().catch(err => { delete PB.cache[key]; throw err; });
    return PB.cache[key];
}

function pbLoading(text) {
    return `<div class="recap-empty">${pbEsc(text)}</div>`;
}

// ---- modal shell ----------------------------------------------------------
async function openPastBingosModal(eventId) {
    let modal = document.getElementById('pastBingosModal');
    if (!modal) {
        document.body.insertAdjacentHTML('beforeend', `
            <div class="modal" id="pastBingosModal">
                <div class="modal-content pb-modal">
                    <button class="close-btn" onclick="closePastBingosModal()">✕</button>
                    <div id="pbBody"></div>
                </div>
            </div>
        `);
        modal = document.getElementById('pastBingosModal');
    }
    modal.classList.add('active');
    if (eventId) return pbOpenEvent(eventId);
    return pbShowPicker();
}

function closePastBingosModal() {
    const modal = document.getElementById('pastBingosModal');
    if (modal) modal.remove();
}

// ---- picker ---------------------------------------------------------------
async function pbShowPicker() {
    PB.id = null;
    pbBody().innerHTML = `<h2>📚 Past Bingos</h2>${pbLoading('Loading past bingos...')}`;
    try {
        const data = await pbFetch('/event/archive/list');
        PB.events = data.archives || [];
    } catch (e) {
        pbBody().innerHTML = `<h2>📚 Past Bingos</h2>${pbLoading('Could not load past bingos. Check your connection and try again.')}`;
        return;
    }

    const adminBar = isAdmin ? `
        <div class="pb-admin-bar">
            <button class="btn-secondary" onclick="archiveCurrentEvent()">📦 Archive current event</button>
            <span>Finished events are archived automatically within an hour of ending.</span>
        </div>` : '';

    if (PB.events.length === 0) {
        pbBody().innerHTML = `<h2>📚 Past Bingos</h2>
            ${pbLoading('No past bingos yet. Once a bingo finishes, its scores, board and luck will appear here.')}${adminBar}`;
        return;
    }

    const cards = PB.events.map(ev => {
        const s = ev.summary || {};
        const winners = (s.winners || []).map(pbEsc).join(', ');
        return `
            <div class="pb-event-card" onclick="pbOpenEvent('${pbEsc(ev._id)}')">
                <div class="pb-event-name">${pbEsc(ev.event_name)}</div>
                <div class="pb-event-dates">${pbEsc(pbDateRange(ev.start_date, ev.end_date))}</div>
                <div class="pb-event-winner">${winners ? `👑 ${winners} <span>${pbNumber(s.top_points)} pts</span>` : 'No winner recorded'}</div>
                <div class="pb-event-meta">
                    <span>👥 ${pbNumber(s.player_count)}</span>
                    <span>🎯 ${pbNumber(s.total_tiles_completed)} tiles</span>
                    <span>💰 ${pbEsc(formatRecapGp(s.total_gp))}</span>
                </div>
            </div>`;
    }).join('');

    const names = [...new Set(PB.events.flatMap(ev => ev.player_names || []))].sort((a, b) => a.localeCompare(b));
    const preselect = typeof currentPlayer !== 'undefined' && names.includes(currentPlayer) ? currentPlayer : '';

    pbBody().innerHTML = `
        <h2>📚 Past Bingos</h2>
        <p class="pb-sub">Scores, boards, luck and more from every finished bingo.</p>
        <div class="pb-event-grid">${cards}</div>
        ${adminBar}
        <div class="pb-history-box">
            <h3>📈 Player history</h3>
            <select id="pbHistoryPlayer" onchange="pbShowPlayerHistory(this.value)">
                <option value="">Pick a player to see every bingo they've played...</option>
                ${names.map(n => `<option value="${pbEsc(n)}"${n === preselect ? ' selected' : ''}>${pbEsc(n)}</option>`).join('')}
            </select>
            <div id="pbHistoryResult"></div>
        </div>`;
    if (preselect) pbShowPlayerHistory(preselect);
}

async function pbShowPlayerHistory(player) {
    const out = document.getElementById('pbHistoryResult');
    if (!out) return;
    if (!player) { out.innerHTML = ''; return; }
    out.innerHTML = pbLoading('Loading...');
    try {
        const data = await pbCached(`history:${player}`, () => pbFetch(`/event/player-history/${encodeURIComponent(player)}`));
        const rows = data.events || [];
        if (rows.length === 0) {
            out.innerHTML = pbLoading(`${player} hasn't played in an archived bingo yet.`);
            return;
        }
        out.innerHTML = `
            <div class="pb-table-wrap"><table class="pb-table">
                <thead><tr><th>Bingo</th><th>Rank</th><th>Points</th><th>Tiles</th><th>KC gained</th><th>Luck</th><th>GP looted</th><th></th></tr></thead>
                <tbody>${rows.map(r => `
                    <tr class="pb-click" onclick="pbOpenEvent('${pbEsc(r.archive_id)}')">
                        <td><strong>${pbEsc(r.event_name)}</strong><div class="pb-muted">${pbEsc(pbDateRange(r.start_date, r.end_date))}</div></td>
                        <td>${pbRankHtml(r.rank)} <span class="pb-muted">of ${r.field_size}</span></td>
                        <td>${pbNumber(r.points)}</td>
                        <td>${pbNumber(r.tiles_completed)}</td>
                        <td>${pbNumber(r.kc_gained)}</td>
                        <td>${pbLuckHtml(r.luck_score)}</td>
                        <td>${pbEsc(formatRecapGp(r.gp_total))}</td>
                        <td>${pbBadgesHtml(r.badges)}</td>
                    </tr>`).join('')}
                </tbody>
            </table></div>`;
    } catch (e) {
        out.innerHTML = pbLoading('Could not load player history.');
    }
}

// ---- event view -----------------------------------------------------------
async function pbOpenEvent(id, tab) {
    PB.id = id;
    PB.drops = { skip: 0, total: 0, loaded: 0 };
    if (!document.getElementById('pastBingosModal')) await openPastBingosModal();
    pbBody().innerHTML = pbLoading('Loading bingo...');
    try {
        PB.detail = await pbCached(`event:${id}`, () => pbFetch(`/event/archive/${id}`));
    } catch (e) {
        pbBody().innerHTML = `
            <button class="btn-cancel pb-back" onclick="pbShowPicker()">← All bingos</button>
            ${pbLoading(e.message || 'Could not load this bingo.')}`;
        return;
    }
    const d = PB.detail;
    const winners = (d.summary?.winners || []).map(pbEsc).join(', ');
    const warnings = d.warnings || [];
    const note = warnings.length
        ? `<div class="pb-note" title="${pbEsc(warnings.join(', '))}">Some figures for this bingo may be incomplete.</div>` : '';
    const tabs = PB_TABS.filter(t => !d.legacy || PB_LEGACY_TABS.includes(t.key));

    pbBody().innerHTML = `
        <button class="btn-cancel pb-back" onclick="pbShowPicker()">← All bingos</button>
        <h2 class="pb-title">${pbEsc(d.event_name)}</h2>
        <div class="pb-sub">${pbEsc(pbDateRange(d.start_date, d.end_date))}${winners ? ` &middot; 👑 ${winners}` : ''}</div>
        ${note}
        <div class="kc-tab-nav pb-tabs">
            ${tabs.map(t => `<button class="kc-tab" id="pbTab-${t.key}" onclick="pbShowTab('${t.key}')">${t.label}</button>`).join('')}
        </div>
        <div id="pbTabBody"></div>`;
    pbShowTab(tab && tabs.some(t => t.key === tab) ? tab : 'overview');
}

async function pbShowTab(tab) {
    PB.tab = tab;
    document.querySelectorAll('.pb-tabs .kc-tab').forEach(el => el.classList.toggle('active', el.id === `pbTab-${tab}`));
    const out = document.getElementById('pbTabBody');
    if (!out) return;
    out.innerHTML = pbLoading('Loading...');
    const id = PB.id;
    try {
        switch (tab) {
            case 'overview': pbRenderOverview(out); break;
            case 'board': pbRenderBoard(out); break;
            case 'kc': await pbRenderKC(out); break;
            case 'luck': await pbRenderLuck(out); break;
            case 'drops': pbRenderDrops(out); break;
            case 'extras': await pbRenderExtras(out); break;
        }
    } catch (e) {
        if (PB.id === id && PB.tab === tab) out.innerHTML = pbLoading(e.message || 'Could not load this section.');
    }
}

// ---- overview -------------------------------------------------------------
function pbRenderOverview(out) {
    const d = PB.detail;
    const s = d.summary || {};
    const stats = [
        ['👥', 'Players', pbNumber(s.player_count)],
        ['🎯', 'Tiles completed', pbNumber(s.total_tiles_completed)],
        ['💰', 'GP looted', formatRecapGp(s.total_gp)],
        ['💎', 'Drops', pbNumber(s.total_drops)],
        ['💀', 'KC gained', pbNumber(s.total_kc_gained)],
    ];

    const rows = (d.leaderboard || []).map(r => `
        <tr class="pb-click" data-player="${pbEsc(r.player)}" onclick="pbOpenRecap(this.dataset.player)" title="View ${pbEsc(r.player)}'s recap">
            <td>${pbRankHtml(r.rank)}</td>
            <td><strong>${pbEsc(r.player)}</strong></td>
            <td title="${pbNumber(r.tile_points)} from tiles + ${pbNumber(r.line_bonus)} line bonus"><strong>${pbNumber(r.points)}</strong></td>
            <td>${pbNumber(r.tiles_completed)}</td>
            <td>${pbNumber(r.kc_gained)}</td>
            <td>${pbEsc(formatRecapGp(r.gp_total))}</td>
            <td>${d.legacy ? '' : pbLuckHtml(r.luck_score)}</td>
            <td>${pbBadgesHtml(r.badges)}</td>
        </tr>`).join('');

    const topDrops = (d.top_drops || []).slice(0, 10);
    const topDropsHtml = topDrops.length ? `
        <h3 class="pb-h3">💰 Biggest drops</h3>
        <div class="pb-table-wrap"><table class="pb-table">
            <tbody>${topDrops.map((x, i) => `
                <tr>
                    <td class="pb-muted">${i + 1}</td>
                    <td><strong>${pbEsc(x.item)}</strong></td>
                    <td>${pbEsc(x.player)}</td>
                    <td class="pb-muted">${pbEsc(x.source || '')}</td>
                    <td>${pbEsc(formatRecapGp(x.value))}</td>
                    <td class="pb-muted">${pbEsc(pbDate(x.timestamp, false))}</td>
                </tr>`).join('')}
            </tbody>
        </table></div>` : '';

    out.innerHTML = `
        <div class="pb-stats">${stats.map(([icon, label, value]) => `
            <div class="pb-stat"><div class="pb-stat-value">${icon} ${pbEsc(value)}</div><div class="pb-stat-label">${label}</div></div>`).join('')}
        </div>
        <h3 class="pb-h3">🏆 Final standings <span class="pb-muted">(click a player for their recap)</span></h3>
        ${rows ? `<div class="pb-table-wrap"><table class="pb-table">
            <thead><tr><th></th><th>Player</th><th>Points</th><th>Tiles</th><th>KC gained</th><th>GP looted</th><th>${d.legacy ? '' : 'Luck'}</th><th>Badges</th></tr></thead>
            <tbody>${rows}</tbody>
        </table></div>` : pbLoading('No scores were recorded for this bingo.')}
        ${topDropsHtml}`;
}

async function pbOpenRecap(player) {
    renderRecapModalContent({ loading: true });
    try {
        const data = await pbFetch(`/event/archive/${PB.id}/player/${encodeURIComponent(player)}`);
        renderRecapModalContent({ data });
    } catch (e) {
        renderRecapModalContent({ error: e.message || 'No recap available.' });
    }
}

// ---- board ----------------------------------------------------------------
function pbTileName(tile) {
    const first = (tile.items || [])[0];
    const firstName = first && typeof first === 'object' ? first.name : first;
    return tile.displayTitle || firstName || 'Empty Tile';
}

function pbRenderBoard(out) {
    const board = PB.detail.board || {};
    const tiles = board.tiles || [];
    if (tiles.length === 0) {
        out.innerHTML = pbLoading('No board was saved for this bingo.');
        return;
    }
    const players = [...new Set(tiles.flatMap(t => t.completedBy || []))].sort((a, b) => a.localeCompare(b));
    const bonuses = board.lineBonuses || {};
    const list = arr => (arr || []).map((v, i) => `${i + 1}: ${v}`).join(' · ');
    const bonusParts = [
        bonuses.rows?.length ? `<strong>Rows</strong> ${list(bonuses.rows)}` : '',
        bonuses.cols?.length ? `<strong>Columns</strong> ${list(bonuses.cols)}` : '',
        bonuses.diags?.length ? `<strong>Diagonals</strong> ${list(bonuses.diags)}` : '',
    ].filter(Boolean);

    out.innerHTML = `
        <div class="pb-board-controls">
            <label for="pbBoardPlayer">Highlight player:</label>
            <select id="pbBoardPlayer" onchange="pbDrawBoard(this.value)">
                <option value="">Everyone</option>
                ${players.map(p => `<option value="${pbEsc(p)}">${pbEsc(p)}</option>`).join('')}
            </select>
        </div>
        <div class="bingo-board pb-board" id="pbBoardGrid"></div>
        ${bonusParts.length ? `<div class="pb-note pb-bonus">Line bonuses (points): ${bonusParts.join(' &nbsp;|&nbsp; ')}</div>` : ''}`;
    pbDrawBoard('');
}

function pbDrawBoard(player) {
    const grid = document.getElementById('pbBoardGrid');
    if (!grid) return;
    const board = PB.detail.board || {};
    const tiles = board.tiles || [];
    const size = board.boardSize || Math.round(Math.sqrt(tiles.length)) || 5;
    grid.style.setProperty('--board-size', size);

    grid.innerHTML = tiles.map(tile => {
        const done = tile.completedBy || [];
        let cls = 'bingo-tile';
        if (done.length) cls += !player || done.includes(player) ? ' completed-by-current' : ' completed-by-others';
        const first = (tile.items || [])[0];
        const itemName = first && typeof first === 'object' ? first.name : first;
        const when = Object.entries(tile.completedAt || {})
            .map(([p, iso]) => `${p} – ${pbDate(iso, false)}`).join('\n');
        return `
            <div class="${cls}" title="${pbEsc(when)}">
                <div class="tile-content">${pbEsc(pbTileName(tile))}</div>
                ${itemName ? `<div class="tile-images"><img class="item-icon" data-item="${pbEsc(itemName)}" alt=""></div>` : ''}
                <div class="tile-value">${pbEsc(tile.value)} points</div>
                ${done.length ? `<div class="tile-players">✓ ${done.map(pbEsc).join(', ')}</div>` : ''}
            </div>`;
    }).join('');
    grid.querySelectorAll('img[data-item]').forEach(img => loadItemImage(img, img.dataset.item));
}

// ---- boss KC --------------------------------------------------------------
async function pbRenderKC(out) {
    const id = PB.id;
    const data = await pbCached(`kc:${id}`, () => pbFetch(`/event/archive/${id}/kc`));
    if (PB.id !== id || PB.tab !== 'kc') return;
    const players = (data.players || []).map(p => ({
        player: p.player,
        bosses: Object.entries(p.effort || {}).filter(([, kc]) => kc > 0).sort((a, b) => b[1] - a[1]),
    })).filter(p => p.bosses.length);
    if (players.length === 0) {
        out.innerHTML = pbLoading('No kill count data was captured for this bingo.');
        return;
    }
    players.forEach(p => { p.total = p.bosses.reduce((sum, [, kc]) => sum + kc, 0); });
    players.sort((a, b) => b.total - a.total);

    out.innerHTML = `
        <p class="pb-sub">Kills gained during the bingo (from its start to its end).</p>
        <div class="pb-toggle">
            <button class="kc-tab ${PB.kcView === 'player' ? 'active' : ''}" id="pbKcPlayer" onclick="pbSetKcView('player')">👤 By player</button>
            <button class="kc-tab ${PB.kcView === 'boss' ? 'active' : ''}" id="pbKcBoss" onclick="pbSetKcView('boss')">🎯 By boss</button>
        </div>
        <div id="pbKcPlayerView"></div>
        <div id="pbKcBossView" style="display:none;"></div>`;

    document.getElementById('pbKcPlayerView').innerHTML = `<div class="pb-card-grid">${players.map(p => `
        <div class="player-kc-card">
            <div class="pb-card-head"><h3>${pbEsc(p.player)}</h3><span class="kc-value">${pbNumber(p.total)} KC</span></div>
            ${p.bosses.slice(0, 6).map(([boss, kc]) => `<div class="boss-kc-item"><span>${pbEsc(boss)}</span><span class="kc-value">${pbNumber(kc)}</span></div>`).join('')}
            ${p.bosses.length > 6 ? `<details class="pb-more"><summary>${p.bosses.length - 6} more bosses</summary>
                ${p.bosses.slice(6).map(([boss, kc]) => `<div class="boss-kc-item"><span>${pbEsc(boss)}</span><span class="kc-value">${pbNumber(kc)}</span></div>`).join('')}
            </details>` : ''}
        </div>`).join('')}</div>`;

    const byBoss = {};
    players.forEach(p => p.bosses.forEach(([boss, kc]) => {
        (byBoss[boss] = byBoss[boss] || []).push({ player: p.player, kc });
    }));
    const bossList = Object.entries(byBoss)
        .map(([boss, rows]) => ({ boss, rows: rows.sort((a, b) => b.kc - a.kc), total: rows.reduce((s, r) => s + r.kc, 0) }))
        .sort((a, b) => b.total - a.total);
    document.getElementById('pbKcBossView').innerHTML = `<div class="pb-boss-list">${bossList.map(b => `
        <details class="player-kc-card pb-boss-card">
            <summary><span>🎯 ${pbEsc(b.boss)}</span><span class="kc-value">${pbNumber(b.total)} KC</span></summary>
            ${b.rows.map(r => `<div class="boss-kc-item"><span>${pbEsc(r.player)}</span><span class="kc-value">${pbNumber(r.kc)}</span></div>`).join('')}
        </details>`).join('')}</div>`;
    pbSetKcView(PB.kcView);
}

function pbSetKcView(view) {
    PB.kcView = view;
    const p = document.getElementById('pbKcPlayerView'), b = document.getElementById('pbKcBossView');
    if (!p || !b) return;
    p.style.display = view === 'player' ? 'block' : 'none';
    b.style.display = view === 'boss' ? 'block' : 'none';
    document.getElementById('pbKcPlayer').classList.toggle('active', view === 'player');
    document.getElementById('pbKcBoss').classList.toggle('active', view === 'boss');
}

// ---- luck -----------------------------------------------------------------
async function pbRenderLuck(out) {
    const id = PB.id;
    const data = await pbCached(`luck:${id}`, () => pbFetch(`/event/archive/${id}/luck`));
    if (PB.id !== id || PB.tab !== 'luck') return;
    out.innerHTML = `
        <p class="pb-sub">Every drop is worth its own drop rate in kills (a 1/400 counts as 400 kills, a 1/50 as 50), so rarer drops count for more. Shown as kills ahead of or behind rate during this bingo. Click a boss to see each item.</p>
        <div class="pb-toggle">
            <button class="kc-tab ${PB.luckView === 'player' ? 'active' : ''}" id="pbLuckPlayer" onclick="pbSetLuckView('player')">👤 Player view</button>
            <button class="kc-tab ${PB.luckView === 'boss' ? 'active' : ''}" id="pbLuckBoss" onclick="pbSetLuckView('boss')">🎯 Boss view</button>
        </div>
        <div id="pbLuckPlayerView"></div>
        <div id="pbLuckBossView" style="display:none;"></div>`;
    renderLuckPlayerView(data, document.getElementById('pbLuckPlayerView'));
    renderLuckBossView(data, document.getElementById('pbLuckBossView'), 'pb-');
    pbSetLuckView(PB.luckView);
}

function pbSetLuckView(view) {
    PB.luckView = view;
    const p = document.getElementById('pbLuckPlayerView'), b = document.getElementById('pbLuckBossView');
    if (!p || !b) return;
    p.style.display = view === 'player' ? 'block' : 'none';
    b.style.display = view === 'boss' ? 'block' : 'none';
    document.getElementById('pbLuckPlayer').classList.toggle('active', view === 'player');
    document.getElementById('pbLuckBoss').classList.toggle('active', view === 'boss');
}

// ---- drops ----------------------------------------------------------------
const PB_DROPS_PAGE = 50;

function pbRenderDrops(out) {
    const players = PB.detail.player_names || [];
    out.innerHTML = `
        <div class="pb-filters">
            <select id="pbDropPlayer" onchange="pbLoadDrops(true)">
                <option value="">All players</option>
                ${players.map(p => `<option value="${pbEsc(p)}">${pbEsc(p)}</option>`).join('')}
            </select>
            <select id="pbDropType" onchange="pbLoadDrops(true)">
                <option value="">All drops</option>
                <option value="loot">Loot only</option>
                <option value="collection_log">Collection log only</option>
            </select>
            <input id="pbDropSearch" type="text" placeholder="Search items..." onkeydown="if (event.key === 'Enter') pbLoadDrops(true)">
            <button class="btn-primary" onclick="pbLoadDrops(true)">Search</button>
        </div>
        <div id="pbDropsCount" class="pb-muted"></div>
        <div class="pb-table-wrap"><table class="pb-table">
            <thead><tr><th>Date</th><th>Player</th><th>Item</th><th>Value</th><th>Source</th></tr></thead>
            <tbody id="pbDropsBody"></tbody>
        </table></div>
        <div style="text-align:center; margin-top:12px;"><button class="btn-secondary" id="pbDropsMore" style="display:none;" onclick="pbLoadDrops(false)">Load more</button></div>`;
    pbLoadDrops(true);
}

async function pbLoadDrops(reset) {
    const body = document.getElementById('pbDropsBody');
    if (!body) return;
    const id = PB.id;
    if (reset) {
        PB.drops = { skip: 0, total: 0, loaded: 0 };
        body.innerHTML = `<tr><td colspan="5" class="pb-muted">Loading...</td></tr>`;
    }
    const params = new URLSearchParams({ limit: PB_DROPS_PAGE, skip: PB.drops.skip });
    const player = document.getElementById('pbDropPlayer')?.value;
    const type = document.getElementById('pbDropType')?.value;
    const search = document.getElementById('pbDropSearch')?.value.trim();
    if (player) params.set('player', player);
    if (type) params.set('type', type);
    if (search) params.set('search', search);
    try {
        const data = await pbFetch(`/event/archive/${id}/drops?${params}`);
        if (PB.id !== id || !document.getElementById('pbDropsBody')) return;
        const rows = (data.history || []).map(h => `
            <tr>
                <td class="pb-muted">${pbEsc(pbDate(h.timestamp, false))}</td>
                <td>${pbEsc(h.player)}</td>
                <td><strong>${pbEsc(h.item)}</strong>${h.drop_type === 'collection_log' ? ' <span class="pb-muted">(collection log)</span>' : ''}</td>
                <td>${h.value ? pbEsc(formatRecapGp(h.value)) : '<span class="pb-muted">–</span>'}</td>
                <td class="pb-muted">${pbEsc(h.source || '')}</td>
            </tr>`).join('');
        if (reset) body.innerHTML = '';
        if (reset && !rows) {
            body.innerHTML = `<tr><td colspan="5" class="pb-muted">No drops match.</td></tr>`;
        } else {
            body.insertAdjacentHTML('beforeend', rows);
        }
        PB.drops.loaded += (data.history || []).length;
        PB.drops.skip = PB.drops.loaded;
        PB.drops.total = data.total || 0;
        document.getElementById('pbDropsCount').textContent = `Showing ${pbNumber(PB.drops.loaded)} of ${pbNumber(PB.drops.total)} drops`;
        document.getElementById('pbDropsMore').style.display = PB.drops.loaded < PB.drops.total ? 'inline-block' : 'none';
    } catch (e) {
        if (reset) body.innerHTML = `<tr><td colspan="5" class="pb-muted">${pbEsc(e.message || 'Could not load drops.')}</td></tr>`;
    }
}

// ---- personal bests -------------------------------------------------------
async function pbRenderExtras(out) {
    const id = PB.id;
    const pbs = await pbCached(`pbs:${id}`, () => pbFetch(`/event/archive/${id}/personal-bests`));
    if (PB.id !== id || PB.tab !== 'extras') return;

    const pbRows = (pbs.personal_bests || []).map(r => `
        <tr>
            <td><strong>${pbEsc(r.boss)}</strong>${r.invocation_level ? ` <span class="pb-muted">(${r.invocation_level} invocation)</span>` : ''}</td>
            <td>${pbEsc(r.player)}</td>
            <td>${pbEsc(r.time_string || r.time_seconds)}</td>
            <td class="pb-muted">${r.party_size > 1 ? `Team of ${r.party_size}` : 'Solo'}</td>
            <td class="pb-muted">${pbEsc(pbDate(r.timestamp, false))}</td>
        </tr>`).join('');

    out.innerHTML = `
        <h3 class="pb-h3" style="margin-top:0;">🏆 Personal bests set</h3>
        ${pbRows ? `<div class="pb-table-wrap"><table class="pb-table">
            <thead><tr><th>Boss</th><th>Player</th><th>Time</th><th>Team</th><th>Date</th></tr></thead><tbody>${pbRows}</tbody></table></div>` : pbLoading('No personal bests were set during this bingo.')}`;
}
