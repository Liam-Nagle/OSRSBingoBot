// ============================================
// Gear Contribution reference data + classifier
// ============================================
//
// Backs the "🛡️ Gear Contribution" analytics tab. Two separate, deliberately
// different definitions of "gear", picked after the plain "any equipable item"
// definition turned out to be too broad and a GP-value cutoff turned out to be
// unstable (the ranking flipped depending on where the line was drawn):
//
//   - Boss/raid uniques (gear-data/boss-unique-items.json): a hand-curated list
//     of actual chase items - weapons, armour, shields, and boss-exclusive
//     jewelry/ammo. Excludes anything that's just GE-buyable/craftable, even if
//     it happens to also drop from a boss's junk table. Each entry is checked
//     against what the boss actually drops, NOT the finished item a player
//     might later craft/combine it into (e.g. Cerberus drops "Primordial
//     crystal", never "Primordial boots" - see the file's _comment for the
//     full rule and why combined items like Soulreaper axe or a spirit shield
//     are deliberately left out in favour of their per-boss components).
//   - Rune-tier+ PvM gear (gear-data/tier-item-sources.json): broader and
//     looser - any rune-tier-or-better weapon/armour/shield sourced from an
//     actual PvM drop (not a shop, clue casket, or minigame reward), no value
//     cutoff. No jewelry or ammo at all in this one.
//
// Both start from the same base signal: gear-data/equipable-items.json, a list
// of every item name the OSRS Wiki tags with combat/equipment bonuses (built
// from the wiki's `infobox_bonuses` bucket - see the fetch commands in this
// feature's PR description for how to refresh it).
//
// None of this is a perfect algorithmic classifier - both curated lists are
// maintained by hand and can miss brand-new items. Edit the JSON files under
// gear-data/ directly to fix a miss; no code changes needed for that.

(function () {
    let equipableSet = null;
    let bossUniqueMap = null;
    let tierSourcesMap = null;
    let loadPromise = null;

    function loadGearData() {
        if (loadPromise) return loadPromise;
        loadPromise = Promise.all([
            fetch('gear-data/equipable-items.json').then(r => r.json()),
            fetch('gear-data/boss-unique-items.json').then(r => r.json()),
            fetch('gear-data/tier-item-sources.json').then(r => r.json())
        ]).then(([equipable, bossUnique, tierSources]) => {
            equipableSet = new Set(equipable);
            bossUniqueMap = bossUnique;
            tierSourcesMap = tierSources;
        }).catch(err => {
            console.error('[GearData] Failed to load gear reference data:', err);
            // Fail safe to "nothing matches" rather than leaving classifiers throwing
            equipableSet = equipableSet || new Set();
            bossUniqueMap = bossUniqueMap || {};
            tierSourcesMap = tierSourcesMap || {};
        });
        return loadPromise;
    }

    // "Black mask (10)" -> not in the whitelist directly, but "black mask" is -
    // charge-state/count suffixes like that are stripped once as a fallback.
    function normalizeToEquipable(itemName) {
        const n = itemName.trim().toLowerCase();
        if (equipableSet.has(n)) return n;
        const stripped = n.replace(/\s*\([^)]*\)\s*$/, '').trim();
        if (stripped && equipableSet.has(stripped)) return stripped;
        return null;
    }

    // List 1: boss/raid unique gear. This list is its own ground truth - unlike
    // List 2, membership does NOT require the item to be in the equipable
    // whitelist, because a boss's real unique drop is often an untradeable
    // component (a crystal, vestige, or sigil) that isn't equipable on its own
    // and only becomes gear once combined with something else - see the
    // "_note" fields in boss-unique-items.json for examples. Returns
    // { source, category } or null.
    function getBossUniqueInfo(itemName) {
        if (!bossUniqueMap) return null;
        const n = itemName.trim().toLowerCase();
        let info = bossUniqueMap[n];
        if (!info) {
            const stripped = n.replace(/\s*\([^)]*\)\s*$/, '').trim();
            if (stripped) info = bossUniqueMap[stripped];
        }
        if (!info || info.category === 'material') return null; // non-counting documentation entries only
        return info;
    }

    // List 2: rune-tier-or-better weapon/armour/shield from an actual PvM drop.
    const LOW_TIER = /\b(bronze|iron|steel|black|white|mithril|adamant)\b/i;
    const AMMO = /arrow|bolt|dart|javelin|thrownaxe|throwing knife|chinchompa/i;
    const JEWELRY = /\b(ring|necklace|amulet|bracelet|pendant)\b/i;
    const NON_PVM_SOURCE = /reward casket|random event|hunters. loot sack|soldier \(tier|rewards? chest|reward pool|lunar chest|grand gold chest|sarcophagus|ancient chest|drill demon|freaky forester|undead lumberjack|gravedigger|beekeeper \(|mime \(|vale offerings|equipment crate|impling/i;

    function isTierGear(itemName) {
        if (!equipableSet) return false;
        const canon = normalizeToEquipable(itemName);
        if (!canon) return false;
        if (AMMO.test(itemName)) return false;
        if (JEWELRY.test(itemName)) return false;
        if (LOW_TIER.test(itemName)) return false;

        const sources = tierSourcesMap[canon];
        if (sources && sources.length) {
            return sources.some(s => !NON_PVM_SOURCE.test(s));
        }
        // Not in our catalogued source data (a brand-new item we've never seen
        // and haven't looked up on the wiki yet) - default to including it once
        // it's cleared the tier/ammo/jewelry filters above, rather than silently
        // dropping a real drop. Add it to gear-data/tier-item-sources.json (with
        // its real wiki drop sources) to classify it precisely instead.
        return true;
    }

    window.GearData = { loadGearData, getBossUniqueInfo, isTierGear, normalizeToEquipable };
})();
