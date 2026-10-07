// ============================================================
// Site navigation
// ============================================================
// One menu definition (NAV_SECTIONS / NAV_ADMIN / NAV_UTILITIES below) rendered as one of three layouts:
//   sidebar - left column beside the board, collapsible to an icon rail (default)
//   topbar  - sticky bar with dropdown panels that describe each page
//   drawer  - ☰ Menu button that slides the full tree in from the left
//
// The chosen layout is remembered per-browser (localStorage). A link like  ?layout=drawer  also sets it.
//
// Loaded before app.js so the nav is already in the DOM when app.js wires up its handlers. app.js relies on
// these element IDs existing exactly once: adminControls, loginBtn, editBtn (with .nav-icon/.nav-label),
// changelogBadge, exportDataBtn, eventTimerBtn, exportBtn - so only the active layout is ever rendered.

const NAV_LAYOUTS = { sidebar: 'Sidebar', topbar: 'Top bar', drawer: 'Drawer' };
const NAV_DEFAULT_LAYOUT = 'sidebar';
const NAV_LAYOUT_KEY = 'navLayout';

// ---- Menu definition ------------------------------------------------------
// A leaf is { icon, label, desc, go } (go = target for navGo) or { icon, label, fn } (fn = raw call).
// A column with tree:true renders as a collapsible sub-tree in the sidebar/drawer; otherwise its
// items sit directly under the section. In the top bar every column is a titled column of the dropdown.
const NAV_SECTIONS = [
    { icon: '💎', label: 'Drops', columns: [
        { title: 'Log', items: [
            { icon: '📜', label: 'Drop History', desc: 'Every recorded drop — filter by player, type or value', go: 'history' },
        ] },
        { title: 'Analytics', icon: '📊', tree: true, items: [
            { icon: '📈', label: 'Trends', desc: 'Drops per day and month-over-month', go: 'analytics:trends' },
            { icon: '🗓️', label: 'Activity', desc: "When the group plays, and who's most active", go: 'analytics:activity' },
            { icon: '🏆', label: 'Items & Value', desc: 'Most dropped items, value leaderboard, loot table', go: 'analytics:items' },
            { icon: '🛡️', label: 'Gear Contribution', desc: "Who's brought in the most gear, all-time", go: 'analytics:gear' },
        ] },
    ] },
    { icon: '⚔️', label: 'Bosses', columns: [
        { title: 'Boss KC', icon: '💀', tree: true, items: [
            { icon: '👥', label: 'Overview', desc: "Each player's top bosses at a glance", go: 'kc:overview' },
            { icon: '🥇', label: 'Leaderboards', desc: "Pick a boss and see who's on top", go: 'kc:leaderboards' },
            { icon: '💪', label: 'Effort', desc: 'KC by player or by boss', go: 'kc:details' },
            { icon: '🧩', label: 'Boss Contribution', desc: "Who's pulling their weight on each boss", go: 'kc:contribution' },
            { icon: '🍀', label: 'Luck Tracker', desc: "Actual drops vs. expected, overall and by boss", go: 'kc:luck' },
        ] },
        { title: 'Records', items: [
            { icon: '🏆', label: 'Personal Bests', desc: 'Fastest recorded times per boss', go: 'pbs' },
        ] },
    ] },
    { icon: '🏁', label: 'Progress', columns: [
        { title: 'Bingo', items: [
            { icon: '📅', label: 'Tile Race Timeline', desc: 'Which tiles got done each day', go: 'timeline' },
            { icon: '📚', label: 'Past Bingos', desc: 'Scores, boards, luck and more from earlier bingos', go: 'past' },
        ] },
        { title: 'Group', items: [
            { icon: '📈', label: 'Group Rank History', desc: 'GIM overall & prestige rank over time', go: 'rank' },
        ] },
    ] },
];

// Shown only once logged in as admin (app.js shows/hides #adminControls)
const NAV_ADMIN = {
    top: [
        { icon: '📝', label: 'Edit Mode', fn: 'toggleEditMode()', id: 'editBtn' },
    ],
    columns: [
        { title: 'Tiles & Board', icon: '🎯', open: true, items: [
            { icon: '✏️', label: 'Manual Override', fn: 'openManualOverrideModal()' },
            { icon: '📐', label: 'Board Size', fn: 'openBoardSizeModal()' },
            { icon: '🔀', label: 'Shuffle Board', fn: 'shuffleBoard()' },
            { icon: '↩️', label: 'Undo Shuffle', fn: 'undoShuffle()' },
            { icon: '🗑️', label: 'Clear Board', fn: 'clearBoard()', danger: true },
        ] },
        { title: 'Event', icon: '📅', items: [
            { icon: '⏱️', label: 'Event Timer', fn: 'openEventConfigModal()', id: 'eventTimerBtn' },
            { icon: '⚙️', label: 'Configure Bonuses', fn: 'openBonusConfig()' },
            { icon: '📦', label: 'Archive Current Event', fn: 'archiveCurrentEvent()' },
            { icon: '📚', label: 'Past Bingos', fn: 'openPastBingosModal()' },
        ] },
        { title: 'Data', icon: '💾', items: [
            { icon: '💾', label: 'Export Board', fn: 'exportBoard()', id: 'exportBtn' },
            { icon: '📥', label: 'Import Board', fn: 'importBoard()' },
            { icon: '🔗', label: 'API Info', fn: 'showApiInfo()' },
            { icon: '🔌', label: 'RuneLite Plugin Token', fn: 'openPluginTokenModal()' },
            { icon: '📡', label: 'Plugin Sync Status', fn: 'openSyncStatusModal()' },
        ] },
    ],
    bottom: [
        { icon: '🚪', label: 'Logout', fn: 'logout()', danger: true },
    ],
};

// Out-of-the-way extras. Order: Export Data, Changelog, Admin Login (login is hidden by app.js once admin).
const NAV_UTILITIES = [
    { icon: '📤', label: 'Export Data', go: 'export', id: 'exportDataBtn' },
    { icon: '📝', label: 'Changelog', fn: 'openChangelogModal()', badge: true },
    { icon: '🔐', label: 'Admin Login', fn: 'openLoginModal()', id: 'loginBtn' },
];

// ---- Layout choice --------------------------------------------------------
function getNavLayout() {
    let fromUrl = null;
    try {
        const params = new URLSearchParams(location.search);
        fromUrl = params.get('layout');
        if (fromUrl && NAV_LAYOUTS[fromUrl]) {
            // Consume the param so a later switch via the banner isn't overridden on reload
            params.delete('layout');
            const qs = params.toString();
            history.replaceState(null, '', location.pathname + (qs ? '?' + qs : '') + location.hash);
        }
    } catch (e) {}

    if (fromUrl && NAV_LAYOUTS[fromUrl]) {
        try { localStorage.setItem(NAV_LAYOUT_KEY, fromUrl); } catch (e) {}
        return fromUrl;
    }

    let saved = null;
    try { saved = localStorage.getItem(NAV_LAYOUT_KEY); } catch (e) {}
    return NAV_LAYOUTS[saved] ? saved : NAV_DEFAULT_LAYOUT;
}

function setNavLayout(layout) {
    if (!NAV_LAYOUTS[layout]) return;
    try { localStorage.setItem(NAV_LAYOUT_KEY, layout); } catch (e) {}
    location.reload();
}

// ---- Shared helpers -------------------------------------------------------
function navEsc(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function navAction(leaf) {
    return leaf.go ? `navGo('${leaf.go}')` : leaf.fn;
}

function navBadgeHtml() {
    return '<span id="changelogBadge" class="changelog-badge" style="display: none;">NEW</span>';
}

// ---- Sidebar / drawer (tree) ---------------------------------------------
function treeLeaf(leaf) {
    const id = leaf.id ? ` id="${leaf.id}"` : '';
    const cls = 'nav-link' + (leaf.danger ? ' danger' : '');
    return `<button class="${cls}"${id} onclick="${navAction(leaf)}">` +
        `<span class="nav-icon">${leaf.icon}</span><span class="nav-label">${navEsc(leaf.label)}</span>` +
        `${leaf.badge ? navBadgeHtml() : ''}</button>`;
}

function treeSubtree(col) {
    return `<details class="side-nav-subtree"${col.open ? ' open' : ''}>` +
        `<summary><span class="nav-icon">${col.icon}</span><span class="nav-label">${navEsc(col.title)}</span><span class="nav-chevron">▸</span></summary>` +
        `<div class="nav-links nav-sublinks">${col.items.map(treeLeaf).join('')}</div></details>`;
}

function treeHtml() {
    let html = '';

    NAV_SECTIONS.forEach(section => {
        html += `<details class="side-nav-tree" open>` +
            `<summary><span class="nav-icon">${section.icon}</span><span class="nav-label">${navEsc(section.label)}</span><span class="nav-chevron">▸</span></summary>` +
            `<div class="nav-links">` +
            section.columns.map(col => col.tree ? treeSubtree({ ...col, open: true }) : col.items.map(treeLeaf).join('')).join('') +
            `</div></details>`;
    });

    html += `<details class="side-nav-tree admin-tree" id="adminControls" style="display: none;" open>` +
        `<summary><span class="nav-icon">🛠️</span><span class="nav-label">Admin</span><span class="nav-chevron">▸</span></summary>` +
        `<div class="nav-links">` +
        NAV_ADMIN.top.map(treeLeaf).join('') +
        NAV_ADMIN.columns.map(treeSubtree).join('') +
        NAV_ADMIN.bottom.map(treeLeaf).join('') +
        `</div></details>`;

    html += `<div class="nav-footer">${NAV_UTILITIES.map(treeLeaf).join('')}</div>`;
    return html;
}

function sidebarHtml() {
    return `<div class="side-nav-backdrop" id="sideNavBackdrop" onclick="closeSideNav()"></div>` +
        `<nav class="side-nav" id="sideNav" aria-label="Main menu">` +
        `<div class="side-nav-header">` +
        `<button class="side-nav-toggle-btn" id="sideNavToggle" onclick="toggleSideNav()" title="Toggle menu">☰</button>` +
        `<span class="side-nav-title">Menu</span></div>` +
        treeHtml() + `</nav>`;
}

// ---- Drawer ---------------------------------------------------------------
function openDrawer() {
    document.getElementById('navDrawer').classList.add('open');
    document.getElementById('drawerBackdrop').classList.add('open');
}

function closeDrawer() {
    const drawer = document.getElementById('navDrawer');
    if (!drawer) return;
    drawer.classList.remove('open');
    document.getElementById('drawerBackdrop').classList.remove('open');
}

function initDrawer() {
    document.addEventListener('keydown', e => { if (e.key === 'Escape') closeDrawer(); });

    // Picking any action closes the drawer so the board/modal isn't left covered
    document.getElementById('navDrawer').addEventListener('click', e => {
        if (e.target.closest('button.nav-link')) closeDrawer();
    });

    // The Changelog "NEW" badge lives inside the drawer - mirror it as a red dot on the ☰ Menu button.
    // app.js shows/hides the badge itself, so just watch it.
    const badge = document.getElementById('changelogBadge');
    const dot = document.getElementById('menuDot');
    if (badge && dot) {
        const sync = () => { dot.style.display = badge.style.display === 'none' ? 'none' : 'block'; };
        new MutationObserver(sync).observe(badge, { attributes: true, attributeFilter: ['style'] });
        sync();
    }
}

function hamburgerHtml() {
    return `<div class="hamburger-wrap"><button class="hamburger" type="button" onclick="openDrawer()" aria-label="Open menu">` +
        `<span class="hamburger-icon">☰</span><span>Menu</span><span class="menu-dot" id="menuDot"></span></button></div>`;
}

function drawerHtml() {
    return `<div class="drawer-backdrop" id="drawerBackdrop" onclick="closeDrawer()"></div>` +
        `<nav class="nav-drawer" id="navDrawer" aria-label="Main menu">` +
        `<div class="drawer-header"><span class="drawer-title">⚔️ Menu</span>` +
        `<button class="drawer-close" type="button" onclick="closeDrawer()" title="Close (Esc)">✕</button></div>` +
        treeHtml() + `</nav>`;
}

// ---- Top bar --------------------------------------------------------------
function menuLink(leaf, compact) {
    const id = leaf.id ? ` id="${leaf.id}"` : '';
    const call = leaf.go ? `menuGo('${leaf.go}')` : `closeMenus();${leaf.fn}`;
    const cls = 'menu-link' + (compact ? ' compact' : '') + (leaf.danger ? ' danger' : '');
    const desc = !compact && leaf.desc ? `<span class="menu-link-desc">${navEsc(leaf.desc)}</span>` : '';
    return `<button class="${cls}"${id} onclick="${call}">` +
        `<span class="menu-link-title"><span class="nav-icon">${leaf.icon}</span> <span class="nav-label">${navEsc(leaf.label)}</span></span>${desc}</button>`;
}

function menuColumn(title, leaves, compact) {
    return `<div class="menu-col"><div class="menu-col-title">${title}</div>${leaves.map(l => menuLink(l, compact)).join('')}</div>`;
}

function menuTrigger(label) {
    return `<button class="menu-trigger" type="button" onclick="toggleMenu(this)" aria-haspopup="true" aria-expanded="false">` +
        `<span>${label}</span><span class="caret">▼</span></button>`;
}

function topbarHtml() {
    let main = '';
    NAV_SECTIONS.forEach(section => {
        main += `<div class="menu-item">${menuTrigger(`${section.icon} ${navEsc(section.label)}`)}` +
            `<div class="menu-panel">` +
            section.columns.map(col => menuColumn(`${col.icon ? col.icon + ' ' : ''}${navEsc(col.title)}`, col.items, false)).join('') +
            `</div></div>`;
    });

    // Admin: Edit Mode leads the first column, Logout closes the last
    const adminCols = NAV_ADMIN.columns.map(c => ({ ...c, items: [...c.items] }));
    adminCols[0].items.unshift(...NAV_ADMIN.top);
    adminCols[adminCols.length - 1].items.push(...NAV_ADMIN.bottom);

    const utility = NAV_UTILITIES.map(u => {
        const id = u.id ? ` id="${u.id}"` : '';
        return `<button class="util-btn" type="button"${id} onclick="${navAction(u)}">${u.icon} ${navEsc(u.label)}${u.badge ? navBadgeHtml() : ''}</button>`;
    }).join('');

    const admin = `<div class="menu-item" id="adminControls" style="display: none;">${menuTrigger('🛠️ Admin')}` +
        `<div class="menu-panel menu-panel-right">` +
        adminCols.map(col => menuColumn(`${col.icon} ${navEsc(col.title)}`, col.items, true)).join('') +
        `</div></div>`;

    return `<nav class="menubar" id="menuBar" aria-label="Main menu">` +
        `<div class="menubar-main">${main}</div>` +
        `<div class="menubar-utility">${utility}${admin}</div></nav>`;
}

function closeMenus() {
    document.querySelectorAll('.menu-item.open').forEach(item => {
        item.classList.remove('open');
        item.querySelector('.menu-trigger').setAttribute('aria-expanded', 'false');
    });
}

function openMenu(item) {
    closeMenus();
    item.classList.add('open');
    item.querySelector('.menu-trigger').setAttribute('aria-expanded', 'true');
}

function toggleMenu(btn) {
    const item = btn.closest('.menu-item');
    if (item.classList.contains('open')) closeMenus(); else openMenu(item);
}

function menuGo(target) {
    closeMenus();
    navGo(target);
}

function initTopbar() {
    document.addEventListener('click', e => { if (!e.target.closest('.menu-item')) closeMenus(); });
    document.addEventListener('keydown', e => { if (e.key === 'Escape') closeMenus(); });
    document.querySelectorAll('.menu-item').forEach(item => {
        item.addEventListener('mouseenter', () => {
            // Like a desktop menu bar: once one menu is open, hovering another switches to it
            if (window.matchMedia('(hover: hover)').matches && document.querySelector('.menu-item.open') && !item.classList.contains('open')) {
                openMenu(item);
            }
        });
    });
}

// ---- Deep links -----------------------------------------------------------
// Jump straight to a page, or to a sub-tab inside a modal, e.g. navGo('analytics:trends'), navGo('kc:leaderboards')
async function navGo(target) {
    const [page, sub] = target.split(':');

    switch (page) {
        case 'history':  openHistoryModal(); break;
        case 'rank':     openRankHistoryModal(); break;
        case 'timeline': openTimelineModal(); break;
        case 'pbs':      openPBsModal(); break;
        case 'past':     openPastBingosModal(sub); break;
        case 'export':   openExportModal(); break;

        case 'analytics':
            openAnalyticsModal();
            showAnalyticsTab(sub || 'trends');
            break;

        case 'kc': {
            const tab = sub || 'overview';
            // openKCModal() resets to Overview once its data has loaded, so start it,
            // show the requested tab straight away, then re-assert it after the load
            const loading = openKCModal();
            showKCTab(tab);
            const pane = document.getElementById('kcTabContent' + tab.charAt(0).toUpperCase() + tab.slice(1));
            if (pane && !pane.innerHTML.trim()) {
                pane.innerHTML = '<div class="loading-message"><div class="loading-spinner"></div><p>Loading Boss Kill Counts...</p></div>';
            }
            await loading;
            showKCTab(tab);
            break;
        }
    }
}

// ---- Layout trial banner --------------------------------------------------
// Temporary: lets people flip between the layouts and tell us which they prefer.
// Once one is chosen, delete this block, the .nav-trial-banner CSS and #navHeadMount's banner call.
const NAV_TRIAL_HIDDEN_KEY = 'navTrialBannerHidden';

function hideNavTrialBanner() {
    const banner = document.getElementById('navTrialBanner');
    if (banner) banner.remove();
    try { localStorage.setItem(NAV_TRIAL_HIDDEN_KEY, '1'); } catch (e) {}
}

function navTrialBannerHtml(current) {
    const options = Object.entries(NAV_LAYOUTS).map(([key, name]) =>
        `<button class="ntb-opt${key === current ? ' current' : ''}" type="button" onclick="setNavLayout('${key}')"${key === current ? ' disabled' : ''}>${name}</button>`
    ).join('');
    return `<div class="nav-trial-banner" id="navTrialBanner">` +
        `<span class="ntb-label">🧭 Trying out new menu layouts:</span>${options}` +
        `<span class="ntb-note">Message me in Discord to say which one you prefer!</span>` +
        `<button class="ntb-close" type="button" onclick="hideNavTrialBanner()" title="Hide this">✕</button></div>`;
}

// ---- Render ---------------------------------------------------------------
(function renderNav() {
    const layout = getNavLayout();
    document.body.dataset.navLayout = layout;

    const head = document.getElementById('navHeadMount');   // above the title: banner (+ ☰ button in drawer layout)
    const top = document.getElementById('navTopMount');     // between the header widgets and the board: top bar
    const side = document.getElementById('navSideMount');   // first column beside the board: sidebar

    let trialHidden = false;
    try { trialHidden = localStorage.getItem(NAV_TRIAL_HIDDEN_KEY) === '1'; } catch (e) {}
    if (head && !trialHidden) head.innerHTML = navTrialBannerHtml(layout);

    if (layout === 'sidebar' && side) {
        side.innerHTML = sidebarHtml();
    } else if (layout === 'topbar' && top) {
        top.innerHTML = topbarHtml();
        initTopbar();
    } else if (layout === 'drawer' && head) {
        head.insertAdjacentHTML('beforeend', hamburgerHtml());
        document.body.insertAdjacentHTML('beforeend', drawerHtml());
        initDrawer();
    }
})();
