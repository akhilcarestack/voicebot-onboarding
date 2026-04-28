/**
 * Bot Data Validator — App Controller
 * Step-based wizard: Connect → Matrix → Operatories → Validation
 */
document.addEventListener('DOMContentLoaded', () => {

    // ============================
    // STATE
    // ============================
    let currentStep = 1;
    let maxStepReached = 1;

    const appData = {
        locations: [],
        providers: [],        // from /api/fetch-all-data — active providers with specialityId
        productionTypes: [],   // merged: main PT + scheduler PT data (slotLength, providerSpecialities)
        operatories: [],       // filtered to selected locations
        users: [],             // users with ProviderID
        slotDurationMinutes: 5,
    };

    // ============================
    // DOM REFS
    // ============================
    const $ = id => document.getElementById(id);

    const els = {
        // Step 1
        apiBaseUrl: $('apiBaseUrl'),
        apiPassword: $('apiPassword'),
        btnConnect: $('btnConnect'),
        connectStatus: $('connectStatus'),
        locationsCard: $('locationsCard'),
        locationsGrid: $('locationsGrid'),
        locationCount: $('locationCount'),
        btnLoadData: $('btnLoadData'),
        loadStatus: $('loadStatus'),
        // Step 2
        matrixStats: $('matrixStats'),
        matrixWrapper: $('matrixWrapper'),
        matrixBadge: $('matrixBadge'),
        // Step 3
        operatoriesContainer: $('operatoriesContainer'),
        operatoryBadge: $('operatoryBadge'),
        // Step 4
        durationContainer: $('durationContainer'),
        durationBadge: $('durationBadge'),
        validationSummary: $('validationSummary'),
        btnExport: $('btnExport'),
        // Global
        loadingOverlay: $('loadingOverlay'),
        loadingText: $('loadingText'),
    };

    // ============================
    // NAVIGATION (with browser history support)
    // ============================

    /**
     * Navigate to a wizard step. Pushes browser history state so that
     * the back / forward buttons move between steps instead of leaving the page.
     *
     * @param {number}  step           Target step (1-4)
     * @param {object}  [opts]         Options
     * @param {boolean} [opts.replace] If true, replaceState instead of pushState
     * @param {boolean} [opts.fromPop] If true, called from popstate — skip pushState
     */
    window.goToStep = function(step, opts = {}) {
        if (step < 1 || step > 4) return;
        if (step > maxStepReached) return;

        currentStep = step;
        updateStepper();

        // Show/hide panels
        document.querySelectorAll('.step-panel').forEach((panel, i) => {
            panel.classList.toggle('active', i + 1 === step);
        });

        // Sync browser history (skip when this was triggered by popstate)
        if (!opts.fromPop) {
            const historyState = { step, maxStepReached };
            const hash = `#step-${step}`;

            if (opts.replace) {
                history.replaceState(historyState, '', hash);
            } else {
                history.pushState(historyState, '', hash);
            }
        }

        // Keep sessionStorage in sync so restore works on re-render
        saveSession();
    };

    // Handle browser back / forward buttons
    window.addEventListener('popstate', (event) => {
        if (event.state && typeof event.state.step === 'number') {
            // Restore maxStepReached in case the user went back to a
            // state where more steps were already unlocked
            if (event.state.maxStepReached != null) {
                maxStepReached = Math.max(maxStepReached, event.state.maxStepReached);
            }
            goToStep(event.state.step, { fromPop: true });
        } else {
            // No state — fall back to parsing the hash
            const hashStep = getStepFromHash();
            if (hashStep && hashStep <= maxStepReached) {
                goToStep(hashStep, { fromPop: true });
            }
        }
    });

    /** Parse "#step-N" from the URL hash and return N (or null). */
    function getStepFromHash() {
        const match = location.hash.match(/^#step-(\d+)$/);
        return match ? parseInt(match[1], 10) : null;
    }

    function updateStepper() {
        for (let i = 1; i <= 4; i++) {
            const stepEl = $(`stepperStep${i}`);
            const lineEl = i < 4 ? $(`stepperLine${i}`) : null;

            stepEl.classList.remove('active', 'completed', 'disabled');

            if (i < currentStep) {
                stepEl.classList.add('completed');
                if (lineEl) lineEl.classList.add('completed');
            } else if (i === currentStep) {
                stepEl.classList.add('active');
                if (lineEl) lineEl.classList.remove('completed');
            } else if (i <= maxStepReached) {
                // reachable but not current
                if (lineEl) lineEl.classList.remove('completed');
            } else {
                stepEl.classList.add('disabled');
                if (lineEl) lineEl.classList.remove('completed');
            }
        }

        // Click handlers on stepper steps
        document.querySelectorAll('.stepper-step').forEach(el => {
            el.onclick = () => {
                const step = parseInt(el.dataset.step);
                if (step <= maxStepReached) goToStep(step);
            };
        });
    }

    // ============================
    // SESSION PERSISTENCE (sessionStorage)
    // ============================
    const SESSION_KEY = 'bdv_session';

    /** Save current wizard state to sessionStorage. */
    function saveSession() {
        try {
            const session = {
                appData: {
                    locations: appData.locations,
                    providers: appData.providers,
                    productionTypes: appData.productionTypes,
                    operatories: appData.operatories,
                    users: appData.users,
                    slotDurationMinutes: appData.slotDurationMinutes,
                },
                maxStepReached,
                currentStep,
                selectedLocationIds: getSelectedLocationIds(),
                apiBaseUrl: els.apiBaseUrl.value.trim(),
            };
            sessionStorage.setItem(SESSION_KEY, JSON.stringify(session));
        } catch (e) {
            console.warn('Failed to save session:', e);
        }
    }

    /**
     * Restore wizard state from sessionStorage.
     * Returns true if a session was restored, false otherwise.
     */
    function restoreSession() {
        try {
            const raw = sessionStorage.getItem(SESSION_KEY);
            if (!raw) return false;

            const session = JSON.parse(raw);
            if (!session || !session.appData) return false;

            // Restore appData
            Object.assign(appData, session.appData);
            maxStepReached = session.maxStepReached || 1;

            // Restore API URL
            if (session.apiBaseUrl) {
                els.apiBaseUrl.value = session.apiBaseUrl;
            }

            // Restore locations UI
            if (appData.locations.length > 0) {
                renderLocations();

                // Re-check previously selected locations
                if (session.selectedLocationIds && session.selectedLocationIds.length > 0) {
                    session.selectedLocationIds.forEach(id => {
                        const cb = document.querySelector(`.location-cb[value="${id}"]`);
                        if (cb) {
                            cb.checked = true;
                            const item = cb.closest('.location-item');
                            if (item) item.classList.add('selected');
                        }
                    });
                    updateLoadButton();
                }

                showStatus(els.connectStatus, `✅ Connected — ${appData.locations.length} locations found`, 'success');
            }

            // Show logout button since we have an active session
            document.getElementById('btnLogout').classList.remove('hidden');

            // Re-render data views if we had loaded data
            if (maxStepReached > 1 && appData.providers.length > 0) {
                buildAndRenderMatrix();
                renderOperatories();
                renderDurationTable();
                renderValidationSummary();
            }

            // Navigate to the stored step (or the one from the URL hash)
            const hashStep = getStepFromHash();
            const targetStep = (hashStep && hashStep <= maxStepReached) ? hashStep : (session.currentStep || 1);
            goToStep(targetStep, { replace: true });

            return true;
        } catch (e) {
            console.warn('Failed to restore session:', e);
            return false;
        }
    }

    // ============================
    // HELPERS
    // ============================
    function getCreds() {
        const base_url = els.apiBaseUrl.value.trim();
        const password = els.apiPassword.value.trim();
        if (!base_url) {
            showStatus(els.connectStatus, 'Please enter the API URL.', 'error');
            return null;
        }
        return { base_url, password };
    }

    function showStatus(el, msg, type = 'info') {
        el.textContent = msg;
        el.className = `status-bar ${type}`;
    }

    function hideStatus(el) {
        el.className = 'status-bar hidden';
    }

    // --- Loading messages that rotate while waiting ---
    const LOADING_MESSAGES = [
        { text: '🤖 Calling the API...', sub: 'Our robot is dialing in' },
        { text: '📞 On hold with the server...', sub: 'Elevator music playing' },
        { text: '🔍 Fetching provider data...', sub: 'Rummaging through records' },
        { text: '🏥 Loading operatories...', sub: 'Counting dental chairs' },
        { text: '⚡ Processing production types...', sub: 'Almost there...' },
        { text: '🧬 Cross-referencing specialties...', sub: 'Robot is speed-reading' },
        { text: '📊 Crunching the numbers...', sub: 'Beep boop beep' },
        { text: '🚀 Preparing your dashboard...', sub: 'Final touches incoming' },
    ];

    let loadingMsgInterval = null;

    function showLoading(msg = 'Loading...') {
        els.loadingText.textContent = msg;
        const subEl = document.getElementById('loadingSub');
        if (subEl) subEl.textContent = 'This may take a minute';
        els.loadingOverlay.classList.add('active');

        // Start rotating messages after a short initial delay
        let msgIndex = 0;
        clearInterval(loadingMsgInterval);
        loadingMsgInterval = setInterval(() => {
            const m = LOADING_MESSAGES[msgIndex % LOADING_MESSAGES.length];
            els.loadingText.textContent = m.text;
            if (subEl) subEl.textContent = m.sub;
            msgIndex++;
        }, 3000);
    }

    function hideLoading() {
        els.loadingOverlay.classList.remove('active');
        clearInterval(loadingMsgInterval);
        loadingMsgInterval = null;
    }

    function getSelectedLocationIds() {
        return Array.from(document.querySelectorAll('.location-cb:checked'))
            .map(cb => parseInt(cb.value));
    }

    // ============================
    // STEP 1: CONNECT & LOCATIONS
    // ============================

    els.btnConnect.addEventListener('click', async () => {
        const creds = getCreds();
        if (!creds) return;

        els.btnConnect.disabled = true;
        showStatus(els.connectStatus, '⏳ Connecting & fetching locations...', 'info');

        try {
            const res = await fetch('/api/fetch-locations', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(creds),
            });

            if (!res.ok) {
                const err = await res.json();
                throw new Error(err.detail || 'Connection failed');
            }

            const data = await res.json();
            appData.locations = data.locations;

            renderLocations();
            showStatus(els.connectStatus, `✅ Connected — ${data.locations.length} locations found`, 'success');
            saveSession();
            document.getElementById('btnLogout').classList.remove('hidden');
        } catch (err) {
            showStatus(els.connectStatus, `❌ ${err.message}`, 'error');
        } finally {
            els.btnConnect.disabled = false;
        }
    });

    function renderLocations() {
        const locs = appData.locations;
        els.locationsCard.style.display = locs.length > 0 ? 'block' : 'none';
        els.locationCount.textContent = `${locs.length} locations`;

        els.locationsGrid.innerHTML = locs.map(loc => `
            <label class="location-item" id="locItem-${loc.id}">
                <input type="checkbox" class="location-cb" value="${loc.id}"
                       onchange="handleLocationToggle(this)">
                <div class="location-info">
                    <div class="loc-name">${loc.name}</div>
                    <div class="loc-detail">${loc.address} · ${loc.phone}</div>
                </div>
            </label>
        `).join('');

        updateLoadButton();
    }

    window.handleLocationToggle = function(cb) {
        const item = cb.closest('.location-item');
        item.classList.toggle('selected', cb.checked);
        updateLoadButton();
    };

    function updateLoadButton() {
        const count = getSelectedLocationIds().length;
        els.btnLoadData.disabled = count === 0;
        els.btnLoadData.textContent = count > 0
            ? `🚀 Load All Data for ${count} Location${count > 1 ? 's' : ''}`
            : '🚀 Load All Data for Selected Locations';
    }

    // Load All Data
    els.btnLoadData.addEventListener('click', async () => {
        const creds = getCreds();
        if (!creds) return;

        const selectedLocationIds = getSelectedLocationIds();
        if (selectedLocationIds.length === 0) {
            showStatus(els.loadStatus, 'Select at least one location.', 'warning');
            return;
        }

        els.btnLoadData.disabled = true;
        showLoading('Fetching providers, production types, operatories & users...');
        showStatus(els.loadStatus, '⏳ Loading data...', 'info');

        try {
            const res = await fetch('/api/fetch-all-data', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    ...creds,
                    selected_location_ids: selectedLocationIds,
                }),
            });

            if (!res.ok) {
                const err = await res.json();
                throw new Error(err.detail || 'Data fetch failed');
            }

            const data = await res.json();
            appData.providers = data.providers;
            appData.productionTypes = data.production_types;
            appData.operatories = data.operatories;
            appData.users = data.users;
            appData.slotDurationMinutes = data.slot_duration_minutes || 5;

            // Build all views
            buildAndRenderMatrix();
            renderOperatories();
            renderDurationTable();
            renderValidationSummary();

            // Advance to step 2
            maxStepReached = 4;
            goToStep(2);

            // Persist session so browser back/forward can restore data
            saveSession();

            showStatus(els.loadStatus, `✅ Loaded: ${data.providers.length} providers, ${data.production_types.length} PTs, ${data.operatories.length} operatories`, 'success');

        } catch (err) {
            showStatus(els.loadStatus, `❌ ${err.message}`, 'error');
        } finally {
            els.btnLoadData.disabled = false;
            hideLoading();
            updateLoadButton();
        }
    });


    // ============================
    // STEP 2: SPECIALTY MATRIX
    // ============================

    function buildAndRenderMatrix() {
        const providers = appData.providers;
        const pts = appData.productionTypes.filter(pt => pt.isActive);

        if (providers.length === 0 || pts.length === 0) {
            els.matrixWrapper.innerHTML = `
                <div class="empty-state">
                    <div class="empty-icon">📊</div>
                    <div class="empty-text">No data available for matrix</div>
                    <div class="empty-sub">${providers.length} providers, ${pts.length} active production types</div>
                </div>`;
            return;
        }

        let matchCount = 0;
        let mismatchCount = 0;

        // Build matrix data
        const matrix = providers.map(prov => {
            const row = pts.map(pt => {
                const provSpecId = prov.specialityId;
                const ptSpecs = pt.providerSpecialities || [];

                if (!provSpecId || ptSpecs.length === 0) {
                    return { status: 'na', provSpec: provSpecId, ptSpecs };
                }

                const isMatch = ptSpecs.includes(provSpecId);
                if (isMatch) matchCount++;
                else mismatchCount++;

                return { status: isMatch ? 'match' : 'mismatch', provSpec: provSpecId, ptSpecs };
            });
            return { provider: prov, cells: row };
        });

        // Render stats
        els.matrixStats.innerHTML = `
            <div class="stat-card teal">
                <div>
                    <div class="stat-value">${matchCount}</div>
                    <div class="stat-label">Matches</div>
                </div>
            </div>
            <div class="stat-card rose">
                <div>
                    <div class="stat-value">${mismatchCount}</div>
                    <div class="stat-label">Mismatches</div>
                </div>
            </div>
            <div class="stat-card violet">
                <div>
                    <div class="stat-value">${providers.length}</div>
                    <div class="stat-label">Providers</div>
                </div>
            </div>
            <div class="stat-card amber">
                <div>
                    <div class="stat-value">${pts.length}</div>
                    <div class="stat-label">Production Types</div>
                </div>
            </div>
        `;

        els.matrixBadge.textContent = `${matchCount} matches`;

        // Render table
        let html = '<table class="matrix-table">';

        // Header row
        html += '<thead><tr>';
        html += '<th class="corner">Provider</th>';
        pts.forEach(pt => {
            const specLabel = (pt.providerSpecialities || []).join(', ') || '—';
            html += `<th class="col-header" data-tooltip="Spec: ${specLabel}">${pt.name}</th>`;
        });
        html += '</tr></thead>';

        // Body
        html += '<tbody>';
        matrix.forEach(row => {
            html += '<tr>';
            html += `<td class="row-header">
                <div class="provider-name">${row.provider.name}</div>
                <div class="provider-spec">${row.provider.providerType} · Spec #${row.provider.specialityId || '—'}</div>
            </td>`;
            row.cells.forEach(cell => {
                const icon = cell.status === 'match' ? '✓' : cell.status === 'mismatch' ? '✗' : '·';
                const tooltip = cell.status === 'na'
                    ? 'No data'
                    : `Provider spec: ${cell.provSpec}, PT specs: ${cell.ptSpecs.join(', ')}`;
                html += `<td class="matrix-cell ${cell.status}" data-tooltip="${tooltip}">
                    <span class="cell-icon">${icon}</span>
                </td>`;
            });
            html += '</tr>';
        });
        html += '</tbody></table>';

        els.matrixWrapper.innerHTML = html;
    }


    // ============================
    // STEP 3: OPERATORIES
    // ============================

    function renderOperatories() {
        const ops = appData.operatories;
        const locs = appData.locations;
        const selectedIds = getSelectedLocationIds();

        if (ops.length === 0) {
            els.operatoriesContainer.innerHTML = `
                <div class="empty-state">
                    <div class="empty-icon">🏥</div>
                    <div class="empty-text">No operatories found</div>
                </div>`;
            return;
        }

        // Group by location
        const grouped = {};
        ops.forEach(op => {
            const lid = op.locationId;
            if (!grouped[lid]) grouped[lid] = [];
            grouped[lid].push(op);
        });

        // Sort operatories by sortOrder within each group
        Object.values(grouped).forEach(group => {
            group.sort((a, b) => (a.sortOrder || 0) - (b.sortOrder || 0));
        });

        let totalOps = 0;
        let html = '';

        // Render each location group
        selectedIds.forEach(lid => {
            const locOps = grouped[lid] || [];
            const loc = locs.find(l => l.id === lid);
            const locName = loc ? loc.name : `Location #${lid}`;

            totalOps += locOps.length;

            html += `
                <div class="operatory-location-group">
                    <div class="group-title">
                        <span>📍</span>
                        ${locName}
                        <span class="badge badge-amber">${locOps.length} operatories</span>
                    </div>
                    <div class="operatory-grid">
                        ${locOps.length > 0 ? locOps.map(op => `
                            <div class="operatory-card">
                                <div class="op-name">${op.name}</div>
                                <div class="op-id">ID: ${op.id}</div>
                            </div>
                        `).join('') : '<div style="color:var(--text-muted); font-size:13px; padding:12px;">No operatories in this location</div>'}
                    </div>
                </div>
            `;
        });

        els.operatoriesContainer.innerHTML = html;
        els.operatoryBadge.textContent = `${totalOps} total`;
    }


    // ============================
    // STEP 4: DURATION TABLE
    // ============================

    function renderDurationTable() {
        const pts = appData.productionTypes.filter(pt => pt.isActive);
        const slotMin = appData.slotDurationMinutes;

        if (pts.length === 0) {
            els.durationContainer.innerHTML = `
                <div class="empty-state">
                    <div class="empty-icon">⏱️</div>
                    <div class="empty-text">No production type data</div>
                </div>`;
            return;
        }

        let html = `
            <table class="duration-table">
                <thead>
                    <tr>
                        <th>ID</th>
                        <th>Production Type</th>
                        <th>Slots</th>
                        <th>Duration (min)</th>
                        <th>Specialties</th>
                        <th>Status</th>
                    </tr>
                </thead>
                <tbody>
        `;

        let validCount = 0;
        let zeroCount = 0;

        pts.forEach(pt => {
            const duration = pt.durationMinutes || 0;
            const slots = pt.slotLength || 0;
            const specs = (pt.providerSpecialities || []).join(', ') || '—';

            let statusHtml;
            if (duration > 0) {
                statusHtml = '<span class="duration-status ok">✓ Configured</span>';
                validCount++;
            } else {
                statusHtml = '<span class="duration-status zero">— No duration</span>';
                zeroCount++;
            }

            html += `
                <tr>
                    <td>${pt.id}</td>
                    <td>${pt.name}</td>
                    <td>${slots}</td>
                    <td>${duration > 0 ? duration + ' min' : '—'}</td>
                    <td>${specs}</td>
                    <td>${statusHtml}</td>
                </tr>
            `;
        });

        html += '</tbody></table>';
        els.durationContainer.innerHTML = html;
        els.durationBadge.textContent = `${validCount} configured, ${zeroCount} missing`;
    }


    // ============================
    // STEP 4: VALIDATION SUMMARY
    // ============================

    function renderValidationSummary() {
        const errors = [];
        const warnings = [];
        const infos = [];

        const providers = appData.providers;
        const pts = appData.productionTypes.filter(pt => pt.isActive);
        const ops = appData.operatories;
        const selectedLocs = getSelectedLocationIds();

        // 1. Specialty mismatch check
        let matchCount = 0;
        let mismatchCount = 0;
        providers.forEach(prov => {
            if (!prov.specialityId) {
                warnings.push(`Provider "${prov.name}" has no specialty ID assigned.`);
                return;
            }
            pts.forEach(pt => {
                const ptSpecs = pt.providerSpecialities || [];
                if (ptSpecs.length > 0 && ptSpecs.includes(prov.specialityId)) {
                    matchCount++;
                }
            });
        });

        // Overall matrix stats
        providers.forEach(prov => {
            if (!prov.specialityId) return;
            const matchingPTs = pts.filter(pt =>
                (pt.providerSpecialities || []).includes(prov.specialityId)
            );
            if (matchingPTs.length === 0) {
                errors.push(`Provider "${prov.name}" (Spec #${prov.specialityId}) has NO matching production types.`);
            }
        });

        // 2. Operatory check per location
        selectedLocs.forEach(lid => {
            const locOps = ops.filter(op => op.locationId === lid);
            const loc = appData.locations.find(l => l.id === lid);
            const locName = loc ? loc.name : `Location #${lid}`;
            if (locOps.length === 0) {
                errors.push(`Location "${locName}" has no operatories.`);
            }
        });

        // 3. Duration check
        const zeroDurationPTs = pts.filter(pt => (pt.durationMinutes || 0) === 0);
        if (zeroDurationPTs.length > 0) {
            warnings.push(`${zeroDurationPTs.length} production type(s) have no duration configured: ${zeroDurationPTs.map(p => p.name).join(', ')}.`);
        }

        // 4. Providers with no specialty
        const noSpecProviders = providers.filter(p => !p.specialityId);
        if (noSpecProviders.length > 0) {
            warnings.push(`${noSpecProviders.length} provider(s) have no specialty: ${noSpecProviders.map(p => p.name).join(', ')}.`);
        }

        // 5. Production types with no specialties configured
        const noSpecPTs = pts.filter(pt => (pt.providerSpecialities || []).length === 0);
        if (noSpecPTs.length > 0) {
            warnings.push(`${noSpecPTs.length} production type(s) have no provider specialty configured: ${noSpecPTs.map(p => p.name).join(', ')}.`);
        }

        // Render
        let html = '';

        if (errors.length === 0 && warnings.length === 0) {
            html += `<div class="validation-item success">
                <span class="v-icon">✅</span>
                <span>All checks passed — configuration looks good!</span>
            </div>`;
        }

        errors.forEach(e => {
            html += `<div class="validation-item error">
                <span class="v-icon">❌</span>
                <span>${e}</span>
            </div>`;
        });

        warnings.forEach(w => {
            html += `<div class="validation-item warning">
                <span class="v-icon">⚠️</span>
                <span>${w}</span>
            </div>`;
        });

        // Info stats
        html += `<div class="validation-item success" style="margin-top:12px;">
            <span class="v-icon">📊</span>
            <span>Summary: ${providers.length} providers, ${pts.length} active PTs, ${ops.length} operatories across ${selectedLocs.length} locations</span>
        </div>`;

        els.validationSummary.innerHTML = html;
    }


    // ============================
    // EXPORT
    // ============================

    els.btnExport.addEventListener('click', async () => {
        const selectedProductionTypeIds = {};
        // For export, map all matching PTs to each provider
        appData.providers.forEach(prov => {
            const matchingPTs = appData.productionTypes.filter(pt =>
                (pt.providerSpecialities || []).includes(prov.specialityId)
            );
            if (matchingPTs.length > 0) {
                selectedProductionTypeIds[prov.id] = matchingPTs.map(pt => pt.id);
            }
        });

        const payload = {
            locations: getSelectedLocationIds().map(String),
            providers: appData.providers.map(p => String(p.id)),
            productionTypes: selectedProductionTypeIds,
            excludedInsurance: document.getElementById('excludedInsurance').value,
            notes: document.getElementById('additionalNotes').value,
            botEnabled: document.getElementById('botFunctionality').checked,
            full_locations: appData.locations,
            full_providers: appData.providers,
            full_production_types: appData.productionTypes,
        };

        try {
            showLoading('Generating Excel...');
            const res = await fetch('/api/save-config-excel', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });

            if (res.ok) {
                const blob = await res.blob();
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = 'voicebot_config.xlsx';
                document.body.appendChild(a);
                a.click();
                a.remove();
                window.URL.revokeObjectURL(url);
            } else {
                alert('Failed to generate Excel file.');
            }
        } catch (err) {
            console.error(err);
            alert('Error exporting configuration.');
        } finally {
            hideLoading();
        }
    });

    // ============================
    // LOGOUT
    // ============================
    document.getElementById('btnLogout').addEventListener('click', () => {
        sessionStorage.removeItem(SESSION_KEY);
        // Navigate to clean entry page (no hash, no state)
        window.location.href = window.location.pathname;
    });

    // ============================
    // INIT
    // ============================

    // Try to restore a previous session (so browser back/forward works
    // even after the page re-renders from popstate).
    const restored = restoreSession();

    if (!restored) {
        updateStepper();
        // Seed the browser history with the initial step.
        history.replaceState({ step: currentStep, maxStepReached }, '', `#step-${currentStep}`);
    }
});
