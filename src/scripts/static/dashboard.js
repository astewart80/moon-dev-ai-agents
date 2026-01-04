        let currentSettings = {};
        let analysisReports = {};

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

                    const pnl = data.account.unrealized_pnl || 0;
                    const pnlEl = document.getElementById('unrealized-pnl');
                    pnlEl.textContent = (pnl >= 0 ? '+$' : '-$') + Math.abs(pnl).toFixed(2);
                    pnlEl.className = 'stat-value ' + (pnl >= 0 ? 'positive' : 'negative');

                    // 24h P/L
                    const pnl24h = data.account.pnl_24h;
                    const pnl24hEl = document.getElementById('pnl-24h');
                    const pnl24hLabel = document.getElementById('pnl-24h-label');
                    const hours24h = data.account.hours_24h || 0;

                    if (pnl24h !== null && pnl24h !== undefined) {
                        const pct = data.account.pnl_24h_pct || 0;
                        pnl24hEl.textContent = (pnl24h >= 0 ? '+' : '') + '$' + pnl24h.toFixed(2) + ' (' + (pnl24h >= 0 ? '+' : '') + pct.toFixed(1) + '%)';
                        pnl24hEl.style.color = pnl24h >= 0 ? 'var(--profit)' : 'var(--loss)';
                        // Update label to show actual period
                        if (hours24h >= 24) {
                            pnl24hLabel.textContent = '24h P/L';
                        } else {
                            pnl24hLabel.textContent = Math.round(hours24h) + 'h P/L';
                        }
                    } else {
                        pnl24hEl.textContent = 'Collecting...';
                        pnl24hEl.style.color = 'var(--text-muted)';
                        pnl24hLabel.textContent = '24h P/L';
                    }

                    // 7d P/L
                    const pnl7d = data.account.pnl_7d;
                    const pnl7dEl = document.getElementById('pnl-7d');
                    const pnl7dLabel = document.getElementById('pnl-7d-label');
                    const hours7d = data.account.hours_7d || 0;

                    if (pnl7d !== null && pnl7d !== undefined) {
                        const pct = data.account.pnl_7d_pct || 0;
                        pnl7dEl.textContent = (pnl7d >= 0 ? '+' : '') + '$' + pnl7d.toFixed(2) + ' (' + (pnl7d >= 0 ? '+' : '') + pct.toFixed(1) + '%)';
                        pnl7dEl.style.color = pnl7d >= 0 ? 'var(--profit)' : 'var(--loss)';
                        // Update label to show actual period
                        if (hours7d >= 168) {
                            pnl7dLabel.textContent = '7D P/L';
                        } else if (hours7d >= 24) {
                            pnl7dLabel.textContent = Math.round(hours7d / 24) + 'D P/L';
                        } else {
                            pnl7dLabel.textContent = Math.round(hours7d) + 'h P/L';
                        }
                    } else {
                        pnl7dEl.textContent = 'Collecting...';
                        pnl7dEl.style.color = 'var(--text-muted)';
                        pnl7dLabel.textContent = '7D P/L';
                    }

                    // Positions
                    const posContainer = document.getElementById('positions-container');
                    const fills = data.fills || [];
                    if (data.account.positions && data.account.positions.length > 0) {
                        posContainer.innerHTML = data.account.positions.map(pos => {
                            const isLong = pos.side.toLowerCase() === 'long';
                            const pnlClass = pos.pnl_percent >= 0 ? 'positive' : 'negative';
                            // Calculate TP/SL prices (TP +12%, SL -5%)
                            const tpPrice = isLong ? pos.entry_price * 1.12 : pos.entry_price * 0.88;
                            const slPrice = isLong ? pos.entry_price * 0.95 : pos.entry_price * 1.05;
                            // Get fills for this symbol
                            const symbolFills = fills.filter(f => f.symbol === pos.symbol);
                            const fillsHtml = symbolFills.length > 0 ? symbolFills.map(f => {
                                const fillTime = new Date(f.timestamp).toLocaleString('en-US', {month:'short', day:'numeric', hour:'2-digit', minute:'2-digit'});
                                return '<div style="display:flex;justify-content:space-between;padding:4px 8px;background:#0a0a15;border-radius:3px;margin-top:4px;font-size:10px;">' +
                                    '<span style="color:#00d4aa;">' + f.qty.toFixed(5) + ' @ $' + f.price.toLocaleString() + '</span>' +
                                    '<span style="color:#666;">$' + f.value.toFixed(2) + ' - ' + fillTime + '</span>' +
                                '</div>';
                            }).join('') : '';
                            return `
                                <div class="position-card ${isLong ? 'long' : 'short'}">
                                    <div class="position-header">
                                        <span class="position-symbol">
                                            ${pos.symbol}
                                            <span class="position-side ${isLong ? 'long' : 'short'}">${pos.side}</span>
                                        </span>
                                    </div>
                                    <div class="position-stats">
                                        <div class="position-stat">
                                            <span class="position-stat-label">Total Qty (Avg)</span>
                                            <span class="position-stat-value">${Math.abs(pos.size).toFixed(5)} @ $${pos.entry_price.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: pos.entry_price < 10 ? 4 : 2})}</span>
                                        </div>
                                        <div class="position-stat">
                                            <span class="position-stat-label">Value</span>
                                            <span class="position-stat-value">$${(Math.abs(pos.size) * pos.entry_price).toFixed(2)}</span>
                                        </div>
                                        <div class="position-stat">
                                            <span class="position-stat-label" style="color:var(--profit);">TP (+12%)</span>
                                            <span class="position-stat-value" style="color:var(--profit);">$${tpPrice.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: tpPrice < 10 ? 4 : 2})}</span>
                                        </div>
                                        <div class="position-stat">
                                            <span class="position-stat-label" style="color:var(--loss);">SL (-5%)</span>
                                            <span class="position-stat-value" style="color:var(--loss);">$${slPrice.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: slPrice < 10 ? 4 : 2})}</span>
                                        </div>
                                    </div>
                                    ${symbolFills.length > 0 ? '<div style="margin-top:8px;border-top:1px solid #1a1a2e;padding-top:8px;"><span style="font-size:10px;color:#666;">Individual Buys:</span>' + fillsHtml + '</div>' : ''}
                                    <div class="position-pnl">
                                        <span class="position-pnl-value ${pnlClass}">
                                            ${pos.pnl_percent >= 0 ? '+' : ''}${pos.pnl_percent.toFixed(2)}% ($${pos.unrealized_pnl.toFixed(2)})
                                        </span>
                                        <div class="position-buttons">
                                            <button class="btn btn-warning btn-reverse-position" onclick="reversePosition('${pos.symbol}')" title="Reverse position direction">Reverse</button>
                                            <button class="btn btn-danger btn-close-position" onclick="closePosition('${pos.symbol}')" title="Close position">Close</button>
                                        </div>
                                    </div>
                                </div>
                            `;
                        }).join('');
                    } else {
                        posContainer.innerHTML = '<div class="no-positions">No open positions</div>';
                    }
                }

                // Update settings
                if (data.settings && !document.activeElement.className.includes('setting-input')) {
                    currentSettings = data.settings;
                    ['leverage', 'max_position_pct', 'stop_loss', 'take_profit', 'sleep_minutes'].forEach(key => {
                        const input = document.getElementById('setting-' + key);
                        if (input) input.value = data.settings[key] || '';
                    });
                }

                // Update watchlist with all symbols (enabled and disabled)
                if (data.settings && data.settings.all_symbols) {
                    analysisReports = data.analysis_reports || {};
                    const tokenList = document.getElementById('token-list');
                    const allSymbols = data.settings.all_symbols;
                    tokenList.innerHTML = Object.entries(allSymbols).map(([symbol, enabled]) => {
                        const report = analysisReports[symbol] || {};
                        const action = enabled ? (report.action || 'PENDING').toLowerCase() : 'disabled';
                        const confidence = report.confidence || '-';
                        return `
                            <div class="token-item ${enabled ? '' : 'disabled'}">
                                <input type="checkbox" ${enabled ? 'checked' : ''} onchange="toggleSymbol('${symbol}', this.checked)" onclick="event.stopPropagation()">
                                <div class="token-info" onclick="showAnalysis('${symbol}')" style="cursor:pointer;">
                                    <div class="token-icon">${symbol.substring(0, 3)}</div>
                                    <span class="token-name">${symbol}</span>
                                </div>
                                <div class="token-meta" onclick="showAnalysis('${symbol}')" style="cursor:pointer;">
                                    <span class="token-confidence">${enabled ? confidence + '%' : 'OFF'}</span>
                                    <span class="token-signal ${action}">${enabled ? (report.action || 'Pending') : 'Disabled'}</span>
                                </div>
                            </div>
                        `;
                    }).join('');
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
            showStatus('Saving...', '');
            try {
                const settings = ['leverage', 'max_position_pct', 'stop_loss', 'take_profit', 'sleep_minutes'];
                for (const s of settings) {
                    const value = document.getElementById('setting-' + s).value;
                    await fetch('/api/setting/' + s + '/' + value, { method: 'POST' });
                }
                // Save confidence threshold
                const confidence = document.getElementById('setting-min_confidence').value;
                await fetch('/api/confidence/' + confidence, { method: 'POST' });
                showStatus('Settings saved! Min confidence: ' + confidence + '%', 'success');
                await fetch('/api/restart', { method: 'POST' });
                setTimeout(fetchData, 2000);
            } catch (error) {
                showStatus('Error: ' + error.message, 'error');
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

                // Update badge
                const badge = document.getElementById('active-interval-badge');
                if (data.auto_adjust) {
                    badge.textContent = 'AUTO';
                    badge.style.background = '#00aa55';
                } else {
                    badge.textContent = 'MANUAL';
                    badge.style.background = '#ff9800';
                }

                // Update name and details
                document.getElementById('active-interval-name').textContent = data.name || '--';
                document.getElementById('active-interval-details').textContent =
                    `(${data.interval_minutes}min scans, ${data.timeframe} candles)`;

                // Update volatility
                const volDisplay = document.getElementById('volatility-value');
                if (data.volatility !== null && data.auto_adjust) {
                    const volColor = data.volatility_level === 'High' ? '#ff4444' :
                                     data.volatility_level === 'Low' ? '#00aa55' : '#ff9800';
                    volDisplay.innerHTML = `<span style="color:${volColor}">${data.volatility}% ATR (${data.volatility_level})</span>`;
                } else if (!data.auto_adjust) {
                    volDisplay.textContent = 'Auto-adjust disabled';
                } else {
                    volDisplay.textContent = '--';
                }
            } catch (error) {
                console.error('Error loading active interval:', error);
            }
        }

        async function loadGoals() {
            try {
                const response = await fetch('/api/goals');
                const goals = await response.json();
                if (goals.daily_profit_target) document.getElementById('goal-daily_profit').value = goals.daily_profit_target;
                if (goals.weekly_profit_target) document.getElementById('goal-weekly_profit').value = goals.weekly_profit_target;
                if (goals.max_daily_loss) document.getElementById('goal-max_loss').value = goals.max_daily_loss;
                if (goals.target_account_balance) document.getElementById('goal-target_balance').value = goals.target_account_balance;
                if (goals.risk_per_trade_percent) document.getElementById('goal-risk_percent').value = goals.risk_per_trade_percent;
                if (goals.preferred_strategy) document.getElementById('goal-strategy').value = goals.preferred_strategy;
                if (goals.custom_goal) document.getElementById('goal-custom').value = goals.custom_goal;
            } catch (error) {
                console.error('Error loading goals:', error);
            }
        }

        async function saveGoals() {
            showStatus('Saving goals...', '');
            try {
                const goals = {
                    daily_profit_target: parseFloat(document.getElementById('goal-daily_profit').value) || 50,
                    weekly_profit_target: parseFloat(document.getElementById('goal-weekly_profit').value) || 250,
                    max_daily_loss: parseFloat(document.getElementById('goal-max_loss').value) || 30,
                    target_account_balance: parseFloat(document.getElementById('goal-target_balance').value) || 1000,
                    risk_per_trade_percent: parseFloat(document.getElementById('goal-risk_percent').value) || 5,
                    preferred_strategy: document.getElementById('goal-strategy').value || 'conservative',
                    custom_goal: document.getElementById('goal-custom').value || ''
                };
                const response = await fetch('/api/goals', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(goals)
                });
                const result = await response.json();
                if (result.success) {
                    showStatus('Goals saved! AI will consider these when trading.', 'success');
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
                if (data.indicators) {
                    for (const [name, enabled] of Object.entries(data.indicators)) {
                        const checkbox = document.getElementById('ind-' + name);
                        if (checkbox) checkbox.checked = enabled;
                    }
                }
            } catch (error) {
                console.error('Error loading indicators:', error);
            }
        }

        async function closePosition(symbol) {
            if (!confirm('Close ' + symbol + ' position?')) return;
            showStatus('Closing ' + symbol + '...', '');
            try {
                const response = await fetch('/api/close-position/' + symbol, { method: 'POST' });
                const data = await response.json();
                showStatus(data.message, data.success ? 'success' : 'error');
                setTimeout(fetchData, 2000);
            } catch (error) {
                showStatus('Error: ' + error.message, 'error');
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
            el.className = 'command-status visible ' + type;
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
            document.querySelectorAll('.timeframe-btn').forEach(btn => {
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
                document.getElementById('setting-min_confidence').value = value;
                document.getElementById('confidence-value').textContent = value;
            } catch (e) {
                console.error('Error loading confidence:', e);
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

        // Init
        fetchData();
        loadIndicators();
        loadEquityChart();
        loadConfidence();
        loadGoals();
        loadScanSettings();
        loadActiveInterval();
        loadTradeAnalysis();
        loadFearGreed();
        initTradingViewChart();
        setInterval(fetchData, 5000);
        setInterval(loadEquityChart, 60000);  // Refresh chart every minute
        setInterval(loadTradeAnalysis, 10000);  // Refresh trade analysis every 10s
        setInterval(loadFearGreed, 300000);  // Refresh Fear & Greed every 5 minutes
        setInterval(loadActiveInterval, 30000);  // Refresh active interval every 30s

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
