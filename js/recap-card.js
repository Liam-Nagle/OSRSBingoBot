// ============================================
// EVENT RECAP CARD
// The shareable "year in review" card for one player. Loaded before app.js and past-bingos.js,
// which both use buildRecapCardHtml() / RECAP_BADGE_INFO / formatRecapGp() (live recap + archived recap).
//
// Artwork lives in img/recap/. Everything the player reads (name, numbers, item names) is real HTML text
// laid over that art, never baked into an image.
//
// The card is exported to PNG by html2canvas, which only re-implements part of CSS: no background-clip:text,
// no mask, no backdrop-filter. Keep the card CSS (css/style.css, ".rc-" classes) inside those limits.
// ============================================

const RECAP_ART = 'img/recap/';

// file = image in img/recap/, emoji = used by the compact Past Bingos tables, desc = hover text on the card
const RECAP_BADGE_INFO = {
    mvp:             { file: 'badge-mvp',                emoji: '🏆', label: 'MVP',                desc: '1st Place this event!' },
    biggest_drop:    { file: 'badge-biggest-drop',       emoji: '💰', label: 'Biggest Drop',       desc: "The event's single most valuable drop" },
    rarest_drop:     { file: 'badge-rarest-drop',        emoji: '💎', label: 'Rarest Drop',        desc: "The event's rarest drop" },
    most_consistent: { file: 'badge-consistent',         emoji: '📅', label: 'Most Consistent',    desc: 'Logged drops on the most days' },
    top_grinder:     { file: 'badge-grinder',            emoji: '⚔️', label: 'Top Grinder',        desc: 'Most KC gained this event' },
    first_blood:     { file: 'badge-first-blood',        emoji: '🥇', label: 'First Blood',        desc: "Completed the event's very first tile" },
    closer:          { file: 'badge-closer',             emoji: '🌒', label: 'Closer',             desc: "Completed the event's last tile" },
    tiny_violin:     { file: 'badge-tiny-violin',        emoji: '🎻', label: 'Tiny Violin',        desc: 'The driest streak on the team' },
    silver_spoon:    { file: 'badge-silver-spoon',       emoji: '🥄', label: 'Silver Spoon',       desc: 'The luckiest streak on the team' },
    completionist:   { file: 'badge-completionist',      emoji: '✅', label: 'Completionist',      desc: 'Most tiles completed' },
    bingo:           { file: 'badge-bingo',              emoji: '🎉', label: 'Bingo!',             desc: 'Completed a full row, column or diagonal' },
    gold_hoarder:    { file: 'badge-gold-hoarder',       emoji: '🪙', label: 'Gold Hoarder',       desc: 'Highest GP looted' },
    boss_hopper:     { file: 'badge-boss-hopper',        emoji: '🐉', label: 'Boss Hopper',        desc: 'Killed the most different bosses' },
    specialist:      { file: 'badge-specialist',         emoji: '🎯', label: 'Specialist',         desc: 'Most KC at a single boss' },
    last_minute:     { file: 'badge-last-minute-hero',   emoji: '⏳', label: 'Last-Minute Hero',   desc: 'Most tiles in the final 24 hours' },
    speed_demon:     { file: 'badge-speed-demon',        emoji: '👟', label: 'Speed Demon',        desc: 'Most tiles in a single day' },
    lone_wolf:       { file: 'badge-lone-wolf',          emoji: '🐺', label: 'Lone Wolf',          desc: 'Most tiles that nobody else completed' },
    night_owl:       { file: 'badge-night-owl',          emoji: '🦉', label: 'Night Owl',          desc: 'Most drops in the late hours' },
    dry_spell:       { file: 'badge-dry-spell-survivor', emoji: '🏜️', label: 'Dry Spell Survivor', desc: 'Longest stretch without a notable drop' },
    weekend:         { file: 'badge-weekend-warrior',    emoji: '🍺', label: 'Weekend Warrior',    desc: 'Most drops on weekends' },
    weekday:         { file: 'badge-weekday-warrior',    emoji: '💼', label: 'Weekday Warrior',    desc: 'Most drops on weekdays' }
};

// Trophy cabinet order (rarest-feeling first) and how many fit on the card.
const RECAP_BADGE_ORDER = [
    'mvp', 'biggest_drop', 'rarest_drop', 'silver_spoon', 'tiny_violin', 'top_grinder', 'first_blood', 'closer',
    'most_consistent', 'completionist', 'bingo', 'gold_hoarder', 'boss_hopper', 'specialist', 'last_minute',
    'speed_demon', 'lone_wolf', 'night_owl', 'dry_spell', 'weekend', 'weekday'
];
const RECAP_MAX_BADGES = 9;
const RECAP_CARD_WIDTH = 540;
const RECAP_CARD_HEIGHT = Math.round(RECAP_CARD_WIDTH * 1704 / 900);   // frame art is 900x1704

// Flavour lines. One is picked per player from a hash of their name (+ the event), so a player's card
// never changes between opens, but different players get different lines.
const RECAP_QUOTES = {
    // GP panel line, chosen by rank on total GP looted: 1st / bottom two / everyone else
    heroFirst: [
        "Top of the loot pile.",
        "No trades. No handouts. Just loot.",
        "Ironman-certified haul.",
        "The bank is going to need another tab.",
        "Try carrying that in one inventory.",
        "Every last coin, earned the hard way.",
        "Please don't let it go to your head."
    ],
    heroMid: [
        "The loot. The grind. The glory.",
        "Your bank thanks you.",
        "Pockets heavier than they started.",
        "Earned, never traded.",
        "Steady hands, full bank.",
        "Another day, another drop."
    ],
    heroLast: [
        "Bank space was never your problem.",
        "Your inventory had room the whole time.",
        "A goblin could've dropped more than this.",
        "Gold? In this economy?",
        "Did you play, or just watch the chat?",
        "Every coin counts. Yours were counted quickly.",
        "Tutorial Island paid better.",
        "Somebody had to be last.",
        "Bank so empty it echoes.",
        "At least you showed up.",
        "Even the Wise Old Man couldn't find your loot.",
        "Your drop log is mostly bones.",
        "Carried by the Tutorial Island stipend.",
        "The monsters are the ones who got rich.",
        "A hard-earned participation award.",
        "Was your wiki tab open at all?",
        "Zero trades, and still nothing to show.",
        "Has the bank been unlocked yet?"
    ],
    // under the big leaderboard place (rank on points, which is what the site's leaderboard shows)
    placeFirst: [
        "Everyone else was playing for second.",
        "Top of the pile. Insufferable, probably.",
        "Untouchable. Don't let it go to your head."
    ],
    placeSecond: [
        "So close. Not close enough.",
        "First loser, technically.",
        "Second place is just first loser with a nicer ribbon."
    ],
    placeMid: [
        "Perfectly average. Congratulations.",
        "Forgettable, but present.",
        "Not first. Not last. Not memorable.",
        "The human equivalent of a bronze dagger."
    ],
    placeNextToLast: [
        "Almost last. Almost.",
        "One bad kill streak from the bottom.",
        "Mathematically not last. Barely."
    ],
    placeLast: [
        "Dead last. Someone had to.",
        "The floor, as promised.",
        "Wooden spoon. Wear it with pride.",
        "Last place. Nowhere to go but up."
    ],
    // under the luck line, only for the Silver Spoon / Tiny Violin holders
    lucky: [
        "The RNG gods remembered your name.",
        "Someone at Jagex likes you.",
        "The spoon has been located.",
        "You didn't get lucky. You got ridiculous.",
        "Even the RNG gods are jealous.",
        "The drop table paid up early.",
        "Rolled the dice and kept the loot."
    ],
    unlucky: [
        "The RNG gods have filed a restraining order.",
        "At this point, it's personal.",
        "The dry streak has become a lifestyle.",
        "Somewhere, a Tiny Violin is playing.",
        "Expected loot has left the chat.",
        "The drop table has you on mute.",
        "Hope is not a drop rate.",
        "So many kills. So little to show."
    ]
};

function hashRecapString(str) {
    let h = 2166136261;
    for (let i = 0; i < str.length; i++) {
        h ^= str.charCodeAt(i);
        h = Math.imul(h, 16777619);
    }
    return h >>> 0;
}

function pickRecapQuote(pool, seed, salt) {
    return pool[hashRecapString(`${salt}|${seed}`) % pool.length];
}

function recapEsc(value) {
    return String(value == null ? '' : value).replace(/[&<>"']/g, c => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[c]));
}

function formatRecapGp(value) {
    if (!value) return '0 gp';
    if (value >= 1000000) return (value / 1000000).toFixed(2).replace(/\.00$/, '').replace(/0$/, '') + 'M gp';
    if (value >= 1000) return (value / 1000).toFixed(1).replace(/\.0$/, '') + 'K gp';
    return `${value.toLocaleString()} gp`;
}

// "8.7M gp" -> {number: '8.7M', unit: 'gp'} so the big GP figure can style the unit separately
function splitRecapGp(value) {
    const text = formatRecapGp(value);
    const cut = text.lastIndexOf(' ');
    return { number: text.slice(0, cut), unit: text.slice(cut + 1) };
}

function formatRecapDate(iso) {
    if (!iso) return null;
    try {
        return new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
    } catch (e) {
        return null;
    }
}

// Dink's "Item Rarity" embed field comes through wrapped in Discord code-block
// fences (e.g. "```\n1 in 500.0 (0.2%)\n```"), and that raw text is what's stored —
// strip the fences/whitespace for display rather than showing them verbatim.
function formatRarityText(raw) {
    if (!raw) return '';
    return raw.replace(/```[a-z]*\n?/gi, '').replace(/```/g, '').replace(/\s+/g, ' ').trim();
}

function recapOrdinalParts(n) {
    const mod100 = n % 100;
    const suffix = (mod100 > 10 && mod100 < 14) ? 'th' : (['th', 'st', 'nd', 'rd'][n % 10] || 'th');
    return { number: n, suffix };
}

function buildRecapCardHtml(data) {
    const player = data.player || '';
    const seed = `${player}|${data.eventName || ''}`;
    const art = (file) => `${RECAP_ART}${file}.png`;

    // ---- trophies ----
    const owned = (data.badges || []).filter(key => RECAP_BADGE_INFO[key]);
    const earned = RECAP_BADGE_ORDER.filter(key => owned.includes(key));
    const shown = earned.slice(0, RECAP_MAX_BADGES);
    const hiddenCount = earned.length - shown.length;
    const cols = shown.length <= 4 ? Math.max(shown.length, 1) : shown.length <= 8 ? 4 : 5;
    const badgeSize = Math.min(shown.length > 6 ? 60 : 88, Math.floor((410 - (cols - 1) * 8) / cols));

    const trophiesHtml = shown.length ? `
        <div class="rc-badge-grid" style="--rc-bsize:${badgeSize}px; max-width:${cols * (badgeSize + 8)}px">
            ${shown.map(key => {
                const info = RECAP_BADGE_INFO[key];
                return `<div class="rc-badge" tabindex="0">
                    <div class="rc-tip"><b>${recapEsc(info.label)}</b><br>${recapEsc(info.desc)}</div>
                    <img src="${art(info.file)}" alt="${recapEsc(info.label)}">
                    <span>${recapEsc(info.label)}</span>
                </div>`;
            }).join('')}
        </div>
        <div class="rc-badge-key ${shown.length > 4 ? 'rc-two' : ''}">
            ${shown.map(key => `<div><b>${recapEsc(RECAP_BADGE_INFO[key].label)}</b> — ${recapEsc(RECAP_BADGE_INFO[key].desc)}</div>`).join('')}
        </div>
        ${hiddenCount > 0 ? `<div class="rc-more">+${hiddenCount} more trophies</div>` : ''}
    ` : `<div class="rc-no-trophies">No trophies this time.<br>The RNG may yet have a redemption arc.</div>`;

    // ---- place on the points leaderboard (the big number under the player name) ----
    let placeHtml = '';
    const n = data.field_size || 0;
    if (data.place && n) {
        const place = data.place;
        const key = place === 1 ? 'placeFirst'
            : (n >= 2 && place >= n) ? 'placeLast'
            : (n >= 3 && place === n - 1) ? 'placeNextToLast'
            : place === 2 ? 'placeSecond'
            : 'placeMid';
        const ord = recapOrdinalParts(place);
        placeHtml = `
            <div class="rc-place ${place === 1 ? 'rc-place-first' : ''}">
                <div class="rc-place-num">${ord.number}<sup>${ord.suffix}</sup></div>
                <div class="rc-place-quip">${recapEsc(pickRecapQuote(RECAP_QUOTES[key], seed, 'place'))}</div>
            </div>`;
    }

    // ---- GP panel: the line under the figure depends on rank by total GP looted ----
    const gpRank = data.gp_rank || 0;
    const gpPool = (!gpRank || !n) ? RECAP_QUOTES.heroMid
        : gpRank === 1 ? RECAP_QUOTES.heroFirst
        : gpRank > n - 2 ? RECAP_QUOTES.heroLast
        : RECAP_QUOTES.heroMid;
    const gp = splitRecapGp(data.gp_total);

    // ---- highlights (each only when it applies) ----
    const cells = [];
    if (data.most_valuable_drop) {
        cells.push({ icon: 'icon-biggest-drop', label: 'Biggest Drop', main: data.most_valuable_drop.item, sub: formatRecapGp(data.most_valuable_drop.value) });
    }
    if (data.rarest_drop) {
        cells.push({ icon: 'icon-rarest-drop', label: 'Rarest Drop', main: data.rarest_drop.item, sub: formatRarityText(data.rarest_drop.rarity) });
    }
    const firstDate = formatRecapDate(data.first_tile_at);
    const lastDate = formatRecapDate(data.last_tile_at);
    if (data.first_tile) {
        cells.push({ icon: 'icon-first-tile', label: 'First Tile', main: data.first_tile, sub: firstDate || '' });
    }
    if (data.last_tile && data.last_tile_at !== data.first_tile_at) {
        cells.push({ icon: 'icon-last-tile', label: 'Last Tile', main: data.last_tile, sub: lastDate || '' });
    }
    const highlightsHtml = cells.map((c, i) => `
        <div class="rc-hl ${(i === cells.length - 1 && cells.length % 2 === 1) ? 'rc-wide' : ''}"><img src="${art(c.icon)}" alt="">
            <div><small>${c.label}</small><strong>${recapEsc(c.main)}</strong>${c.sub ? `<em>${recapEsc(c.sub)}</em>` : ''}</div>
        </div>`).join('');

    let luckHtml = '';
    const hasLuckBadge = (data.badges || []).some(b => b === 'tiny_violin' || b === 'silver_spoon');
    if (typeof data.luck_score === 'number' && hasLuckBadge) {
        const unlucky = data.luck_score < 0;
        const magnitude = Math.round(Math.abs(data.luck_score)).toLocaleString();
        luckHtml = `
            <div class="rc-hl rc-luck"><img src="${art('icon-luck')}" alt="">
                <div><small>Luck</small>
                    <strong class="${unlucky ? 'rc-bad' : 'rc-good'}">${magnitude} kills ${unlucky ? 'behind' : 'ahead of'} drop rate</strong>
                    <em>${recapEsc(pickRecapQuote(unlucky ? RECAP_QUOTES.unlucky : RECAP_QUOTES.lucky, seed, 'luck'))}</em>
                </div>
            </div>`;
    }

    return `
        <div class="rc-scale">
            <div class="rc recap-card ${shown.length > 6 ? 'rc-tight' : ''}" id="recapCardCapture">
                <img class="rc-back" src="${art('backing-dark')}" alt="">
                <img class="rc-frame" src="${art('frame')}" alt="">
                <div class="rc-inner">
                    <div class="rc-eyebrow">Bingo · Year in Review</div>
                    <div class="rc-event">${recapEsc(data.eventName || 'Bingo Event')}</div>
                    <div class="rc-player" id="recapPlayerName">${recapEsc(player)}</div>
                    ${placeHtml}

                    <div class="rc-hero">
                        <div class="rc-hero-label">Total GP Looted</div>
                        <div class="rc-hero-value">${recapEsc(gp.number)}<small>${recapEsc(gp.unit)}</small></div>
                        <div class="rc-hero-tag">${recapEsc(pickRecapQuote(gpPool, seed, 'hero'))}</div>
                    </div>

                    <div class="rc-stats">
                        <div class="rc-stat"><img src="${art('icon-drops')}" alt=""><b>${data.drop_count || 0}</b><i>Drops</i></div>
                        <div class="rc-stat"><img src="${art('icon-tiles')}" alt=""><b>${data.tiles_completed || 0}</b><i>Tiles</i></div>
                        <div class="rc-stat"><img src="${art('icon-kc')}" alt=""><b>${(data.kc_gained || 0).toLocaleString()}</b><i>KC Gained</i></div>
                    </div>

                    <div class="rc-divider"></div>
                    <div class="rc-highlights">${highlightsHtml}${luckHtml}</div>
                    <div class="rc-divider"></div>

                    <div class="rc-trophies">
                        <div class="rc-section-title">Trophies Earned</div>
                        ${trophiesHtml}
                    </div>
                </div>
            </div>
        </div>`;
}

// ---- fonts, sizing, export -------------------------------------------------

// The card uses two Google fonts. Loaded the first time a recap opens rather than on every page view.
function ensureRecapFonts() {
    if (document.getElementById('recapFonts')) return;
    const link = document.createElement('link');
    link.id = 'recapFonts';
    link.rel = 'stylesheet';
    link.href = 'https://fonts.googleapis.com/css2?family=Cinzel:wght@500;700;900&family=Crimson+Pro:ital,wght@0,500;0,700;1,500&display=swap';
    document.head.appendChild(link);
}

async function recapFontsReady() {
    try {
        await Promise.all([
            document.fonts.load("900 36px 'Cinzel'"),
            document.fonts.load("700 12px 'Cinzel'"),
            document.fonts.load("700 14px 'Crimson Pro'"),
            document.fonts.load("italic 500 14px 'Crimson Pro'")
        ]);
        await document.fonts.ready;
    } catch (e) { /* fall back to whatever fonts are available */ }
}

// Shrinks the player name until it fits on one line, and scales the whole card down on narrow screens.
function layoutRecapCard() {
    const name = document.getElementById('recapPlayerName');
    if (name) {
        let size = 36;
        name.style.fontSize = size + 'px';
        while (name.scrollWidth > name.clientWidth && size > 16) {
            size -= 1;
            name.style.fontSize = size + 'px';
        }
    }
    // The card is a fixed 540px wide; shrink it so the whole card plus its buttons fits on screen without scrolling.
    const scale = document.querySelector('#recapModalBody .rc-scale');
    if (scale) {
        const fitWidth = (window.innerWidth - 24) / RECAP_CARD_WIDTH;
        const fitHeight = (window.innerHeight - 96) / RECAP_CARD_HEIGHT;
        scale.style.zoom = Math.max(0.25, Math.min(1, fitWidth, fitHeight));
    }
}

async function prepareRecapCard() {
    ensureRecapFonts();
    layoutRecapCard();
    await recapFontsReady();
    layoutRecapCard();
}

async function captureRecapCanvas() {
    const card = document.getElementById('recapCardCapture');
    if (!card || typeof html2canvas === 'undefined') return null;
    await recapFontsReady();
    // Transparent outside the frame; the export copy shows the badge explanations as text
    // (a hover tooltip can't survive being turned into a flat image).
    return await html2canvas(card, {
        backgroundColor: null,
        scale: 2,
        useCORS: true,
        onclone: (doc) => {
            const cloned = doc.getElementById('recapCardCapture');
            if (cloned) cloned.classList.add('rc-export');
            const scale = doc.querySelector('.rc-scale');
            if (scale) scale.style.zoom = '1';
        }
    });
}

window.addEventListener('resize', () => { if (document.getElementById('recapCardCapture')) layoutRecapCard(); });

document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && document.getElementById('recapModal')) closeRecapModal();
});
