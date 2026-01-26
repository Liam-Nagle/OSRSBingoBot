/* ============================================
   OSRS Bingo Board - JavaScript
   ============================================

   Main application logic for the OSRS Bingo Board

   Features:
   - Bingo board management
   - Player view and filtering
   - Drop history tracking
   - Analytics dashboard
   - Admin controls
   - Real-time updates

   API Endpoint: https://osrsbingobot.onrender.com
   ============================================ */

        let editMode = false;
        let currentTileIndex = null;
        let isAdmin = false;
        let currentPlayer = null;
        let bingoData = {
            boardSize: 5,
            tiles: [],
            completions: {},
            lineBonuses: {
                rows: [50, 50, 50, 50, 50],
                cols: [50, 50, 50, 50, 50],
                diags: [100, 100]
            }
        };

        const API_URL = 'https://osrsbingobot.onrender.com'; //Production ENV
        //const API_URL = 'http://localhost:5000'; //Local Testing

        // Tenant & Plan tracking
        let currentTenant = null;
        let tenantPlan = 'free';
        let tenantFeatures = {};
        let tenantLimits = {};


        async function loadTenantInfo() {
            console.log('📊 Loading tenant info...');

            try {
                const response = await fetch(`${API_URL}/api/tenant/info`);

                if (!response.ok) {
                    console.error('Failed to load tenant info:', response.status);
                    return;
                }

                const data = await response.json();

                if (data.success) {
                    currentTenant = data.tenant;
                    tenantPlan = data.tenant.plan;
                    tenantFeatures = data.features;
                    tenantLimits = data.limits;

                    console.log('✅ Tenant loaded:', currentTenant.name);
                    console.log('   Plan:', tenantPlan);
                    console.log('   Features:', tenantFeatures);
                    console.log('   Limits:', tenantLimits);

                    // Update UI based on plan
                    updateUIForPlan();
                } else {
                    console.error('Tenant info error:', data.error);
                }

            } catch (error) {
                console.error('❌ Error loading tenant info:', error);
            }
        }

        function updateUIForPlan() {
            console.log('🎨 Updating UI for plan:', tenantPlan);

            const isPremium = tenantPlan === 'premium' || tenantPlan === 'owner';

            if (isPremium) {
                // Premium/Owner - show everything
                document.body.classList.add('plan-premium');
                document.body.classList.remove('plan-free');
                console.log('   ✅ Premium features enabled');
                return;
            }

            // Free tier - hide premium features
            document.body.classList.add('plan-free');
            document.body.classList.remove('plan-premium');

            // Hide premium buttons (UPDATED LIST)
            const premiumFeatures = [
                'analyticsBtn',
                'deathsBtn',
                'bossKCBtn',
                'eventTimerBtn',
                'exportBtn',
                'viewHistoryBtn',      // NEW
                'rankHistoryBtn'       // NEW
            ];

            premiumFeatures.forEach(btnId => {
                const btn = document.getElementById(btnId);
                if (btn) {
                    // Add premium badge
                    if (!btn.querySelector('.premium-badge')) {
                        const badge = document.createElement('span');
                        badge.className = 'premium-badge';
                        badge.textContent = '⭐';
                        badge.title = 'Premium feature';
                        btn.appendChild(badge);
                    }

                    // Override click to show upgrade modal
                    btn.onclick = (e) => {
                        e.preventDefault();
                        e.stopPropagation();
                        showUpgradeModal(btnId);
                    };

                    console.log('   🔒 Locked:', btnId);
                }
            });
        }

        function showUpgradeModal(featureName = '') {
            // Feature name mapping
            const featureNames = {
                'analyticsBtn': 'Analytics & Charts',
                'deathsBtn': 'Death Tracking',
                'bossKCBtn': 'Boss KC Tracking',
                'eventTimerBtn': 'Event Timer',
                'exportBtn': 'Export Data',
                'viewHistoryBtn': 'Drop History',
                'rankHistoryBtn': 'Rank History'
            };

            const feature = featureNames[featureName] || 'Premium Features';

            const modal = document.createElement('div');
            modal.className = 'modal active';
            modal.id = 'upgradeModal';

            modal.innerHTML = `
                <div class="modal-content upgrade-modal-content">
                    <button class="close-btn" onclick="closeUpgradeModal()">×</button>

                    <div class="upgrade-modal-icon">⭐</div>
                    <h2 class="upgrade-modal-title">Upgrade to Premium</h2>
                    <p class="upgrade-modal-subtitle">
                        Unlock <strong>${feature}</strong> and all premium features!
                    </p>

                    <div class="upgrade-pricing-box">
                        <div class="upgrade-price-container">
                            <div class="upgrade-price">£2.99</div>
                            <div class="upgrade-price-period">per month</div>
                        </div>

                        <div class="upgrade-features-title">
                            ✓ Everything in Free, plus:
                        </div>

                        <div class="upgrade-features-list">
                            ✓ Unlimited board size (up to 9x9)<br>
                            ✓ Unlimited drop history<br>
                            ✓ Full analytics & charts<br>
                            ✓ Death tracking & statistics<br>
                            ✓ Boss KC tracking<br>
                            ✓ Complete rank history<br>
                            ✓ Event timer with auto-filtering<br>
                            ✓ Export data (CSV/JSON)<br>
                            ✓ Priority support
                        </div>
                    </div>

                    <button class="upgrade-btn-primary" onclick="window.location.href='${API_URL}/upgrade'">
                        Upgrade Now - £2.99/month
                    </button>

                    <button class="upgrade-btn-secondary" onclick="closeUpgradeModal()">
                        Maybe Later
                    </button>

                    <p class="upgrade-guarantee">
                        7-day money-back guarantee • Cancel anytime
                    </p>
                </div>
            `;

            document.body.appendChild(modal);
        }

        function closeUpgradeModal() {
            const modal = document.getElementById('upgradeModal');
            if (modal) {
                modal.remove();
            }
        }

        function changePlayer() {
            currentPlayer = document.getElementById('playerSelect').value || null;
            localStorage.setItem('lastViewedPlayer', currentPlayer || '');
            renderBoard();
            updateFavoriteButton();

            // Refresh bonus overlay if it's visible
            if (bonusOverlayVisible) {
                showBonusOverlay();
            }
        }

        function toggleFavorite() {
            if (!currentPlayer) {
                alert('Please select a player first!');
                return;
            }

            const favoritePlayer = localStorage.getItem('favoritePlayer');
            if (favoritePlayer === currentPlayer) {
                localStorage.removeItem('favoritePlayer');
                alert(`${currentPlayer} removed from favorites`);
            } else {
                localStorage.setItem('favoritePlayer', currentPlayer);
                alert(`${currentPlayer} set as favorite! The board will load with this player's view next time.`);
            }
            updateFavoriteButton();
        }

        function updateFavoriteButton() {
            const btn = document.getElementById('favoriteBtn');
            const favoritePlayer = localStorage.getItem('favoritePlayer');

            if (currentPlayer && favoritePlayer === currentPlayer) {
                btn.classList.add('active');
                btn.textContent = '⭐ Favorited';
            } else {
                btn.classList.remove('active');
                btn.textContent = '⭐ Favorite';
            }
        }

        function updatePlayerDropdown() {
            const select = document.getElementById('playerSelect');
            const currentValue = select.value;

            const allPlayers = new Set();
            bingoData.tiles.forEach(tile => {
                tile.completedBy.forEach(player => allPlayers.add(player));
            });

            const sortedPlayers = Array.from(allPlayers).sort();

            select.innerHTML = '<option value="">Everyone (No Filter)</option>';
            sortedPlayers.forEach(player => {
                const option = document.createElement('option');
                option.value = player;
                option.textContent = player;
                select.appendChild(option);
            });

            if (currentValue && sortedPlayers.includes(currentValue)) {
                select.value = currentValue;
            } else if (currentPlayer && sortedPlayers.includes(currentPlayer)) {
                select.value = currentPlayer;
            } else {
                const favoritePlayer = localStorage.getItem('favoritePlayer');
                if (favoritePlayer && sortedPlayers.includes(favoritePlayer)) {
                    select.value = favoritePlayer;
                    currentPlayer = favoritePlayer;
                }
            }
        }

        function checkAdminStatus() {
            const savedAdmin = sessionStorage.getItem('isAdmin');
            if (savedAdmin === 'true') {
                isAdmin = true;
                showAdminControls();
            }
        }

        function openLoginModal() {
            document.getElementById('adminPasswordInput').value = '';
            document.getElementById('loginError').style.display = 'none';
            document.getElementById('loginModal').classList.add('active');
        }

        function closeLoginModal() {
            document.getElementById('loginModal').classList.remove('active');
        }

        async function attemptLogin() {
            const password = document.getElementById('adminPasswordInput').value;
            const errorElement = document.getElementById('loginError');

            errorElement.style.display = 'none';

            try {
                const response = await fetch(`${API_URL}/login`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ password: password })
                });

                const result = await response.json();

                if (response.ok && result.success) {
                    isAdmin = true;
                    sessionStorage.setItem('isAdmin', 'true');
                    sessionStorage.setItem('adminPassword', password);
                    showAdminControls();
                    closeLoginModal();
                    alert('✅ Admin access granted!');
                } else {
                    errorElement.textContent = result.message || 'Incorrect password!';
                    errorElement.style.display = 'block';
                }
            } catch (error) {
                console.error('Login error:', error);
                errorElement.textContent = '❌ Could not connect to server. Make sure the API is running.';
                errorElement.style.display = 'block';
            }
        }

        function logout() {
            if (confirm('Logout from admin panel?')) {
                isAdmin = false;
                editMode = false;
                sessionStorage.removeItem('isAdmin');
                sessionStorage.removeItem('adminPassword');
                hideAdminControls();
            }
        }

        function openManualOverrideModal() {
            if (!isAdmin) {
                alert('⛔ Admin access required!');
                return;
            }

            const totalTiles = bingoData.boardSize * bingoData.boardSize;
            document.getElementById('maxTileNum').textContent = totalTiles;
            document.getElementById('overrideTileNum').max = totalTiles;

            // Clear tile override section
            document.getElementById('overrideTileNum').value = '';
            document.getElementById('overridePlayerName').value = '';
            document.querySelector('input[name="overrideAction"][value="add"]').checked = true;
            document.getElementById('overrideError').style.display = 'none';
            document.getElementById('overrideSuccess').style.display = 'none';

            // Clear manual drop section
            document.getElementById('manualDropPlayer').value = '';
            document.getElementById('manualDropItem').value = '';
            document.getElementById('manualDropError').style.display = 'none';
            document.getElementById('manualDropSuccess').style.display = 'none';

            document.getElementById('manualOverrideModal').classList.add('active');
        }

        function closeManualOverrideModal() {
            document.getElementById('manualOverrideModal').classList.remove('active');
        }

        async function executeTileOverride() {
            const tileNum = parseInt(document.getElementById('overrideTileNum').value);
            const playerName = document.getElementById('overridePlayerName').value.trim();
            const action = document.querySelector('input[name="overrideAction"]:checked').value;

            const errorEl = document.getElementById('overrideError');
            const successEl = document.getElementById('overrideSuccess');

            errorEl.style.display = 'none';
            successEl.style.display = 'none';

            const totalTiles = bingoData.boardSize * bingoData.boardSize;
            if (!tileNum || tileNum < 1 || tileNum > totalTiles) {
                errorEl.textContent = `Please enter a tile number between 1 and ${totalTiles}`;
                errorEl.style.display = 'block';
                return;
            }

            if (!playerName) {
                errorEl.textContent = 'Please enter a player name';
                errorEl.style.display = 'block';
                return;
            }

            const password = sessionStorage.getItem('adminPassword');
            if (!password) {
                errorEl.textContent = 'Session expired. Please log in again.';
                errorEl.style.display = 'block';
                return;
            }

            try {
                const response = await fetch(`${API_URL}/manual-override`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        password: password,
                        tileIndex: tileNum - 1,
                        playerName: playerName,
                        action: action
                    })
                });

                const result = await response.json();

                if (response.ok && result.success) {
                    successEl.textContent = `✅ ${result.message}`;
                    successEl.style.display = 'block';

                    await refreshFromAPI();

                    // Clear inputs after success
                    setTimeout(() => {
                        document.getElementById('overrideTileNum').value = '';
                        document.getElementById('overridePlayerName').value = '';
                        successEl.style.display = 'none';
                    }, 2000);
                } else {
                    errorEl.textContent = result.error || result.message || 'Override failed';
                    errorEl.style.display = 'block';
                }
            } catch (error) {
                console.error('Manual override error:', error);
                errorEl.textContent = '❌ Could not connect to server';
                errorEl.style.display = 'block';
            }
        }

        async function executeManualDrop() {
            const playerName = document.getElementById('manualDropPlayer').value.trim();
            const itemName = document.getElementById('manualDropItem').value.trim();

            const errorEl = document.getElementById('manualDropError');
            const successEl = document.getElementById('manualDropSuccess');

            errorEl.style.display = 'none';
            successEl.style.display = 'none';

            // Validation
            if (!playerName) {
                errorEl.textContent = 'Please enter a player name';
                errorEl.style.display = 'block';
                return;
            }

            if (!itemName) {
                errorEl.textContent = 'Please enter an item name';
                errorEl.style.display = 'block';
                return;
            }

            // Get admin password from session
            const password = sessionStorage.getItem('adminPassword');
            if (!password) {
                errorEl.textContent = 'Session expired. Please log in again.';
                errorEl.style.display = 'block';
                return;
            }

            try {
                const response = await fetch(`${API_URL}/manual-drop`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        password: password,
                        playerName: playerName,
                        itemName: itemName
                    })
                });

                const result = await response.json();

                if (response.ok && result.success) {
                    successEl.textContent = `✅ ${result.message}`;
                    successEl.style.display = 'block';

                    // Clear inputs after success
                    setTimeout(() => {
                        document.getElementById('manualDropPlayer').value = '';
                        document.getElementById('manualDropItem').value = '';
                        successEl.style.display = 'none';
                    }, 2000);
                } else {
                    errorEl.textContent = result.error || result.message || 'Failed to add drop';
                    errorEl.style.display = 'block';
                }
            } catch (error) {
                console.error('Manual drop error:', error);
                errorEl.textContent = '❌ Could not connect to server';
                errorEl.style.display = 'block';
            }
        }

        function showAdminControls() {
            document.getElementById('adminControls').style.display = 'flex';
            document.getElementById('adminControls').style.gap = '10px';
            document.getElementById('adminControls').style.flexWrap = 'wrap';
            document.getElementById('adminControls').style.justifyContent = 'center';
            document.getElementById('loginBtn').style.display = 'none';
        }

        function hideAdminControls() {
            document.getElementById('adminControls').style.display = 'none';
            document.getElementById('loginBtn').style.display = 'block';
            const btn = document.getElementById('editBtn');
            btn.textContent = '📝 Edit Mode';
            btn.style.background = 'linear-gradient(135deg, #cd8b2d 0%, #a67318 100%)';
        }

        function formatItemName(itemName) {
            if (itemName.includes('_')) {
                return itemName.trim();
            }
            return itemName.trim().replace(/\s+/g, '_');
        }

        function loadItemImage(img, itemName) {
            const baseUrl = 'https://oldschool.runescape.wiki/images/';

            const formats = [
                formatItemName(itemName),
                itemName.trim().replace(/\s+/g, '_'),
                itemName.trim().toLowerCase().replace(/\s+/g, '_'),
                itemName.trim().toUpperCase().replace(/\s+/g, '_')
            ];

            let attemptIndex = 0;

            function tryNext() {
                if (attemptIndex >= formats.length) {
                    img.style.display = 'none';
                    return;
                }

                const format = formats[attemptIndex];
                attemptIndex++;

                img.onload = () => {
                    img.style.display = 'block';
                };

                img.onerror = () => {
                    tryNext();
                };

                img.src = `${baseUrl}${encodeURIComponent(format)}_detail.png`;
            }

            tryNext();
        }

        async function initBoard() {
            console.log('🚀 Initializing bingo board...');
            console.log(`API URL: ${API_URL}/bingo`);

            // Load tenant info FIRST
            await loadTenantInfo();

            try {
                const response = await fetch(`${API_URL}/bingo`);
                console.log(`API Response Status: ${response.status}`);

                if (response.ok) {
                    bingoData = await response.json();
                    console.log('✅ Loaded bingo data from API:', bingoData);

                    if (!bingoData.boardSize) {
                        bingoData.boardSize = 5;
                    }

                    if (!bingoData.lineBonuses) {
                        bingoData.lineBonuses = createDefaultBonuses(bingoData.boardSize);
                    }

                    bingoData.tiles.forEach(tile => {
                        if (!tile.hasOwnProperty('displayTitle')) {
                            tile.displayTitle = '';
                        }
                    });
                } else {
                    console.log('❌ API returned error status');
                    throw new Error('API error');
                }
            } catch (err) {
                console.log('ℹ️  API not available, using localStorage');
                const saved = localStorage.getItem('bingoData');
                if (saved) {
                    bingoData = JSON.parse(saved);
                    console.log('✅ Loaded from localStorage');
                    if (!bingoData.boardSize) {
                        bingoData.boardSize = 5;
                    }
                    if (!bingoData.lineBonuses) {
                        bingoData.lineBonuses = createDefaultBonuses(bingoData.boardSize);
                    }
                    if (bingoData.adminPassword) {
                        delete bingoData.adminPassword;
                    }
                    bingoData.tiles.forEach(tile => {
                        if (!tile.hasOwnProperty('displayTitle')) {
                            tile.displayTitle = '';
                        }
                    });
                } else {
                    console.log('📝 Creating new empty board');
                    bingoData.boardSize = 5;
                    const totalTiles = bingoData.boardSize * bingoData.boardSize;
                    for (let i = 0; i < totalTiles; i++) {
                        bingoData.tiles.push({
                            items: [],
                            value: 10,
                            completedBy: [],
                            displayTitle: ''
                        });
                    }
                    bingoData.lineBonuses = createDefaultBonuses(bingoData.boardSize);
                }
            }

            document.documentElement.style.setProperty('--board-size', bingoData.boardSize);

            checkAdminStatus();

            updatePlayerDropdown();

            const favoritePlayer = localStorage.getItem('favoritePlayer');
            const lastViewedPlayer = localStorage.getItem('lastViewedPlayer');

            if (favoritePlayer) {
                currentPlayer = favoritePlayer;
                document.getElementById('playerSelect').value = favoritePlayer;
            } else if (lastViewedPlayer) {
                currentPlayer = lastViewedPlayer;
                document.getElementById('playerSelect').value = lastViewedPlayer;
            }

            updateFavoriteButton();
            renderBoard();
            updatePlayerStats();
            setInterval(refreshFromAPI, 5000);
            addCloseButtonsToModals();
            console.log('✅ Board initialized, auto-refresh every 5 seconds');
        }

        function createDefaultBonuses(size) {
            return {
                rows: Array(size).fill(50),
                cols: Array(size).fill(50),
                diags: [100, 100]
            };
        }

        async function refreshFromAPI() {
            try {
                const response = await fetch(`${API_URL}/bingo`);
                if (response.ok) {
                    const newData = await response.json();

                    const oldDataStr = JSON.stringify(bingoData);
                    const newDataStr = JSON.stringify(newData);

                    if (oldDataStr !== newDataStr) {
                        console.log('📊 Data updated from API');
                        bingoData = newData;

                        if (!bingoData.boardSize) {
                            bingoData.boardSize = 5;
                        }

                        if (!bingoData.lineBonuses) {
                            bingoData.lineBonuses = createDefaultBonuses(bingoData.boardSize);
                        }

                        bingoData.tiles.forEach(tile => {
                            if (!tile.hasOwnProperty('displayTitle')) {
                                tile.displayTitle = '';
                            }
                        });

                        document.documentElement.style.setProperty('--board-size', bingoData.boardSize);

                        updatePlayerDropdown();
                        renderBoard();
                        updatePlayerStats();

                        localStorage.setItem('bingoData', JSON.stringify(bingoData));
                    }
                }
            } catch (err) {
                console.log('⚠️  Could not fetch from API:', err.message);
            }
        }

        async function manualRefresh() {
            console.log('🔄 Manual refresh triggered...');
            await refreshFromAPI();
            alert('Board refreshed!');
        }

        function renderBoard() {
            console.log('🔄 renderBoard called, bonusOverlayVisible:', bonusOverlayVisible);
            const board = document.getElementById('bingoBoard');
            if (!board) {
                console.error('Board element not found!');
                return;
            }

            board.innerHTML = '';

            bingoData.tiles.forEach((tile, index) => {
                const tileEl = document.createElement('div');
                tileEl.className = 'bingo-tile';

                // Check if tile is completed and by whom
                const isCompleted = tile.completedBy && tile.completedBy.length > 0;
                const completedByCurrentPlayer = currentPlayer && isCompleted && tile.completedBy.includes(currentPlayer);

                if (isCompleted) {
                    if (completedByCurrentPlayer) {
                        tileEl.classList.add('completed-by-current');
                    } else if (currentPlayer) {
                        tileEl.classList.add('completed-by-others');
                    } else {
                        tileEl.classList.add('completed-by-current');
                    }
                }

                const displayName = tile.displayTitle || (tile.items && tile.items.length > 0 ? tile.items[0] : 'Empty Tile');
                const players = isCompleted ? `✓ ${tile.completedBy.join(', ')}` : '';

                // Handle multi-item requirements
                let progressHtml = '';
                if (tile.requiredItems && tile.requiredItems.length > 1 && currentPlayer) {
                    const playerProgress = (tile.itemProgress && tile.itemProgress[currentPlayer]) ? tile.itemProgress[currentPlayer] : [];
                    const collected = playerProgress.length;
                    const total = tile.requiredItems.length;

                    if (collected > 0 && !completedByCurrentPlayer) {
                        progressHtml = `<div style="font-size: 11px; color: #cd8b2d; margin-top: 5px; font-weight: bold;">📦 ${collected}/${total} pieces</div>`;
                    }
                }

                let imagesHtml = '';
                if (tile.items && tile.items.length > 0) {
                    const displayItem = tile.items[0];
                    const imgId = `img-${index}`;
                    imagesHtml = `
                        <div class="tile-images">
                            <img id="${imgId}" class="item-icon" alt="${displayItem}">
                        </div>
                    `;
                }

                const itemCountHtml = tile.items && tile.items.length > 1
                    ? `<div style="font-size: 11px; color: ${tile.completedBy.length > 0 ? 'rgba(255,255,255,0.7)' : '#999'}; margin-top: 5px;">(${tile.items.length} item${tile.items.length !== 1 ? 's' : ''} ${tile.requireAllItems ? 'to complete' : 'can complete'})</div>`
                    : '';

                tileEl.innerHTML = `
                    <div class="tile-content">${displayName}</div>
                    ${imagesHtml}
                    <div class="tile-value">${tile.value} points</div>
                    ${progressHtml}
                    ${itemCountHtml}
                    ${players ? `<div class="tile-players">${players}</div>` : ''}
                `;

                tileEl.onclick = () => handleTileClick(index);
                board.appendChild(tileEl);

                if (tile.items && tile.items.length > 0) {
                    const imgId = `img-${index}`;
                    const img = document.getElementById(imgId);
                    if (img) {
                        loadItemImage(img, tile.items[0]);
                    }
                }
            });

            saveData();

            // Restore bonus overlay if it was visible
            if (bonusOverlayVisible) {
                console.log('🎁 renderBoard finished - restoring bonus overlay');
                showBonusOverlay();
            }
        }

        // Simplified check functions that don't break if data is incomplete
        function checkRowComplete(player, row) {
            if (!player || !bingoData.tiles) return false;
            const size = bingoData.boardSize || 5;
            for (let col = 0; col < size; col++) {
                const index = row * size + col;
                const tile = bingoData.tiles[index];
                if (!tile || !tile.completedBy || !tile.completedBy.includes(player)) {
                    return false;
                }
            }
            return true;
        }

        function checkColComplete(player, col) {
            if (!player || !bingoData.tiles) return false;
            const size = bingoData.boardSize || 5;
            for (let row = 0; row < size; row++) {
                const index = row * size + col;
                const tile = bingoData.tiles[index];
                if (!tile || !tile.completedBy || !tile.completedBy.includes(player)) {
                    return false;
                }
            }
            return true;
        }

        function checkDiagonalComplete(player, diagIndex) {
            if (!player || !bingoData.tiles) return false;
            const size = bingoData.boardSize || 5;
            if (diagIndex === 0) {
                // Top-left to bottom-right
                for (let i = 0; i < size; i++) {
                    const index = i * size + i;
                    const tile = bingoData.tiles[index];
                    if (!tile || !tile.completedBy || !tile.completedBy.includes(player)) {
                        return false;
                    }
                }
            } else {
                // Top-right to bottom-left
                for (let i = 0; i < size; i++) {
                    const index = i * size + (size - 1 - i);
                    const tile = bingoData.tiles[index];
                    if (!tile || !tile.completedBy || !tile.completedBy.includes(player)) {
                        return false;
                    }
                }
            }
            return true;
        }

        function handleTileClick(index) {
            if (editMode && isAdmin) {
                openEditModal(index);
            } else {
                // Use the new modal instead of alert()
                openTileInfoModal(index);
            }
        }

        function toggleEditMode() {
            if (!isAdmin) {
                alert('⛔ Admin access required!');
                return;
            }
            editMode = !editMode;
            const btn = document.getElementById('editBtn');
            btn.textContent = editMode ? '✓ Edit Mode ON' : '📝 Edit Mode';
            btn.style.background = editMode ? 'linear-gradient(135deg, #FF8C00 0%, #FF7000 100%)' : 'linear-gradient(135deg, #cd8b2d 0%, #a67318 100%)';
        }

        function openEditModal(index) {
            currentTileIndex = index;
            const tile = bingoData.tiles[index];
            const textarea = document.getElementById('tileItems');
            textarea.value = tile.items ? tile.items.join('\n') : '';
            document.getElementById('tileValue').value = tile.value || 10;
            document.getElementById('tileDisplayTitle').value = tile.displayTitle || '';

            // Set multi-item requirement checkbox
            const requireAllCheckbox = document.getElementById('requireAllItems');
            requireAllCheckbox.checked = tile.requiredItems && tile.requiredItems.length > 1;

            updateItemPreview();
            textarea.oninput = updateItemPreview;

            document.getElementById('editModal').classList.add('active');
        }

        function updateItemPreview() {
            const items = document.getElementById('tileItems').value
                .split('\n')
                .map(i => i.trim())
                .filter(i => i.length > 0);

            const previewDiv = document.getElementById('itemPreview');

            if (items.length === 0) {
                previewDiv.style.display = 'none';
                return;
            }

            previewDiv.style.display = 'flex';

            if (items.length === 1) {
                previewDiv.innerHTML = `
                    <div class="item-preview-item">
                        <img id="preview-img-0" alt="${items[0]}">
                        <span>${items[0]}</span>
                    </div>
                `;
            } else {
                previewDiv.innerHTML = `
                    <div class="item-preview-item">
                        <img id="preview-img-0" alt="${items[0]}">
                        <span><strong>${items[0]}</strong> (Display)</span>
                    </div>
                    <div style="flex-basis: 100%; height: 0;"></div>
                    <div style="font-size: 11px; color: #2c1810; padding: 5px; width: 100%;">
                        <strong>Also triggers on:</strong> ${items.slice(1).join(', ')}
                    </div>
                `;
            }

            const img = document.getElementById('preview-img-0');
            if (img) {
                loadItemImage(img, items[0]);
            }
        }

        function closeModal() {
            document.getElementById('editModal').classList.remove('active');
        }

        function saveTile() {
            const items = document.getElementById('tileItems').value
                .split('\n')
                .map(i => i.trim())
                .filter(i => i.length > 0);
            const value = parseInt(document.getElementById('tileValue').value) || 10;
            const displayTitle = document.getElementById('tileDisplayTitle').value.trim();
            const requireAll = document.getElementById('requireAllItems').checked;

            bingoData.tiles[currentTileIndex].items = items;
            bingoData.tiles[currentTileIndex].value = value;
            bingoData.tiles[currentTileIndex].displayTitle = displayTitle;

            // Handle multi-item requirements
            if (requireAll && items.length > 1) {
                bingoData.tiles[currentTileIndex].requiredItems = items;
                bingoData.tiles[currentTileIndex].itemProgress = bingoData.tiles[currentTileIndex].itemProgress || {};
                bingoData.tiles[currentTileIndex].requireAllItems = true;
            } else {
                // Regular tile - remove multi-item fields if they exist
                delete bingoData.tiles[currentTileIndex].requiredItems;
                delete bingoData.tiles[currentTileIndex].itemProgress;
                delete bingoData.tiles[currentTileIndex].requireAllItems;  // ← ADD THIS LINE
            }

            closeModal();
            renderBoard();
        }

        function openBoardSizeModal() {
            if (!isAdmin) {
                alert('⛔ Admin access required!');
                return;
            }
            if (tenantPlan === 'free') {
                const select = document.getElementById('boardSizeSelect');
                const options = select.querySelectorAll('option');

                options.forEach(option => {
                    const size = parseInt(option.value);
                    if (size > tenantLimits.board_size) {
                        option.disabled = true;
                        option.textContent += ' (Premium)';
                    }
                });
            }
            document.getElementById('boardSizeSelect').value = bingoData.boardSize;
            document.getElementById('boardSizeModal').classList.add('active');
        }

        function closeBoardSizeModal() {
            document.getElementById('boardSizeModal').classList.remove('active');
        }

        function changeBoardSize() {
            const newSize = parseInt(document.getElementById('boardSizeSelect').value);

            if (tenantLimits.board_size && newSize > tenantLimits.board_size) {
                alert(`⭐ Board size ${newSize}x${newSize} requires Premium!\n\nFree tier is limited to ${tenantLimits.board_size}x${tenantLimits.board_size}.\n\nUpgrade to Premium for up to 9x9 boards.`);
                showUpgradeModal('boardSize');
                return;
            }

            if (confirm(`Change board to ${newSize}x${newSize}? This will clear all tiles and progress!`)) {
                bingoData = {
                    boardSize: newSize,
                    tiles: [],
                    completions: {},
                    lineBonuses: createDefaultBonuses(newSize)
                };

                const totalTiles = newSize * newSize;
                for (let i = 0; i < totalTiles; i++) {
                    bingoData.tiles.push({
                        items: [],
                        value: 10,
                        completedBy: [],
                        displayTitle: ''
                    });
                }

                document.documentElement.style.setProperty('--board-size', newSize);

                closeBoardSizeModal();
                renderBoard();
                updatePlayerStats();
                saveData();
            }
        }

        function openBonusConfig() {
            if (!isAdmin) {
                alert('⛔ Admin access required!');
                return;
            }
            const size = bingoData.boardSize;

            let rowsHtml = '';
            for (let i = 0; i < size; i++) {
                rowsHtml += `
                    <div class="bonus-item">
                        <label>Row ${i + 1}:</label>
                        <input type="number" id="row${i}" min="0" value="${bingoData.lineBonuses.rows[i] || 50}">
                    </div>
                `;
            }

            let colsHtml = '';
            for (let i = 0; i < size; i++) {
                colsHtml += `
                    <div class="bonus-item">
                        <label>Column ${i + 1}:</label>
                        <input type="number" id="col${i}" min="0" value="${bingoData.lineBonuses.cols[i] || 50}">
                    </div>
                `;
            }

            const modalContent = document.querySelector('#bonusModal .modal-content');
            modalContent.innerHTML = `
                <h2>⚙️ Configure Line Bonuses</h2>
                <p style="color: #666; margin-bottom: 20px;">Set bonus points for completing each row, column, or diagonal.</p>

                <div class="bonus-config-section">
                    <h3>Rows</h3>
                    <div class="bonus-grid">
                        ${rowsHtml}
                    </div>
                </div>

                <div class="bonus-config-section">
                    <h3>Columns</h3>
                    <div class="bonus-grid">
                        ${colsHtml}
                    </div>
                </div>

                <div class="bonus-config-section">
                    <h3>Diagonals</h3>
                    <div class="bonus-grid">
                        <div class="bonus-item">
                            <label>Diagonal ↘:</label>
                            <input type="number" id="diag0" min="0" value="${bingoData.lineBonuses.diags[0] || 100}">
                        </div>
                        <div class="bonus-item">
                            <label>Diagonal ↙:</label>
                            <input type="number" id="diag1" min="0" value="${bingoData.lineBonuses.diags[1] || 100}">
                        </div>
                    </div>
                </div>

                <div class="modal-buttons" style="margin-top: 30px;">
                    <button class="btn-cancel" onclick="closeBonusModal()">Cancel</button>
                    <button class="btn-save" onclick="saveBonusConfig()">Save</button>
                </div>
            `;

            document.getElementById('bonusModal').classList.add('active');
        }

        function closeBonusModal() {
            document.getElementById('bonusModal').classList.remove('active');
        }

        function saveBonusConfig() {
            const size = bingoData.boardSize;

            bingoData.lineBonuses = {
                rows: [],
                cols: [],
                diags: []
            };

            for (let i = 0; i < size; i++) {
                bingoData.lineBonuses.rows.push(parseInt(document.getElementById(`row${i}`).value) || 0);
                bingoData.lineBonuses.cols.push(parseInt(document.getElementById(`col${i}`).value) || 0);
            }
            bingoData.lineBonuses.diags.push(parseInt(document.getElementById('diag0').value) || 0);
            bingoData.lineBonuses.diags.push(parseInt(document.getElementById('diag1').value) || 0);

            closeBonusModal();
            saveData();
            updatePlayerStats();
        }

        function parseValueFilter(filterText) {
            /**
             * Parse value filter strings like:
             * - ">100k" → { operator: '>', value: 100000 }
             * - "<1m" → { operator: '<', value: 1000000 }
             * - "=500k" → { operator: '=', value: 500000 }
             * - "100k-1m" → { operator: 'range', min: 100000, max: 1000000 }
             */

            if (!filterText || filterText.trim() === '') {
                return null;
            }

            filterText = filterText.trim().toLowerCase();

            // Check for range (e.g., "100k-1m")
            const rangeMatch = filterText.match(/^(\d+\.?\d*[km]?)\s*-\s*(\d+\.?\d*[km]?)$/);
            if (rangeMatch) {
                return {
                    operator: 'range',
                    min: parseValueShorthand(rangeMatch[1]),
                    max: parseValueShorthand(rangeMatch[2])
                };
            }

            // Check for operator (>, <, =, >=, <=)
            const operatorMatch = filterText.match(/^([><=]+)(\d+\.?\d*[km]?)$/);
            if (operatorMatch) {
                return {
                    operator: operatorMatch[1],
                    value: parseValueShorthand(operatorMatch[2])
                };
            }

            // Just a number (treat as exact match)
            const exactMatch = filterText.match(/^(\d+\.?\d*[km]?)$/);
            if (exactMatch) {
                return {
                    operator: '=',
                    value: parseValueShorthand(exactMatch[1])
                };
            }

            return null;
        }

        function parseValueShorthand(str) {
            /**
             * Convert shorthand to number:
             * - "100k" → 100000
             * - "2.5m" → 2500000
             * - "500" → 500
             */

            str = str.toLowerCase().trim();

            if (str.endsWith('m')) {
                return parseFloat(str.replace('m', '')) * 1000000;
            } else if (str.endsWith('k')) {
                return parseFloat(str.replace('k', '')) * 1000;
            } else {
                return parseFloat(str);
            }
        }

        function checkValueFilter(dropValue, filter) {
            /**
             * Check if a drop value matches the filter criteria
             */

            if (!filter) return true;

            const value = dropValue || 0;

            switch (filter.operator) {
                case '>':
                    return value > filter.value;
                case '>=':
                    return value >= filter.value;
                case '<':
                    return value < filter.value;
                case '<=':
                    return value <= filter.value;
                case '=':
                    // Allow 10% tolerance for exact matches
                    return Math.abs(value - filter.value) < (filter.value * 0.1);
                case 'range':
                    return value >= filter.min && value <= filter.max;
                default:
                    return true;
            }
        }

        function clearBoard() {
            if (confirm('Clear all tiles and player progress?')) {
                const currentSize = bingoData.boardSize;
                bingoData = {
                    boardSize: currentSize,
                    tiles: [],
                    completions: {},
                    lineBonuses: createDefaultBonuses(currentSize)
                };
                const totalTiles = currentSize * currentSize;
                for (let i = 0; i < totalTiles; i++) {
                    bingoData.tiles.push({
                        items: [],
                        value: 10,
                        completedBy: [],
                        displayTitle: ''
                    });
                }
                renderBoard();
                updatePlayerStats();
            }
        }

        async function shuffleBoard() {
            if (!isAdmin) {
                alert('⛔ Admin access required!');
                return;
            }

            const confirmed = confirm(
                '🔀 Shuffle Board?\n\n' +
                'This will randomly reorder all tiles while keeping their content and completions intact.\n\n' +
                'Are you sure you want to shuffle?'
            );

            if (!confirmed) return;

            const password = sessionStorage.getItem('adminPassword');
            if (!password) {
                alert('Session expired. Please log in again.');
                return;
            }

            localStorage.setItem('previousBoardState', JSON.stringify(bingoData.tiles));

            try {
                const response = await fetch(`${API_URL}/shuffle-board`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ password: password })
                });

                const result = await response.json();

                if (response.ok && result.success) {
                    alert(`✅ ${result.message}`);

                    // Update local data with shuffled tiles
                    bingoData.tiles = result.tiles;

                    // Re-render the board
                    renderBoard();
                    updatePlayerStats();
                } else {
                    alert(`❌ ${result.error || result.message || 'Shuffle failed'}`);
                }
            } catch (error) {
                console.error('Shuffle error:', error);
                alert('❌ Could not connect to server');
            }
        }

        function undoShuffle() {
            const previous = localStorage.getItem('previousBoardState');
            if (!previous) {
                alert('No previous board state to restore!');
                return;
            }

            if (confirm('Restore previous board layout?')) {
                bingoData.tiles = JSON.parse(previous);
                renderBoard();
                saveData();
                alert('✅ Board restored to previous state!');
            }
        }

        function exportBoard() {
            const dataStr = JSON.stringify(bingoData, null, 2);
            const dataBlob = new Blob([dataStr], {type: 'application/json'});
            const url = URL.createObjectURL(dataBlob);
            const link = document.createElement('a');
            link.href = url;
            link.download = 'bingo-board.json';
            link.click();
        }

        function importBoard() {
            const input = document.createElement('input');
            input.type = 'file';
            input.accept = '.json';
            input.onchange = (e) => {
                const file = e.target.files[0];
                const reader = new FileReader();
                reader.onload = (event) => {
                    try {
                        bingoData = JSON.parse(event.target.result);
                        if (!bingoData.lineBonuses) {
                            bingoData.lineBonuses = {
                                rows: [50, 50, 50, 50, 50],
                                cols: [50, 50, 50, 50, 50],
                                diags: [100, 100]
                            };
                        }
                        renderBoard();
                        updatePlayerStats();
                        alert('Board imported successfully!');
                    } catch (err) {
                        alert('Error importing board: ' + err.message);
                    }
                };
                reader.readAsText(file);
            };
            input.click();
        }

        async function saveData() {
            console.log('💾 Saving data...');

            const dataToSave = {...bingoData};
            if (dataToSave.adminPassword) {
                delete dataToSave.adminPassword;
            }

            localStorage.setItem('bingoData', JSON.stringify(dataToSave));

            try {
                const response = await fetch(`${API_URL}/update`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(dataToSave)
                });

                if (response.ok) {
                    console.log('✅ Synced to API successfully');
                } else {
                    console.log('⚠️  API sync failed with status:', response.status);
                }
            } catch (err) {
                console.log('⚠️  Could not sync to API:', err.message);
            }
        }

        function checkLineCompletion(player) {
            const size = bingoData.boardSize;
            const completions = {
                rows: [],
                cols: [],
                diagonals: []
            };

            for (let row = 0; row < size; row++) {
                let complete = true;
                for (let col = 0; col < size; col++) {
                    const index = row * size + col;
                    if (!bingoData.tiles[index].completedBy.includes(player)) {
                        complete = false;
                        break;
                    }
                }
                if (complete) completions.rows.push(row);
            }

            for (let col = 0; col < size; col++) {
                let complete = true;
                for (let row = 0; row < size; row++) {
                    const index = row * size + col;
                    if (!bingoData.tiles[index].completedBy.includes(player)) {
                        complete = false;
                        break;
                    }
                }
                if (complete) completions.cols.push(col);
            }

            let diag1 = true, diag2 = true;
            for (let i = 0; i < size; i++) {
                if (!bingoData.tiles[i * size + i].completedBy.includes(player)) diag1 = false;
                if (!bingoData.tiles[i * size + (size - 1 - i)].completedBy.includes(player)) diag2 = false;
            }
            if (diag1) completions.diagonals.push(0);
            if (diag2) completions.diagonals.push(1);

            return completions;
        }

        function updatePlayerStats() {
            const statsDiv = document.getElementById('playerStats');
            const playerScores = {};

            bingoData.tiles.forEach(tile => {
                tile.completedBy.forEach(player => {
                    if (!playerScores[player]) {
                        playerScores[player] = {
                            tiles: 0,
                            points: 0,
                            lineBonus: 0,
                            lines: {rows: [], cols: [], diagonals: []}
                        };
                    }
                    playerScores[player].tiles++;
                    playerScores[player].points += tile.value;
                });
            });

            Object.keys(playerScores).forEach(player => {
                const lines = checkLineCompletion(player);
                playerScores[player].lines = lines;

                let totalBonus = 0;
                lines.rows.forEach(rowIdx => {
                    totalBonus += bingoData.lineBonuses.rows[rowIdx];
                });
                lines.cols.forEach(colIdx => {
                    totalBonus += bingoData.lineBonuses.cols[colIdx];
                });
                lines.diagonals.forEach(diagIdx => {
                    totalBonus += bingoData.lineBonuses.diags[diagIdx];
                });

                playerScores[player].lineBonus = totalBonus;
                playerScores[player].points += totalBonus;
            });

            if (Object.keys(playerScores).length === 0) {
                statsDiv.innerHTML = '<div class="no-players">No drops recorded yet!</div>';
                return;
            }

            const sorted = Object.entries(playerScores).sort((a, b) => b[1].points - a[1].points);

            const rankEmojis = ['🥇', '🥈', '🥉'];

            statsDiv.innerHTML = sorted.map(([player, stats], index) => {
                const rankClass = index < 3 ? `rank-${index + 1}` : '';
                const rankEmoji = index < 3 ? rankEmojis[index] : '';
                const isCurrentView = player === currentPlayer ? 'current-view' : '';

                const lineText = [];
                if (stats.lines.rows.length > 0) lineText.push(`${stats.lines.rows.length} row${stats.lines.rows.length > 1 ? 's' : ''}`);
                if (stats.lines.cols.length > 0) lineText.push(`${stats.lines.cols.length} col${stats.lines.cols.length > 1 ? 's' : ''}`);
                if (stats.lines.diagonals.length > 0) lineText.push(`${stats.lines.diagonals.length} diagonal${stats.lines.diagonals.length > 1 ? 's' : ''}`);

                return `
                    <div class="player-card ${rankClass} ${isCurrentView}">
                        ${rankEmoji ? `<div class="player-rank">${rankEmoji}</div>` : ''}
                        <div class="player-name">${player}</div>
                        <div class="player-score">${stats.points.toLocaleString()} points</div>
                        <div class="player-stats">
                            ${stats.tiles} tiles completed
                            ${stats.lineBonus > 0 ? `<span class="bonus-badge">+${stats.lineBonus} bonus</span>` : ''}
                        </div>
                        ${lineText.length > 0 ? `<div class="player-stats" style="margin-top: 5px;">✓ ${lineText.join(', ')}</div>` : ''}
                    </div>
                `;
            }).join('');
        }

        function showApiInfo() {
            document.getElementById('apiUrl').value = `${API_URL}/drop`;
            document.getElementById('apiModal').classList.add('active');
        }

        function closeApiModal() {
            document.getElementById('apiModal').classList.remove('active');
        }

        function openHistoryModal() {
            document.getElementById('historyModal').classList.add('active');
            populateYearSelector();
            setDateFilter('all'); // Default to all time
            updateHistoryPlayerFilter();
        }

        function closeHistoryModal() {
            document.getElementById('historyModal').classList.remove('active');
        }

        function populateYearSelector() {
            const yearSelect = document.getElementById('yearSelect');
            const currentYear = new Date().getFullYear();

            yearSelect.innerHTML = '<option value="">Select Year...</option>';

            // Add years from 2020 to current year
            for (let year = currentYear; year >= 2020; year--) {
                const option = document.createElement('option');
                option.value = year;
                option.textContent = year;
                yearSelect.appendChild(option);
            }
        }

        function setDateFilter(filter) {
            const today = new Date();
            const startDateInput = document.getElementById('startDate');
            const endDateInput = document.getElementById('endDate');
            const monthSelect = document.getElementById('monthSelect');
            const yearSelect = document.getElementById('yearSelect');

            // Update active button
            document.querySelectorAll('.date-filter-btn').forEach(btn => {
                btn.classList.remove('active');
            });

            if (filter !== 'custom') {
                const activeBtn = document.querySelector(`[data-filter="${filter}"]`);
                if (activeBtn) activeBtn.classList.add('active');
            }

            // Reset month selector
            monthSelect.value = '';
            yearSelect.value = '';

            switch(filter) {
                case 'today':
                    const todayStr = today.toISOString().split('T')[0];
                    startDateInput.value = todayStr;
                    endDateInput.value = todayStr;
                    break;

                case 'week':
                    const weekAgo = new Date(today);
                    weekAgo.setDate(today.getDate() - 7);
                    startDateInput.value = weekAgo.toISOString().split('T')[0];
                    endDateInput.value = today.toISOString().split('T')[0];
                    break;

                case 'month':
                    const monthAgo = new Date(today);
                    monthAgo.setMonth(today.getMonth() - 1);
                    startDateInput.value = monthAgo.toISOString().split('T')[0];
                    endDateInput.value = today.toISOString().split('T')[0];
                    break;

                case 'all':
                    startDateInput.value = '';
                    endDateInput.value = '';
                    break;

                case 'custom':
                    // Just mark as custom, don't change dates
                    break;
            }

            loadHistory();
        }

        function setSpecificMonth() {
            const month = document.getElementById('monthSelect').value;
            const year = document.getElementById('yearSelect').value;

            if (month && year) {
                // Set date range to cover the entire month
                const startDate = new Date(year, parseInt(month) - 1, 1);
                const endDate = new Date(year, parseInt(month), 0); // Last day of month

                document.getElementById('startDate').value = startDate.toISOString().split('T')[0];
                document.getElementById('endDate').value = endDate.toISOString().split('T')[0];

                // Mark custom as active
                setDateFilter('custom');
            }
        }

        function clearDateFilter() {
            document.getElementById('startDate').value = '';
            document.getElementById('endDate').value = '';
            document.getElementById('monthSelect').value = '';
            document.getElementById('yearSelect').value = '';
            setDateFilter('all');
        }

        function updateHistoryPlayerFilter(historyData = null) {
            const select = document.getElementById('historyPlayerFilter');
            const currentValue = select.value;

            // Get all unique players from history data (or fall back to tiles)
            const allPlayers = new Set();

            if (historyData && historyData.length > 0) {
                // Use actual history data (better!)
                historyData.forEach(record => {
                    if (record.player) {
                        allPlayers.add(record.player);
                    }
                });
            } else {
                // Fallback: use tile completions
                bingoData.tiles.forEach(tile => {
                    tile.completedBy.forEach(player => allPlayers.add(player));
                });
            }

            const sortedPlayers = Array.from(allPlayers).sort();

            // Rebuild dropdown
            select.innerHTML = '<option value="">All Players</option>';
            sortedPlayers.forEach(player => {
                const option = document.createElement('option');
                option.value = player;
                option.textContent = player;
                select.appendChild(option);
            });

            // Restore selection
            if (currentValue && sortedPlayers.includes(currentValue)) {
                select.value = currentValue;
            }

            if (document.getElementById('historyModal').classList.contains('active')) {
                filterHistory();
            }
        }

        async function loadHistory() {
            const contentDiv = document.getElementById('historyContent');
            const countSpan = document.getElementById('historyCount');
            const playerFilter = document.getElementById('historyPlayerFilter').value;
            const startDate = document.getElementById('startDate').value;
            const endDate = document.getElementById('endDate').value;

            contentDiv.innerHTML = '<div style="text-align: center; color: #666; padding: 40px;">Loading history...</div>';
            countSpan.textContent = '';

            try {
                let url = `${API_URL}/history?limit=1000`;

                if (playerFilter) {
                    url += `&player=${encodeURIComponent(playerFilter)}`;
                }

                if (startDate) {
                    url += `&start_date=${startDate}T00:00:00Z`;
                }

                if (endDate) {
                    url += `&end_date=${endDate}T23:59:59Z`;
                }

                console.log('Fetching history:', url);

                const response = await fetch(url);
                if (!response.ok) {
                    throw new Error('Failed to fetch history');
                }

                const data = await response.json();

                if (!data.history  || data.history.length === 0) {
                    contentDiv.innerHTML = '<div style="text-align: center; color: #666; padding: 40px;">No drops found for this time period!</div>';
                    countSpan.textContent = '(0 drops)';
                    return;
                }

                // Update count
                countSpan.textContent = `(${data.count} drop${data.count !== 1 ? 's' : ''})`;

                // Render history
                let html = '';
                data.history.forEach((record, index) => {
                    const timestamp = new Date(record.timestamp);
                    const timeAgo = getTimeAgo(timestamp);
                    const dateStr = timestamp.toLocaleDateString();
                    const timeStr = timestamp.toLocaleTimeString();

                    //Format value for display
                    let valueDisplay = '';
                    if (record.value && record.value > 0) {
                        if (record.value >= 1000000) {
                            valueDisplay = `<span style="color: #4CAF50; font-weight: bold; margin-left: 10px;">(${(record.value / 1000000).toFixed(2)}M gp)</span>`;
                        } else if (record.value >= 1000) {
                            valueDisplay = `<span style="color: #4CAF50; font-weight: bold; margin-left: 10px;">(${(record.value / 1000).toFixed(0)}K gp)</span>`;
                        } else {
                            valueDisplay = `<span style="color: #4CAF50; font-weight: bold; margin-left: 10px;">(${record.value.toLocaleString()} gp)</span>`;
                        }
                    }

                    const tileInfo = record.tileCompleted && record.tilesInfo && record.tilesInfo.length > 0
                        ? `<div style="margin-top: 5px; padding: 5px; background: rgba(76,175,80,0.2); border-radius: 3px; font-size: 11px;">
                             ✅ Completed Tile ${record.tilesInfo[0].tile}: ${record.tilesInfo[0].items.join(', ')} (+${record.tilesInfo[0].value} points)
                           </div>`
                        : '<div style="margin-top: 5px; font-size: 11px; color: #999;">No tile completed</div>';

                    const deleteBtn = isAdmin
                        ? `<button onclick="deleteHistoryEntry('${record.player}', '${record.item}', '${record.timestamp}')"
                                   style="padding: 4px 8px; background: linear-gradient(135deg, #8b1a1a 0%, #660000 100%); color: white; border: 1px solid #4d0000; border-radius: 3px; cursor: pointer; font-size: 10px; font-weight: bold; margin-left: 10px;">
                             🗑️ Delete
                           </button>`
                        : '';

                    const collectionLogBadge = record.drop_type === 'collection_log'
                        ? '<span style="background: #4CAF50; color: white; padding: 2px 6px; border-radius: 3px; font-size: 10px; margin-left: 8px; font-weight: bold;">📖 COLLECTION LOG</span>'
                        : '';

                    //Add data attributes for filtering
                    html += `
                        <div style="background: white; padding: 12px; border-radius: 5px; margin-bottom: 10px; border-left: 4px solid ${record.tileCompleted ? '#4CAF50' : '#8B6914'};"
                             data-player="${record.player}"
                             data-type="${record.drop_type || 'loot'}"
                             data-item="${record.item}"
                             data-value="${record.value || 0}">
                            <div style="display: flex; justify-content: space-between; align-items: start; margin-bottom: 5px;">
                                <div style="flex: 1;">
                                    <strong style="color: #ffcc33; background: #2c1810; padding: 2px 8px; border-radius: 3px; font-size: 13px;">${record.player}</strong>
                                    <span style="color: #2c1810; margin-left: 10px; font-weight: bold;">received</span>
                                    <strong style="color: #cd8b2d; margin-left: 5px;">${record.item}</strong>
                                    ${collectionLogBadge}
                                    ${valueDisplay}
                                    ${deleteBtn}
                                </div>
                                <div style="text-align: right; font-size: 11px; color: #666;">
                                    <div>${timeAgo}</div>
                                    <div>${dateStr} ${timeStr}</div>
                                </div>
                            </div>
                            ${tileInfo}
                        </div>
                    `;
                });

                contentDiv.innerHTML = html;

                // Update player filter with actual history data
                updateHistoryPlayerFilter(data.history);

            } catch (error) {
                console.error('Error loading history:', error);
                contentDiv.innerHTML = '<div style="text-align: center; color: #8b1a1a; padding: 40px;">❌ Failed to load history. Make sure the API is running.</div>';
                countSpan.textContent = '';
            }
        }

        function filterHistory() {
            const playerFilter = document.getElementById('historyPlayerFilter').value;
            const typeFilter = document.getElementById('historyTypeFilter').value;  // ← ADD THIS
            const searchFilter = document.getElementById('historySearchFilter').value.toLowerCase();
            const valueFilterText = document.getElementById('historyValueFilter').value;

            // Parse value filter
            const valueFilter = parseValueFilter(valueFilterText);

            const allRecords = document.querySelectorAll('#historyContent > div');
            let visibleCount = 0;

            allRecords.forEach(record => {
                const player = record.dataset.player || '';
                const type = record.dataset.type || '';  // ← ADD THIS
                const item = record.dataset.item || '';
                const value = parseFloat(record.dataset.value) || 0;

                let show = true;

                // Player filter
                if (playerFilter && player !== playerFilter) {
                    show = false;
                }

                // Type filter  ← ADD THIS SECTION
                if (typeFilter && type !== typeFilter) {
                    show = false;
                }

                // Search filter
                if (searchFilter && !item.toLowerCase().includes(searchFilter)) {
                    show = false;
                }

                // Value filter
                if (!checkValueFilter(value, valueFilter)) {
                    show = false;
                }

                record.style.display = show ? '' : 'none';
                if (show) visibleCount++;
            });

            // Update count
            const totalCount = allRecords.length;
            document.getElementById('historyCount').textContent = `(${visibleCount} of ${totalCount} drop${totalCount !== 1 ? 's' : ''})`;
        }

        function clearAllFilters() {
            document.getElementById('historyPlayerFilter').value = '';
            document.getElementById('historyValueFilter').value = '';
            document.getElementById('historySearchFilter').value = '';
            filterHistory();
        }

        function getTimeAgo(date) {
            const seconds = Math.floor((new Date() - date) / 1000);

            if (seconds < 60) return 'Just now';
            if (seconds < 3600) return `${Math.floor(seconds / 60)} minutes ago`;
            if (seconds < 86400) return `${Math.floor(seconds / 3600)} hours ago`;
            if (seconds < 604800) return `${Math.floor(seconds / 86400)} days ago`;
            return `${Math.floor(seconds / 604800)} weeks ago`;
        }

        async function deleteHistoryEntry(player, item, timestamp) {
            if (!confirm(`Delete this drop?\n\nPlayer: ${player}\nItem: ${item}\n\nThis cannot be undone!`)) {
                return;
            }

            const password = sessionStorage.getItem('adminPassword');
            if (!password) {
                alert('Session expired. Please log in again.');
                return;
            }

            try {
                const response = await fetch(`${API_URL}/delete-history`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        password: password,
                        playerName: player,
                        itemName: item,
                        timestamp: timestamp
                    })
                });

                const result = await response.json();

                if (response.ok && result.success) {
                    alert(`✅ ${result.message}`);
                    loadHistory(); // Refresh history list
                } else {
                    alert(`❌ ${result.error || result.message || 'Failed to delete'}`);
                }
            } catch (error) {
                console.error('Delete history error:', error);
                alert('❌ Could not connect to server');
            }
        }

        // Analytics Functions
        let analyticsCharts = {};

        function openAnalyticsModal() {
            document.getElementById('analyticsModal').classList.add('active');
            loadAnalytics();
        }

        function closeAnalyticsModal() {
            document.getElementById('analyticsModal').classList.remove('active');
            // Destroy charts to prevent memory leaks
            Object.values(analyticsCharts).forEach(chart => {
                if (chart) chart.destroy();
            });
            analyticsCharts = {};
        }

        // Bonus Overlay Toggle
        let bonusOverlayVisible = false;

        function toggleBonusOverlay() {
            bonusOverlayVisible = !bonusOverlayVisible;
            console.log(`🎁 Toggle overlay: ${bonusOverlayVisible ? 'SHOW' : 'HIDE'}`);
            const btn = document.getElementById('bonusToggleBtn');

            if (bonusOverlayVisible) {
                btn.textContent = '🎁 Hide Bonuses';
                btn.style.background = 'linear-gradient(135deg, #FF8C00 0%, #FF7000 100%)';
                showBonusOverlay();
            } else {
                btn.textContent = '🎁 Show Bonuses';
                btn.style.background = 'linear-gradient(135deg, #2196F3 0%, #0b7dda 100%)';
                hideBonusOverlay();
            }
        }

        function showBonusOverlay() {
            console.log('🎁 showBonusOverlay called');
            const board = document.getElementById('bingoBoard');
            const boardContainer = document.querySelector('.board-container');

            if (!board || !bingoData.lineBonuses) {
                console.log('❌ Cannot show overlay - board or bonuses missing');
                return;
            }

            // Remove any existing overlay
            hideBonusOverlay();

            const size = bingoData.boardSize || 5;
            const bonuses = bingoData.lineBonuses;

            // Create main overlay container
            const overlayContainer = document.createElement('div');
            overlayContainer.id = 'bonusOverlay';
            overlayContainer.className = 'bonus-overlay-container';
            overlayContainer.style.cssText = `
                position: absolute;
                top: 0;
                left: 0;
                width: 100%;
                height: 100%;
                pointer-events: none;
            `;

            // Row bonuses (right side)
            const rowContainer = document.createElement('div');
            rowContainer.className = 'bonus-overlay-row';

            for (let i = 0; i < size; i++) {
                const isComplete = currentPlayer ? checkRowComplete(currentPlayer, i) : false;
                const bonusDiv = document.createElement('div');
                bonusDiv.className = 'bonus-overlay-item' + (isComplete ? ' completed' : '');
                bonusDiv.innerHTML = `+${bonuses.rows[i]}`;
                bonusDiv.title = `Row ${i + 1} bonus` + (isComplete ? ' (Completed!)' : '');
                rowContainer.appendChild(bonusDiv);
            }
            overlayContainer.appendChild(rowContainer);

            // Column bonuses (bottom)
            const colContainer = document.createElement('div');
            colContainer.className = 'bonus-overlay-col';

            for (let i = 0; i < size; i++) {
                const isComplete = currentPlayer ? checkColComplete(currentPlayer, i) : false;
                const bonusDiv = document.createElement('div');
                bonusDiv.className = 'bonus-overlay-item' + (isComplete ? ' completed' : '');
                bonusDiv.innerHTML = `+${bonuses.cols[i]}`;
                bonusDiv.title = `Column ${i + 1} bonus` + (isComplete ? ' (Completed!)' : '');
                colContainer.appendChild(bonusDiv);
            }
            overlayContainer.appendChild(colContainer);

            // Diagonal bonuses (corners)
            const diag1Complete = currentPlayer ? checkDiagonalComplete(currentPlayer, 0) : false;
            const diag1Div = document.createElement('div');
            diag1Div.className = 'bonus-overlay-diag top-left' + (diag1Complete ? ' completed' : '');
            diag1Div.innerHTML = `↘ +${bonuses.diags[0]}`;
            diag1Div.title = 'Diagonal bonus (top-left to bottom-right)' + (diag1Complete ? ' (Completed!)' : '');
            overlayContainer.appendChild(diag1Div);

            const diag2Complete = currentPlayer ? checkDiagonalComplete(currentPlayer, 1) : false;
            const diag2Div = document.createElement('div');
            diag2Div.className = 'bonus-overlay-diag top-right' + (diag2Complete ? ' completed' : '');
            diag2Div.innerHTML = `↙ +${bonuses.diags[1]}`;
            diag2Div.title = 'Diagonal bonus (top-right to bottom-left)' + (diag2Complete ? ' (Completed!)' : '');
            overlayContainer.appendChild(diag2Div);

            board.appendChild(overlayContainer);

            // Add extra padding to board container so bonuses don't get cut off
            boardContainer.style.paddingRight = '90px';
            boardContainer.style.paddingBottom = '70px';

            console.log('✅ Overlay added successfully');
        }

        function hideBonusOverlay() {
            console.log('🎁 hideBonusOverlay called');
            const overlay = document.getElementById('bonusOverlay');
            const boardContainer = document.querySelector('.board-container');

            if (overlay) {
                console.log('  → Removing overlay');
                overlay.remove();
            }

            // Remove extra padding
            if (boardContainer) {
                boardContainer.style.paddingRight = '';
                boardContainer.style.paddingBottom = '';
            }
        }

        async function loadAnalytics() {
            const loadingDiv = document.getElementById('analyticsLoading');
            const contentDiv = document.getElementById('analyticsContent');

            loadingDiv.style.display = 'none';
            contentDiv.style.display = 'block';

            // Initialize expandable charts
            setTimeout(() => {
                initializeExpandableCharts();
            }, 100);

            try {
                // Fetch all history data
                const response = await fetch(`${API_URL}/history?limit=10000`);
                if (!response.ok) throw new Error('Failed to fetch history');

                const data = await response.json();

                if (!data.history || data.history.length === 0) {
                    loadingDiv.innerHTML = '<div style="text-align: center; padding: 60px; color: #666;">No data available yet!</div>';
                    return;
                }

                // Process data - convert timestamps to Date objects
                const drops = data.history.map(d => ({
                    ...d,
                    timestamp: new Date(d.timestamp)
                }));

                // Populate player filter (for filtering feature)
                populateAnalyticsPlayerFilter(drops);

                // Initialize filters
                analyticsSelectedPlayers = [];
                updateAnalyticsPlayerButton();
                renderAnalyticsFilterChips();

                // Generate all analytics with filtering support
                const players = analyticsSelectedPlayers.length > 0
                    ? analyticsSelectedPlayers
                    : [...new Set(drops.map(r => r.player))];

                const playerColors = assignPlayerColors(players);

                // Use new chart update functions that support multi-player
                updateDropsOverTimeChart(drops, players, playerColors);
                updateTopItemsChart(drops, players, playerColors);
                updateActivityHeatmapChart(drops, players, playerColors);

                // Also generate the other charts
                generateKeyStats(drops);
                generateDayOfWeekChart(drops);
                generatePlayerActivityChart(drops);
                generateMonthComparisonChart(drops);

                loadingDiv.style.display = 'none';
                contentDiv.style.display = 'block';

            } catch (error) {
                console.error('Error loading analytics:', error);
                loadingDiv.innerHTML = '<div style="text-align: center; padding: 60px; color: #8b1a1a;">❌ Failed to load analytics</div>';
            }
        }

        // Chart expansion functionality
        let currentExpandedChart = null;
        let expandedChartInstance = null;

        function makeChartExpandable(chartId, chartTitle) {
            const canvas = document.getElementById(chartId);
            if (!canvas) return;

            // Add cursor pointer style
            canvas.style.cursor = 'pointer';

            // Add click handler
            canvas.onclick = function() {
                expandChart(chartId, chartTitle);
            };
        }

        function expandChart(chartId, chartTitle) {
            const sourceCanvas = document.getElementById(chartId);
            if (!sourceCanvas) return;

            const overlay = document.getElementById('expandedChartOverlay');
            const expandedCanvas = document.getElementById('expandedChartCanvas');
            const titleElement = document.getElementById('expandedChartTitle');

            // Store references
            currentExpandedChart = chartId;
            expandedChartType = chartId;

            // Sync filters from main view
            syncFiltersToExpanded();

            // Set title
            titleElement.textContent = chartTitle;

            // Destroy previous expanded chart if exists
            if (expandedChartInstance) {
                expandedChartInstance.destroy();
            }

            // Get the original chart instance
            const originalChart = Chart.getChart(sourceCanvas);
            if (!originalChart) {
                console.error('No chart found for', chartId);
                return;
            }

            // Clone the chart configuration
            const config = {
                type: originalChart.config.type,
                data: JSON.parse(JSON.stringify(originalChart.config.data)), // Deep clone
                options: JSON.parse(JSON.stringify(originalChart.config.options || {}))
            };

            // Enhance options for larger display
            if (!config.options) config.options = {};
            if (!config.options.plugins) config.options.plugins = {};
            if (!config.options.plugins.legend) config.options.plugins.legend = {};
            config.options.plugins.legend.labels = {
                ...config.options.plugins.legend.labels,
                font: { size: 14 },
                padding: 15
            };
            config.options.maintainAspectRatio = false;

            // Show overlay
            overlay.style.display = 'flex';

            // Create expanded chart
            const ctx = expandedCanvas.getContext('2d');
            expandedChartInstance = new Chart(ctx, config);
        }

        function closeExpandedChart() {
            const overlay = document.getElementById('expandedChartOverlay');
            overlay.style.display = 'none';

            // Sync filters back to main analytics view
            syncFiltersToMain();

            // Destroy expanded chart instance
            if (expandedChartInstance) {
                expandedChartInstance.destroy();
                expandedChartInstance = null;
            }

            currentExpandedChart = null;
            expandedChartType = null;
        }

        function syncFiltersToMain() {
            // Copy filter values from expanded view back to main analytics
            const expandedType = document.getElementById('expandedTypeFilter')?.value || '';
            const expandedValue = document.getElementById('expandedValueFilter')?.value || '0';
            const expandedSearch = document.getElementById('expandedSearchFilter')?.value || '';

            document.getElementById('analyticsTypeFilter').value = expandedType;
            document.getElementById('analyticsValueFilter').value = expandedValue;
            document.getElementById('analyticsSearchFilter').value = expandedSearch;

            // Copy selected players back
            analyticsSelectedPlayers = [...expandedSelectedPlayers];
            updateAnalyticsPlayerButton();

            // Reload main analytics with updated filters
            if (expandedType || expandedValue !== '0' || expandedSearch || expandedSelectedPlayers.length > 0) {
                applyAnalyticsFilters();
            }
        }

        // Expanded chart filter functionality
        let expandedSelectedPlayers = [];
        let expandedChartData = null;
        let expandedChartType = null;

        function syncFiltersToExpanded() {
            // Copy filter values from main analytics to expanded view
            const mainType = document.getElementById('analyticsTypeFilter')?.value || '';
            const mainValue = document.getElementById('analyticsValueFilter')?.value || '0';
            const mainSearch = document.getElementById('analyticsSearchFilter')?.value || '';

            document.getElementById('expandedTypeFilter').value = mainType;
            document.getElementById('expandedValueFilter').value = mainValue;
            document.getElementById('expandedSearchFilter').value = mainSearch;

            // Copy selected players
            expandedSelectedPlayers = [...analyticsSelectedPlayers];
            updateExpandedPlayerButton();
            populateExpandedPlayerDropdown();
        }

        function toggleExpandedPlayerDropdown() {
            const dropdown = document.getElementById('expandedPlayerDropdown');
            dropdown.style.display = dropdown.style.display === 'none' ? 'block' : 'none';
        }

        function populateExpandedPlayerDropdown() {
            if (!expandedChartData) return;

            const dropdown = document.getElementById('expandedPlayerDropdown');
            const players = [...new Set(expandedChartData.map(d => d.player))].sort();

            dropdown.innerHTML = players.map(player => {
                const isChecked = expandedSelectedPlayers.includes(player);
                return `
                    <label style="display: block; padding: 8px 12px; cursor: pointer; color: #333; ${isChecked ? 'background: rgba(205, 139, 45, 0.2);' : ''}">
                        <input type="checkbox"
                               ${isChecked ? 'checked' : ''}
                               onchange="toggleExpandedPlayer('${player.replace(/'/g, "\\'")}')">
                        ${player}
                    </label>
                `;
            }).join('');
        }

        function toggleExpandedPlayer(player) {
            const index = expandedSelectedPlayers.indexOf(player);
            if (index === -1) {
                expandedSelectedPlayers.push(player);
            } else {
                expandedSelectedPlayers.splice(index, 1);
            }
            updateExpandedPlayerButton();
            applyExpandedChartFilters();
        }

        function updateExpandedPlayerButton() {
            const button = document.getElementById('expandedPlayerButton');
            if (!button) return;

            if (expandedSelectedPlayers.length === 0) {
                button.textContent = 'All Players';
            } else if (expandedSelectedPlayers.length === 1) {
                button.textContent = expandedSelectedPlayers[0];
            } else {
                button.textContent = `${expandedSelectedPlayers.length} Players Selected`;
            }
        }

        async function applyExpandedChartFilters() {
            if (!expandedChartType || !currentExpandedChart) return;

            renderExpandedFilterChips();

            // Get filter values
            const typeFilter = document.getElementById('expandedTypeFilter')?.value || '';
            const valueFilter = parseInt(document.getElementById('expandedValueFilter')?.value || '0');
            const searchFilter = document.getElementById('expandedSearchFilter')?.value.toLowerCase() || '';

            // Build query parameters
            const params = new URLSearchParams({ limit: 10000 });
            if (typeFilter) params.append('type', typeFilter);
            if (valueFilter > 0) params.append('minValue', valueFilter);
            if (searchFilter) params.append('search', searchFilter);

            try {
                const response = await fetch(`${API_URL}/history?${params}`);
                const data = await response.json();

                let filteredHistory = (data.history || []).map(d => ({
                    ...d,
                    timestamp: new Date(d.timestamp)
                }));

                // Store for player dropdown
                expandedChartData = filteredHistory;

                // Get players to display
                const players = expandedSelectedPlayers.length > 0
                    ? expandedSelectedPlayers
                    : [...new Set(filteredHistory.map(r => r.player))];

                const playerColors = assignPlayerColors(players);

                // Update the expanded chart based on type
                updateExpandedChartWithData(currentExpandedChart, filteredHistory, players, playerColors);

            } catch (error) {
                console.error('Failed to apply expanded chart filters:', error);
            }
        }

function updateExpandedChartWithData(chartId, drops, players, playerColors) {
            if (!expandedChartInstance) return;

            // Destroy current chart
            expandedChartInstance.destroy();

            // Get the canvas context
            const ctx = document.getElementById('expandedChartCanvas').getContext('2d');

            // Create chart based on type using the ACTUAL chart creation logic
            let config;

            switch(chartId) {
                case 'dropsPerDayChart':
                    // Recreate drops over time chart with filtered data
                    const last30Days = [];
                    const dayCounts = {};
                    const today = new Date();

                    for (let i = 29; i >= 0; i--) {
                        const date = new Date(today);
                        date.setDate(today.getDate() - i);
                        const dateStr = date.toISOString().split('T')[0];
                        last30Days.push(dateStr);
                        players.forEach(player => {
                            if (!dayCounts[player]) dayCounts[player] = {};
                            dayCounts[player][dateStr] = 0;
                        });
                    }

                    drops.forEach(d => {
                        const dateStr = d.timestamp.toISOString().split('T')[0];
                        if (last30Days.includes(dateStr)) {
                            if (dayCounts[d.player]) {
                                dayCounts[d.player][dateStr] = (dayCounts[d.player][dateStr] || 0) + 1;
                            }
                        }
                    });

                    const datasets = players.map(player => ({
                        label: player,
                        data: last30Days.map(date => dayCounts[player]?.[date] || 0),
                        borderColor: playerColors[player],
                        backgroundColor: playerColors[player] + '20',
                        tension: 0.4,
                        fill: true
                    }));

                    config = {
                        type: 'line',
                        data: {
                            labels: last30Days.map(d => {
                                const date = new Date(d);
                                return `${date.getMonth() + 1}/${date.getDate()}`;
                            }),
                            datasets: datasets
                        },
                        options: {
                            responsive: true,
                            maintainAspectRatio: false,
                            plugins: {
                                title: {
                                    display: true,
                                    text: 'Drops Over Time (Last 30 Days)',
                                    font: { size: 16 }
                                },
                                legend: {
                                    labels: { font: { size: 14 }, padding: 15 }
                                }
                            },
                            scales: {
                                y: {
                                    beginAtZero: true,
                                    ticks: { stepSize: 1 }
                                }
                            }
                        }
                    };
                    break;

                case 'topItemsChart':
                    // Recreate top items chart with filtered data
                    const itemValues = {};
                    drops.forEach(d => {
                        const value = d.value || 0;
                        if (itemValues[d.item]) {
                            itemValues[d.item] += value;
                        } else {
                            itemValues[d.item] = value;
                        }
                    });

                    const sortedItems = Object.entries(itemValues)
                        .sort((a, b) => b[1] - a[1])
                        .slice(0, 10);

                    config = {
                        type: 'bar',
                        data: {
                            labels: sortedItems.map(item => item[0]),
                            datasets: [{
                                label: 'Total Value (GP)',
                                data: sortedItems.map(item => item[1]),
                                backgroundColor: '#cd8b2d',
                                borderColor: '#8B6914',
                                borderWidth: 2
                            }]
                        },
                        options: {
                            responsive: true,
                            maintainAspectRatio: false,
                            indexAxis: 'y',
                            plugins: {
                                title: {
                                    display: true,
                                    text: 'Top 10 Most Valuable Drops',
                                    font: { size: 16 }
                                },
                                legend: {
                                    display: false
                                }
                            },
                            scales: {
                                x: {
                                    beginAtZero: true,
                                    ticks: {
                                        callback: function(value) {
                                            if (value >= 1000000) {
                                                return (value / 1000000).toFixed(1) + 'M';
                                            } else if (value >= 1000) {
                                                return (value / 1000).toFixed(0) + 'K';
                                            }
                                            return value;
                                        }
                                    }
                                }
                            }
                        }
                    };
                    break;

                case 'dayOfWeekChart':
                    // Recreate day of week chart with filtered data
                    const dayNames = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
                    const dayCounts2 = [0, 0, 0, 0, 0, 0, 0];

                    drops.forEach(d => {
                        const day = d.timestamp.getDay();
                        dayCounts2[day]++;
                    });

                    config = {
                        type: 'bar',
                        data: {
                            labels: dayNames,
                            datasets: [{
                                label: 'Drops',
                                data: dayCounts2,
                                backgroundColor: '#cd8b2d',
                                borderColor: '#8B6914',
                                borderWidth: 2
                            }]
                        },
                        options: {
                            responsive: true,
                            maintainAspectRatio: false,
                            plugins: {
                                title: {
                                    display: true,
                                    text: 'Activity by Day of Week',
                                    font: { size: 16 }
                                },
                                legend: {
                                    display: false
                                }
                            },
                            scales: {
                                y: {
                                    beginAtZero: true,
                                    ticks: { stepSize: 1 }
                                }
                            }
                        }
                    };
                    break;

                case 'hourHeatmapChart':
                    // Recreate hour heatmap with filtered data
                    const hourCounts = {};
                    const hours = Array.from({length: 24}, (_, i) => i);

                    players.forEach(player => {
                        hourCounts[player] = Array(24).fill(0);
                    });

                    drops.forEach(d => {
                        const hour = d.timestamp.getHours();
                        if (hourCounts[d.player]) {
                            hourCounts[d.player][hour]++;
                        }
                    });

                    const hourDatasets = players.map(player => ({
                        label: player,
                        data: hourCounts[player] || Array(24).fill(0),
                        borderColor: playerColors[player],
                        backgroundColor: playerColors[player] + '40',
                        tension: 0.4,
                        fill: true
                    }));

                    config = {
                        type: 'line',
                        data: {
                            labels: hours.map(h => `${h}:00`),
                            datasets: hourDatasets
                        },
                        options: {
                            responsive: true,
                            maintainAspectRatio: false,
                            plugins: {
                                title: {
                                    display: true,
                                    text: 'Activity by Hour of Day',
                                    font: { size: 16 }
                                },
                                legend: {
                                    labels: { font: { size: 14 }, padding: 15 }
                                }
                            },
                            scales: {
                                y: {
                                    beginAtZero: true,
                                    ticks: { stepSize: 1 }
                                }
                            }
                        }
                    };
                    break;

                case 'playerActivityChart':
                    // Recreate player activity chart with filtered data
                    const playerCounts = {};
                    drops.forEach(d => {
                        playerCounts[d.player] = (playerCounts[d.player] || 0) + 1;
                    });

                    const sortedPlayers = Object.entries(playerCounts)
                        .sort((a, b) => b[1] - a[1]);

                    config = {
                        type: 'doughnut',
                        data: {
                            labels: sortedPlayers.map(p => p[0]),
                            datasets: [{
                                data: sortedPlayers.map(p => p[1]),
                                backgroundColor: sortedPlayers.map(p => playerColors[p[0]] || '#cd8b2d'),
                                borderColor: '#8B6914',
                                borderWidth: 2
                            }]
                        },
                        options: {
                            responsive: true,
                            maintainAspectRatio: false,
                            plugins: {
                                title: {
                                    display: true,
                                    text: 'Player Activity Distribution',
                                    font: { size: 16 }
                                },
                                legend: {
                                    labels: { font: { size: 14 }, padding: 15 }
                                }
                            }
                        }
                    };
                    break;

                case 'monthComparisonChart':
                    // Recreate month comparison chart with filtered data
                    const monthNames2 = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
                    const monthCounts2 = {};

                    drops.forEach(d => {
                        const monthKey = `${d.timestamp.getFullYear()}-${String(d.timestamp.getMonth() + 1).padStart(2, '0')}`;
                        monthCounts2[monthKey] = (monthCounts2[monthKey] || 0) + 1;
                    });

                    const sortedMonths = Object.entries(monthCounts2)
                        .sort((a, b) => a[0].localeCompare(b[0]))
                        .slice(-6);

                    config = {
                        type: 'bar',
                        data: {
                            labels: sortedMonths.map(m => {
                                const [year, month] = m[0].split('-');
                                return `${monthNames2[parseInt(month) - 1]} ${year}`;
                            }),
                            datasets: [{
                                label: 'Drops',
                                data: sortedMonths.map(m => m[1]),
                                backgroundColor: '#cd8b2d',
                                borderColor: '#8B6914',
                                borderWidth: 2
                            }]
                        },
                        options: {
                            responsive: true,
                            maintainAspectRatio: false,
                            plugins: {
                                title: {
                                    display: true,
                                    text: 'Monthly Drop Comparison (Last 6 Months)',
                                    font: { size: 16 }
                                },
                                legend: {
                                    display: false
                                }
                            },
                            scales: {
                                y: {
                                    beginAtZero: true,
                                    ticks: { stepSize: 1 }
                                }
                            }
                        }
                    };
                    break;

                default:
                    console.error('Unknown chart type:', chartId);
                    return;
            }

            // Create the new chart
            expandedChartInstance = new Chart(ctx, config);
        }

        function renderExpandedFilterChips() {
            const container = document.getElementById('expandedAppliedFilters');
            if (!container) return;

            const chips = [];

            // Player chips
            if (expandedSelectedPlayers.length > 0) {
                expandedSelectedPlayers.forEach(player => {

                    chips.push(`
                        <span style="background: linear-gradient(135deg, #cd8b2d 0%, #a67318 100%); color: white; padding: 4px 10px; border-radius: 12px; font-size: 11px; display: inline-flex; align-items: center; gap: 5px;">
                            👤 ${player}
                            <button onclick="toggleExpandedPlayer('${player.replace(/'/g, "\\'")}'); event.stopPropagation();"
                                    style="background: none; border: none; color: white; cursor: pointer; font-size: 14px; padding: 0; line-height: 1;">✕</button>
                        </span>
                    `);
                });
            }

            // Type chip
            const typeFilter = document.getElementById('expandedTypeFilter')?.value;
            if (typeFilter) {
                const typeLabel = typeFilter === 'loot' ? 'Loot Drop' : 'Collection Log';
                chips.push(`
                    <span style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 4px 10px; border-radius: 12px; font-size: 11px; display: inline-flex; align-items: center; gap: 5px;">
                        📦 ${typeLabel}
                        <button onclick="document.getElementById('expandedTypeFilter').value=''; applyExpandedChartFilters(); event.stopPropagation();"
                                style="background: none; border: none; color: white; cursor: pointer; font-size: 14px; padding: 0; line-height: 1;">✕</button>
                    </span>
                `);
            }

            // Value chip
            const valueFilter = document.getElementById('expandedValueFilter')?.value;
            if (valueFilter && valueFilter !== '0') {
                const valueLabel = parseInt(valueFilter) >= 1000000
                    ? `${parseInt(valueFilter) / 1000000}M+`
                    : `${parseInt(valueFilter) / 1000}K+`;
                chips.push(`
                    <span style="background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%); color: white; padding: 4px 10px; border-radius: 12px; font-size: 11px; display: inline-flex; align-items: center; gap: 5px;">
                        💰 ${valueLabel}
                        <button onclick="document.getElementById('expandedValueFilter').value='0'; applyExpandedChartFilters(); event.stopPropagation();"
                                style="background: none; border: none; color: white; cursor: pointer; font-size: 14px; padding: 0; line-height: 1;">✕</button>
                    </span>
                `);
            }

            // Search chip
            const searchFilter = document.getElementById('expandedSearchFilter')?.value;
            if (searchFilter) {
                chips.push(`
                    <span style="background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%); color: white; padding: 4px 10px; border-radius: 12px; font-size: 11px; display: inline-flex; align-items: center; gap: 5px;">
                        🔍 "${searchFilter}"
                        <button onclick="document.getElementById('expandedSearchFilter').value=''; applyExpandedChartFilters(); event.stopPropagation();"
                                style="background: none; border: none; color: white; cursor: pointer; font-size: 14px; padding: 0; line-height: 1;">✕</button>
                    </span>
                `);
            }

            container.innerHTML = chips.join('');
        }

        // Close dropdown when clicking outside
        document.addEventListener('click', function(event) {
            const dropdown = document.getElementById('expandedPlayerDropdown');
            const button = document.getElementById('expandedPlayerButton');
            if (dropdown && button && !dropdown.contains(event.target) && !button.contains(event.target)) {
                dropdown.style.display = 'none';
            }
        });

        // Make all charts expandable after they're created
        function initializeExpandableCharts() {
            makeChartExpandable('dropsPerDayChart', '📊 Drops Over Time');
            makeChartExpandable('topItemsChart', '🏆 Most Valuable Drops');
            makeChartExpandable('dayOfWeekChart', '📅 Activity by Day of Week');
            makeChartExpandable('hourHeatmapChart', '🕐 Activity Heatmap');
            makeChartExpandable('playerActivityChart', '👥 Player Activity');
            makeChartExpandable('monthComparisonChart', '📆 Monthly Comparison');
        }

        function generateKeyStats(drops) {
            // Total drops
            document.getElementById('totalDrops').textContent = drops.length.toLocaleString();

            // Unique players
            const uniquePlayers = new Set(drops.map(d => d.player));
            document.getElementById('uniquePlayers').textContent = uniquePlayers.size;

            // Tiles completed
            const tilesCompleted = drops.filter(d => d.tileCompleted).length;
            document.getElementById('tilesCompleted').textContent = tilesCompleted.toLocaleString();

            // Most active day
            const dayCount = {};
            drops.forEach(d => {
                const dateStr = d.timestamp.toISOString().split('T')[0];
                dayCount[dateStr] = (dayCount[dateStr] || 0) + 1;
            });
            const mostActiveDay = Object.entries(dayCount).sort((a, b) => b[1] - a[1])[0];
            if (mostActiveDay) {
                const date = new Date(mostActiveDay[0]);
                document.getElementById('mostActiveDay').textContent = `${date.toLocaleDateString()} (${mostActiveDay[1]} drops)`;
            }

            // Best month
            const monthCount = {};
            const monthNames = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
            drops.forEach(d => {
                const monthKey = `${d.timestamp.getFullYear()}-${String(d.timestamp.getMonth() + 1).padStart(2, '0')}`;
                monthCount[monthKey] = (monthCount[monthKey] || 0) + 1;
            });
            const bestMonth = Object.entries(monthCount).sort((a, b) => b[1] - a[1])[0];
            if (bestMonth) {
                const [year, month] = bestMonth[0].split('-');
                document.getElementById('bestMonth').textContent = `${monthNames[parseInt(month) - 1]} ${year} (${bestMonth[1]} drops)`;
            }
        }

        function generateDropsPerDayChart(drops) {
            const ctx = document.getElementById('dropsPerDayChart').getContext('2d');

            // Get last 30 days
            const last30Days = [];
            const dayCounts = {};
            const today = new Date();

            for (let i = 29; i >= 0; i--) {
                const date = new Date(today);
                date.setDate(today.getDate() - i);
                const dateStr = date.toISOString().split('T')[0];
                last30Days.push(dateStr);
                dayCounts[dateStr] = 0;
            }

            drops.forEach(d => {
                const dateStr = d.timestamp.toISOString().split('T')[0];
                if (dayCounts.hasOwnProperty(dateStr)) {
                    dayCounts[dateStr]++;
                }
            });

            const data = last30Days.map(d => dayCounts[d]);
            const labels = last30Days.map(d => {
                const date = new Date(d);
                return `${date.getMonth() + 1}/${date.getDate()}`;
            });

            if (analyticsCharts.dropsPerDay) analyticsCharts.dropsPerDay.destroy();

            analyticsCharts.dropsPerDay = new Chart(ctx, {
                type: 'line',
                data: {
                    labels: labels,
                    datasets: [{
                        label: 'Drops',
                        data: data,
                        borderColor: '#cd8b2d',
                        backgroundColor: 'rgba(205, 139, 45, 0.2)',
                        fill: true,
                        tension: 0.4
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: true,
                    plugins: {
                        legend: { display: false }
                    },
                    scales: {
                        y: {
                            beginAtZero: true,
                            ticks: { stepSize: 1 }
                        }
                    }
                }
            });
        }

        function generateDayOfWeekChart(drops) {
            const ctx = document.getElementById('dayOfWeekChart').getContext('2d');

            const dayNames = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
            const dayCounts = [0, 0, 0, 0, 0, 0, 0];

            drops.forEach(d => {
                dayCounts[d.timestamp.getDay()]++;
            });

            if (analyticsCharts.dayOfWeek) analyticsCharts.dayOfWeek.destroy();

            analyticsCharts.dayOfWeek = new Chart(ctx, {
                type: 'bar',
                data: {
                    labels: dayNames,
                    datasets: [{
                        label: 'Drops',
                        data: dayCounts,
                        backgroundColor: '#cd8b2d',
                        borderColor: '#8B6914',
                        borderWidth: 2
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: true,
                    plugins: {
                        legend: { display: false }
                    },
                    scales: {
                        y: {
                            beginAtZero: true,
                            ticks: { stepSize: 1 }
                        }
                    }
                }
            });
        }

        function generateHourHeatmap(drops) {
            const ctx = document.getElementById('hourHeatmapChart').getContext('2d');

            const hourCounts = Array(24).fill(0);

            drops.forEach(d => {
                hourCounts[d.timestamp.getHours()]++;
            });

            const labels = Array.from({length: 24}, (_, i) => {
                const hour = i % 12 || 12;
                const ampm = i < 12 ? 'AM' : 'PM';
                return `${hour}${ampm}`;
            });

            if (analyticsCharts.hourHeatmap) analyticsCharts.hourHeatmap.destroy();

            analyticsCharts.hourHeatmap = new Chart(ctx, {
                type: 'bar',
                data: {
                    labels: labels,
                    datasets: [{
                        label: 'Drops',
                        data: hourCounts,
                        backgroundColor: hourCounts.map(count => {
                            const maxCount = Math.max(...hourCounts);
                            const intensity = maxCount > 0 ? count / maxCount : 0;
                            return `rgba(205, 139, 45, ${0.3 + intensity * 0.7})`;
                        }),
                        borderColor: '#8B6914',
                        borderWidth: 1
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: true,
                    plugins: {
                        legend: { display: false }
                    },
                    scales: {
                        y: {
                            beginAtZero: true,
                            ticks: { stepSize: 1 }
                        }
                    }
                }
            });
        }

        function generatePlayerActivityChart(drops) {
            const ctx = document.getElementById('playerActivityChart').getContext('2d');

            const playerCounts = {};
            drops.forEach(d => {
                playerCounts[d.player] = (playerCounts[d.player] || 0) + 1;
            });

            const sortedPlayers = Object.entries(playerCounts)
                .sort((a, b) => b[1] - a[1])
                .slice(0, 10); // Top 10 players

            if (analyticsCharts.playerActivity) analyticsCharts.playerActivity.destroy();

            analyticsCharts.playerActivity = new Chart(ctx, {
                type: 'bar',
                data: {
                    labels: sortedPlayers.map(p => p[0]),
                    datasets: [{
                        label: 'Drops',
                        data: sortedPlayers.map(p => p[1]),
                        backgroundColor: '#4CAF50',
                        borderColor: '#2d7a2f',
                        borderWidth: 2
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: true,
                    indexAxis: 'y',
                    plugins: {
                        legend: { display: false }
                    },
                    scales: {
                        x: {
                            beginAtZero: true,
                            ticks: { stepSize: 1 }
                        }
                    }
                }
            });
        }

        function generateMonthComparisonChart(drops) {
            const ctx = document.getElementById('monthComparisonChart').getContext('2d');

            const monthCounts = {};
            const monthNames = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

            drops.forEach(d => {
                const monthKey = `${d.timestamp.getFullYear()}-${String(d.timestamp.getMonth() + 1).padStart(2, '0')}`;
                monthCounts[monthKey] = (monthCounts[monthKey] || 0) + 1;
            });

            const sortedMonths = Object.entries(monthCounts)
                .sort((a, b) => a[0].localeCompare(b[0]))
                .slice(-12); // Last 12 months

            const labels = sortedMonths.map(m => {
                const [year, month] = m[0].split('-');
                return `${monthNames[parseInt(month) - 1]} ${year.substring(2)}`;
            });

            if (analyticsCharts.monthComparison) analyticsCharts.monthComparison.destroy();

            analyticsCharts.monthComparison = new Chart(ctx, {
                type: 'line',
                data: {
                    labels: labels,
                    datasets: [{
                        label: 'Drops',
                        data: sortedMonths.map(m => m[1]),
                        borderColor: '#2196F3',
                        backgroundColor: 'rgba(33, 150, 243, 0.2)',
                        fill: true,
                        tension: 0.4
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: true,
                    plugins: {
                        legend: { display: false }
                    },
                    scales: {
                        y: {
                            beginAtZero: true,
                            ticks: { stepSize: 1 }
                        }
                    }
                }
            });
        }

        function generateTopItemsChart(drops) {
            const ctx = document.getElementById('topItemsChart').getContext('2d');

            const itemCounts = {};
            drops.forEach(d => {
                itemCounts[d.item] = (itemCounts[d.item] || 0) + 1;
            });

            const sortedItems = Object.entries(itemCounts)
                .sort((a, b) => b[1] - a[1])
                .slice(0, 10); // Top 10 items

            if (analyticsCharts.topItems) analyticsCharts.topItems.destroy();

            analyticsCharts.topItems = new Chart(ctx, {
                type: 'doughnut',
                data: {
                    labels: sortedItems.map(i => i[0]),
                    datasets: [{
                        data: sortedItems.map(i => i[1]),
                        backgroundColor: [
                            '#FFD700', '#C0C0C0', '#CD7F32', '#4CAF50', '#2196F3',
                            '#FF9800', '#9C27B0', '#E91E63', '#00BCD4', '#8BC34A'
                        ],
                        borderColor: '#8B6914',
                        borderWidth: 2
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: true,
                    plugins: {
                        legend: {
                            position: 'right',
                            labels: {
                                boxWidth: 15,
                                font: { size: 11 }
                            }
                        }
                    }
                }
            });
        }

        // Analytics Filter State
        let analyticsSelectedPlayers = []; // Empty = All players

        function toggleAnalyticsPlayerDropdown() {
            const dropdown = document.getElementById('analyticsPlayerDropdown');
            dropdown.style.display = dropdown.style.display === 'none' ? 'block' : 'none';
        }

        // Close dropdown when clicking outside
        document.addEventListener('click', (e) => {
            const dropdown = document.getElementById('analyticsPlayerDropdown');
            const button = document.getElementById('analyticsPlayerButton');
            if (dropdown && button && !dropdown.contains(e.target) && !button.contains(e.target)) {
                dropdown.style.display = 'none';
            }
        });

        function populateAnalyticsPlayerFilter(historyData) {
            const dropdown = document.getElementById('analyticsPlayerDropdown');
            if (!dropdown) return;

            // Get unique players from history
            const allPlayers = new Set();
            historyData.forEach(record => {
                if (record.player) {
                    allPlayers.add(record.player);
                }
            });

            const sortedPlayers = Array.from(allPlayers).sort();

            // Build checkbox list
            let html = '';

            // "All Players" checkbox
            html += `
                <label style="display: block; padding: 8px 12px; cursor: pointer; border-bottom: 1px solid #eee;">
                    <input type="checkbox"
                           id="analyticsPlayerAll"
                           onchange="toggleAllAnalyticsPlayers(this)"
                           ${analyticsSelectedPlayers.length === 0 ? 'checked' : ''}
                           style="margin-right: 8px;">
                    <span style="color: #333; font-weight: bold;">All Players</span>
                </label>
            `;

            // Individual players
            sortedPlayers.forEach(player => {
                const checked = analyticsSelectedPlayers.length === 0 || analyticsSelectedPlayers.includes(player);
                html += `
                    <label style="display: block; padding: 8px 12px; cursor: pointer; color: #333; hover: background: #f5f5f5;">
                        <input type="checkbox"
                               class="analyticsPlayerCheckbox"
                               value="${player}"
                               onchange="toggleAnalyticsPlayer('${player}')"
                               ${checked ? 'checked' : ''}
                               style="margin-right: 8px;">
                        ${player}
                    </label>
                `;
            });

            dropdown.innerHTML = html;
        }

        function toggleAllAnalyticsPlayers(checkbox) {
            if (checkbox.checked) {
                // Select all
                analyticsSelectedPlayers = [];
                document.querySelectorAll('.analyticsPlayerCheckbox').forEach(cb => {
                    cb.checked = true;
                });
            } else {
                // Deselect all
                analyticsSelectedPlayers = [];
                document.querySelectorAll('.analyticsPlayerCheckbox').forEach(cb => {
                    cb.checked = false;
                });
            }
            updateAnalyticsPlayerButton();
            applyAnalyticsFilters();
        }

function toggleAnalyticsPlayer(player) {
            const allCheckbox = document.getElementById('analyticsPlayerAll');
            const playerCheckbox = document.querySelector(`.analyticsPlayerCheckbox[value="${player}"]`);

            if (analyticsSelectedPlayers.length === 0) {
                // Was "all", now selecting just one player
                if (playerCheckbox && playerCheckbox.checked) {
                    // Player checkbox is checked - select ONLY this player
                    analyticsSelectedPlayers = [player];
                } else {
                    // Player checkbox is unchecked - select everyone EXCEPT this player
                    const checkboxes = document.querySelectorAll('.analyticsPlayerCheckbox');
                    analyticsSelectedPlayers = [];
                    checkboxes.forEach(cb => {
                        if (cb.value !== player) {
                            analyticsSelectedPlayers.push(cb.value);
                        }
                    });
                }
                allCheckbox.checked = false;
            } else {
                // Toggle individual player
                const index = analyticsSelectedPlayers.indexOf(player);
                if (index > -1) {
                    // Player is in list - remove them
                    analyticsSelectedPlayers.splice(index, 1);
                } else {
                    // Player not in list - add them
                    analyticsSelectedPlayers.push(player);
                }

                // Check if all are selected
                const checkboxes = document.querySelectorAll('.analyticsPlayerCheckbox');
                const allSelected = Array.from(checkboxes).every(cb => cb.checked);
                if (allSelected) {
                    analyticsSelectedPlayers = [];
                    allCheckbox.checked = true;
                } else {
                    allCheckbox.checked = false;
                }
            }

            updateAnalyticsPlayerButton();
            applyAnalyticsFilters();
        }

        function updateAnalyticsPlayerButton() {
            const button = document.getElementById('analyticsPlayerButton');
            if (!button) return;

            if (analyticsSelectedPlayers.length === 0) {
                button.textContent = 'All Players';
            } else if (analyticsSelectedPlayers.length === 1) {
                button.textContent = analyticsSelectedPlayers[0];
            } else {
                button.textContent = `${analyticsSelectedPlayers.length} Players Selected`;
            }
        }

        function getAnalyticsFilterChips() {
            const chips = [];

            // Player chips
            if (analyticsSelectedPlayers.length > 0) {
                analyticsSelectedPlayers.forEach(player => {
                    chips.push({
                        type: 'player',
                        label: player,
                        value: player
                    });
                });
            }

            // Type filter
            const typeFilter = document.getElementById('analyticsTypeFilter')?.value;
            if (typeFilter) {
                chips.push({
                    type: 'type',
                    label: typeFilter === 'loot' ? 'Loot Drop' : 'Collection Log',
                    value: typeFilter
                });
            }

            // Value filter
            const valueFilter = document.getElementById('analyticsValueFilter')?.value;
            if (valueFilter && valueFilter !== '0') {
                const valueMil = parseInt(valueFilter) / 1000000;
                chips.push({
                    type: 'value',
                    label: `${valueMil}M+ value`,
                    value: valueFilter
                });
            }

            // Search filter
            const searchFilter = document.getElementById('analyticsSearchFilter')?.value;
            if (searchFilter) {
                chips.push({
                    type: 'search',
                    label: `"${searchFilter}"`,
                    value: searchFilter
                });
            }

            return chips;
        }

        function renderAnalyticsFilterChips() {
            const container = document.getElementById('analyticsAppliedFilters');
            if (!container) return;

            const chips = getAnalyticsFilterChips();

            if (chips.length === 0) {
                container.innerHTML = '';
                return;
            }

            let html = '<div style="font-size: 12px; color: #999; margin-right: 10px;">Active filters:</div>';
            chips.forEach(chip => {
                html += `
                    <span style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 4px 10px; border-radius: 12px; font-size: 11px; display: inline-flex; align-items: center; gap: 5px;">
                        ${chip.label}
                        <span onclick="removeAnalyticsFilter('${chip.type}', '${chip.value}')"
                              style="cursor: pointer; opacity: 0.8; font-weight: bold;">✕</span>
                    </span>
                `;
            });

            container.innerHTML = html;
        }

        function removeAnalyticsFilter(type, value) {
            switch (type) {
                case 'player':
                    toggleAnalyticsPlayer(value);
                    break;
                case 'type':
                    document.getElementById('analyticsTypeFilter').value = '';
                    break;
                case 'value':
                    document.getElementById('analyticsValueFilter').value = '0';
                    break;
                case 'search':
                    document.getElementById('analyticsSearchFilter').value = '';
                    break;
            }
            applyAnalyticsFilters();
        }

        function applyAnalyticsFilters() {
            renderAnalyticsFilterChips();
            // Reload analytics with filtered data
            loadAnalyticsWithFilters();
        }

async function loadAnalyticsWithFilters() {
            // Get filter values
            const typeFilter = document.getElementById('analyticsTypeFilter')?.value || '';
            const valueFilter = parseInt(document.getElementById('analyticsValueFilter')?.value || '0');
            const searchFilter = document.getElementById('analyticsSearchFilter')?.value.toLowerCase() || '';

            // Build query parameters
            const params = new URLSearchParams({
                limit: 10000
            });

            if (typeFilter) params.append('type', typeFilter);
            if (valueFilter > 0) params.append('minValue', valueFilter);
            if (searchFilter) params.append('search', searchFilter);

            try {
                const response = await fetch(`${API_URL}/history?${params}`);
                const data = await response.json();

                let filteredHistory = data.history || [];

                //Process data - convert timestamps to Date objects
                filteredHistory = filteredHistory.map(d => ({
                    ...d,
                    timestamp: new Date(d.timestamp)
                }));

                // Apply player filter (client-side for multi-select)
                if (analyticsSelectedPlayers.length > 0) {
                    filteredHistory = filteredHistory.filter(record =>
                        analyticsSelectedPlayers.includes(record.player)
                    );
                }

                // Get player list and colors
                const players = analyticsSelectedPlayers.length > 0
                    ? analyticsSelectedPlayers
                    : [...new Set(filteredHistory.map(r => r.player))];

                const playerColors = assignPlayerColors(players);

                // Update multi-player charts
                updateDropsOverTimeChart(filteredHistory, players, playerColors);
                updateTopItemsChart(filteredHistory, players, playerColors);
                updateActivityHeatmapChart(filteredHistory, players, playerColors);

                // Update other charts
                generateKeyStats(filteredHistory);
                generateDayOfWeekChart(filteredHistory);
                generatePlayerActivityChart(filteredHistory);
                generateMonthComparisonChart(filteredHistory);

            } catch (error) {
                console.error('Failed to load analytics:', error);
            }
        }

        async function cleanupDeathMarkdown() {
            if (!isAdmin) {
                alert('Admin access required!');
                return;
            }

            if (!confirm('Clean markdown links from all death records in database?\n\nThis will fix old data that has [NPC Name](url) format.')) {
                return;
            }

            try {
                const response = await fetch(`${API_URL}/deaths/cleanup-markdown`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' }
                });

                const result = await response.json();

                if (response.ok && result.success) {
                    alert(`✅ Cleanup complete!\n\nUpdated: ${result.updated} records\nTotal checked: ${result.total_checked}`);
                    // Reload deaths to show cleaned data
                    loadDeathStats();
                } else {
                    alert(`❌ Cleanup failed: ${result.error || 'Unknown error'}`);
                }
            } catch (error) {
                console.error('Cleanup error:', error);
                alert(`❌ Failed to clean death data: ${error.message}`);
            }
        }


        function updateDropsOverTimeChart(historyData, players, playerColors) {
            const ctx = document.getElementById('dropsPerDayChart').getContext('2d');

            // Get last 30 days
            const last30Days = [];
            const today = new Date();

            for (let i = 29; i >= 0; i--) {
                const date = new Date(today);
                date.setDate(today.getDate() - i);
                const dateStr = date.toISOString().split('T')[0];
                last30Days.push(dateStr);
            }

            const labels = last30Days.map(d => {
                const date = new Date(d);
                return `${date.getMonth() + 1}/${date.getDate()}`;
            });

            // Create datasets for each player
            const datasets = players.map(player => {
                const dayCounts = {};
                last30Days.forEach(d => dayCounts[d] = 0);

                historyData.forEach(drop => {
                    if (drop.player === player) {
                        const dateStr = drop.timestamp.toISOString().split('T')[0];
                        if (dayCounts.hasOwnProperty(dateStr)) {
                            dayCounts[dateStr]++;
                        }
                    }
                });

                const data = last30Days.map(d => dayCounts[d]);
                const color = playerColors[player] || '#cd8b2d';

                return {
                    label: player,
                    data: data,
                    borderColor: color,
                    backgroundColor: color + '33',
                    fill: false,
                    tension: 0.4,
                    pointRadius: 3,
                    pointHoverRadius: 5
                };
            });

            if (analyticsCharts.dropsPerDay) analyticsCharts.dropsPerDay.destroy();

            analyticsCharts.dropsPerDay = new Chart(ctx, {
                type: 'line',
                data: {
                    labels: labels,
                    datasets: datasets
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: true,
                    plugins: {
                        legend: {
                            display: players.length > 1,
                            position: 'top',
                            labels: {
                                boxWidth: 12,
                                font: { size: 10 }
                            }
                        },
                        title: {
                            display: true,
                            text: 'Drops Over Time (Last 30 Days)',
                            font: { size: 14, weight: 'bold' }
                        }
                    },
                    scales: {
                        y: {
                            beginAtZero: true,
                            ticks: { stepSize: 1 }
                        }
                    }
                }
            });
        }

        function updateValueDistributionChart(historyData, players, playerColors) {
            const ctx = document.getElementById('valueDistributionChart');
            if (!ctx) return;

            const ranges = [
                { label: '0-100K', min: 0, max: 100000 },
                { label: '100K-500K', min: 100000, max: 500000 },
                { label: '500K-1M', min: 500000, max: 1000000 },
                { label: '1M-5M', min: 1000000, max: 5000000 },
                { label: '5M+', min: 5000000, max: Infinity }
            ];

            const datasets = players.map(player => {
                const rangeCounts = ranges.map(() => 0);

                historyData.forEach(drop => {
                    if (drop.player === player && drop.value) {
                        ranges.forEach((range, index) => {
                            if (drop.value >= range.min && drop.value < range.max) {
                                rangeCounts[index]++;
                            }
                        });
                    }
                });

                const color = playerColors[player] || '#cd8b2d';

                return {
                    label: player,
                    data: rangeCounts,
                    backgroundColor: color + '99',
                    borderColor: color,
                    borderWidth: 1
                };
            });

            if (analyticsCharts.valueDistribution) analyticsCharts.valueDistribution.destroy();

            analyticsCharts.valueDistribution = new Chart(ctx, {
                type: 'bar',
                data: {
                    labels: ranges.map(r => r.label),
                    datasets: datasets
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: true,
                    plugins: {
                        legend: {
                            display: players.length > 1,
                            position: 'top',
                            labels: {
                                boxWidth: 12,
                                font: { size: 10 }
                            }
                        },
                        title: {
                            display: true,
                            text: 'Drop Value Distribution',
                            font: { size: 14, weight: 'bold' }
                        }
                    },
                    scales: {
                        y: {
                            beginAtZero: true,
                            ticks: { stepSize: 1 }
                        }
                    }
                }
            });
        }

        function updateTopItemsChart(historyData, players, playerColors) {
            const ctx = document.getElementById('topItemsChart').getContext('2d');

            if (players.length === 1) {
                const itemCounts = {};
                historyData.forEach(d => {
                    if (d.player === players[0]) {
                        itemCounts[d.item] = (itemCounts[d.item] || 0) + 1;
                    }
                });

                const sortedItems = Object.entries(itemCounts)
                    .sort((a, b) => b[1] - a[1])
                    .slice(0, 10);

                if (analyticsCharts.topItems) analyticsCharts.topItems.destroy();

                analyticsCharts.topItems = new Chart(ctx, {
                    type: 'doughnut',
                    data: {
                        labels: sortedItems.map(i => i[0]),
                        datasets: [{
                            data: sortedItems.map(i => i[1]),
                            backgroundColor: [
                                '#FFD700', '#C0C0C0', '#CD7F32', '#4CAF50', '#2196F3',
                                '#FF9800', '#9C27B0', '#E91E63', '#00BCD4', '#8BC34A'
                            ],
                            borderColor: '#8B6914',
                            borderWidth: 2
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: true,
                        plugins: {
                            legend: {
                                position: 'right',
                                labels: {
                                    boxWidth: 15,
                                    font: { size: 11 }
                                }
                            },
                            title: {
                                display: true,
                                text: `Top Items - ${players[0]}`,
                                font: { size: 14, weight: 'bold' }
                            }
                        }
                    }
                });
            } else {
                const playerDropCounts = {};
                players.forEach(player => {
                    playerDropCounts[player] = historyData.filter(d => d.player === player).length;
                });

                const sortedPlayers = Object.entries(playerDropCounts)
                    .sort((a, b) => b[1] - a[1]);

                const colors = sortedPlayers.map(([player]) => playerColors[player] || '#cd8b2d');

                if (analyticsCharts.topItems) analyticsCharts.topItems.destroy();

                analyticsCharts.topItems = new Chart(ctx, {
                    type: 'doughnut',
                    data: {
                        labels: sortedPlayers.map(p => p[0]),
                        datasets: [{
                            data: sortedPlayers.map(p => p[1]),
                            backgroundColor: colors,
                            borderColor: '#8B6914',
                            borderWidth: 2
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: true,
                        plugins: {
                            legend: {
                                position: 'right',
                                labels: {
                                    boxWidth: 15,
                                    font: { size: 11 }
                                }
                            },
                            title: {
                                display: true,
                                text: 'Total Drops by Player',
                                font: { size: 14, weight: 'bold' }
                            }
                        }
                    }
                });
            }
        }

        function updateActivityHeatmapChart(historyData, players, playerColors) {
            const ctx = document.getElementById('hourHeatmapChart');
            if (!ctx) return;

            const hours = Array.from({length: 24}, (_, i) => i);

            const datasets = players.map(player => {
                const hourCounts = Array(24).fill(0);

                historyData.forEach(drop => {
                    if (drop.player === player) {
                        const hour = drop.timestamp.getHours();
                        hourCounts[hour]++;
                    }
                });

                const color = playerColors[player] || '#cd8b2d';

                return {
                    label: player,
                    data: hourCounts,
                    backgroundColor: color + '66',
                    borderColor: color,
                    borderWidth: 1
                };
            });

            if (analyticsCharts.hourHeatmap) analyticsCharts.hourHeatmap.destroy();

            analyticsCharts.hourHeatmap = new Chart(ctx, {
                type: 'bar',
                data: {
                    labels: hours.map(h => `${h}:00`),
                    datasets: datasets
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: true,
                    plugins: {
                        legend: {
                            display: players.length > 1,
                            position: 'top',
                            labels: {
                                boxWidth: 12,
                                font: { size: 10 }
                            }
                        },
                        title: {
                            display: true,
                            text: 'Activity by Hour of Day',
                            font: { size: 14, weight: 'bold' }
                        }
                    },
                    scales: {
                        y: {
                            beginAtZero: true,
                            ticks: { stepSize: 1 }
                        },
                        x: {
                            ticks: {
                                maxRotation: 45,
                                minRotation: 45,
                                font: { size: 9 }
                            }
                        }
                    }
                }
            });
        }

        function updateAnalyticsCharts(historyData) {
            // Get player colors (assign colors to each player)
            const players = analyticsSelectedPlayers.length > 0
                ? analyticsSelectedPlayers
                : [...new Set(historyData.map(r => r.player))];

            const playerColors = assignPlayerColors(players);

            // Update each chart with multi-player support
            updateDropsOverTimeChart(historyData, players, playerColors);
            updateValueDistributionChart(historyData, players, playerColors);
            updateTopItemsChart(historyData, players, playerColors);
            updateActivityHeatmapChart(historyData, players, playerColors);
        }

        function assignPlayerColors(players) {
            const colors = [
                '#667eea', '#764ba2', '#f093fb', '#4facfe',
                '#43e97b', '#fa709a', '#fee140', '#30cfd0',
                '#a8edea', '#fed6e3', '#c471f5', '#fa71cd'
            ];

            const colorMap = {};
            players.forEach((player, index) => {
                colorMap[player] = colors[index % colors.length];
            });

            return colorMap;
        }

        // Helper function to clean markdown links from Dink messages
        function cleanMarkdownLinks(text) {
            if (!text) return text;

            // Convert markdown links [text](url) to just the text
            // Regex: \[([^\]]+)\]\([^\)]+\)
            return text.replace(/\[([^\]]+)\]\([^\)]+\)/g, '$1');
        }


        // ===========================
        // ENHANCED DEATH TRACKING
        // ===========================

        function openDeathsModal() {
            document.getElementById('deathsModal').classList.add('active');
            loadDeathStats();
        }

        function closeDeathsModal() {
            document.getElementById('deathsModal').classList.remove('active');
        }

        async function loadDeathStats() {
            const loadingDiv = document.getElementById('deathsLoading');
            const contentDiv = document.getElementById('deathsContent');

            loadingDiv.style.display = 'block';
            contentDiv.style.display = 'none';

            try {
                // Fetch player deaths, NPC deaths, AND player-NPC breakdown
                const [playerResponse, npcResponse, playerNpcResponse] = await Promise.all([
                    fetch(`${API_URL}/deaths`),
                    fetch(`${API_URL}/deaths/by-npc`),
                    fetch(`${API_URL}/deaths/by-player-npc`)  // ⭐ NEW ENDPOINT
                ]);

                if (!playerResponse.ok) {
                    throw new Error('Failed to fetch death statistics');
                }

                const playerData = await playerResponse.json();
                const npcData = npcResponse.ok ? await npcResponse.json() : { npc_stats: [] };
                const playerNpcData = playerNpcResponse.ok ? await playerNpcResponse.json() : { player_npc_deaths: {} };  // ⭐ NEW DATA

                // Update total deaths
                document.getElementById('totalDeathsCount').textContent = playerData.total_deaths.toLocaleString();

                // Build player stats HTML
                const playerStatsDiv = document.getElementById('deathPlayerStats');

                if (playerData.player_stats.length === 0) {
                    playerStatsDiv.innerHTML = '<div style="text-align: center; padding: 40px; color: #666;">No deaths recorded yet!</div>';
                } else {
                    let html = '<div style="display: grid; gap: 15px;">';

                    playerData.player_stats.forEach((player, index) => {
                        const rank = index + 1;
                        const medal = rank === 1 ? '🥇' : rank === 2 ? '🥈' : rank === 3 ? '🥉' : '';
                        const rankClass = rank <= 3 ? `rank-${rank}` : '';

                        // Format last death date
                        let lastDeathText = '';
                        if (player.last_death) {
                            const date = new Date(player.last_death);
                            const now = new Date();
                            const diffMs = now - date;
                            const diffMins = Math.floor(diffMs / 60000);
                            const diffHours = Math.floor(diffMs / 3600000);
                            const diffDays = Math.floor(diffMs / 86400000);

                            if (diffMins < 60) {
                                lastDeathText = `${diffMins} minute${diffMins !== 1 ? 's' : ''} ago`;
                            } else if (diffHours < 24) {
                                lastDeathText = `${diffHours} hour${diffHours !== 1 ? 's' : ''} ago`;
                            } else {
                                lastDeathText = `${diffDays} day${diffDays !== 1 ? 's' : ''} ago`;
                            }
                        }

                        // ⭐ UPDATED: Get player's nemesis with EXACT death count
                        let nemesisHtml = '';
                        if (playerNpcData.player_npc_deaths && playerNpcData.player_npc_deaths[player.player]) {
                            // Get all NPCs this player died to, sorted by death count
                            const playerNpcs = Object.entries(playerNpcData.player_npc_deaths[player.player])
                                .sort((a, b) => b[1] - a[1]);  // Sort by death count descending

                            if (playerNpcs.length > 0) {
                                const [nemesisNpc, nemesisDeaths] = playerNpcs[0];  // Get #1 deadliest
                                const cleanNemesisNpc = cleanMarkdownLinks(nemesisNpc);
                                nemesisHtml = `<div style="font-size: 12px; color: #8B0000; margin-top: 3px;">
                                    💀 Nemesis: ${cleanNemesisNpc} (${nemesisDeaths} death${nemesisDeaths !== 1 ? 's' : ''})
                                </div>`;
                            }
                        }

                        // Last death NPC
                        let lastNpcHtml = '';
                        if (player.last_npc) {
                            // Clean up NPC display
                            let npcDisplay = cleanMarkdownLinks(player.last_npc);

                            // If it's Unknown or %NPC%, style it differently
                            if (npcDisplay === 'Unknown' || npcDisplay === '%NPC%') {
                                npcDisplay = '<span style="color: #999; font-style: italic;">Unknown cause</span>';
                            }

                            lastNpcHtml = `<div style="font-size: 12px; color: #666; margin-top: 3px;">
                                ⚔️ Last death: ${npcDisplay}${lastDeathText ? ` (${lastDeathText})` : ''}
                            </div>`;
                        } else if (lastDeathText) {
                            lastNpcHtml = `<div style="font-size: 12px; color: #666; margin-top: 3px;">
                                ⏱️ Last death: ${lastDeathText}
                            </div>`;
                        }

                        html += `
                            <div style="background: ${rankClass ? 'linear-gradient(135deg, rgba(139,0,0,0.1) 0%, rgba(107,0,0,0.05) 100%)' : 'rgba(0,0,0,0.03)'};
                                        padding: 20px;
                                        border-radius: 8px;
                                        border-left: 4px solid ${rank === 1 ? '#FFD700' : rank === 2 ? '#C0C0C0' : rank === 3 ? '#CD7F32' : '#8B0000'};
                                        display: grid;
                                        grid-template-columns: auto 1fr auto;
                                        align-items: center;
                                        gap: 15px;">

                                <div style="font-size: 32px;">${medal || '💀'}</div>

                                <div>
                                    <div style="font-weight: bold; font-size: 18px; color: #2c1810; margin-bottom: 5px;">
                                        #${rank} ${player.player}
                                    </div>
                                    ${nemesisHtml}
                                    ${lastNpcHtml}
                                </div>

                                <div style="text-align: right;">
                                    <div style="font-size: 28px; font-weight: bold; color: #8B0000;">
                                        ${player.deaths}
                                    </div>
                                    <div style="font-size: 12px; color: #666;">
                                        death${player.deaths !== 1 ? 's' : ''}
                                    </div>
                                </div>
                            </div>
                        `;
                    });

                    html += '</div>';
                    playerStatsDiv.innerHTML = html;
                }

                // Build deadliest bosses section (UNCHANGED)
                const deadliestBossesDiv = document.getElementById('deadliestBosses');

                if (!npcData.npc_stats || npcData.npc_stats.length === 0) {
                    deadliestBossesDiv.innerHTML = '<div style="text-align: center; padding: 40px; color: #666;">No NPC death data available!</div>';
                } else {
                    let bossHtml = '<div style="display: grid; gap: 12px;">';

                    npcData.npc_stats.slice(0, 10).forEach((npc, index) => {
                        const rank = index + 1;
                        const medal = rank === 1 ? '👑' : rank === 2 ? '💀' : rank === 3 ? '⚔️' : `${rank}.`;
                        const barWidth = Math.max(10, (npc.deaths / npcData.npc_stats[0].deaths) * 100);

                        let lastVictimHtml = '';
                        if (npc.last_victim) {
                            let timeAgo = '';
                            if (npc.last_death_time) {
                                const date = new Date(npc.last_death_time);
                                const now = new Date();
                                const diffMs = now - date;
                                const diffMins = Math.floor(diffMs / 60000);
                                const diffHours = Math.floor(diffMs / 3600000);
                                const diffDays = Math.floor(diffMs / 86400000);
                                if (diffMins < 60) {
                                    timeAgo = `${diffMins} min${diffMins !== 1 ? 's' : ''} ago`;
                                } else if (diffHours < 24) {
                                    timeAgo = `${diffHours} hr${diffHours !== 1 ? 's' : ''} ago`;
                                } else {
                                    timeAgo = `${diffDays} day${diffDays !== 1 ? 's' : ''} ago`;
                                }
                            }
                            lastVictimHtml = `<div style="font-size: 11px; color: #8B0000; margin-top: 2px;">🎯 Last killed: ${npc.last_victim}${timeAgo ? ` (${timeAgo})` : ''}</div>`;
                        }

                        bossHtml += `
                            <div style="background: rgba(139,0,0,0.05); padding: 15px; border-radius: 8px; border-left: 4px solid #8B0000;">
                                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                                    <div style="display: flex; align-items: center; gap: 12px; flex: 1;">
                                        <div style="font-size: 20px; min-width: 30px;">${medal}</div>
                                        <div>
                                            <div style="font-weight: bold; font-size: 16px; color: #2c1810;">${cleanMarkdownLinks(npc.npc)}</div>
                                            <div style="font-size: 11px; color: #666; margin-top: 2px;">
                                                ${npc.unique_players} player${npc.unique_players !== 1 ? 's' : ''} killed
                                            </div>
                                            ${lastVictimHtml}
                                        </div>
                                    </div>
                                    <div style="text-align: right;">
                                        <div style="font-size: 24px; font-weight: bold; color: #8B0000;">${npc.deaths}</div>
                                        <div style="font-size: 11px; color: #666;">kills</div>
                                    </div>
                                </div>
                                <div style="background: rgba(139,0,0,0.1); height: 8px; border-radius: 4px; overflow: hidden;">
                                    <div style="background: linear-gradient(90deg, #8B0000 0%, #CD5C5C 100%); height: 100%; width: ${barWidth}%; transition: width 0.5s;"></div>
                                </div>
                            </div>
                        `;
                    });

                    bossHtml += '</div>';
                    deadliestBossesDiv.innerHTML = bossHtml;
                }

                loadingDiv.style.display = 'none';
                contentDiv.style.display = 'block';

            } catch (error) {
                console.error('Error loading death stats:', error);
                loadingDiv.innerHTML = `
                    <div style="text-align: center; padding: 40px;">
                        <div style="font-size: 48px; margin-bottom: 20px;">❌</div>
                        <div style="color: #d32f2f; font-weight: bold; font-size: 18px;">Failed to load death statistics</div>
                        <div style="color: #666; font-size: 14px; margin-top: 10px;">${error.message}</div>
                    </div>
                `;
            }
        }

        // ============================================
        // DEATHS VIEW SWITCHING
        // ============================================

        function switchDeathsView(view) {
            // Update button states
            document.getElementById('deathsViewOverview').classList.toggle('active', view === 'overview');
            document.getElementById('deathsViewBreakdown').classList.toggle('active', view === 'breakdown');

            // Toggle content visibility
            document.getElementById('deathsOverviewContent').style.display = view === 'overview' ? 'grid' : 'none';
            document.getElementById('deathsBreakdownContent').style.display = view === 'breakdown' ? 'block' : 'none';

            // Load breakdown data if switching to that view
            if (view === 'breakdown') {
                loadDeathsBreakdown();
            }
        }

        async function loadDeathsBreakdown() {
            const container = document.getElementById('deathsBreakdownContent');

            // Don't reload if already loaded (unless empty)
            if (container.children.length > 0 && !container.textContent.includes('Loading')) {
                return;
            }

            container.innerHTML = '<div class="loading-message"><div class="loading-spinner"></div><p>Loading death breakdown...</p></div>';

            try {
                const response = await fetch(`${API_URL}/deaths/by-player-npc`);
                const data = await response.json();

                if (!data.player_npc_deaths || Object.keys(data.player_npc_deaths).length === 0) {
                    container.innerHTML = '<div style="text-align: center; padding: 60px; color: #666;">No death data available!</div>';
                    return;
                }

                renderDeathsBreakdown(data.player_npc_deaths);

            } catch (error) {
                console.error('Failed to load deaths breakdown:', error);
                container.innerHTML = '<div style="text-align: center; padding: 60px; color: #8B0000;">❌ Failed to load breakdown data</div>';
            }
        }

        function renderDeathsBreakdown(playerNpcData) {
            const container = document.getElementById('deathsBreakdownContent');

            // Aggregate all NPCs across all players
            const npcTotals = {};
            Object.values(playerNpcData).forEach(npcs => {
                Object.entries(npcs).forEach(([npc, count]) => {
                    npcTotals[npc] = (npcTotals[npc] || 0) + count;
                });
            });

            // Sort NPCs by total deaths
            const sortedNPCs = Object.entries(npcTotals)
                .sort((a, b) => b[1] - a[1]);

            if (sortedNPCs.length === 0) {
                container.innerHTML = '<div style="text-align: center; padding: 60px; color: #666;">No NPC death data found!</div>';
                return;
            }

            // Create accordion-style cards for each NPC
            let html = '<div style="display: grid; gap: 15px;">';

            sortedNPCs.forEach(([npc, totalDeaths]) => {
                const cleanNpc = cleanMarkdownLinks(npc);
                const npcId = `boss-${cleanNpc.replace(/[^a-zA-Z0-9]/g, '')}`;

                // Get all players who died to this NPC
                const playerDeaths = [];
                Object.entries(playerNpcData).forEach(([player, npcs]) => {
                    if (npcs[npc]) {
                        playerDeaths.push({ player, deaths: npcs[npc] });
                    }
                });

                // Sort players by death count
                playerDeaths.sort((a, b) => b.deaths - a.deaths);

                // Create player rankings HTML
                let playersHtml = '<div style="display: grid; gap: 8px; margin-top: 15px;" class="boss-death-players" id="' + npcId + '-players" style="display: none;">';
                playerDeaths.forEach((pd, index) => {
                    const rank = index + 1;
                    const rankIcon = rank === 1 ? '🥇' : rank === 2 ? '🥈' : rank === 3 ? '🥉' : `${rank}.`;

                    playersHtml += `
                        <div style="background: rgba(139,0,0,0.03); padding: 12px; border-radius: 6px; display: flex; justify-content: space-between; align-items: center; border-left: 3px solid ${rank === 1 ? '#FFD700' : rank === 2 ? '#C0C0C0' : rank === 3 ? '#CD7F32' : '#8B0000'};">
                            <div style="display: flex; align-items: center; gap: 12px;">
                                <span style="font-size: 18px; min-width: 30px;">${rankIcon}</span>
                                <span style="font-weight: bold; color: #2c1810;">${pd.player}</span>
                            </div>
                            <div style="text-align: right;">
                                <div style="font-size: 20px; font-weight: bold; color: #8B0000;">${pd.deaths}</div>
                                <div style="font-size: 11px; color: #666;">death${pd.deaths !== 1 ? 's' : ''}</div>
                            </div>
                        </div>
                    `;
                });
                playersHtml += '</div>';

                html += `
                    <div style="background: rgba(139,0,0,0.05); padding: 20px; border-radius: 8px; border-left: 4px solid #8B0000; cursor: pointer;" onclick="toggleBossDeathDetail('${npcId}')">
                        <div style="display: flex; justify-content: space-between; align-items: center;">
                            <div>
                                <div style="font-weight: bold; font-size: 18px; color: #2c1810; margin-bottom: 5px;">
                                    💀 ${cleanNpc}
                                </div>
                                <div style="font-size: 12px; color: #666;">
                                    ${playerDeaths.length} player${playerDeaths.length !== 1 ? 's' : ''} died here • Click to expand
                                </div>
                            </div>
                            <div style="text-align: right;">
                                <div style="font-size: 28px; font-weight: bold; color: #8B0000;">${totalDeaths}</div>
                                <div style="font-size: 12px; color: #666;">total deaths</div>
                            </div>
                        </div>
                        ${playersHtml}
                    </div>
                `;
            });

            html += '</div>';
            container.innerHTML = html;
        }

        function toggleBossDeathDetail(bossId) {
            const playersDiv = document.getElementById(`${bossId}-players`);
            if (playersDiv) {
                const isHidden = playersDiv.style.display === 'none';
                playersDiv.style.display = isHidden ? 'block' : 'none';
            }
        }

        function openTileInfoModal(index) {
            const tile = bingoData.tiles[index];
            const displayName = tile.displayTitle || (tile.items.length > 0 ? tile.items[0] : 'Empty Tile');

            // Build items list HTML
            let itemsHtml = '<ul class="tile-info-list">';
            if (tile.items.length === 0) {
                itemsHtml += '<li style="color: #999;">No items configured</li>';
            } else {
                tile.items.forEach((item, idx) => {
                    if (idx === 0) {
                        itemsHtml += `<li><strong>${item}</strong> (Display item)</li>`;
                    } else {
                        itemsHtml += `<li>${item}</li>`;
                    }
                });
            }
            itemsHtml += '</ul>';

            // Build completions HTML
            let completionsHtml = '';
            if (tile.completedBy.length > 0) {
                completionsHtml = '<div class="tile-completions">';
                tile.completedBy.forEach(player => {
                    completionsHtml += `<span class="completion-badge">✓ ${player}</span>`;
                });
                completionsHtml += '</div>';
            } else {
                completionsHtml = '<p style="color: #999; font-style: italic;">Nobody has completed this tile yet!</p>';
            }

            // Generate wiki link (using first item)
            let wikiLinkHtml = '';
            if (tile.items.length > 0) {
                const wikiItemName = tile.items[0].trim().replace(/\s+/g, '_');
                const wikiUrl = `https://oldschool.runescape.wiki/w/${encodeURIComponent(wikiItemName)}`;
                wikiLinkHtml = `
                    <a href="${wikiUrl}" target="_blank" class="wiki-link-btn">
                        📖 View on OSRS Wiki
                    </a>
                `;
            }

            // Build icon HTML
            let iconHtml = '';
            if (tile.items.length > 0) {
                iconHtml = `<img src="https://oldschool.runescape.wiki/images/${encodeURIComponent(tile.items[0].trim().replace(/\s+/g, '_'))}_detail.png"
                                 class="tile-info-icon"
                                 onerror="this.style.display='none'">`;
            }

            // Create modal HTML
            const modalHtml = `
                <div class="modal tile-info-modal" id="tileInfoModal">
                    <div class="modal-content">
                        <button class="close-btn" onclick="closeTileInfoModal()">×</button>

                        <div class="tile-info-header">
                            ${iconHtml}
                            <div class="tile-info-title">
                                <h2>${displayName}</h2>
                                <div class="tile-info-subtitle">Tile #${index + 1} • ${tile.value} points</div>
                            </div>
                        </div>

                        <div class="tile-info-section">
                            <h3>📋 Items</h3>
                            ${itemsHtml}
                            ${tile.items.length > 1 ? `<p style="font-size: 12px; color: #666; margin-top: 10px;"><em>${tile.requireAllItems ? 'All of these items are required to complete this tile' : 'Any of these items will complete this tile'}</em></p>` : ''}
                            ${wikiLinkHtml}
                        </div>

                        <div class="tile-info-section">
                            <h3>✓ Completed By</h3>
                            ${completionsHtml}
                        </div>
                    </div>
                </div>
            `;

            // Remove existing modal if present
            const existingModal = document.getElementById('tileInfoModal');
            if (existingModal) {
                existingModal.remove();
            }

            // Add modal to body
            document.body.insertAdjacentHTML('beforeend', modalHtml);

            // Show modal
            document.getElementById('tileInfoModal').classList.add('active');
        }

        function closeTileInfoModal() {
            const modal = document.getElementById('tileInfoModal');
            if (modal) {
                modal.classList.remove('active');
                setTimeout(() => modal.remove(), 300);
            }
        }

        async function openKCModal() {
            document.getElementById('kcModal').classList.add('active');

            // Show admin controls if admin
            if (isAdmin) {
                document.getElementById('kcAdminControls').style.display = 'block';
            }

            // Show loading state in Overview tab
            const overviewContainer = document.getElementById('kcTabContentOverview');
            if (overviewContainer) {
                overviewContainer.innerHTML = `
                    <div class="loading-message">
                        <div class="loading-spinner"></div>
                        <p>Loading Boss Kill Counts...</p>
                    </div>
                `;
            }

            // Load data
            await loadKCData();

            showKCTab('overview');
        }

        function closeKCModal() {
            document.getElementById('kcModal').classList.remove('active');
        }

        function showKCTab(tab) {
            // Hide all tabs
            document.querySelectorAll('.kc-tab-content').forEach(el => el.style.display = 'none');
            document.querySelectorAll('.kc-tab').forEach(el => el.classList.remove('active'));

            // Show selected tab
            document.getElementById(`kcTabContent${tab.charAt(0).toUpperCase() + tab.slice(1)}`).style.display = 'block';
            document.getElementById(`kcTab${tab.charAt(0).toUpperCase() + tab.slice(1)}`).classList.add('active');
        }

        function showEffortView(view) {
            // Toggle buttons
            document.getElementById('effortViewPlayer').classList.toggle('active', view === 'player');
            document.getElementById('effortViewBoss').classList.toggle('active', view === 'boss');

            // Toggle content
            document.getElementById('effortPlayerView').style.display = view === 'player' ? 'block' : 'none';
            document.getElementById('effortBossView').style.display = view === 'boss' ? 'block' : 'none';
        }

        async function loadKCData() {
            try {
                const response = await fetch(`${API_URL}/kc/all`);
                const data = await response.json();

                renderKCOverview(data);
                renderKCLeaderboards(data);
                renderKCEffort(data);
            } catch (error) {
                console.error('Failed to load KC data:', error);
            }
        }

        function renderKCOverview(data) {
            const container = document.getElementById('kcTabContentOverview');
            if (!container) {
                console.error('KC Overview container not found');
                return;
            }

            console.log('Rendering KC Overview with data:', data);

            if (!data || Object.keys(data).length === 0) {
                container.innerHTML = '<div class="loading-message" style="padding: 40px;">No KC data yet! Click "Fetch All Players KC" to get started.</div>';
                return;
            }

            let html = '<div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(400px, 1fr)); gap: 20px;">';

            for (const [player, playerData] of Object.entries(data)) {
                const bosses = playerData.bosses || {};
                const bossEntries = Object.entries(bosses).sort((a, b) => b[1] - a[1]);
                const topBosses = bossEntries.slice(0, 5);

                const lastUpdate = playerData.timestamp ? new Date(playerData.timestamp).toLocaleString() : 'Unknown';

                html += `
                    <div class="player-kc-card">
                        <h3>${player}</h3>
                        <div style="font-size: 11px; color: #8b7355; margin-bottom: 15px;">Last updated: ${lastUpdate}</div>
                        <div>
                `;

                if (topBosses.length > 0) {
                    topBosses.forEach(([boss, kc]) => {
                        html += `<div class="boss-kc-item">
                            <span>${boss}</span>
                            <span class="kc-value">${kc.toLocaleString()} KC</span>
                        </div>`;
                    });
                } else {
                    html += '<div style="color: #8b7355; font-style: italic; text-align: center; padding: 20px;">No boss KC found</div>';
                }

                html += `
                        </div>
                        <button onclick="showPlayerKCDetail('${player}')" class="btn-primary" style="margin-top: 15px; width: 100%;">
                            View All Bosses
                        </button>
                    </div>
                `;
            }

            html += '</div>';
            container.innerHTML = html;
            console.log('KC Overview rendered successfully');
        }

        function renderKCLeaderboards(data) {
            const container = document.getElementById('kcTabContentLeaderboards');
            if (!container) {
                console.error('KC Leaderboards container not found');
                return;
            }

            console.log('Rendering KC Leaderboards with data:', data);

            if (!data || Object.keys(data).length === 0) {
                container.innerHTML = '<div style="text-align: center; color: #666; padding: 40px;">No KC data available</div>';
                return;
            }

            // Aggregate all bosses
            const allBosses = new Set();
            Object.values(data).forEach(playerData => {
                if (playerData.bosses) {
                    Object.keys(playerData.bosses).forEach(boss => allBosses.add(boss));
                }
            });

            const sortedBosses = Array.from(allBosses).sort();

            let html = `
                <div style="margin-bottom: 20px;">
                    <label style="display: block; margin-bottom: 10px; font-weight: bold;">Select Boss:</label>
                    <select id="bossLeaderboardSelect" onchange="updateBossLeaderboard(this.value, ${JSON.stringify(data).replace(/"/g, '&quot;')})" style="width: 100%; padding: 10px; border-radius: 4px; border: 1px solid #ddd; background: white; color: #333; font-size: 14px;">
                        <option value="">-- Select a Boss --</option>
            `;

            sortedBosses.forEach(boss => {
                html += `<option value="${boss}">${boss}</option>`;
            });

            html += `
                    </select>
                </div>
                <div id="bossLeaderboardContent" style="margin-top: 20px;">
                    <div style="text-align: center; color: #666; padding: 40px;">Please select a boss to view leaderboard</div>
                </div>
            `;

            container.innerHTML = html;
            console.log('KC Leaderboards rendered successfully');
        }

        window.updateBossLeaderboard = function(boss, dataStr) {
            const container = document.getElementById('bossLeaderboardContent');
            if (!container) return;

            if (!boss) {
                container.innerHTML = '<div style="text-align: center; color: #666; padding: 40px;">Please select a boss</div>';
                return;
            }

            // Parse data
            let data;
            try {
                data = typeof dataStr === 'string' ? JSON.parse(dataStr) : dataStr;
            } catch (e) {
                // If parsing fails, fetch fresh data
                fetch(`${API_URL}/kc/all`)
                    .then(r => r.json())
                    .then(freshData => updateBossLeaderboardWithData(boss, freshData))
                    .catch(err => {
                        console.error('Failed to fetch KC data:', err);
                        container.innerHTML = '<div style="text-align: center; color: #8b1a1a; padding: 40px;">❌ Failed to load leaderboard</div>';
                    });
                return;
            }

            updateBossLeaderboardWithData(boss, data);
        };

        function updateBossLeaderboardWithData(boss, data) {
            const container = document.getElementById('bossLeaderboardContent');
            if (!container) return;

            const leaderboard = [];

            Object.entries(data).forEach(([player, playerData]) => {
                if (playerData.bosses && playerData.bosses[boss]) {
                    leaderboard.push({
                        player: player,
                        kc: playerData.bosses[boss]
                    });
                }
            });

            leaderboard.sort((a, b) => b.kc - a.kc);

            if (leaderboard.length === 0) {
                container.innerHTML = `<div style="text-align: center; color: #666; padding: 40px;">No one has KC for ${boss}</div>`;
                return;
            }

            let html = '<div style="background: rgba(255,255,255,0.05); padding: 20px; border-radius: 8px;">';
            leaderboard.forEach((entry, index) => {
                const medal = index === 0 ? '🥇' : index === 1 ? '🥈' : index === 2 ? '🥉' : '';
                html += `
                    <div style="display: flex; justify-content: space-between; padding: 12px; margin-bottom: 8px; background: rgba(255,255,255,0.03); border-radius: 4px;">
                        <span style="font-size: 16px;">
                            ${medal} #${index + 1} ${entry.player}
                        </span>
                        <span style="color: #4CAF50; font-weight: bold; font-size: 16px;">
                            ${entry.kc.toLocaleString()} KC
                        </span>
                    </div>
                `;
            });
            html += '</div>';
            container.innerHTML = html;
        }

        async function renderKCEffort(data) {
            const playerContainer = document.getElementById('effortPlayerView');
            const bossContainer = document.getElementById('effortBossView');

            if (!playerContainer || !bossContainer) {
                console.error('Effort containers not found');
                return;
            }

            try {
                const response = await fetch(`${API_URL}/kc/effort`);
                const effortData = await response.json();

                console.log('Effort API Response:', effortData);

                if (!effortData.success) {
                    const message = effortData.message || 'Unable to calculate effort';
                    playerContainer.innerHTML = `
                        <div class="loading-message" style="padding: 40px;">
                            <p>⚠️ ${message}</p>
                            ${message.includes('snapshot') ? '<p style="margin-top: 20px;">Use the "Mark as Bingo Start" button in admin controls to set a baseline.</p>' : ''}
                        </div>
                    `;
                    bossContainer.innerHTML = playerContainer.innerHTML;
                    return;
                }

                // Transform API data to match expected format
                const transformedData = {
                    success: true,
                    players: effortData.players.map(player => {
                        const bossesArray = Object.entries(player.effort || {}).map(([boss, gained]) => ({
                            boss: boss,
                            gained: gained,
                            start: 0,  // API doesn't provide this in current format
                            current: gained  // Approximation
                        }));

                        const totalKills = bossesArray.reduce((sum, b) => sum + b.gained, 0);

                        return {
                            player: player.player,
                            totalKills: totalKills,
                            bosses: bossesArray
                        };
                    })
                };

                console.log('Transformed Data:', transformedData);

                // Render both views
                renderEffortPlayerView(transformedData, playerContainer);
                renderEffortBossView(transformedData, bossContainer);

            } catch (error) {
                console.error('Failed to load effort data:', error);
                const errorHtml = `
                    <div class="loading-message" style="padding: 40px;">
                        <p>Failed to load effort data</p>
                        <p style="font-size: 12px; color: #8b7355; margin-top: 10px;">Error: ${error.message}</p>
                    </div>
                `;
                playerContainer.innerHTML = errorHtml;
                bossContainer.innerHTML = errorHtml;
            }
        }

        function renderEffortPlayerView(effortData, container) {
            const players = effortData.players || [];

            if (players.length === 0) {
                container.innerHTML = `
                    <div class="loading-message" style="padding: 40px;">
                        <p>No effort data available yet!</p>
                        <p style="margin-top: 20px;">Fetch KC after marking bingo start to track progress.</p>
                    </div>
                `;
                return;
            }

            // Sort players by total kills gained
            players.sort((a, b) => b.totalKills - a.totalKills);

            let html = '<div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(400px, 1fr)); gap: 20px;">';

            players.forEach((player, index) => {
                const rankEmojis = ['🥇', '🥈', '🥉'];
                const rankEmoji = index < 3 ? rankEmojis[index] : `#${index + 1}`;

                html += `
                    <div class="player-kc-card">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px;">
                            <h3 style="margin: 0;">${player.player}</h3>
                            <span style="font-size: 24px;">${rankEmoji}</span>
                        </div>
                        <div style="background: rgba(205, 139, 45, 0.1); padding: 10px; border-radius: 5px; margin-bottom: 15px; text-align: center;">
                            <div style="font-size: 24px; font-weight: bold; color: #cd8b2d;">${player.totalKills.toLocaleString()}</div>
                            <div style="font-size: 12px; color: #8b7355;">Total KC Gained</div>
                        </div>
                `;

                if (player.bosses && player.bosses.length > 0) {
                    // Sort bosses by gains
                    const sortedBosses = [...player.bosses].sort((a, b) => b.gained - a.gained);
                    const topBosses = sortedBosses.slice(0, 5);

                    topBosses.forEach(boss => {
                        html += `
                            <div class="boss-kc-item">
                                <span>${boss.boss}</span>
                                <span class="kc-value">+${boss.gained.toLocaleString()}</span>
                            </div>
                        `;
                    });

                    if (sortedBosses.length > 5) {
                        html += `<div style="text-align: center; color: #8b7355; font-size: 12px; margin-top: 10px; font-style: italic;">+${sortedBosses.length - 5} more bosses</div>`;
                    }
                } else {
                    html += '<div style="text-align: center; color: #8b7355; font-style: italic; padding: 20px;">No gains yet</div>';
                }

                html += `</div>`;
            });

            html += '</div>';
            container.innerHTML = html;
        }

        function renderEffortBossView(effortData, container) {
            const players = effortData.players || [];

            if (players.length === 0) {
                container.innerHTML = `
                    <div class="loading-message" style="padding: 40px;">
                        <p>No effort data available yet!</p>
                    </div>
                `;
                return;
            }

            // Aggregate boss data across all players
            const bossMap = new Map();

            players.forEach(player => {
                if (player.bosses) {
                    player.bosses.forEach(boss => {
                        if (!bossMap.has(boss.boss)) {
                            bossMap.set(boss.boss, []);
                        }
                        bossMap.get(boss.boss).push({
                            player: player.player,
                            gained: boss.gained,
                            start: boss.start,
                            current: boss.current
                        });
                    });
                }
            });

            // Convert to array and sort by total gains
            const bossList = Array.from(bossMap.entries()).map(([boss, playerData]) => {
                const totalGains = playerData.reduce((sum, p) => sum + p.gained, 0);
                // Sort players by gains for this boss
                playerData.sort((a, b) => b.gained - a.gained);
                return { boss, playerData, totalGains };
            }).sort((a, b) => b.totalGains - a.totalGains);

            if (bossList.length === 0) {
                container.innerHTML = '<div class="loading-message" style="padding: 40px;">No boss gains recorded yet!</div>';
                return;
            }

            // Create accordion-style boss cards
            let html = '<div style="display: flex; flex-direction: column; gap: 15px;">';

            bossList.forEach(({ boss, playerData, totalGains }) => {
                html += `
                    <div class="player-kc-card" style="cursor: pointer;" onclick="toggleBossDetail('${boss.replace(/'/g, "\\'")}')">
                        <div style="display: flex; justify-content: space-between; align-items: center;">
                            <h3 style="margin: 0;">🎯 ${boss}</h3>
                            <div style="text-align: right;">
                                <div class="kc-value" style="font-size: 20px;">+${totalGains.toLocaleString()}</div>
                                <div style="font-size: 11px; color: #8b7355;">Total Gained</div>
                            </div>
                        </div>

                        <!-- Expandable Player List -->
                        <div id="boss-detail-${boss.replace(/[^a-zA-Z0-9]/g, '_')}" style="display: none; margin-top: 15px; padding-top: 15px; border-top: 2px solid rgba(205, 139, 45, 0.3);">
                            <div style="font-size: 13px; font-weight: bold; color: #8b7355; margin-bottom: 10px;">📊 Player Rankings:</div>
                `;

                playerData.forEach((player, index) => {
                    const rankEmojis = ['🥇', '🥈', '🥉'];
                    const rankIcon = index < 3 ? rankEmojis[index] : `${index + 1}.`;

                    html += `
                        <div style="display: flex; justify-content: space-between; align-items: center; padding: 8px; background: rgba(255, 255, 255, 0.3); border-radius: 4px; margin-bottom: 6px;">
                            <div style="display: flex; align-items: center; gap: 10px;">
                                <span style="font-size: 16px; min-width: 30px;">${rankIcon}</span>
                                <span style="font-weight: 500;">${player.player}</span>
                            </div>
                            <div style="text-align: right;">
                                <div class="kc-value">+${player.gained.toLocaleString()}</div>
                                <div style="font-size: 10px; color: #8b7355;">${player.start} → ${player.current} KC</div>
                            </div>
                        </div>
                    `;
                });

                html += `
                        </div>
                    </div>
                `;
            });

            html += '</div>';
            container.innerHTML = html;
        }

        function toggleBossDetail(boss) {
            const elementId = `boss-detail-${boss.replace(/[^a-zA-Z0-9]/g, '_')}`;
            const element = document.getElementById(elementId);
            if (element) {
                element.style.display = element.style.display === 'none' ? 'block' : 'none';
            }
        }

        function showPlayerKCDetail(player) {
            fetch(`${API_URL}/kc/all`)
                .then(r => r.json())
                .then(data => {
                    if (!data[player]) {
                        alert(`No KC data found for ${player}`);
                        return;
                    }

                    const bosses = data[player].bosses || {};
                    const bossEntries = Object.entries(bosses).sort((a, b) => b[1] - a[1]);

                    // Set title
                    document.getElementById('playerKCDetailTitle').textContent = `📊 ${player}'s Boss Kill Counts`;

                    // Generate boss list HTML
                    let html = '<div style="display: flex; flex-direction: column; gap: 10px;">';

                    if (bossEntries.length === 0) {
                        html += '<div style="text-align: center; color: #8b7355; padding: 40px; font-style: italic;">No boss KC found</div>';
                    } else {
                        bossEntries.forEach(([boss, kc]) => {
                            html += `
                                <div class="boss-kc-item">
                                    <span>${boss}</span>
                                    <span class="kc-value">${kc.toLocaleString()} KC</span>
                                </div>
                            `;
                        });
                    }

                    html += '</div>';

                    // Populate and show modal
                    document.getElementById('playerKCDetailContent').innerHTML = html;
                    document.getElementById('playerKCDetailModal').classList.add('active');
                })
                .catch(err => {
                    console.error('Failed to load player detail:', err);
                    alert('Failed to load player details');
                });
        }

        function closePlayerKCDetailModal() {
            document.getElementById('playerKCDetailModal').classList.remove('active');
        }

        async function fetchAllPlayersKC() {
            if (!confirm('Fetch current KC for all players?\n\nNote: Players must be tracked on WiseOldMan.net first.\nIf a player isn\'t found, add them at: https://wiseoldman.net')) {
                return;
            }

            console.log('='.repeat(60));
            console.log('🚀 FETCHING KC FROM WISEOLDMAN API');
            console.log('='.repeat(60));

            try {
                const response = await fetch(`${API_URL}/kc/snapshot`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ type: 'current' })
                });

                const result = await response.json();

                // Log all debug info to console
                console.log('\n📊 API RESPONSE:');
                console.log(result);

                if (result.debug) {
                    console.log('\n🔍 DEBUG LOG:');
                    result.debug.forEach(line => console.log(line));
                }

                if (result.results) {
                    console.log('\n👥 PER-PLAYER RESULTS:');
                    result.results.forEach(player => {
                        console.log(`\n${player.player}:`);
                        if (player.debug) {
                            player.debug.forEach(line => console.log(`  ${line}`));
                        }
                    });
                }

                console.log('\n' + '='.repeat(60));

                const successful = result.successful || 0;
                const total = result.snapshots || 0;
                const failed = result.results?.filter(r => !r.success) || [];

                let message = '';

                if (successful > 0) {
                    message = `✅ Fetched KC for ${successful}/${total} players!\n\n`;
                    if (failed.length > 0) {
                        message += `⚠️ ${failed.length} player(s) not found on WiseOldMan:\n`;
                        failed.forEach(f => {
                            message += `  • ${f.player}\n`;
                        });
                        message += `\nAdd them at: https://wiseoldman.net`;
                    }
                    alert(message);
                    loadKCData();
                } else {
                    message = `❌ No players found on WiseOldMan!\n\n`;
                    message += `Players need to be added to WiseOldMan first.\n`;
                    message += `Visit: https://wiseoldman.net\n\n`;
                    message += `Check browser console (F12) for details.`;
                    alert(message);
                }

            } catch (error) {
                console.error('❌ FETCH ERROR:', error);
                alert('❌ Failed to fetch KC\n\nCheck browser console (F12) for details.');
            }
        }

        async function markBingoStart() {
            if (!confirm('Mark current KC as bingo start? This sets the baseline for effort tracking.')) {
                return;
            }

            try {
                const response = await fetch(`${API_URL}/kc/snapshot`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ type: 'start' })
                });

                const result = await response.json();
                alert(`✅ Marked bingo start for ${result.snapshots} players`);
                loadKCData();
            } catch (error) {
                alert('❌ Failed to mark bingo start');
                console.error(error);
            }
        }

        // ============================================
        // CHANGELOG MODAL
        // ============================================

        // Changelog data (update this manually or load from JSON file)
        const changelogData = [
                            {
                version: "v2.6.0",
                date: "2025-01-21",
                title: "Added Boss Breakdown in Deaths statistics",
                changes: [
                    { type: "feature", text: "Added an event timer. Configure on the admin panel" },
                ]
            },
                            {
                version: "v2.5.0",
                date: "2025-01-21",
                title: "Added Boss Breakdown in Deaths statistics",
                changes: [
                    { type: "feature", text: "Added the ability for admin to shuffle and undo shuffle the bingo board" },
                ]
            },
                            {
                version: "v2.4.1",
                date: "2025-01-13",
                title: "Added Boss Breakdown in Deaths statistics",
                changes: [
                    { type: "fix", text: "Fixed deaths modal with bosses. Wasn't displaying some things correctly" },
                    { type: "fix", text: "Fixed Boss KC modal not having an X button" },
                ]
            },
                              {
                version: "v2.4.0",
                date: "2025-01-13",
                title: "Added Boss Breakdown in Deaths statistics",
                changes: [
                    { type: "feature", text: "Added a new Boss breakdown in death statistics which shows deaths per boss" },
                ]
            },
                              {
                version: "v2.3.0",
                date: "2025-01-09",
                title: "Rank History Modal",
                changes: [
                    { type: "feature", text: "Added new Rank History modal that tracks progress and ranks overtime" },
                ]
            },
                             {
                version: "v2.2.1",
                date: "2025-01-07",
                title: "Fixed NPC Urls in name",
                changes: [
                    { type: "fix", text: "Fixed NPC Urls in name" },
                ]
            },
                            {
                version: "v2.2.1",
                date: "2025-01-06",
                title: "Expanded chart filters not working",
                changes: [
                    { type: "fix", text: "Expanded chart filters not working" },
                ]
            },
                            {
                version: "v2.2.0",
                date: "2025-01-06",
                title: "Added expandable charts",
                changes: [
                    { type: "feature", text: "Added expandable charts (Click on a chart to expand)" },
                    { type: "feature", text: "Added filtes to the expandable charts" },
                ]
            },
                           {
                version: "v2.1.0",
                date: "2025-01-06",
                title: "Added new effort tab with Boss/Player view",
                changes: [
                    { type: "feature", text: "Added new effort tab with Boss/Player view" },
                    { type: "fix", text: "Fixed view all boss modal opening underneath BossKC modal" },
                ]
            },
                           {
                version: "v2.0.2",
                date: "2025-01-05",
                title: "Modal change to BossKC",
                changes: [
                    { type: "improvement", text: "Updated view all BossKC modal. No longer an alert." },
                ]
            },
                           {
                version: "v2.0.1",
                date: "2025-01-05",
                title: "Lots of styling changes and fixed BossKC not loading correctly",
                changes: [
                    { type: "improvement", text: "Updated some styling across the site" },
                    { type: "fix", text: "BossKC Modal wouldn't always load without switching tabs. Should be fixed" },
                ]
            },
                          {
                version: "v2.0.0",
                date: "2025-01-05",
                title: "Highscore scraping and more styling improvements",
                changes: [
                    { type: "feature", text: "Added highscores which pulls overall highscore and scrapes for prestige highscore" },
                    { type: "improvement", text: "Improved BossKC modal styling to match others" },
                ]
            },
                          {
                version: "v1.9.2",
                date: "2025-01-04",
                title: "Clan highscore widget improvements",
                changes: [
                    { type: "improvement", text: "Improved clan highscore widget" },
                ]
            },
                          {
                version: "v1.9.1",
                date: "2025-01-04",
                title: "Clan highscore widget and styling",
                changes: [
                    { type: "feature", text: "Added a new clan highscore widget" },
                    { type: "improvement", text: "Improved styling on the Boss KC modal" },
                ]
            },
                          {
                version: "v1.9.0",
                date: "2025-01-02",
                title: "Fixed bot hosting and tile finding logic",
                changes: [
                    { type: "fix", text: "Hopefully fixed weird discord bot rate limit issue" },
                    { type: "fix", text: "Fixed death display with URLs" },
                    { type: "fix", text: "Fixed death display incase no NPC" },
                    { type: "fix", text: "Fixed tile finding logic. Shouldn't trigger on part names anymore.." },
                ]
            },
                          {
                version: "v1.8.2",
                date: "2025-01-02",
                title: "Track Collection Log and Loot Drop Separately",
                changes: [
                    { type: "fix", text: "Added some missing functions for boss KC" },
                ]
            },
                          {
                version: "v1.8.1",
                date: "2025-01-02",
                title: "Track Collection Log and Loot Drop Separately",
                changes: [
                    { type: "fix", text: "Fix filters on Analytics" },
                    { type: "fix", text: "Fixed Boss KC Tracking page" },
                ]
            },
                         {
                version: "v1.8.0",
                date: "2025-01-02",
                title: "Track Collection Log and Loot Drop Separately",
                changes: [
                    { type: "feature", text: "Added new Boss Kill Counts section" },
                    { type: "feature", text: "Tracks KC overtime (Start of Bingo -> Current)" },
                    { type: "feature", text: "Calculate Effort (KC Gained)" },
                    { type: "feature", text: "Added a Boss Leaderboard" },
                    { type: "feature", text: "Added player KC comparison" },
                    { type: "feature", text: "Added admin controls to fetch/snapshot KC" }
                ]
            },
                        {
                version: "v1.7.1",
                date: "2025-01-02",
                title: "Track Collection Log and Loot Drop Separately",
                changes: [
                    { type: "fix", text: "Fixed filters on Analytics page" },
                ]
            },
                        {
                version: "v1.7.0",
                date: "2025-01-02",
                title: "Track Collection Log and Loot Drop Separately",
                changes: [
                    { type: "feature", text: "Added new filters into the Analytics page. Similar to History" },
                    { type: "feature", text: "Updated chart code to allow comparison between players with multi-colours" },
                    { type: "feature", text: "Added a small legend to show chart colour assigned to players" }
                ]
            },
                       {
                version: "v1.6.3",
                date: "2025-01-02",
                title: "Track Collection Log and Loot Drop Separately",
                changes: [
                    { type: "fix", text: "Fixed player filters in History. Now filters based on History data and not tile completions" }
                ]
            },
                      {
                version: "v1.6.2",
                date: "2025-01-02",
                title: "Track Collection Log and Loot Drop Separately",
                changes: [
                    { type: "fix", text: "Fixed background import logic for item values" }
                ]
            },
                     {
                version: "v1.6.1",
                date: "2025-01-02",
                title: "Track Collection Log and Loot Drop Separately",
                changes: [
                    { type: "improvement", text: "Fixed import history endpoint for duplicates. It will now add them both as a loot and collection log" }
                ]
            },
                    {
                version: "v1.6.0",
                date: "2025-01-02",
                title: "Track Collection Log and Loot Drop Separately",
                changes: [
                    { type: "feature", text: "Collection Log and Loot Drop entries now tracked separately" },
                    { type: "feature", text: "Loot Drop values always saved - never lost!" },
                    { type: "improvement", text: "Removed deduplication - simpler, more reliable code" }
                ]
            },
                    {
                version: "v1.5.2",
                date: "2025-01-01",
                title: "History Display & Filter Fixes",
                changes: [
                    { type: "fix", text: "Fixed item names appearing twice in drop history" },
                    { type: "fix", text: "Fixed drop type filter not working (now properly filters Loot vs Collection Log)" }
                ]
            },
                    {
                version: "v1.5.1",
                date: "2025-01-01",
                title: "Collection Log Detection Fix",
                changes: [
                    { type: "fix", text: "Fixed Collection Log drops now properly detected and labeled" },
                    { type: "improvement", text: "Added Collection Log badge in history for easy identification" },
                ]
            },
                    {
                version: "v1.5.0",
                date: "2025-01-01",
                title: "Drop Value Tracking & Advanced History Filters",
                changes: [
                    { type: "feature", text: "Added drop value tracking - all loot drops now record their GP value" },
                    { type: "feature", text: "Advanced value filters in history modal (>100k, <1m, ranges, etc.)" },
                    { type: "feature", text: "Formatted value display in history (2.95M gp, 150K gp, etc.)" },
                    { type: "feature", text: "Item name search filter for history" },
                    { type: "improvement", text: "Discord bot now sends item values when recording drops" },
                    { type: "improvement", text: "History reimport now includes values from Dink messages" }
                ]
            },
                    {
                version: "v1.4.4",
                date: "2024-12-31",
                title: "Require-All Items Clarity Update",
                changes: [
                    { type: "fix", text: "Bugfix to fix the previous changelog" },
                    { type: "improvement", text: "Changed Deadliest Bosses to Deadliest NPCs" },
                ]
            },
            {
                version: "v1.4.3",
                date: "2024-12-31",
                title: "Require-All Items Clarity Update",
                changes: [
                    { type: "improvement", text: "Updated board display: tiles requiring all items now show '3 items to complete' instead of '3 items can complete'" },
                    { type: "improvement", text: "Updated tile info modal: clearly indicates if all items are required vs. any item" },
                    { type: "improvement", text: "Improved user clarity for multi-item tile requirements" }
                ]
            },
            {
                version: "v1.4.2",
                date: "2024-12-31",
                title: "Death Tracking & UI Improvements",
                changes: [
                    { type: "fix", text: "Removed modal close button at the bottom. Only X is now visible" },
                ]
            },
            {
                version: "v1.4.1",
                date: "2024-12-31",
                title: "Death Tracking & UI Improvements",
                changes: [
                    { type: "fix", text: "Modal close button now actually inside the modal" },
                ]
            },
            {
                version: "v1.4.0",
                date: "2024-12-31",
                title: "Death Tracking & UI Improvements",
                changes: [
                    { type: "feature", text: "Updated death tracking with player rankings" },
                    { type: "feature", text: "Deadliest bosses leaderboard with last victim tracking" },
                    { type: "feature", text: "Exact nemesis death counts" },
                    { type: "improvement", text: "Moved close buttons to top right with X icon" },
                    { type: "improvement", text: "Replaced alert popups with themed tile info modals" },
                    { type: "feature", text: "Added wiki links for items in tile info" },
                    { type: "feature", text: "Added changelog to track all updates" }
                ]
            },
            {
                version: "v1.3.0",
                date: "2024-12-30",
                title: "MongoDB Integration & History Import",
                changes: [
                    { type: "feature", text: "Discord history import with automatic deduplication" },
                    { type: "feature", text: "Analytics dashboard with drop trends" },
                    { type: "feature", text: "Collection Log support" },
                    { type: "feature", text: "Personalized player views with favorites" },
                    { type: "fix", text: "Fixed Collection Log item detection" }
                ]
            },
            {
                version: "v1.2.0",
                date: "2024-12-30",
                title: "Line Bonuses & Multi-Item Tiles",
                changes: [
                    { type: "feature", text: "Configurable line bonuses (rows, columns, diagonals)" },
                    { type: "feature", text: "Multi-item tile support (any item can complete tile)" },
                    { type: "feature", text: "Bonus overlay toggle to visualize completed lines" },
                    { type: "improvement", text: "Leaderboard now shows line completion bonuses" }
                ]
            },
            {
                version: "v1.1.0",
                date: "2024-12-30",
                title: "Initial Release",
                changes: [
                    { type: "feature", text: "Core bingo board functionality" },
                    { type: "feature", text: "Discord bot integration with Dink plugin" },
                    { type: "feature", text: "Admin panel for board configuration" },
                    { type: "feature", text: "Real-time drop tracking" },
                    { type: "feature", text: "Leaderboard with player scores" }
                ]
            }
        ];

        function openChangelogModal() {
            const changelogHtml = changelogData.map(entry => {
                const changesHtml = entry.changes.map(change => {
                    const badgeClass = `badge-${change.type}`;
                    const typeLabel = change.type.charAt(0).toUpperCase() + change.type.slice(1);
                    return `<li><span class="changelog-type-badge ${badgeClass}">${typeLabel}</span>${change.text}</li>`;
                }).join('');

                return `
                    <div class="changelog-entry">
                        <div class="changelog-date">
                            📅 ${entry.date}
                            <span class="changelog-version">${entry.version}</span>
                        </div>
                        <div class="changelog-title">${entry.title}</div>
                        <ul class="changelog-changes">
                            ${changesHtml}
                        </ul>
                    </div>
                `;
            }).join('');

            const modalHtml = `
                <div class="modal" id="changelogModal">
                    <div class="modal-content" style="max-width: 800px; max-height: 90vh; overflow-y: auto;">
                        <button class="close-btn" onclick="closeChangelogModal()">×</button>
                        <h2>📜 Changelog</h2>
                        <p style="color: #666; margin-bottom: 20px;">Recent updates and improvements to the OSRS Bingo Board</p>
                        ${changelogHtml}
                    </div>
                </div>
            `;

            // Remove existing modal if present
            const existingModal = document.getElementById('changelogModal');
            if (existingModal) {
                existingModal.remove();
            }

            // Add modal to body
            document.body.insertAdjacentHTML('beforeend', modalHtml);

            // Show modal
            document.getElementById('changelogModal').classList.add('active');
        }

        function closeChangelogModal() {
            const modal = document.getElementById('changelogModal');
            if (modal) {
                modal.classList.remove('active');
                setTimeout(() => modal.remove(), 300);
            }
        }

        function addCloseButtonsToModals() {
            const modals = [
                { id: 'loginModal', closeFunc: 'closeLoginModal()' },
                { id: 'manualOverrideModal', closeFunc: 'closeManualOverrideModal()' },
                { id: 'boardSizeModal', closeFunc: 'closeBoardSizeModal()' },
                { id: 'editModal', closeFunc: 'closeModal()' },
                { id: 'bonusModal', closeFunc: 'closeBonusModal()' },
                { id: 'historyModal', closeFunc: 'closeHistoryModal()' },
                { id: 'analyticsModal', closeFunc: 'closeAnalyticsModal()' },
                { id: 'deathsModal', closeFunc: 'closeDeathsModal()' },
                { id: 'apiModal', closeFunc: 'closeApiModal()' }
            ];

            modals.forEach(modal => {
                const modalEl = document.getElementById(modal.id);
                if (modalEl) {
                    const modalContent = modalEl.querySelector('.modal-content');
                    if (modalContent) {
                        // Check if close button already exists
                        if (!modalContent.querySelector('.close-btn')) {
                            const closeBtn = document.createElement('button');
                            closeBtn.className = 'close-btn';
                            closeBtn.innerHTML = '×';
                            closeBtn.setAttribute('onclick', modal.closeFunc);
                            modalContent.insertBefore(closeBtn, modalContent.firstChild);
                        }
                    }
                }
            });
        }


        // ============================================
        // GIM HIGHSCORE
        // ============================================

        async function loadGroupHighscore() {
            try {
                // Check localStorage cache first
                const cacheKey = 'gim_highscore_cache';
                const cached = localStorage.getItem(cacheKey);

                if (cached) {
                    const data = JSON.parse(cached);
                    const cacheAge = Date.now() - data.timestamp;
                    const oneHour = 60 * 60 * 1000;

                    // If cache is less than 1 hour old, use it
                    if (cacheAge < oneHour) {
                        console.log(`✅ Using cached GIM data (${Math.round(cacheAge / 60000)} minutes old)`);
                        displayGimData(data);
                        return;
                    } else {
                        console.log('⏰ Cache expired, fetching new data...');
                    }
                } else {
                    console.log('📥 No cache found, fetching data for first time...');
                }

                // Show loading state
                document.getElementById('groupName').textContent = 'Unsociables';
                document.getElementById('groupRank').textContent = 'Overall: Fetching...';
                document.getElementById('groupPrestige').textContent = 'Prestige: Fetching...';
                document.getElementById('groupXP').textContent = 'Total XP: Please wait 2-3 min...';

                console.log('🛡️ Fetching GIM highscore via CORS proxy (this will take 2-3 minutes)...');

                const groupName = 'unsociables';
                const proxyUrl = 'https://corsproxy.io/?';
                const baseUrl = 'https://secure.runescape.com/m=hiscore_oldschool_ironman/group-ironman/?groupSize=5&page=';

                let overallRank = null;
                let totalXp = null;
                let prestigeCount = 0;
                let found = false;

                // Search through pages (max 150)
                for (let page = 1; page <= 150; page++) {
                    if (found) break;

                    const url = proxyUrl + encodeURIComponent(baseUrl + page);

                    try {
                        console.log(`📄 Fetching page ${page}...`);

                        const response = await fetch(url);

                        if (!response.ok) {
                            console.error(`Page ${page} returned ${response.status}`);

                            // If we get blocked, stop trying
                            if (response.status === 403) {
                                console.error('❌ Blocked by Cloudflare - stopping');
                                throw new Error('Blocked by Cloudflare');
                            }
                            continue;
                        }

                        const html = await response.text();

                        // Parse the HTML
                        const parser = new DOMParser();
                        const doc = parser.parseFromString(html, 'text/html');

                        // Find tbody
                        const tbody = doc.querySelector('tbody');
                        if (!tbody) {
                            console.warn(`No tbody on page ${page}`);
                            continue;
                        }

                        const rows = tbody.querySelectorAll('tr');

                        for (const row of rows) {
                            const cells = row.querySelectorAll('td');
                            if (cells.length < 4) continue;

                            // Cell 0: Rank
                            const rankText = cells[0].textContent.trim().replace(',', '');
                            const rank = parseInt(rankText);
                            if (isNaN(rank)) continue;

                            // Cell 1: Group name
                            const nameCell = cells[1];
                            const hasStar = nameCell.querySelector('img') !== null;
                            const cleanName = nameCell.textContent.trim().toLowerCase();

                            // Cell 3: XP
                            const xpText = cells[3].textContent.trim().replace(/,/g, '');
                            const xp = parseInt(xpText);

                            // Check if this is our group
                            if (cleanName.includes(groupName)) {
                                console.log(`✅ FOUND: ${cleanName} at rank #${rank}`);

                                overallRank = rank;
                                totalXp = xp;
                                found = true;

                                if (hasStar) {
                                    prestigeCount += 1;
                                    console.log(`⭐ Group has PRESTIGE!`);
                                } else {
                                    console.log(`❌ Group does NOT have prestige`);
                                }

                                break;
                            }

                            // Count prestige groups before us
                            if (hasStar && !found) {
                                prestigeCount++;
                            }
                        }

                        // Progress indicator every 10 pages
                        if (page % 10 === 0 && !found) {
                            console.log(`💤 Scanned ${page * 20} groups, found ${prestigeCount} prestige groups...`);
                        }

                        // Longer delay to avoid rate limiting (1-2 seconds)
                        if (!found) {
                            await new Promise(resolve => setTimeout(resolve, 1000 + Math.random() * 1000));
                        }

                    } catch (error) {
                        console.error(`Error fetching page ${page}:`, error);

                        // If it's a network/blocking error, stop trying
                        if (error.message.includes('Blocked')) {
                            throw error;
                        }
                        continue;
                    }
                }

                if (!found) {
                    throw new Error('Group not found in top 3000');
                }

                const prestigeRank = prestigeCount > 0 ? prestigeCount : null;

                console.log('📊 RESULTS:');
                console.log(`   Overall: #${overallRank.toLocaleString()}`);
                if (prestigeRank) {
                    console.log(`   Prestige: #${prestigeRank.toLocaleString()} ⭐`);
                }
                console.log(`   XP: ${totalXp.toLocaleString()}`);

                // Cache the results
                const cacheData = {
                    overallRank,
                    prestigeRank,
                    totalXp,
                    timestamp: Date.now()
                };

                localStorage.setItem(cacheKey, JSON.stringify(cacheData));
                console.log('💾 Cached data for 1 hour');

                // Display the data
                displayGimData(cacheData);

            } catch (error) {
                console.error('Failed to load GIM highscore:', error);
                document.getElementById('groupName').textContent = 'Unsociables';
                document.getElementById('groupRank').textContent = 'Overall: Error';
                document.getElementById('groupPrestige').textContent = 'Prestige: Error';
                document.getElementById('groupXP').textContent = 'Total XP: Try refresh';
            }
        }

        // Save rank snapshot automatically
        async function saveRankSnapshot(rankData) {
            try {
                // Calculate changes from previous data
                const previousData = localStorage.getItem('previousRankData');
                let changes = { rankChange: 0, prestigeRankChange: 0, xpChange: 0 };

                if (previousData) {
                    const prev = JSON.parse(previousData);
                    changes.rankChange = prev.rank - rankData.rank; // Negative = rank went down (worse)
                    changes.prestigeRankChange = prev.prestigeRank - rankData.prestigeRank;
                    changes.xpChange = rankData.totalXp - prev.totalXp;
                }

                // Save to backend
                await fetch(`${API_URL}/rank/snapshot`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        rank: rankData.rank,
                        prestigeRank: rankData.prestigeRank,
                        totalXp: rankData.totalXp,
                        ...changes
                    })
                });

                // Store current as previous for next time
                localStorage.setItem('previousRankData', JSON.stringify(rankData));

                console.log('📊 Rank snapshot saved');
            } catch (error) {
                console.error('Failed to save rank snapshot:', error);
            }
        }

        function openRankHistoryModal() {
            document.getElementById('rankHistoryModal').classList.add('active');
            loadRankHistory();
        }

        function closeRankHistoryModal() {
            document.getElementById('rankHistoryModal').classList.remove('active');
        }

        async function loadRankHistory() {
            const loadingDiv = document.getElementById('rankHistoryLoading');
            const contentDiv = document.getElementById('rankHistoryContent');

            loadingDiv.style.display = 'block';
            contentDiv.style.display = 'none';

            try {
                const response = await fetch(`${API_URL}/rank/history`);
                const data = await response.json();

                if (!data.success || !data.history || data.history.length === 0) {
                    loadingDiv.innerHTML = '<div style="text-align: center; padding: 60px; color: #8b7355;">No rank history data yet! Data is saved automatically as you use the site.</div>';
                    return;
                }

                const history = data.history.reverse(); // Oldest to newest for chart

                // Show current stats with changes
                const latest = history[history.length - 1];
                const previous = history[history.length - 2];

                document.getElementById('currentRank').textContent = latest.rank.toLocaleString();
                document.getElementById('currentPrestige').textContent = latest.prestigeRank.toLocaleString();
                document.getElementById('currentXP').textContent = formatXp(latest.totalXp);

                if (previous) {
                    const rankDiff = previous.rank - latest.rank;
                    const prestigeDiff = previous.prestigeRank - latest.prestigeRank;
                    const xpDiff = latest.totalXp - previous.totalXp;

                    document.getElementById('rankChange').innerHTML = rankDiff > 0
                        ? `<span style="color: #4CAF50;">⬆ +${rankDiff} (improved)</span>`
                        : rankDiff < 0
                        ? `<span style="color: #8B0000;">⬇ ${rankDiff} (dropped)</span>`
                        : '<span style="color: #8b7355;">No change</span>';

                    document.getElementById('prestigeChange').innerHTML = prestigeDiff > 0
                        ? `<span style="color: #4CAF50;">⬆ +${prestigeDiff}</span>`
                        : prestigeDiff < 0
                        ? `<span style="color: #8B0000;">⬇ ${prestigeDiff}</span>`
                        : '<span style="color: #8b7355;">No change</span>';

                    document.getElementById('xpChange').innerHTML = xpDiff > 0
                        ? `<span style="color: #4CAF50;">+${formatXp(xpDiff)}</span>`
                        : '<span style="color: #8b7355;">No change</span>';
                }

                // Render chart
                renderRankHistoryChart(history);

                // Render table
                renderRankHistoryTable(history.slice().reverse()); // Newest first for table

                loadingDiv.style.display = 'none';
                contentDiv.style.display = 'block';

            } catch (error) {
                console.error('Failed to load rank history:', error);
                loadingDiv.innerHTML = '<div style="text-align: center; padding: 60px; color: #8B0000;">❌ Failed to load rank history</div>';
            }
        }

        function renderRankHistoryChart(history) {
            const ctx = document.getElementById('rankHistoryChart').getContext('2d');

            // Destroy existing chart if it exists
            if (window.rankHistoryChartInstance) {
                window.rankHistoryChartInstance.destroy();
            }

            window.rankHistoryChartInstance = new Chart(ctx, {
                type: 'line',
                data: {
                    labels: history.map(h => new Date(h.timestamp).toLocaleDateString()),
                    datasets: [
                        {
                            label: 'Overall Rank',
                            data: history.map(h => h.rank),
                            borderColor: '#cd8b2d',
                            backgroundColor: 'rgba(205, 139, 45, 0.1)',
                            yAxisID: 'y',
                            tension: 0.3
                        },
                        {
                            label: 'Prestige Rank',
                            data: history.map(h => h.prestigeRank),
                            borderColor: '#c4614b',
                            backgroundColor: 'rgba(255, 215, 0, 0.1)',
                            yAxisID: 'y',
                            tension: 0.3
                        }
                    ]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    interaction: {
                        mode: 'index',
                        intersect: false
                    },
                    plugins: {
                        title: {
                            display: true,
                            text: 'Rank Progression Over Time',
                            color: '#6d5635',
                            font: { size: 16 }
                        },
                        legend: {
                            labels: { color: '#6d5635' }
                        }
                    },
                    scales: {
                        y: {
                            type: 'linear',
                            display: true,
                            position: 'left',
                            reverse: true, // Lower rank = better
                            title: {
                                display: true,
                                text: 'Rank (lower is better)',
                                color: '#6d5635'
                            },
                            ticks: { color: '#6d5635' }
                        },
                        x: {
                            ticks: { color: '#6d5635' }
                        }
                    }
                }
            });
        }

        function renderRankHistoryTable(history) {
            const tbody = document.getElementById('rankHistoryTable');

            let html = '';
            history.forEach((record, index) => {
                const date = new Date(record.timestamp);
                const dateStr = date.toLocaleDateString() + ' ' + date.toLocaleTimeString();

                const nextRecord = history[index + 1]; // Next in array = previous in time

                let changeHtml = '';
                if (nextRecord) {
                    const rankDiff = nextRecord.rank - record.rank;
                    const prestigeDiff = nextRecord.prestigeRank - record.prestigeRank;

                    if (rankDiff !== 0 || prestigeDiff !== 0) {
                        changeHtml = '<div style="font-size: 11px;">';
                        if (rankDiff > 0) changeHtml += `<div style="color: #4CAF50;">Rank: +${rankDiff} ⬆</div>`;
                        if (rankDiff < 0) changeHtml += `<div style="color: #8B0000;">Rank: ${rankDiff} ⬇</div>`;
                        if (prestigeDiff > 0) changeHtml += `<div style="color: #4CAF50;">Prestige: +${prestigeDiff} ⬆</div>`;
                        if (prestigeDiff < 0) changeHtml += `<div style="color: #8B0000;">Prestige: ${prestigeDiff} ⬇</div>`;
                        changeHtml += '</div>';
                    }
                }

                html += `
                    <tr style="border-bottom: 1px solid rgba(205, 139, 45, 0.2);">
                        <td style="padding: 12px; color: #6d5635;">${dateStr}</td>
                        <td style="padding: 12px; text-align: center; color: #cd8b2d; font-weight: bold;">${record.rank.toLocaleString()}</td>
                        <td style="padding: 12px; text-align: center; color: #c4614b; font-weight: bold;">${record.prestigeRank.toLocaleString()}</td>
                        <td style="padding: 12px; text-align: center; color: #6d5635;">${formatXp(record.totalXp)}</td>
                        <td style="padding: 12px; text-align: center;">${changeHtml || '-'}</td>
                    </tr>
                `;
            });

            tbody.innerHTML = html;
        }

        // Format XP
        function formatXp(xp) {
            if (!xp) return null;
            if (xp >= 1_000_000_000) {
                return `${(xp / 1_000_000_000).toFixed(2)}B`;
            } else if (xp >= 1_000_000) {
                return `${(xp / 1_000_000).toFixed(1)}M`;
            } else {
                return xp.toLocaleString();
            }
        }

        function displayGimData(data) {

            document.getElementById('groupName').textContent = 'Unsociables';
            document.getElementById('groupRank').textContent = `Overall: #${data.overallRank.toLocaleString()}`;

            if (data.prestigeRank) {
                document.getElementById('groupPrestige').textContent = `Prestige: #${data.prestigeRank.toLocaleString()} ⭐`;
            } else {
                document.getElementById('groupPrestige').textContent = 'Prestige: Lost';
            }

            document.getElementById('groupXP').textContent = `Total XP: ${formatXp(data.totalXp)}`;

            // Auto-save rank snapshot
            saveRankSnapshot({
                rank: data.overallRank,
                prestigeRank: data.prestigeRank,
                totalXp: data.totalXp
            });
        }

                // Helper functions to create chart configs
        function createDropsOverTimeConfig(drops, players, playerColors) {
            // Extract the config creation logic from updateDropsOverTimeChart
            // Return the config object
            // (You'll need to extract this from your existing chart creation functions)
            return Chart.getChart(document.getElementById('dropsPerDayChart'))?.config || {};
        }

        function createTopItemsConfig(drops, players, playerColors) {
            return Chart.getChart(document.getElementById('topItemsChart'))?.config || {};
        }

        function createDayOfWeekConfig(drops) {
            return Chart.getChart(document.getElementById('dayOfWeekChart'))?.config || {};
        }

        function createHourHeatmapConfig(drops, players, playerColors) {
            return Chart.getChart(document.getElementById('hourHeatmapChart'))?.config || {};
        }

        function createPlayerActivityConfig(drops) {
            return Chart.getChart(document.getElementById('playerActivityChart'))?.config || {};
        }

        function createMonthComparisonConfig(drops) {
            return Chart.getChart(document.getElementById('monthComparisonChart'))?.config || {};
        }

        // ============================================
        // EVENT TIMER SYSTEM
        // ============================================

        let eventTimerInterval = null;

        async function loadEventConfig() {
            try {
                const response = await fetch(`${API_URL}/event/config`);
                const config = await response.json();

                if (config.enabled && config.startDate && config.endDate) {
                    displayEventTimer(config);
                    startEventCountdown(config);
                } else {
                    hideEventTimer();
                }
            } catch (error) {
                console.error('Failed to load event config:', error);
                hideEventTimer();
            }
        }

        function displayEventTimer(config) {
            const widget = document.getElementById('eventTimerWidget');
            const nameEl = document.getElementById('eventName');

            nameEl.textContent = config.eventName || 'Bingo Event';

            widget.classList.add('active'); // Use class instead of inline style
        }

        function hideEventTimer() {
            const widget = document.getElementById('eventTimerWidget');
            widget.classList.remove('active');

            if (eventTimerInterval) {
                clearInterval(eventTimerInterval);
                eventTimerInterval = null;
            }
        }

function startEventCountdown(config) {
            if (eventTimerInterval) {
                clearInterval(eventTimerInterval);
            }

            function updateCountdown() {
                const now = new Date();
                const start = new Date(config.startDate);
                const end = new Date(config.endDate);

                const countdownEl = document.getElementById('eventCountdown');
                const statusEl = document.getElementById('eventStatus');
                const badgeEl = statusEl.closest('.event-timer-status-badge');

                // Check if event hasn't started
                if (now < start) {
                    const timeUntilStart = start - now;
                    countdownEl.textContent = formatTimeRemaining(timeUntilStart);
                    statusEl.textContent = 'Starts In';
                    badgeEl.className = 'event-timer-status-badge status-pending';
                }
                // Check if event is active
                else if (now >= start && now <= end) {
                    const timeRemaining = end - now;

                    if (timeRemaining <= 0) {
                        countdownEl.textContent = '00:00:00';
                        statusEl.textContent = 'Event Ended';
                        badgeEl.className = 'event-timer-status-badge status-ended';
                        clearInterval(eventTimerInterval);
                        return;
                    }

                    countdownEl.textContent = formatTimeRemaining(timeRemaining);
                    statusEl.textContent = 'Event Active';
                    badgeEl.className = 'event-timer-status-badge status-active';
                }
                // Event has ended
                else {
                    countdownEl.textContent = '00:00:00';
                    statusEl.textContent = 'Event Ended';
                    badgeEl.className = 'event-timer-status-badge status-ended';
                    clearInterval(eventTimerInterval);
                }
            }

            updateCountdown();
            eventTimerInterval = setInterval(updateCountdown, 1000);
        }

        function formatTimeRemaining(milliseconds) {
            const totalSeconds = Math.floor(milliseconds / 1000);
            const days = Math.floor(totalSeconds / 86400);
            const hours = Math.floor((totalSeconds % 86400) / 3600);
            const minutes = Math.floor((totalSeconds % 3600) / 60);
            const seconds = totalSeconds % 60;

            if (days > 0) {
                return `${days}d ${hours}h ${minutes}m`;
            } else if (hours > 0) {
                return `${hours}h ${minutes}m ${seconds}s`;
            } else {
                return `${minutes}:${seconds.toString().padStart(2, '0')}`;
            }
        }

        function openEventConfigModal() {
            if (!isAdmin) {
                alert('⛔ Admin access required!');
                return;
            }

            // Load current config
            loadCurrentEventConfig();
            document.getElementById('eventConfigModal').classList.add('active');
        }

        function closeEventConfigModal() {
            document.getElementById('eventConfigModal').classList.remove('active');
        }

        async function loadCurrentEventConfig() {
            try {
                const response = await fetch(`${API_URL}/event/config`);
                const config = await response.json();

                document.getElementById('eventEnabled').checked = config.enabled || false;
                document.getElementById('eventNameInput').value = config.eventName || 'Bingo Event';

                if (config.startDate) {
                    // Convert ISO string to datetime-local format
                    const startDate = new Date(config.startDate);
                    document.getElementById('eventStartDate').value = formatDateForInput(startDate);
                }

                if (config.endDate) {
                    const endDate = new Date(config.endDate);
                    document.getElementById('eventEndDate').value = formatDateForInput(endDate);
                }

                toggleEventFields();
            } catch (error) {
                console.error('Failed to load event config:', error);
            }
        }

        function formatDateForInput(date) {
            const year = date.getFullYear();
            const month = String(date.getMonth() + 1).padStart(2, '0');
            const day = String(date.getDate()).padStart(2, '0');
            const hours = String(date.getHours()).padStart(2, '0');
            const minutes = String(date.getMinutes()).padStart(2, '0');
            return `${year}-${month}-${day}T${hours}:${minutes}`;
        }

        function toggleEventFields() {
            const enabled = document.getElementById('eventEnabled').checked;
            document.getElementById('eventFields').style.display = enabled ? 'block' : 'none';
        }

        async function saveEventConfig() {
            const password = sessionStorage.getItem('adminPassword');
            if (!password) {
                alert('Session expired. Please log in again.');
                return;
            }

            const enabled = document.getElementById('eventEnabled').checked;
            const eventName = document.getElementById('eventNameInput').value.trim();
            const startDateInput = document.getElementById('eventStartDate');
            const endDateInput = document.getElementById('eventEndDate');

            // Get the actual values
            const startDate = startDateInput ? startDateInput.value : '';
            const endDate = endDateInput ? endDateInput.value : '';

            console.log('Event Config Debug:');
            console.log('Enabled:', enabled);
            console.log('Event Name:', eventName);
            console.log('Start Date:', startDate);
            console.log('End Date:', endDate);

            if (enabled) {
                // Only validate if event is enabled
                if (!eventName) {
                    alert('Please enter an event name!');
                    return;
                }

                if (!startDate || startDate === '') {
                    alert('Please set a start date!');
                    return;
                }

                if (!endDate || endDate === '') {
                    alert('Please set an end date!');
                    return;
                }

                // Validate dates
                const start = new Date(startDate);
                const end = new Date(endDate);

                console.log('Parsed Start:', start);
                console.log('Parsed End:', end);

                if (isNaN(start.getTime())) {
                    alert('Invalid start date!');
                    return;
                }

                if (isNaN(end.getTime())) {
                    alert('Invalid end date!');
                    return;
                }

                if (end <= start) {
                    alert('End date must be after start date!');
                    return;
                }
            }

            try {
                const payload = {
                    password: password,
                    enabled: enabled,
                    eventName: eventName || 'Bingo Event',
                    startDate: startDate ? new Date(startDate).toISOString() : null,
                    endDate: endDate ? new Date(endDate).toISOString() : null
                };

                console.log('Sending payload:', payload);

                const response = await fetch(`${API_URL}/event/config`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(payload)
                });

                const result = await response.json();
                console.log('Server response:', result);

                if (response.ok && result.success) {
                    alert('✅ Event configuration saved!');
                    closeEventConfigModal();
                    loadEventConfig(); // Reload timer
                } else {
                    alert(`❌ ${result.error || result.message || 'Failed to save configuration'}`);
                }
            } catch (error) {
                console.error('Save event config error:', error);
                alert('❌ Could not connect to server: ' + error.message);
            }
        }

        // Load event config on page load
        loadEventConfig();


        // Load on page load
        loadGroupHighscore();

        // Auto-refresh every 1 hour (to match cache expiry)
        setInterval(loadGroupHighscore, 60 * 60 * 1000);


        // Run this when the page loads
        document.addEventListener('DOMContentLoaded', function() {
            addCloseButtonsToModals();
        });

        (async () => {
            await initBoard();
            loadEventConfig(); // Load and display event timer
        })();