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

        const API_URL = 'https://osrsbingobot.onrender.com';

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
                    ? `<div style="font-size: 11px; color: ${isCompleted ? 'rgba(255,255,255,0.7)' : '#8B6914'}; margin-top: 5px;">(${tile.items.length} items can complete)</div>`
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
            } else {
                // Regular tile - remove multi-item fields if they exist
                delete bingoData.tiles[currentTileIndex].requiredItems;
                delete bingoData.tiles[currentTileIndex].itemProgress;
            }

            closeModal();
            renderBoard();
        }

        function openBoardSizeModal() {
            if (!isAdmin) {
                alert('⛔ Admin access required!');
                return;
            }
            document.getElementById('boardSizeSelect').value = bingoData.boardSize;
            document.getElementById('boardSizeModal').classList.add('active');
        }

        function closeBoardSizeModal() {
            document.getElementById('boardSizeModal').classList.remove('active');
        }

        function changeBoardSize() {
            const newSize = parseInt(document.getElementById('boardSizeSelect').value);

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

        function updateHistoryPlayerFilter() {
            const select = document.getElementById('historyPlayerFilter');
            const currentValue = select.value;

            // Get all unique players
            const allPlayers = new Set();
            bingoData.tiles.forEach(tile => {
                tile.completedBy.forEach(player => allPlayers.add(player));
            });

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

                    const tileInfo = record.tileCompleted && record.tilesInfo && record.tilesInfo.length > 0
                        ? `<div style="margin-top: 5px; padding: 5px; background: rgba(76,175,80,0.2); border-radius: 3px; font-size: 11px;">
                             ✅ Completed Tile ${record.tilesInfo[0].tile}: ${record.tilesInfo[0].items.join(', ')} (+${record.tilesInfo[0].value} points)
                           </div>`
                        : '<div style="margin-top: 5px; font-size: 11px; color: #999;">No tile completed</div>';

                    // Delete button (only for admins)
                    const deleteBtn = isAdmin
                        ? `<button onclick="deleteHistoryEntry('${record.player}', '${record.item}', '${record.timestamp}')"
                                   style="padding: 4px 8px; background: linear-gradient(135deg, #8b1a1a 0%, #660000 100%); color: white; border: 1px solid #4d0000; border-radius: 3px; cursor: pointer; font-size: 10px; font-weight: bold; margin-left: 10px;">
                             🗑️ Delete
                           </button>`
                        : '';

                    html += `
                        <div style="background: white; padding: 12px; border-radius: 5px; margin-bottom: 10px; border-left: 4px solid ${record.tileCompleted ? '#4CAF50' : '#8B6914'};">
                            <div style="display: flex; justify-content: space-between; align-items: start; margin-bottom: 5px;">
                                <div style="flex: 1;">
                                    <strong style="color: #ffcc33; background: #2c1810; padding: 2px 8px; border-radius: 3px; font-size: 13px;">${record.player}</strong>
                                    <span style="color: #2c1810; margin-left: 10px; font-weight: bold;">received</span>
                                    <strong style="color: #cd8b2d; margin-left: 5px;">${record.item}</strong>
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

            } catch (error) {
                console.error('Error loading history:', error);
                contentDiv.innerHTML = '<div style="text-align: center; color: #8b1a1a; padding: 40px;">❌ Failed to load history. Make sure the API is running.</div>';
                countSpan.textContent = '';
            }
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

            loadingDiv.style.display = 'block';
            contentDiv.style.display = 'none';

            try {
                // Fetch all history data
                const response = await fetch(`${API_URL}/history?limit=10000`);
                if (!response.ok) throw new Error('Failed to fetch history');

                const data = await response.json();

                if (!data.history || data.history.length === 0) {
                    loadingDiv.innerHTML = '<div style="text-align: center; padding: 60px; color: #666;">No data available yet!</div>';
                    return;
                }

                // Process data
                const drops = data.history.map(d => ({
                    ...d,
                    timestamp: new Date(d.timestamp)
                }));

                // Generate all analytics
                generateKeyStats(drops);
                generateDropsPerDayChart(drops);
                generateDayOfWeekChart(drops);
                generateHourHeatmap(drops);
                generatePlayerActivityChart(drops);
                generateMonthComparisonChart(drops);
                generateTopItemsChart(drops);

                loadingDiv.style.display = 'none';
                contentDiv.style.display = 'block';

            } catch (error) {
                console.error('Error loading analytics:', error);
                loadingDiv.innerHTML = '<div style="text-align: center; padding: 60px; color: #8b1a1a;">❌ Failed to load analytics</div>';
            }
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
                                nemesisHtml = `<div style="font-size: 12px; color: #8B0000; margin-top: 3px;">
                                    💀 Nemesis: ${nemesisNpc} (${nemesisDeaths} death${nemesisDeaths !== 1 ? 's' : ''})
                                </div>`;
                            }
                        }

                        // Last death NPC
                        let lastNpcHtml = '';
                        if (player.last_npc) {
                            lastNpcHtml = `<div style="font-size: 12px; color: #666; margin-top: 3px;">
                                ⚔️ Last death: ${player.last_npc}${lastDeathText ? ` (${lastDeathText})` : ''}
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
                                            <div style="font-weight: bold; font-size: 16px; color: #2c1810;">${npc.npc}</div>
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
                        <button class="modal-close-btn" onclick="closeTileInfoModal()">×</button>

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
                            ${tile.items.length > 1 ? '<p style="font-size: 12px; color: #666; margin-top: 10px;"><em>Any of these items will complete this tile</em></p>' : ''}
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

        // ============================================
        // CHANGELOG MODAL
        // ============================================

        // Changelog data (update this manually or load from JSON file)
        const changelogData = [
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
                        <button class="modal-close-btn" onclick="closeChangelogModal()">×</button>
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
                        if (!modalContent.querySelector('.modal-close-btn')) {
                            const closeBtn = document.createElement('button');
                            closeBtn.className = 'modal-close-btn';
                            closeBtn.innerHTML = '×';
                            closeBtn.setAttribute('onclick', modal.closeFunc);
                            modalContent.insertBefore(closeBtn, modalContent.firstChild);
                        }
                    }
                }
            });
        }

        // Run this when the page loads
        document.addEventListener('DOMContentLoaded', function() {
            addCloseButtonsToModals();
        });

        // Also run it in initBoard() to make sure it catches dynamically created modals
        // Add this line at the end of your initBoard() function:
        // addCloseButtonsToModals();

        (async () => {
            await initBoard();
        })();