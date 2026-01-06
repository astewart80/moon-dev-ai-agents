        let currentSettings = {};
        let analysisReports = {};
        let recommendations = [];
        let isSaving = false;  // Prevent fetchData from overwriting during save

        // Theme Toggle
        function toggleTheme() {
            const html = document.documentElement;
            const currentTheme = html.getAttribute('data-theme');
            const newTheme = currentTheme === 'light' ? 'dark' : 'light';

            html.setAttribute('data-theme', newTheme);
            localStorage.setItem('theme', newTheme);
            updateThemeIcons(newTheme);
        }

        function updateThemeIcons(theme) {
            const darkIcon = document.getElementById('dark-icon');
            const lightIcon = document.getElementById('light-icon');

            if (theme === 'light') {
                darkIcon.classList.remove('active');
                lightIcon.classList.add('active');
            } else {
                darkIcon.classList.add('active');
                lightIcon.classList.remove('active');
            }
        }

        // Load saved theme on page load
        (function() {
            const savedTheme = localStorage.getItem('theme') || 'dark';
            document.documentElement.setAttribute('data-theme', savedTheme);
            // Icons will be updated after DOM loads
            document.addEventListener('DOMContentLoaded', () => updateThemeIcons(savedTheme));
        })();

        // Update time
        function updateTime() {
            const now = new Date();
            document.getElementById('current-time').textContent = now.toLocaleTimeString('en-US', { hour12: false });
        }
        setInterval(updateTime, 1000);
        updateTime();

        async function fetchData() {
            try {
                const response = await fetch('/api/data');
                const data = await response.json();

                // Update status
                const isRunning = data.bot_status === 'RUNNING';
                const statusDot = document.getElementById('status-dot');
                const statusText = document.getElementById('status-text');

                statusDot.className = 'status-dot ' + (isRunning ? 'running' : 'stopped');
                statusText.textContent = isRunning ? 'Online' : 'Offline';

                // Update account
                if (data.account) {
                    document.getElementById('equity').textContent = '$' + (data.account.equity || 0).toFixed(2);
                    document.getElementById('balance').textContent = '$' + (data.account.balance || 0).toFixed(2);
                    document.getElementById('available').textContent = '$' + (data.account.available_margin || 0).toFixed(2);

                    const pnl = data.account.unrealized_pnl || 0;
                    const pnlEl = document.getElementById('unrealized-pnl-sub');
                    pnlEl.textContent = 'Unrealized: ' + (pnl >= 0 ? '+$' : '-$') + Math.abs(pnl).toFixed(2);
                    pnlEl.style.color = pnl >= 0 ? 'var(--profit)' : 'var(--loss)';

                    // 24h P/L
                    const pnl24h = data.account.pnl_24h;
                    const pnl24hEl = document.getElementById('pnl-24h');
                    const pnl24hLabel = document.getElementById('pnl-24h-label');
                    const hours24h = data.account.hours_24h || 0;

                    // Show 24H P/L with available data
                    if (pnl24h !== null && pnl24h !== undefined) {
                        const pct = data.account.pnl_24h_pct || 0;
                        pnl24hEl.textContent = (pnl24h >= 0 ? '+' : '') + '$' + pnl24h.toFixed(2) + ' (' + (pnl24h >= 0 ? '+' : '') + pct.toFixed(1) + '%)';
                        pnl24hEl.style.color = pnl24h >= 0 ? 'var(--profit)' : 'var(--loss)';
                    } else {
                        pnl24hEl.textContent = 'N/A';
                        pnl24hEl.style.color = 'var(--text-muted)';
                    }
                    pnl24hLabel.textContent = '24H P/L';

                    // 7d P/L
                    const pnl7d = data.account.pnl_7d;
                    const pnl7dEl = document.getElementById('pnl-7d');
                    const pnl7dLabel = document.getElementById('pnl-7d-label');
                    const hours7d = data.account.hours_7d || 0;

                    // Only show 7D P/L if we have at least 7 days (168 hours) of data
                    if (pnl7d !== null && pnl7d !== undefined && hours7d >= 168) {
                        const pct = data.account.pnl_7d_pct || 0;
                        pnl7dEl.textContent = (pnl7d >= 0 ? '+' : '') + '$' + pnl7d.toFixed(2) + ' (' + (pnl7d >= 0 ? '+' : '') + pct.toFixed(1) + '%)';
                        pnl7dEl.style.color = pnl7d >= 0 ? 'var(--profit)' : 'var(--loss)';
                    } else {
                        pnl7dEl.textContent = 'N/A';
                        pnl7dEl.style.color = 'var(--text-muted)';
                    }
                    pnl7dLabel.textContent = '7D P/L';

                    // Positions
                    const posContainer = document.getElementById('positions-container');
                    const fills = data.fills || [];
                    if (data.account.positions && data.account.positions.length > 0) {
                        posContainer.innerHTML = data.account.positions.map(pos => {
                            const isLong = pos.side.toLowerCase() === 'long';
                            const pnlClass = pos.pnl_percent >= 0 ? 'positive' : 'negative';
                            // Use actual TP/SL from HyperLiquid
                            const tpPrice = pos.tp_price;
                            const slPrice = pos.sl_price;
                            const tpPct = pos.tp_pct;
                            const slPct = pos.sl_pct;
                            const formatPrice = (p) => p < 0.01 ? p.toFixed(6) : p < 1 ? p.toFixed(5) : p < 10 ? p.toFixed(4) : p.toFixed(2);
                            const roeClass = pos.roe_percent >= 0 ? 'positive' : 'negative';
                            return `
                                <div class="position-card ${isLong ? 'long' : 'short'}">
                                    <div class="position-top">
                                        <div class="position-symbol">
                                            <div class="position-icon">${pos.symbol.substring(0, 3)}</div>
                                            <span class="position-name">${pos.symbol}</span>
                                            <span class="position-side ${isLong ? 'long' : 'short'}">${pos.side}</span>
                                        </div>
                                        <div class="position-pnl">
                                            <div class="position-pnl-value ${pnlClass}" title="ROE: ${pos.roe_percent >= 0 ? '+' : ''}${pos.roe_percent}%">
                                                ${pos.roe_percent >= 0 ? '+' : ''}${pos.roe_percent}% ROE
                                            </div>
                                            <div class="position-pnl-usd">${pos.unrealized_pnl >= 0 ? '+' : ''}$${pos.unrealized_pnl.toFixed(2)} (${pos.pnl_percent >= 0 ? '+' : ''}${pos.pnl_percent.toFixed(2)}%)</div>
                                        </div>
                                    </div>
                                    <div class="position-details">
                                        <div class="position-detail">
                                            <span class="position-detail-label">${pos.leverage}x</span>
                                        </div>
                                        <div class="position-detail">
                                            <span class="position-detail-label">Entry:</span>
                                            <span class="position-detail-value">$${formatPrice(pos.entry_price)}</span>
                                        </div>
                                        <div class="position-detail">
                                            <span class="position-detail-label">Mark:</span>
                                            <span class="position-detail-value">${pos.mark_price ? '$' + formatPrice(pos.mark_price) : '--'}</span>
                                        </div>
                                        <div class="position-detail">
                                            <span class="position-detail-label">Size:</span>
                                            <span class="position-detail-value">$${(Math.abs(pos.size) * pos.entry_price).toFixed(2)}</span>
                                        </div>
                                        <div class="position-detail">
                                            <span class="position-detail-label">Margin:</span>
                                            <span class="position-detail-value">$${pos.margin_used ? pos.margin_used.toFixed(2) : '--'}</span>
                                        </div>
                                    </div>
                                    <div class="position-details">
                                        <div class="position-detail">
                                            <span class="position-detail-label">Liq${pos.liq_distance ? ' ' + pos.liq_distance + '%' : ''}:</span>
                                            <span class="position-detail-value sl">${pos.liq_price ? '$' + formatPrice(pos.liq_price) : '--'}</span>
                                        </div>
                                        <div class="position-detail">
                                            <span class="position-detail-label">TP${tpPct ? ' +' + tpPct + '%' : ''}:</span>
                                            <span class="position-detail-value tp">${tpPrice ? '$' + formatPrice(tpPrice) : '--'}</span>
                                        </div>
                                        <div class="position-detail">
                                            <span class="position-detail-label">SL${slPct ? ' -' + slPct + '%' : ''}:</span>
                                            <span class="position-detail-value sl">${slPrice ? '$' + formatPrice(slPrice) : '--'}</span>
                                        </div>
                                        <div class="position-detail ${pos.rr_ratio >= 2 ? 'rr-good' : pos.rr_ratio >= 1 ? 'rr-ok' : 'rr-bad'}">
                                            <span class="position-detail-label">R:R</span>
                                            <span class="position-detail-value">${pos.rr_ratio ? pos.rr_ratio + ':1' : '--'}</span>
                                        </div>
                                    </div>
                                    <div class="position-actions">
                                        <button class="btn btn-take-half" onclick="takeHalfProfit('${pos.symbol}')" title="Take 50% Profit" style="background: #ff9800; color: #000;">½</button>
                                        <button class="btn btn-reverse-position" onclick="reversePosition('${pos.symbol}')" title="Reverse">Rev</button>
                                        <button class="btn btn-danger btn-close-position" onclick="closePosition('${pos.symbol}')" title="Close">Close</button>
                                    </div>
                                </div>
                            `;
                        }).join('');
                    } else {
                        posContainer.innerHTML = '<div class="no-positions">No open positions</div>';
                    }
                }

                // Update settings (skip if saving or user is editing)
                if (data.settings && !isSaving && !document.activeElement.className.includes('setting-input')) {
                    currentSettings = data.settings;
                    ['leverage', 'max_position_pct', 'stop_loss', 'take_profit', 'sleep_minutes'].forEach(key => {
                        const input = document.getElementById('setting-' + key);
                        if (input) input.value = data.settings[key] || '';
                    });
                }

                // Fetch recommendations and update watchlist
                try {
                    const recsResponse = await fetch('/api/recommendations');
                    const recsData = await recsResponse.json();
                    recommendations = recsData.recommendations || [];
                    analysisReports = data.analysis_reports || {};

                    // Update goal progress display
                    if (recsData.goals) {
                        const goals = recsData.goals;
                        const progressPct = Math.min(150, Math.max(-50, goals.daily_progress_pct));
                        const barWidth = progressPct >= 0 ? Math.min(100, progressPct) : Math.abs(progressPct);

                        const goalBar = document.getElementById('goal-bar');
                        const goalCurrent = document.getElementById('goal-current');
                        const goalTarget = document.getElementById('goal-target');
                        const tradingMode = document.getElementById('trading-mode');

                        goalBar.style.width = barWidth + '%';
                        goalBar.className = 'goal-bar' + (progressPct >= 100 ? ' exceeded' : progressPct < 0 ? ' negative' : '');

                        const effectivePnl = goals.daily_pnl_effective;
                        goalCurrent.textContent = (effectivePnl >= 0 ? '+$' : '-$') + Math.abs(effectivePnl).toFixed(0);
                        goalCurrent.className = effectivePnl >= 0 ? 'profit' : 'loss';
                        goalTarget.textContent = `/ $${goals.daily_target} daily (${progressPct.toFixed(0)}%)`;

                        tradingMode.textContent = goals.trading_mode;
                        tradingMode.className = 'trading-mode ' + goals.trading_mode.toLowerCase();
                    }

                    const tokenList = document.getElementById('token-list');
                    const allSymbols = data.settings?.all_symbols || {};

                    // Create a map of recommendations by symbol
                    const recsMap = {};
                    recommendations.forEach(rec => { recsMap[rec.symbol] = rec; });

                    // Build watchlist: show all configured symbols
                    const watchlistHtml = Object.entries(allSymbols)
                        .filter(([symbol, enabled]) => enabled)
                        .map(([symbol, enabled]) => {
                            const rec = recsMap[symbol];
                            const report = analysisReports[symbol] || {};

                            if (rec) {
                                // Has position - show recommendations data
                                const action = (rec.action || 'HOLD').toLowerCase();
                                const signalClass = action.includes('buy') || action.includes('profit') ? 'buy' :
                                                   action.includes('sell') || action.includes('close') || action.includes('stop') ? 'sell' : 'nothing';
                                const pnlClass = rec.pnl_pct >= 0 ? 'profit' : 'loss';
                                return `
                                    <div class="watchlist-item has-position" onclick="showAnalysis('${rec.symbol}')">
                                        <div class="watchlist-left">
                                            <div class="watchlist-icon">${rec.symbol.substring(0, 3)}</div>
                                            <div class="watchlist-info">
                                                <span class="watchlist-name">${rec.symbol}</span>
                                                <span class="watchlist-meta">${rec.tf_confluence || '-'} · RSI ${rec.rsi_1h?.toFixed(0) || '-'}</span>
                                            </div>
                                        </div>
                                        <div class="watchlist-right">
                                            <div class="watchlist-pnl ${pnlClass}">${rec.pnl_pct >= 0 ? '+' : ''}${rec.pnl_pct?.toFixed(1) || '0'}%</div>
                                            <span class="watchlist-signal ${signalClass}">${rec.action || 'HOLD'}</span>
                                        </div>
                                    </div>
                                `;
                            } else {
                                // No position - show analysis report data
                                const action = (report.action || 'SCAN').toLowerCase();
                                const confidence = report.confidence || '-';
                                const signalClass = action === 'buy' ? 'buy' : action === 'sell' ? 'sell' : 'nothing';
                                return `
                                    <div class="watchlist-item no-position" onclick="showAnalysis('${symbol}')">
                                        <div class="watchlist-left">
                                            <div class="watchlist-icon">${symbol.substring(0, 3)}</div>
                                            <div class="watchlist-info">
                                                <span class="watchlist-name">${symbol}</span>
                                                <span class="watchlist-meta">No position</span>
                                            </div>
                                        </div>
                                        <div class="watchlist-right">
                                            <span class="watchlist-confidence">${confidence}%</span>
                                            <span class="watchlist-signal ${signalClass}">${report.action || 'SCAN'}</span>
                                        </div>
                                    </div>
                                `;
                            }
                        }).join('');

                    tokenList.innerHTML = watchlistHtml || '<div class="no-positions">No symbols configured</div>';
                } catch (e) {
                    console.error('Error fetching recommendations:', e);
                }

                // Update logs - only auto-scroll if user is at bottom
                const logEl = document.querySelector('.logs-content');
                const wasAtBottom = logEl.scrollHeight - logEl.scrollTop <= logEl.clientHeight + 50;
                document.getElementById('log-content').textContent = data.logs.join('');
                if (wasAtBottom) {
                    logEl.scrollTop = logEl.scrollHeight;
                }

            } catch (error) {
                console.error('Fetch error:', error);
            }
        }

        function scrollLogsToBottom() {
            const logEl = document.querySelector('.logs-content');
            logEl.scrollTop = logEl.scrollHeight;
        }

        async function sendCommand(command) {
            showStatus('Processing...', '');
            try {
                const response = await fetch('/api/' + command, { method: 'POST' });
                const data = await response.json();
                showStatus(data.message, data.success ? 'success' : 'error');
                setTimeout(fetchData, 1000);
            } catch (error) {
                showStatus('Error: ' + error.message, 'error');
            }
        }

        async function saveSettings() {
            isSaving = true;
            showStatus('Saving...', '');
            try {
                // Read all values upfront to prevent race condition with fetchData
                const settingsToSave = {};
                ['leverage', 'max_position_pct', 'stop_loss', 'take_profit', 'sleep_minutes'].forEach(s => {
                    settingsToSave[s] = document.getElementById('setting-' + s).value;
                });
                const confidence = document.getElementById('setting-min_confidence').value;

                // Now save them
                for (const [s, value] of Object.entries(settingsToSave)) {
                    await fetch('/api/setting/' + s + '/' + value, { method: 'POST' });
                }
                await fetch('/api/confidence/' + confidence, { method: 'POST' });

                // Save auto TP/SL settings
                await saveAutoTpsl();

                showStatus('Settings saved! Min confidence: ' + confidence + '%', 'success');
                await fetch('/api/restart', { method: 'POST' });
                setTimeout(() => { isSaving = false; fetchData(); }, 2000);
            } catch (error) {
                showStatus('Error: ' + error.message, 'error');
                isSaving = false;
            }
        }

        async function saveScanSettings() {
            showStatus('Saving scan settings...', '');
            try {
                const preset = document.getElementById('scan-preset').value;
                const autoAdjust = document.getElementById('auto-adjust').checked;
                const response = await fetch('/api/scan-settings', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({preset: preset, auto_adjust: autoAdjust})
                });
                const data = await response.json();
                showStatus(data.message, data.success ? 'success' : 'error');
            } catch (error) {
                showStatus('Error: ' + error.message, 'error');
            }
        }

        async function loadScanSettings() {
            try {
                const response = await fetch('/api/scan-settings');
                const settings = await response.json();
                if (settings.preset) document.getElementById('scan-preset').value = settings.preset;
                if (settings.auto_adjust !== undefined) document.getElementById('auto-adjust').checked = settings.auto_adjust;
            } catch (error) {
                console.error('Error loading scan settings:', error);
            }
        }

        async function loadActiveInterval() {
            try {
                const response = await fetch('/api/active-interval');
                const data = await response.json();

                // Update badge (safe element access)
                const badge = document.getElementById('active-interval-badge');
                if (badge) {
                    if (data.auto_adjust) {
                        badge.textContent = 'AUTO';
                        badge.style.background = 'var(--profit)';
                    } else {
                        badge.textContent = 'MANUAL';
                        badge.style.background = 'var(--warning)';
                    }
                }

                // Update name and details
                const nameEl = document.getElementById('active-interval-name');
                const detailsEl = document.getElementById('active-interval-details');
                if (nameEl) nameEl.textContent = data.name || '--';
                if (detailsEl) detailsEl.textContent = `${data.interval_minutes}min scans`;

            } catch (error) {
                console.error('Error loading active interval:', error);
            }
        }

        async function loadGoals() {
            try {
                const response = await fetch('/api/goals');
                const goals = await response.json();
                const setVal = (id, val) => { const el = document.getElementById(id); if (el && val) el.value = val; };

                setVal('goal-daily_profit', goals.daily_profit_target);
                setVal('goal-weekly_profit', goals.weekly_profit_target);
                setVal('goal-max_loss', goals.max_daily_loss);
                setVal('goal-target_balance', goals.target_account_balance);
            } catch (error) {
                console.error('Error loading goals:', error);
            }
        }

        async function saveGoals() {
            showStatus('Saving goals...', '');
            try {
                const getVal = (id, def) => { const el = document.getElementById(id); return el ? (parseFloat(el.value) || def) : def; };

                const goals = {
                    daily_profit_target: getVal('goal-daily_profit', 50),
                    weekly_profit_target: getVal('goal-weekly_profit', 250),
                    max_daily_loss: getVal('goal-max_loss', 30),
                    target_account_balance: getVal('goal-target_balance', 1000)
                };
                const response = await fetch('/api/goals', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(goals)
                });
                const result = await response.json();
                if (result.success) {
                    showStatus('Goals saved!', 'success');
                } else {
                    showStatus('Error: ' + result.message, 'error');
                }
            } catch (error) {
                showStatus('Error: ' + error.message, 'error');
            }
        }

        async function toggleIndicator(name, enabled) {
            try {
                const response = await fetch('/api/indicator/' + name + '/' + enabled, { method: 'POST' });
                const data = await response.json();
                showStatus(data.message, data.success ? 'success' : 'error');
            } catch (error) {
                showStatus('Error: ' + error.message, 'error');
            }
        }

        async function toggleSymbol(symbol, enabled) {
            try {
                const response = await fetch('/api/symbol/' + symbol + '/' + enabled, { method: 'POST' });
                const data = await response.json();
                showStatus(data.message, data.success ? 'success' : 'error');
                setTimeout(fetchData, 500);  // Refresh to show updated state
            } catch (error) {
                showStatus('Error: ' + error.message, 'error');
            }
        }

        async function loadIndicators() {
            try {
                const response = await fetch('/api/indicators');
                const data = await response.json();
                const container = document.getElementById('indicators-container');

                if (data.indicators && container) {
                    // Define indicator impacts
                    const impacts = {
                        'mtf_analysis': 'high',
                        'rsi_obv_divergence': 'high',
                        'swing_sr': 'high',
                        'atr_volatility': 'medium',
                        'market_regime': 'medium',
                        'rsi': 'medium',
                        'macd': 'medium',
                        'ema': 'low',
                        'sma': 'low',
                        'volume': 'low'
                    };

                    container.innerHTML = Object.entries(data.indicators).map(([name, enabled]) => {
                        const impact = impacts[name] || 'low';
                        const displayName = name.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
                        return `
                            <div class="indicator-item" onclick="toggleIndicator('${name}', !document.getElementById('ind-${name}').checked); document.getElementById('ind-${name}').checked = !document.getElementById('ind-${name}').checked;">
                                <input type="checkbox" id="ind-${name}" ${enabled ? 'checked' : ''} onclick="event.stopPropagation(); toggleIndicator('${name}', this.checked);">
                                <span>${displayName}</span>
                                <span class="indicator-impact ${impact}">${impact.toUpperCase()}</span>
                            </div>
                        `;
                    }).join('');
                }
            } catch (error) {
                console.error('Error loading indicators:', error);
            }
        }

        async function manualClose() {
            const symbol = document.getElementById('manual-symbol').value;
            const percent = parseInt(document.getElementById('manual-close-pct').value);

            if (!confirm(`Close ${percent}% of ${symbol} position?`)) return;

            showStatus(`⚡ Closing ${percent}% of ${symbol}...`, 'warning');
            const startTime = Date.now();

            try {
                const response = await fetch('/api/fast-close', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ symbol: symbol, percent: percent })
                });
                const data = await response.json();
                const elapsed = ((Date.now() - startTime) / 1000).toFixed(1);

                if (data.success) {
                    showStatus(`✅ ${data.message}`, 'success');
                } else {
                    showStatus(`❌ ${data.message} (${elapsed}s)`, 'error');
                }
                setTimeout(fetchData, 1000);
            } catch (error) {
                showStatus('❌ Error: ' + error.message, 'error');
            }
        }

        async function takeHalfProfit(symbol) {
            showStatus(`⚡ Taking 50% profit on ${symbol}...`, 'warning');
            const startTime = Date.now();

            try {
                const response = await fetch('/api/fast-close', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ symbol: symbol, percent: 50 })
                });
                const data = await response.json();
                const elapsed = ((Date.now() - startTime) / 1000).toFixed(1);

                if (data.success) {
                    showStatus(`✅ ${data.message}`, 'success');
                } else {
                    showStatus(`❌ ${data.message} (${elapsed}s)`, 'error');
                }
                setTimeout(fetchData, 1000);
            } catch (error) {
                showStatus('❌ Error: ' + error.message, 'error');
            }
        }

        async function closePosition(symbol) {
            if (!confirm('Close ' + symbol + ' position immediately?')) return;

            // Disable all close buttons to prevent multiple clicks
            const closeButtons = document.querySelectorAll('.btn-close-position');
            closeButtons.forEach(btn => {
                btn.disabled = true;
                if (btn.onclick && btn.onclick.toString().includes(symbol)) {
                    btn.textContent = 'CLOSING...';
                    btn.style.background = '#ff9800';
                }
            });

            showStatus('⚡ CLOSING ' + symbol + ' NOW...', 'warning');
            const startTime = Date.now();

            try {
                const response = await fetch('/api/fast-close', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ symbol: symbol, percent: 100 })
                });
                const data = await response.json();
                const elapsed = ((Date.now() - startTime) / 1000).toFixed(1);

                if (data.success) {
                    showStatus('✅ ' + data.message, 'success');
                    fetchData();
                } else {
                    showStatus('❌ ' + data.message + ' (' + elapsed + 's)', 'error');
                }
            } catch (error) {
                showStatus('❌ Error: ' + error.message, 'error');
            } finally {
                // Re-enable buttons after short delay
                setTimeout(() => {
                    closeButtons.forEach(btn => {
                        btn.disabled = false;
                        btn.textContent = 'Close';
                        btn.style.background = '';
                    });
                    fetchData();
                }, 1000);
            }
        }

        async function reversePosition(symbol) {
            if (!confirm('Reverse ' + symbol + ' position? This will close current position and open opposite direction.')) return;
            showStatus('Reversing ' + symbol + '...', '');
            try {
                const response = await fetch('/api/reverse-position/' + symbol, { method: 'POST' });
                const data = await response.json();
                showStatus(data.message, data.success ? 'success' : 'error');
                setTimeout(fetchData, 3000);
            } catch (error) {
                showStatus('Error: ' + error.message, 'error');
            }
        }

        async function setAllTpSl() {
            showStatus('Setting TP/SL for all positions...', '');
            try {
                const response = await fetch('/api/set-all-tpsl', { method: 'POST' });
                const data = await response.json();
                showStatus(data.message, data.success ? 'success' : 'error');
            } catch (error) {
                showStatus('Error: ' + error.message, 'error');
            }
        }

        async function cancelDuplicateOrders() {
            showStatus('Cancelling duplicate orders...', '');
            try {
                const response = await fetch('/api/cancel-duplicate-orders', { method: 'POST' });
                const data = await response.json();
                showStatus(data.message, data.success ? 'success' : 'error');
                setTimeout(fetchData, 2000);
            } catch (error) {
                showStatus('Error: ' + error.message, 'error');
            }
        }

        async function cancelAllOrders() {
            if (!confirm('Cancel ALL open orders (TP/SL)? This cannot be undone.')) return;
            showStatus('Cancelling all orders...', '');
            try {
                const response = await fetch('/api/cancel-all-orders', { method: 'POST' });
                const data = await response.json();
                showStatus(data.message, data.success ? 'success' : 'error');
                setTimeout(fetchData, 2000);
            } catch (error) {
                showStatus('Error: ' + error.message, 'error');
            }
        }

        async function forceBuy() {
            const symbol = prompt('Enter symbol to buy (e.g., BTC, ETH, SOL):', 'BTC');
            if (!symbol) return;
            if (!confirm('Force buy ' + symbol.toUpperCase() + ' with 25% of account?')) return;
            showStatus('Buying ' + symbol.toUpperCase() + '...', '');
            try {
                const response = await fetch('/api/force-buy/' + symbol.toUpperCase(), { method: 'POST' });
                const data = await response.json();
                showStatus(data.message, data.success ? 'success' : 'error');
                setTimeout(fetchData, 2000);
            } catch (error) {
                showStatus('Error: ' + error.message, 'error');
            }
        }

        async function manualBuy(side) {
            const symbol = document.getElementById('manual-symbol').value;
            const size = parseFloat(document.getElementById('manual-size').value) || 50;
            const leverage = parseInt(document.getElementById('manual-leverage').value) || 5;

            const sideText = side === 'long' ? 'LONG' : 'SHORT';
            if (!confirm(`Open ${sideText} position?\n\nSymbol: ${symbol}\nSize: $${size}\nLeverage: ${leverage}x`)) return;

            showStatus(`⚡ Opening ${sideText} ${symbol}...`, '');
            const startTime = Date.now();
            try {
                const response = await fetch('/api/fast-trade', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        symbol: symbol,
                        side: side,
                        size_usd: size,
                        leverage: leverage
                    })
                });
                const data = await response.json();
                const elapsed = ((Date.now() - startTime) / 1000).toFixed(1);
                if (data.success) {
                    showStatus(`✅ ${data.message}`, 'success');
                } else {
                    showStatus(`❌ ${data.message} (${elapsed}s)`, 'error');
                }
                setTimeout(fetchData, 1000);
            } catch (error) {
                showStatus('❌ Error: ' + error.message, 'error');
            }
        }

        function showAnalysis(symbol) {
            const modal = document.getElementById('modal-overlay');
            document.getElementById('modal-title').textContent = symbol + ' Analysis';
            const report = analysisReports[symbol];
            document.getElementById('modal-body').textContent = report && report.analysis
                ? report.analysis
                : 'No analysis available. Run analysis to generate report.';
            modal.classList.add('active');
        }

        function closeModal(event) {
            if (!event || event.target.id === 'modal-overlay') {
                document.getElementById('modal-overlay').classList.remove('active');
            }
        }

        function showStatus(message, type) {
            const el = document.getElementById('command-status');
            el.textContent = message;
            el.className = 'toast visible ' + type;
            setTimeout(() => el.classList.remove('visible'), 3000);
        }

        document.addEventListener('keydown', e => { if (e.key === 'Escape') closeModal(); });

        // Backtest function
        async function runBacktest() {
            const modal = document.getElementById('modal-overlay');
            document.getElementById('modal-title').textContent = 'Backtest Results';
            document.getElementById('modal-body').innerHTML = `
                <div class="backtest-loading">
                    <div class="spinner"></div>
                    <div>Running backtest simulation...</div>
                    <div style="font-size: 10px; margin-top: 8px; color: var(--text-muted);">This may take 30-60 seconds</div>
                </div>
            `;
            modal.classList.add('active');

            try {
                const response = await fetch('/api/run-backtest', { method: 'POST' });
                const data = await response.json();

                if (data.error) {
                    document.getElementById('modal-body').innerHTML = `
                        <div style="color: var(--loss); text-align: center; padding: 20px;">
                            <div style="font-size: 24px; margin-bottom: 12px;">Error</div>
                            <div>${data.error}</div>
                        </div>
                    `;
                    return;
                }

                const summary = data.summary || {};
                const reasons = data.close_reasons || {};
                const roiClass = summary.roi_pct >= 0 ? 'positive' : 'negative';
                const pnlClass = summary.total_pnl >= 0 ? 'positive' : 'negative';

                document.getElementById('modal-body').innerHTML = `
                    <div class="backtest-results">
                        <div class="backtest-grid">
                            <div class="backtest-big-stat">
                                <div class="backtest-big-value ${roiClass}">${summary.roi_pct >= 0 ? '+' : ''}${(summary.roi_pct || 0).toFixed(2)}%</div>
                                <div class="backtest-big-label">Return on Investment</div>
                            </div>
                            <div class="backtest-big-stat">
                                <div class="backtest-big-value ${pnlClass}">${summary.total_pnl >= 0 ? '+' : ''}$${(summary.total_pnl || 0).toFixed(2)}</div>
                                <div class="backtest-big-label">Total P/L</div>
                            </div>
                        </div>

                        <div class="backtest-section">
                            <h3>Performance Summary</h3>
                            <div class="backtest-grid">
                                <div class="backtest-stat">
                                    <span class="backtest-stat-label">Initial Balance</span>
                                    <span class="backtest-stat-value">$${(summary.initial_balance || 0).toFixed(2)}</span>
                                </div>
                                <div class="backtest-stat">
                                    <span class="backtest-stat-label">Final Balance</span>
                                    <span class="backtest-stat-value ${pnlClass}">$${(summary.final_balance || 0).toFixed(2)}</span>
                                </div>
                                <div class="backtest-stat">
                                    <span class="backtest-stat-label">Max Drawdown</span>
                                    <span class="backtest-stat-value negative">${(summary.max_drawdown_pct || 0).toFixed(2)}%</span>
                                </div>
                                <div class="backtest-stat">
                                    <span class="backtest-stat-label">Profit Factor</span>
                                    <span class="backtest-stat-value">${(summary.profit_factor || 0).toFixed(2)}</span>
                                </div>
                            </div>
                        </div>

                        <div class="backtest-section">
                            <h3>Trade Statistics</h3>
                            <div class="backtest-grid">
                                <div class="backtest-stat">
                                    <span class="backtest-stat-label">Total Trades</span>
                                    <span class="backtest-stat-value">${summary.total_trades || 0}</span>
                                </div>
                                <div class="backtest-stat">
                                    <span class="backtest-stat-label">Win Rate</span>
                                    <span class="backtest-stat-value">${(summary.win_rate || 0).toFixed(1)}%</span>
                                </div>
                                <div class="backtest-stat">
                                    <span class="backtest-stat-label">Winning Trades</span>
                                    <span class="backtest-stat-value positive">${summary.winning_trades || 0}</span>
                                </div>
                                <div class="backtest-stat">
                                    <span class="backtest-stat-label">Losing Trades</span>
                                    <span class="backtest-stat-value negative">${summary.losing_trades || 0}</span>
                                </div>
                                <div class="backtest-stat">
                                    <span class="backtest-stat-label">Avg Win</span>
                                    <span class="backtest-stat-value positive">$${(summary.avg_win || 0).toFixed(2)}</span>
                                </div>
                                <div class="backtest-stat">
                                    <span class="backtest-stat-label">Avg Loss</span>
                                    <span class="backtest-stat-value negative">$${(summary.avg_loss || 0).toFixed(2)}</span>
                                </div>
                            </div>
                        </div>

                        <div class="backtest-section">
                            <h3>Close Reasons</h3>
                            <div class="backtest-reasons">
                                ${Object.entries(reasons).map(([reason, count]) => `
                                    <div class="backtest-reason">
                                        <span>${reason.replace(/_/g, ' ')}</span>
                                        <span class="backtest-reason-count">${count}</span>
                                    </div>
                                `).join('')}
                            </div>
                        </div>

                        <div style="text-align: center; font-size: 10px; color: var(--text-muted); margin-top: 8px;">
                            Backtest uses simplified signal simulation (RSI/MACD/SMA). Live trading uses Grok AI analysis.
                        </div>
                    </div>
                `;
            } catch (error) {
                document.getElementById('modal-body').innerHTML = `
                    <div style="color: var(--loss); text-align: center; padding: 20px;">
                        <div style="font-size: 24px; margin-bottom: 12px;">Error</div>
                        <div>${error.message}</div>
                    </div>
                `;
            }
        }

        // Equity Chart
        let equityChart = null;
        let selectedTimeframeHours = 168; // Default 7 days
        let allEquityData = []; // Store all data

        function setChartTimeframe(hours) {
            selectedTimeframeHours = hours;

            // Update active button
            document.querySelectorAll('.chart-tab[data-hours]').forEach(btn => {
                btn.classList.remove('active');
                if (parseInt(btn.dataset.hours) === hours) {
                    btn.classList.add('active');
                }
            });

            // Reload chart with new timeframe
            renderEquityChart();
        }

        function renderEquityChart() {
            if (!allEquityData || allEquityData.length === 0) {
                return;
            }

            const ctx = document.getElementById('equity-chart').getContext('2d');
            const now = new Date();
            const cutoffTime = new Date(now.getTime() - (selectedTimeframeHours * 60 * 60 * 1000));

            // Filter data by selected timeframe
            const filteredData = allEquityData.filter(point => new Date(point.x) >= cutoffTime);

            if (filteredData.length === 0) {
                // If no data in range, show all data
                filteredData.push(...allEquityData);
            }

            // Calculate chart colors based on performance
            const firstValue = filteredData[0].y;
            const lastValue = filteredData[filteredData.length - 1].y;
            const isProfit = lastValue >= firstValue;
            const lineColor = isProfit ? '#00ff88' : '#ff3366';
            const fillColor = isProfit ? 'rgba(0, 255, 136, 0.1)' : 'rgba(255, 51, 102, 0.1)';

            // Format data for Chart.js
            const chartData = filteredData.map(point => ({
                x: new Date(point.x),
                y: point.y
            }));

            // Determine time unit based on range
            let timeUnit = 'hour';
            let displayFormat = 'MMM d, HH:mm';
            if (selectedTimeframeHours <= 1) {
                timeUnit = 'minute';
                displayFormat = 'HH:mm';
            } else if (selectedTimeframeHours <= 24) {
                timeUnit = 'hour';
                displayFormat = 'HH:mm';
            } else if (selectedTimeframeHours <= 168) {
                timeUnit = 'hour';
                displayFormat = 'MMM d, HH:mm';
            } else if (selectedTimeframeHours <= 720) {
                timeUnit = 'day';
                displayFormat = 'MMM d';
            } else {
                timeUnit = 'week';
                displayFormat = 'MMM d';
            }

            // Destroy existing chart
            if (equityChart) {
                equityChart.destroy();
            }

            equityChart = new Chart(ctx, {
                type: 'line',
                data: {
                    datasets: [{
                        label: 'Equity',
                        data: chartData,
                        borderColor: lineColor,
                        backgroundColor: fillColor,
                        borderWidth: 2,
                        fill: true,
                        tension: 0.3,
                        pointRadius: 0,
                        pointHoverRadius: 4,
                        pointHoverBackgroundColor: lineColor
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    interaction: {
                        intersect: false,
                        mode: 'index'
                    },
                    plugins: {
                        legend: {
                            display: false
                        },
                        tooltip: {
                            backgroundColor: '#0d0d18',
                            borderColor: '#1a1a2e',
                            borderWidth: 1,
                            titleColor: '#e8e8ed',
                            bodyColor: '#00f5ff',
                            titleFont: { family: 'JetBrains Mono' },
                            bodyFont: { family: 'JetBrains Mono' },
                            callbacks: {
                                label: function(context) {
                                    return '$' + context.parsed.y.toFixed(2);
                                }
                            }
                        }
                    },
                    scales: {
                        x: {
                            type: 'time',
                            time: {
                                unit: timeUnit,
                                displayFormats: {
                                    minute: 'HH:mm',
                                    hour: displayFormat,
                                    day: 'MMM d',
                                    week: 'MMM d'
                                }
                            },
                            grid: {
                                color: '#1a1a2e',
                                drawBorder: false
                            },
                            ticks: {
                                color: '#6b6b7b',
                                font: { family: 'JetBrains Mono', size: 10 },
                                maxTicksLimit: 6
                            }
                        },
                        y: {
                            grid: {
                                color: '#1a1a2e',
                                drawBorder: false
                            },
                            ticks: {
                                color: '#6b6b7b',
                                font: { family: 'JetBrains Mono', size: 10 },
                                callback: function(value) {
                                    return '$' + value.toFixed(0);
                                }
                            }
                        }
                    }
                }
            });
        }

        async function loadEquityChart() {
            try {
                const response = await fetch('/api/equity-history');
                const data = await response.json();

                if (!data.history || data.history.length === 0) {
                    return;
                }

                // Store all data
                allEquityData = data.history;

                // Render with current timeframe
                renderEquityChart();
            } catch (error) {
                console.error('Error loading equity chart:', error);
            }
        }

        // Load confidence setting from server
        async function loadConfidence() {
            try {
                const response = await fetch('/api/confidence');
                const data = await response.json();
                const value = data.min_confidence || 70;
                const input = document.getElementById('setting-min_confidence');
                if (input) input.value = value;
            } catch (e) {
                console.error('Error loading confidence:', e);
            }
        }

        // Load auto TP/SL settings
        async function loadAutoTpsl() {
            try {
                const response = await fetch('/api/auto-tpsl');
                const data = await response.json();

                // Load ATR settings (safe element access)
                const setVal = (id, val) => { const el = document.getElementById(id); if (el) el.value = val; };
                const setChecked = (id, val) => { const el = document.getElementById(id); if (el) el.checked = val; };

                setChecked('atr-stops-enabled', data.use_atr || false);
                setVal('atr-period', data.atr_period || 14);
                setVal('atr-sl-mult', data.atr_sl_multiplier || 2.0);
                setVal('atr-tp-mult', data.atr_tp_multiplier || 3.0);
                setVal('atr-min-sl', data.atr_min_sl || 1.0);
            } catch (e) {
                console.error('Error loading auto TP/SL settings:', e);
            }
        }

        // Save auto TP/SL settings
        async function saveAutoTpsl() {
            try {
                const getVal = (id, def) => { const el = document.getElementById(id); return el ? (parseFloat(el.value) || def) : def; };
                const getChecked = (id) => { const el = document.getElementById(id); return el ? el.checked : false; };

                const settings = {
                    enabled: true,  // Always enabled
                    // ATR settings
                    use_atr: getChecked('atr-stops-enabled'),
                    atr_period: parseInt(getVal('atr-period', 14)),
                    atr_sl_multiplier: getVal('atr-sl-mult', 2.0),
                    atr_tp_multiplier: getVal('atr-tp-mult', 3.0),
                    atr_min_sl: getVal('atr-min-sl', 1.0)
                };
                const response = await fetch('/api/auto-tpsl', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(settings)
                });
                const result = await response.json();
                if (result.success) {
                    showStatus('ATR settings saved', 'success');
                }
            } catch (e) {
                console.error('Error saving auto TP/SL settings:', e);
                showStatus('Failed to save ATR settings', 'error');
            }
        }

        // Load trade analysis/reasoning
        async function loadTradeAnalysis() {
            try {
                const response = await fetch('/api/trade-analysis');
                const data = await response.json();
                const container = document.getElementById('trade-analysis-container');

                if (data.trades && data.trades.length > 0) {
                    container.innerHTML = data.trades.map(trade => `
                        <div style="margin-bottom:12px;padding:10px;background:#1a1a2e;border-radius:6px;border-left:3px solid ${trade.action === 'BUY' ? '#00d4aa' : '#ff6b6b'};">
                            <div style="display:flex;justify-content:space-between;margin-bottom:6px;">
                                <span style="color:${trade.action === 'BUY' ? '#00d4aa' : '#ff6b6b'};font-weight:bold;">${trade.symbol} ${trade.action}</span>
                                <span style="color:#666;font-size:11px;">${trade.timestamp}</span>
                            </div>
                            <div style="color:#888;font-size:11px;margin-bottom:4px;">Confidence: ${trade.confidence}% | Entry: $${trade.entry_price}</div>
                            <div style="color:#a0a0a0;">${trade.reasoning}</div>
                        </div>
                    `).join('');
                } else {
                    container.innerHTML = '<div class="no-analysis" style="color:#666;">No trades yet. Analysis will appear here when positions are opened.</div>';
                }
            } catch (e) {
                console.error('Error loading trade analysis:', e);
            }
        }

        async function clearTradeAnalysis() {
            try {
                await fetch('/api/trade-analysis/clear', { method: 'POST' });
                loadTradeAnalysis();
                showStatus('Trade analysis cleared', 'success');
            } catch (e) {
                showStatus('Error clearing analysis', 'error');
            }
        }

        // TradingView Chart Functions
        let currentSymbol = 'BINANCE:BTCUSDT';
        let currentInterval = '60';

        function initTradingViewChart() {
            const container = document.getElementById('tradingview-widget');
            container.innerHTML = '';

            new TradingView.widget({
                "autosize": true,
                "symbol": currentSymbol,
                "interval": currentInterval,
                "timezone": "Etc/UTC",
                "theme": "dark",
                "style": "1",
                "locale": "en",
                "toolbar_bg": "#0a0a12",
                "enable_publishing": false,
                "hide_top_toolbar": false,
                "hide_legend": false,
                "save_image": false,
                "container_id": "tradingview-widget",
                "backgroundColor": "#0d0d18",
                "gridColor": "#1a1a2e",
                "hide_side_toolbar": true,
                "allow_symbol_change": false,
                "studies": ["RSI@tv-basicstudies", "MACD@tv-basicstudies"]
            });
        }

        function updateTradingViewChart() {
            currentSymbol = document.getElementById('chart-symbol').value;
            initTradingViewChart();
        }

        function setLiveChartTimeframe(interval) {
            currentInterval = interval;
            // Update button states
            document.querySelectorAll('.live-tf-btn').forEach(btn => {
                btn.classList.remove('active');
                if (btn.dataset.interval === interval) {
                    btn.classList.add('active');
                }
            });
            initTradingViewChart();
        }

        // Fear & Greed Index
        async function loadFearGreed() {
            try {
                const response = await fetch('/api/fear-greed');
                const data = await response.json();
                const valueEl = document.getElementById('fg-value');
                const labelEl = document.getElementById('fg-label');
                const containerEl = document.getElementById('fear-greed');

                if (data.value) {
                    valueEl.textContent = data.value;
                    labelEl.textContent = data.label;

                    // Color based on value
                    let color = 'var(--text-primary)';
                    if (data.value <= 25) {
                        color = 'var(--loss)';  // Extreme Fear - red
                    } else if (data.value <= 45) {
                        color = '#ff8800';  // Fear - orange
                    } else if (data.value <= 55) {
                        color = 'var(--warning)';  // Neutral - yellow
                    } else if (data.value <= 75) {
                        color = '#88cc00';  // Greed - light green
                    } else {
                        color = 'var(--profit)';  // Extreme Greed - green
                    }
                    valueEl.style.color = color;
                }
            } catch (e) {
                console.error('Error loading Fear & Greed:', e);
            }
        }

        // Log Scanner Status
        async function loadScannerStatus() {
            try {
                const response = await fetch('/api/log-scanner-status');
                const data = await response.json();

                const dot = document.getElementById('scanner-dot');
                const text = document.getElementById('scanner-text');
                const badge = document.getElementById('scanner-badge');

                if (data.running) {
                    if (dot) dot.className = 'status-dot running';
                    if (text) text.textContent = 'Scanner';
                    if (badge) badge.title = 'Log Scanner Active - Monitors for missing TP/SL and errors';
                } else {
                    if (dot) dot.className = 'status-dot stopped';
                    if (text) text.textContent = 'Scanner OFF';
                    if (badge) badge.title = 'WARNING: Log Scanner NOT RUNNING!';
                }
            } catch (e) {
                console.error('Error loading scanner status:', e);
            }
        }

        // Daily Drawdown / Circuit Breaker
        async function loadDailyDrawdown() {
            try {
                const response = await fetch('/api/daily-drawdown');
                const data = await response.json();

                const dailyPnlEl = document.getElementById('daily-pnl');
                const dailyLimitEl = document.getElementById('daily-limit');
                const alertEl = document.getElementById('circuit-breaker-alert');
                const alertMsgEl = document.getElementById('circuit-breaker-msg');

                if (data.error) {
                    if (dailyPnlEl) dailyPnlEl.textContent = '--';
                    return;
                }

                // Update Daily P/L display
                const pnl = data.daily_pnl || 0;
                const pnlPct = data.daily_pnl_pct || 0;
                if (dailyPnlEl) {
                    dailyPnlEl.textContent = (pnl >= 0 ? '+' : '') + '$' + pnl.toFixed(2) + ' (' + (pnl >= 0 ? '+' : '') + pnlPct.toFixed(1) + '%)';
                    dailyPnlEl.style.color = pnl >= 0 ? 'var(--profit)' : 'var(--loss)';
                }

                // Update limit display
                if (dailyLimitEl) dailyLimitEl.textContent = '-$' + (data.limit_usd || 50);

                // Update circuit breaker alert
                if (data.circuit_breaker_triggered) {
                    if (alertEl) alertEl.style.display = 'block';
                    if (alertMsgEl) alertMsgEl.textContent = 'Triggered at ' + (data.triggered_at || 'unknown');
                } else {
                    if (alertEl) alertEl.style.display = 'none';
                }

            } catch (e) {
                console.error('Error loading daily drawdown:', e);
            }
        }

        async function resetDrawdown() {
            if (!confirm('Reset daily drawdown circuit breaker?\n\nThis will set current balance as the new starting point for today.')) {
                return;
            }

            try {
                const response = await fetch('/api/daily-drawdown/reset', { method: 'POST' });
                const data = await response.json();

                if (data.success) {
                    showStatus(data.message, 'success');
                    loadDailyDrawdown();  // Refresh display
                } else {
                    showStatus('Reset failed: ' + data.message, 'error');
                }
            } catch (e) {
                showStatus('Reset failed: ' + e.message, 'error');
            }
        }

        // Discord Alerts
        async function loadAlerts() {
            try {
                const response = await fetch('/api/alerts');
                const data = await response.json();

                if (data.error) return;

                document.getElementById('alerts-enabled').checked = data.enabled !== false;
                document.getElementById('discord-webhook').value = data.discord_webhook || '';

                // Load alert type checkboxes
                const alertTypes = data.alert_types || {};
                const typeIds = ['position_opened', 'position_closed', 'stop_loss_hit', 'take_profit_hit',
                                 'trailing_stop_hit', 'drawdown_warning', 'circuit_breaker', 'critical_error'];

                typeIds.forEach(type => {
                    const el = document.getElementById('alert-' + type);
                    if (el) {
                        el.checked = alertTypes[type] !== false;
                    }
                });
            } catch (e) {
                console.error('Error loading alerts:', e);
            }
        }

        async function saveAlerts() {
            try {
                const alertTypes = {};
                const typeIds = ['position_opened', 'position_closed', 'stop_loss_hit', 'take_profit_hit',
                                 'trailing_stop_hit', 'drawdown_warning', 'circuit_breaker', 'critical_error'];

                typeIds.forEach(type => {
                    const el = document.getElementById('alert-' + type);
                    if (el) {
                        alertTypes[type] = el.checked;
                    }
                });

                const settings = {
                    enabled: document.getElementById('alerts-enabled').checked,
                    discord_webhook: document.getElementById('discord-webhook').value.trim(),
                    alert_types: alertTypes
                };

                const response = await fetch('/api/alerts', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(settings)
                });

                const data = await response.json();
                if (data.success) {
                    showStatus('Alert settings saved!', 'success');
                } else {
                    showStatus('Failed to save alerts: ' + (data.error || 'Unknown error'), 'error');
                }
            } catch (e) {
                showStatus('Error saving alerts: ' + e.message, 'error');
            }
        }

        async function testAlert() {
            const webhook = document.getElementById('discord-webhook').value.trim();
            if (!webhook) {
                showStatus('Please enter a Discord webhook URL first', 'error');
                return;
            }

            // Save first to ensure webhook is stored
            await saveAlerts();

            try {
                showStatus('Sending test alert...', 'info');
                const response = await fetch('/api/alerts/test', { method: 'POST' });
                const data = await response.json();

                if (data.success) {
                    showStatus('Test alert sent! Check your Discord channel.', 'success');
                } else {
                    showStatus('Test failed: ' + data.message, 'error');
                }
            } catch (e) {
                showStatus('Error sending test: ' + e.message, 'error');
            }
        }

        // Init
        fetchData();
        loadIndicators();
        loadEquityChart();
        loadConfidence();
        loadAutoTpsl();
        loadGoals();
        loadAlerts();
        loadScanSettings();
        loadActiveInterval();
        loadTradeAnalysis();
        loadFearGreed();
        loadScannerStatus();
        loadDailyDrawdown();
        initTradingViewChart();
        setInterval(fetchData, 5000);
        setInterval(loadEquityChart, 60000);  // Refresh chart every minute
        setInterval(loadTradeAnalysis, 10000);  // Refresh trade analysis every 10s
        setInterval(loadFearGreed, 300000);  // Refresh Fear & Greed every 5 minutes
        setInterval(loadActiveInterval, 30000);  // Refresh active interval every 30s
        setInterval(loadScannerStatus, 30000);  // Check scanner status every 30s
        setInterval(loadDailyDrawdown, 30000);  // Check daily drawdown every 30s

        // Price Ticker
        async function loadPriceTicker() {
            try {
                const response = await fetch('/api/prices');
                const data = await response.json();
                const container = document.getElementById('price-ticker-items');

                if (data.prices) {
                    container.innerHTML = Object.entries(data.prices).map(([symbol, info]) => {
                        const changeClass = info.change >= 0 ? 'positive' : 'negative';
                        const changeSign = info.change >= 0 ? '+' : '';
                        return `
                            <div class="ticker-item">
                                <span class="ticker-symbol">${symbol}</span>
                                <span class="ticker-price">$${info.price.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: info.price < 10 ? 4 : 2})}</span>
                                <span class="ticker-change ${changeClass}">${changeSign}${info.change.toFixed(2)}%</span>
                            </div>
                        `;
                    }).join('');
                }
            } catch (e) {
                console.error('Error loading prices:', e);
            }
        }

        loadPriceTicker();
        setInterval(loadPriceTicker, 5000);  // Update prices every 5 seconds

        // Correlation Exposure
        async function loadCorrelation() {
            try {
                const response = await fetch('/api/correlation');
                const data = await response.json();
                const container = document.getElementById('correlation-groups');
                const status = document.getElementById('correlation-status');

                if (data.error) {
                    status.textContent = 'Error';
                    status.style.color = '#ff4444';
                    return;
                }

                if (!data.enabled) {
                    status.textContent = 'Disabled';
                    status.style.color = '#888';
                    container.innerHTML = '<div style="color:#666;">Correlation sizing disabled</div>';
                    return;
                }

                status.textContent = `${data.reduction_pct}% reduction`;
                status.style.color = '#00aa55';

                if (data.groups && data.groups.length > 0) {
                    container.innerHTML = data.groups.map(g => {
                        const barColor = g.at_limit ? '#ff4444' : (g.exposure_pct > g.max_pct * 0.7 ? '#ffaa00' : '#00aa55');
                        const barWidth = Math.min(100, (g.exposure_pct / g.max_pct) * 100);
                        const symbols = g.positions.map(p => p.symbol).join(', ');
                        return `
                            <div style="margin-bottom:6px;" title="${symbols}: $${g.exposure_usd.toFixed(0)}">
                                <div style="display:flex;justify-content:space-between;margin-bottom:2px;">
                                    <span style="color:#aaa;">${g.group.replace('_', ' ')}</span>
                                    <span style="color:${barColor};">${g.exposure_pct}%/${g.max_pct}%</span>
                                </div>
                                <div style="height:4px;background:#1a1a2e;border-radius:2px;overflow:hidden;">
                                    <div style="height:100%;width:${barWidth}%;background:${barColor};transition:width 0.3s;"></div>
                                </div>
                            </div>
                        `;
                    }).join('');
                } else {
                    container.innerHTML = '<div style="color:#666;">No correlated positions</div>';
                }
            } catch (e) {
                console.error('Error loading correlation:', e);
            }
        }

        loadCorrelation();
        setInterval(loadCorrelation, 30000);  // Update correlation every 30 seconds

        // AI Recommendations (Enhanced v2.0)
        async function loadRecommendations(execute = false) {
            const container = document.getElementById('recommendations-container');
            const status = document.getElementById('recommendations-status');

            container.innerHTML = '<div style="padding: 20px; color: var(--text-muted);">Analyzing positions (multi-TF + funding + fib)...</div>';
            status.textContent = 'Running enhanced analysis...';

            try {
                const url = execute ? '/api/recommendations?execute=true' : '/api/recommendations';
                const response = await fetch(url);
                const data = await response.json();

                if (data.error) {
                    container.innerHTML = `<div style="padding: 20px; color: #ff4444;">Error: ${data.error}</div>`;
                    status.textContent = 'Error';
                    return;
                }

                if (!data.recommendations || data.recommendations.length === 0) {
                    container.innerHTML = '<div style="padding: 20px; color: var(--text-muted);">No open positions to analyze</div>';
                    status.textContent = `Updated: ${new Date(data.timestamp).toLocaleTimeString()}`;
                    return;
                }

                // Render enhanced recommendations
                container.innerHTML = data.recommendations.map(rec => {
                    const actionColors = {
                        'HOLD': '#888',
                        'TAKE_PROFIT_50': '#00cc66',
                        'TAKE_PROFIT_25': '#00aa55',
                        'CLOSE': '#ff4444',
                        'ERROR': '#ff4444'
                    };
                    const actionColor = actionColors[rec.action] || '#888';
                    const pnlColor = rec.pnl_pct >= 0 ? '#00ff88' : '#ff4444';

                    // Confluence colors
                    const tfColors = {
                        'STRONG_BULL': '#00ff88',
                        'BULL': '#00aa55',
                        'MIXED': '#888',
                        'BEAR': '#ff8800',
                        'STRONG_BEAR': '#ff4444'
                    };
                    const tfColor = tfColors[rec.tf_confluence] || '#888';

                    // Trend emoji
                    const trendEmoji = (t) => t === 'BULLISH' ? '🟢' : t === 'BEARISH' ? '🔴' : '⚪';

                    // Funding color
                    const fundingColors = {
                        'LONGS_CROWDED': '#ff4444',
                        'LONGS_PAYING': '#ff8800',
                        'NEUTRAL': '#888',
                        'SHORTS_PAYING': '#00aa55',
                        'SHORTS_CROWDED': '#00ff88'
                    };
                    const fundingColor = fundingColors[rec.funding_signal] || '#888';

                    return `
                        <div style="padding: 12px; border-bottom: 1px solid var(--border);">
                            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                                <span style="font-weight: 600; font-size: 15px;">${rec.symbol}</span>
                                <span style="color: ${actionColor}; font-weight: 600; font-size: 12px; padding: 3px 10px; background: ${actionColor}22; border-radius: 4px;">
                                    ${rec.action.replace(/_/g, ' ')}
                                </span>
                            </div>

                            <div style="display: flex; justify-content: space-between; font-size: 12px; margin-bottom: 6px;">
                                <span>P&L: <span style="color: ${pnlColor}; font-weight: 600;">${rec.pnl_pct >= 0 ? '+' : ''}${rec.pnl_pct}%</span> <span style="color: var(--text-muted);">($${rec.pnl_usd >= 0 ? '+' : ''}${rec.pnl_usd.toFixed(0)})</span></span>
                                <span>Confidence: <b>${rec.confidence}%</b></span>
                            </div>

                            <div style="font-size: 11px; color: var(--text-secondary); margin-bottom: 8px; padding: 6px; background: var(--bg-secondary); border-radius: 4px;">
                                ${rec.reason}
                            </div>

                            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 6px; font-size: 10px;">
                                <div style="color: var(--text-muted);">
                                    <b>Timeframes:</b> ${trendEmoji(rec.tf_1h)}1H ${trendEmoji(rec.tf_4h)}4H ${trendEmoji(rec.tf_1d)}D
                                    <span style="color: ${tfColor}; margin-left: 4px;">[${rec.tf_confluence}]</span>
                                </div>
                                <div style="color: var(--text-muted);">
                                    <b>Funding:</b> <span style="color: ${fundingColor};">${rec.funding_signal}</span>
                                    ${rec.funding_rate ? `(${(rec.funding_rate * 8760).toFixed(0)}%/yr)` : ''}
                                </div>
                            </div>

                            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 6px; font-size: 10px; margin-top: 4px;">
                                <div style="color: var(--text-muted);">
                                    <b>RSI:</b> 1H:${rec.rsi_1h || 'N/A'} 4H:${rec.rsi_4h || 'N/A'} | ADX:${rec.adx || 'N/A'}
                                </div>
                                <div style="color: var(--text-muted);">
                                    <b>Fib:</b> ${rec.fib_signal} ${rec.fib_levels ? `(S:$${rec.fib_levels.support?.toLocaleString()} R:$${rec.fib_levels.resistance?.toLocaleString()})` : ''}
                                </div>
                            </div>
                        </div>
                    `;
                }).join('');

                // Show actions taken if executed
                let statusText = `v2.0 | Updated: ${new Date(data.timestamp).toLocaleTimeString()}`;
                if (data.executed && data.actions_taken && data.actions_taken.length > 0) {
                    statusText += ` | Actions: ${data.actions_taken.join(', ')}`;
                    showToast(data.actions_taken.join(', '), 'success');
                }
                status.textContent = statusText;

            } catch (e) {
                console.error('Error loading recommendations:', e);
                container.innerHTML = `<div style="padding: 20px; color: #ff4444;">Error: ${e.message}</div>`;
                status.textContent = 'Error loading recommendations';
            }
        }

        async function executeRecommendations() {
            if (confirm('Execute all high-confidence (≥70%) recommendations?')) {
                await loadRecommendations(true);
            }
        }

        // Auto-refresh recommendations every 2 minutes
        setInterval(() => loadRecommendations(false), 120000);
