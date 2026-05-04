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
        operatory_providers: {},
        operatory_production_types: {},
        allProviderNameMap: {},  // complete provider name map (all locations) for operatory resolution
        calendarPtDurations: {},  // production type calendar durations from timestamp details
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
        providerCountBadge: $('providerCountBadge'),
        selectAllProviders: $('selectAllProviders'),
        providersGrid: $('providersGrid'),
        productionTypeCountBadge: $('productionTypeCountBadge'),
        selectAllProductionTypes: $('selectAllProductionTypes'),
        productionTypesGrid: $('productionTypesGrid'),
        // Step 3
        operatoriesContainer: $('operatoriesContainer'),
        operatoryBadge: $('operatoryBadge'),
        matrixStats: $('matrixStats'),
        matrixWrapper: $('matrixWrapper'),
        matrixBadge: $('matrixBadge'),
        matrixProviderSelect: $('matrixProviderSelect'),
        filterHint: $('filterHint'),
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

            if (!stepEl) continue;

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
                    operatory_providers: appData.operatory_providers,
                    operatory_production_types: appData.operatory_production_types,
                    allProviderNameMap: appData.allProviderNameMap,
                    calendarPtDurations: appData.calendarPtDurations,
                },
                maxStepReached,
                currentStep,
                selectedLocationIds: getSelectedLocationIds(),
                selectedProviderIds: getSelectedProviderIds(),
                selectedProductionTypeIds: getSelectedProductionTypeIds(),
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
                renderProvidersStep();
                
                if (session.selectedProviderIds && session.selectedProviderIds.length > 0) {
                    session.selectedProviderIds.forEach(id => {
                        const cb = document.querySelector(`.provider-cb[value="${id}"]`);
                        if (cb) {
                            cb.checked = true;
                            const item = cb.closest('.location-item');
                            if (item) item.classList.add('selected');
                        }
                    });
                    
                    // Update Select All checkbox state
                    const allChecked = document.querySelectorAll('.provider-cb:not(:checked)').length === 0;
                    if (els.selectAllProviders) els.selectAllProviders.checked = allChecked;
                }

                if (session.selectedProductionTypeIds && session.selectedProductionTypeIds.length > 0) {
                    session.selectedProductionTypeIds.forEach(id => {
                        const cb = document.querySelector(`.pt-cb[value="${id}"]`);
                        if (cb) {
                            cb.checked = true;
                            const item = cb.closest('.location-item');
                            if (item) item.classList.add('selected');
                        }
                    });
                    
                    // Update Select All checkbox state
                    const allPTChecked = document.querySelectorAll('.pt-cb:not(:checked)').length === 0;
                    if (els.selectAllProductionTypes) els.selectAllProductionTypes.checked = allPTChecked;
                }

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
            appData.productionTypes = (data.production_types || []).filter(
                pt => !pt.name || !pt.name.toLowerCase().includes('lunch')
            );
            appData.operatories = data.operatories;
            appData.users = data.users;
            appData.operatory_providers = data.operatory_providers;
            appData.operatory_production_types = data.operatory_production_types || {};
            appData.allProviderNameMap = data.all_provider_name_map || {};
            appData.slotDurationMinutes = data.slot_duration_minutes || 5;
            appData.calendarPtDurations = data.calendar_pt_durations || {};

            // Build all views
            renderProvidersStep();
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
    // STEP 2: SELECT PROVIDERS
    // ============================

    function renderProvidersStep() {
        const provs = appData.providers.filter(p => p.isActive);
        els.providerCountBadge.textContent = `${provs.length} providers`;

        if (provs.length === 0) {
            els.providersGrid.innerHTML = `
                <div class="empty-state">
                    <div class="empty-icon">👤</div>
                    <div class="empty-text">No providers found</div>
                </div>`;
        } else {
            els.providersGrid.innerHTML = provs.map(prov => `
                <label class="location-item" id="provItem-${prov.id}">
                    <input type="checkbox" class="provider-cb" value="${prov.id}"
                           onchange="handleProviderToggle(this)">
                    <div class="location-info">
                        <div class="loc-name">${prov.name}</div>
                        <div class="loc-detail">${prov.providerType || 'Unknown'} · Spec #${prov.specialityId || '—'} · Concurrency: ${prov.concurrency || 'N/A'}</div>
                    </div>
                </label>
            `).join('');
        }

        // Reset select all checkbox
        if (els.selectAllProviders) els.selectAllProviders.checked = false;

        // Render PTs
        const pts = appData.productionTypes.filter(p => p.isActive);
        els.productionTypeCountBadge.textContent = `${pts.length} production types`;

        if (pts.length === 0) {
            els.productionTypesGrid.innerHTML = `
                <div class="empty-state">
                    <div class="empty-icon">⚙️</div>
                    <div class="empty-text">No production types found</div>
                </div>`;
        } else {
            els.productionTypesGrid.innerHTML = pts.map(pt => `
                <label class="location-item" id="ptItem-${pt.id}">
                    <input type="checkbox" class="pt-cb" value="${pt.id}"
                           onchange="handleProductionTypeToggle(this)">
                    <div class="location-info">
                        <div class="loc-name">${pt.name}</div>
                        <div class="loc-detail">Spec: ${(pt.providerSpecialities || []).join(', ') || 'None'}</div>
                    </div>
                </label>
            `).join('');
        }

        if (els.selectAllProductionTypes) els.selectAllProductionTypes.checked = false;
    }

    window.handleProviderToggle = function(cb) {
        const item = cb.closest('.location-item');
        item.classList.toggle('selected', cb.checked);
        
        // Update Select All checkbox state
        const allChecked = document.querySelectorAll('.provider-cb:not(:checked)').length === 0;
        if (els.selectAllProviders) els.selectAllProviders.checked = allChecked;
        
        // Trigger data view updates on selection change
        buildAndRenderMatrix();
        renderOperatories();
        saveSession();
    };

    if (els.selectAllProviders) {
        els.selectAllProviders.addEventListener('change', (e) => {
            const isChecked = e.target.checked;
            document.querySelectorAll('.provider-cb').forEach(cb => {
                cb.checked = isChecked;
                const item = cb.closest('.location-item');
                if (item) item.classList.toggle('selected', isChecked);
            });
            
            buildAndRenderMatrix();
            renderOperatories();
            saveSession();
        });
    }

    window.handleProductionTypeToggle = function(cb) {
        const item = cb.closest('.location-item');
        item.classList.toggle('selected', cb.checked);
        
        const allChecked = document.querySelectorAll('.pt-cb:not(:checked)').length === 0;
        if (els.selectAllProductionTypes) els.selectAllProductionTypes.checked = allChecked;
        
        buildAndRenderMatrix();
        renderOperatories();
        renderDurationTable();
        renderValidationSummary();
        saveSession();
    };

    if (els.selectAllProductionTypes) {
        els.selectAllProductionTypes.addEventListener('change', (e) => {
            const isChecked = e.target.checked;
            document.querySelectorAll('.pt-cb').forEach(cb => {
                cb.checked = isChecked;
                const item = cb.closest('.location-item');
                if (item) item.classList.toggle('selected', isChecked);
            });
            
            buildAndRenderMatrix();
            renderOperatories();
            renderDurationTable();
            renderValidationSummary();
            saveSession();
        });
    }

    function getSelectedProviderIds() {
        return Array.from(document.querySelectorAll('.provider-cb:checked'))
            .map(cb => parseInt(cb.value));
    }

    function getSelectedProviders() {
        const selectedIds = getSelectedProviderIds();
        return appData.providers.filter(p => p.isActive && selectedIds.includes(p.id));
    }

    function getSelectedProductionTypeIds() {
        return Array.from(document.querySelectorAll('.pt-cb:checked'))
            .map(cb => parseInt(cb.value));
    }

    function getSelectedProductionTypes() {
        const selectedIds = getSelectedProductionTypeIds();
        return appData.productionTypes.filter(pt => pt.isActive && selectedIds.includes(pt.id));
    }


    // ============================
    // STEP 4: SPECIALTY MATRIX
    // ============================

    /**
     * Populate the provider filter dropdown.
     * Called once after data load; preserves current selection if still valid.
     */
    function populateProviderDropdown() {
        const providers = getSelectedProviders();
        const prev = els.matrixProviderSelect.value;

        let html = '<option value="all">All Providers</option>';
        providers.forEach(p => {
            html += `<option value="${p.id}">${p.name} (${p.providerType || 'Unknown'})</option>`;
        });
        els.matrixProviderSelect.innerHTML = html;

        // Restore previous selection if still valid
        if (prev !== 'all' && providers.some(p => String(p.id) === prev)) {
            els.matrixProviderSelect.value = prev;
        }
    }

    // Listen for filter changes
    els.matrixProviderSelect.addEventListener('change', () => {
        buildAndRenderMatrix();
        saveSession();
    });

    function buildAndRenderMatrix() {
        const allProviders = getSelectedProviders();
        const allPts = getSelectedProductionTypes();

        // Populate dropdown (idempotent — preserves selection)
        populateProviderDropdown();

        if (allProviders.length === 0 || allPts.length === 0) {
            els.matrixWrapper.innerHTML = `
                <div class="empty-state">
                    <div class="empty-icon">📊</div>
                    <div class="empty-text">No data available for matrix</div>
                    <div class="empty-sub">${allProviders.length} providers, ${allPts.length} active production types</div>
                </div>`;
            els.filterHint.textContent = '';
            return;
        }

        // --- Apply provider filter ---
        const selectedValue = els.matrixProviderSelect.value;
        let filteredProviders;
        let filteredPts;

        if (selectedValue === 'all') {
            filteredProviders = allProviders;
            filteredPts = allPts;
            els.filterHint.textContent = '';
        } else {
            const selectedId = parseInt(selectedValue, 10);
            const selectedProv = allProviders.find(p => p.id === selectedId);
            filteredProviders = selectedProv ? [selectedProv] : allProviders;

            // Filter PTs to those compatible with the selected provider:
            // 1. PT has this provider in its allocatedProviderIds, OR
            // 2. Fallback: PT's providerSpecialities includes provider's specialityId
            filteredPts = allPts.filter(pt => {
                const allocIds = pt.allocatedProviderIds || [];
                const ptSpecs = pt.providerSpecialities || [];

                // If scheduler has explicit provider allocations, use them
                if (allocIds.length > 0) {
                    return allocIds.includes(selectedId);
                }
                // Fallback to specialty-based match
                if (selectedProv && selectedProv.specialityId && ptSpecs.length > 0) {
                    return ptSpecs.includes(selectedProv.specialityId);
                }
                // If no data available, include the PT
                return true;
            });

            const provName = selectedProv ? selectedProv.name : 'Unknown';
            els.filterHint.textContent = `Showing ${filteredPts.length} compatible production type${filteredPts.length !== 1 ? 's' : ''} for ${provName}`;
        }

        // --- Build matrix data ---
        let matchCount = 0;
        let mismatchCount = 0;

        const matrix = filteredProviders.map(prov => {
            const row = filteredPts.map(pt => {
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

        // --- Render stats ---
        const showingAll = selectedValue === 'all';
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
                    <div class="stat-value">${filteredProviders.length}${!showingAll ? ' / ' + allProviders.length : ''}</div>
                    <div class="stat-label">Providers</div>
                </div>
            </div>
            <div class="stat-card amber">
                <div>
                    <div class="stat-value">${filteredPts.length}${!showingAll ? ' / ' + allPts.length : ''}</div>
                    <div class="stat-label">Production Types</div>
                </div>
            </div>
        `;

        els.matrixBadge.textContent = `${matchCount} matches`;

        // --- Render table ---
        if (filteredPts.length === 0) {
            els.matrixWrapper.innerHTML = `
                <div class="empty-state">
                    <div class="empty-icon">🔍</div>
                    <div class="empty-text">No compatible production types found</div>
                    <div class="empty-sub">This provider has no allocated or specialty-matching production types</div>
                </div>`;
            return;
        }

        let html = '<table class="matrix-table">';

        // Header row
        html += '<thead><tr>';
        html += '<th class="corner">Provider</th>';
        filteredPts.forEach(pt => {
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
                <div class="provider-spec">${row.provider.providerType} · Spec #${row.provider.specialityId || '—'} · Concurrency: ${row.provider.concurrency || 'N/A'}</div>
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

        // --- Specialty Matrix Inference ---
        const providersWithNoMatches = [];
        const ptsWithNoMatches = [];

        matrix.forEach(row => {
            const hasMatch = row.cells.some(c => c.status === 'match');
            if (!hasMatch) {
                providersWithNoMatches.push(row.provider.name);
            }
        });

        filteredPts.forEach((pt, ptIndex) => {
            const hasMatch = matrix.some(row => row.cells[ptIndex].status === 'match');
            if (!hasMatch) {
                ptsWithNoMatches.push(pt.name);
            }
        });

        if (providersWithNoMatches.length > 0 || ptsWithNoMatches.length > 0) {
            html += `
                <div class="operatory-inference-panel" style="margin-top: 16px;">
                    <div class="inference-header">
                        <span class="inference-icon">⚠️</span>
                        <span class="inference-title">Specialty Matching Gaps</span>
                    </div>
            `;
            if (providersWithNoMatches.length > 0) {
                html += `
                    <p class="inference-desc">The following <strong>${providersWithNoMatches.length}</strong> provider${providersWithNoMatches.length > 1 ? 's have' : ' has'} <em>no matching production types</em> based on specialty.</p>
                    <div class="inference-tags" style="margin-bottom: 12px;">
                        ${providersWithNoMatches.map(name => `<span class="inference-tag">${name}</span>`).join('')}
                    </div>
                `;
            }
            if (ptsWithNoMatches.length > 0) {
                html += `
                    <p class="inference-desc">The following <strong>${ptsWithNoMatches.length}</strong> production type${ptsWithNoMatches.length > 1 ? 's have' : ' has'} <em>no compatible providers</em> based on specialty.</p>
                    <div class="inference-tags">
                        ${ptsWithNoMatches.map(name => `<span class="inference-tag">${name}</span>`).join('')}
                    </div>
                `;
            }
            html += `</div>`;
        } else {
            html += `
                <div class="operatory-inference-panel ok" style="margin-top: 16px;">
                    <div class="inference-header">
                        <span class="inference-icon">✅</span>
                        <span class="inference-title">All Specialties Connected</span>
                    </div>
                    <p class="inference-desc">Every selected provider has at least one compatible production type, and every selected production type has at least one compatible provider.</p>
                </div>
            `;
        }

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

        // Collect selected IDs for highlighting and inference
        const selectedPtIds = getSelectedProductionTypeIds();
        const selectedProviderIds = getSelectedProviderIds();

        // Track which selected items appear in at least one operatory (across all locations)
        const ptIdsInOperatories = new Set();
        const providerIdsInOperatories = new Set();

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
                        ${locOps.length > 0 ? locOps.map(op => {
                            const providerIds = appData.operatory_providers && appData.operatory_providers[op.id] ? appData.operatory_providers[op.id] : [];
                            
                            // Track which selected providers appear in operatories
                            providerIds.forEach(pid => {
                                if (selectedProviderIds.includes(pid)) {
                                    providerIdsInOperatories.add(pid);
                                }
                            });

                            const providerTags = providerIds.map(pid => {
                                // First try location-filtered providers, then fall back to the full name map
                                const prov = appData.providers.find(p => p.id === pid);
                                let name;
                                let isActive = false;
                                let concurrency = null;
                                if (prov) {
                                    name = prov.name;
                                    isActive = prov.isActive;
                                    concurrency = prov.concurrency;
                                } else {
                                    const lookup = appData.allProviderNameMap && appData.allProviderNameMap[String(pid)];
                                    name = lookup ? lookup.name : `ID: ${pid}`;
                                    isActive = lookup ? lookup.isActive : false;
                                    concurrency = lookup ? lookup.concurrency : null;
                                }
                                const isSelected = selectedProviderIds.includes(pid);
                                const activeClass = isActive ? '' : ' inactive';
                                const concurrencyLabel = concurrency != null ? ` (${concurrency})` : '';
                                return `<span class="op-provider-tag${isSelected ? ' selected' : ''}${activeClass}" title="${isSelected ? 'Selected provider' : (isActive ? 'Active (not selected)' : 'Inactive provider')}${concurrency != null ? ' · Concurrency: ' + concurrency : ''}">${name}${concurrencyLabel}</span>`;
                            });
                            
                            const providersHtml = providerTags.length > 0
                                ? `<div class="op-providers"><strong>Providers:</strong><div class="op-provider-tags">${providerTags.join('')}</div></div>`
                                : `<div class="op-providers op-providers-empty"><em>No providers assigned</em></div>`;

                            const ptIds = appData.operatory_production_types && appData.operatory_production_types[op.id] ? appData.operatory_production_types[op.id] : [];

                            // Track which selected PTs appear in operatories
                            ptIds.forEach(ptId => {
                                if (selectedPtIds.includes(ptId)) {
                                    ptIdsInOperatories.add(ptId);
                                }
                            });

                            const ptTags = ptIds.map(ptId => {
                                const pt = appData.productionTypes.find(p => p.id === ptId);
                                const ptName = pt ? pt.name : `ID: ${ptId}`;
                                return { id: ptId, name: ptName };
                            }).filter(item => item.name.toLowerCase() !== 'lunch').map(item => {
                                const isSelected = selectedPtIds.includes(item.id);
                                return `<span class="op-pt-tag${isSelected ? ' selected' : ''}" title="${isSelected ? 'Selected production type' : 'Production Type'}">${item.name}</span>`;
                            });

                            const ptsHtml = ptTags.length > 0
                                ? `<div class="op-pts"><strong>Production Types:</strong><div class="op-pt-tags">${ptTags.join('')}</div></div>`
                                : `<div class="op-pts op-pts-empty"><em>No production types linked</em></div>`;

                            return `
                            <div class="operatory-card">
                                <div class="op-name">${op.name}</div>
                                <div class="op-id">ID: ${op.id}</div>
                                ${providersHtml}
                                ${ptsHtml}
                            </div>
                            `;
                        }).join('') : '<div style="color:var(--text-muted); font-size:13px; padding:12px;">No operatories in this location</div>'}
                    </div>
                </div>
            `;
        });

        // --- Inference section: selected PTs not assigned to any operatory ---
        const missingPts = selectedPtIds
            .filter(ptId => !ptIdsInOperatories.has(ptId))
            .map(ptId => {
                const pt = appData.productionTypes.find(p => p.id === ptId);
                return pt ? pt.name : `ID: ${ptId}`;
            });

        if (missingPts.length > 0) {
            html += `
                <div class="operatory-inference-panel">
                    <div class="inference-header">
                        <span class="inference-icon">⚠️</span>
                        <span class="inference-title">Production Type Coverage Gap</span>
                    </div>
                    <p class="inference-desc">The following <strong>${missingPts.length}</strong> selected production type${missingPts.length > 1 ? 's are' : ' is'} <em>not assigned to any operatory</em> across the selected locations. This means no operatory is configured to handle these production types, which could lead to scheduling gaps.</p>
                    <div class="inference-tags">
                        ${missingPts.map(name => `<span class="inference-tag">${name}</span>`).join('')}
                    </div>
                </div>
            `;
        } else if (selectedPtIds.length > 0) {
            html += `
                <div class="operatory-inference-panel ok">
                    <div class="inference-header">
                        <span class="inference-icon">✅</span>
                        <span class="inference-title">All Production Types Covered</span>
                    </div>
                    <p class="inference-desc">Every selected production type is assigned to at least one operatory across the selected locations.</p>
                </div>
            `;
        }

        // --- Inference section: selected Providers not assigned to any operatory ---
        const missingProviders = selectedProviderIds
            .filter(pid => !providerIdsInOperatories.has(pid))
            .map(pid => {
                const prov = appData.providers.find(p => p.id === pid);
                if (prov) return prov.name;
                const lookup = appData.allProviderNameMap && appData.allProviderNameMap[String(pid)];
                return lookup ? lookup.name : `ID: ${pid}`;
            });

        if (missingProviders.length > 0) {
            html += `
                <div class="operatory-inference-panel">
                    <div class="inference-header">
                        <span class="inference-icon">⚠️</span>
                        <span class="inference-title">Provider Coverage Gap</span>
                    </div>
                    <p class="inference-desc">The following <strong>${missingProviders.length}</strong> selected provider${missingProviders.length > 1 ? 's are' : ' is'} <em>not assigned to any operatory</em> across the selected locations. This means no operatory is configured to handle these providers, which could lead to scheduling gaps.</p>
                    <div class="inference-tags">
                        ${missingProviders.map(name => `<span class="inference-tag">${name}</span>`).join('')}
                    </div>
                </div>
            `;
        } else if (selectedProviderIds.length > 0) {
            html += `
                <div class="operatory-inference-panel ok">
                    <div class="inference-header">
                        <span class="inference-icon">✅</span>
                        <span class="inference-title">All Providers Covered</span>
                    </div>
                    <p class="inference-desc">Every selected provider is assigned to at least one operatory across the selected locations.</p>
                </div>
            `;
        }

        els.operatoriesContainer.innerHTML = html;
        els.operatoryBadge.textContent = `${totalOps} total`;
    }


    // ============================
    // STEP 4: DURATION TABLE
    // ============================

    function renderDurationTable() {
        const pts = getSelectedProductionTypes();
        const slotMin = appData.slotDurationMinutes;
        const calDurations = appData.calendarPtDurations || {};
        const dayNames = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

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
                        <th>Default Duration</th>
                        <th>Calendar Durations</th>
                        <th>Scheduled Days</th>
                        <th>Templates</th>
                        <th>Duration Validation</th>
                    </tr>
                </thead>
                <tbody>
        `;

        let validCount = 0;
        let mismatchCount = 0;
        let noCalendarCount = 0;

        pts.forEach(pt => {
            const defaultDuration = pt.durationMinutes || 0;
            const calData = calDurations[String(pt.id)];
            const calDurs = calData ? calData.durations : [];
            const calDays = calData ? calData.days.map(d => dayNames[d] || d) : [];
            const calTemplates = calData ? calData.templates : [];
            const calTimeRanges = calData ? calData.time_ranges : [];

            // Default duration display
            const defaultDurHtml = defaultDuration > 0
                ? `<span class="dur-badge dur-default">${defaultDuration} min</span>`
                : '<span class="dur-badge dur-none">— Not set</span>';

            // Calendar duration display
            let calDurHtml;
            if (calDurs.length > 0) {
                calDurHtml = calDurs.map(d => `<span class="dur-badge dur-calendar">${d} min</span>`).join(' ');
            } else {
                calDurHtml = '<span class="dur-badge dur-none">— Not in calendar</span>';
            }

            // Scheduled days display
            const daysHtml = calDays.length > 0
                ? calDays.map(d => `<span class="day-badge">${d}</span>`).join(' ')
                : '<span style="color: var(--text-muted);">—</span>';

            // Templates display
            const templatesHtml = calTemplates.length > 0
                ? calTemplates.map(t => `<span class="template-badge" title="${t}">${t}</span>`).join(' ')
                : '<span style="color: var(--text-muted);">—</span>';

            // Duration validation
            // Calendar durations can be valid multiples of the default duration
            // e.g., default = 60 min → 60, 120, 180 are all valid (1×, 2×, 3×)
            let validationHtml;
            if (calDurs.length === 0) {
                validationHtml = '<span class="duration-status zero">⚠ Not in calendar</span>';
                noCalendarCount++;
            } else if (defaultDuration === 0) {
                validationHtml = '<span class="duration-status zero">⚠ No default set</span>';
                noCalendarCount++;
            } else {
                const isMultiple = (d) => d > 0 && d % defaultDuration === 0;
                const allMultiples = calDurs.every(isMultiple);
                const someMultiples = calDurs.some(isMultiple);
                const invalidDurs = calDurs.filter(d => !isMultiple(d));

                if (allMultiples) {
                    const multiples = calDurs.map(d => `${d / defaultDuration}×`).join(', ');
                    validationHtml = `<span class="duration-status ok">✓ Valid multiples (${multiples})</span>`;
                    validCount++;
                } else if (someMultiples) {
                    validationHtml = `<span class="duration-status warn">⚠ Mixed: ${invalidDurs.join(', ')} min not a multiple of ${defaultDuration}</span>`;
                    mismatchCount++;
                } else {
                    validationHtml = `<span class="duration-status error">✗ Mismatch: ${calDurs.join(', ')} min — none are multiples of default ${defaultDuration} min</span>`;
                    mismatchCount++;
                }
            }

            // Build expandable time ranges row
            let timeRangeDetail = '';
            if (calTimeRanges.length > 0) {
                const groupedByTemplate = {};
                calTimeRanges.forEach(tr => {
                    if (!groupedByTemplate[tr.template]) groupedByTemplate[tr.template] = [];
                    groupedByTemplate[tr.template].push(tr);
                });
                timeRangeDetail = Object.entries(groupedByTemplate).map(([tmpl, ranges]) => {
                    const rangeStrs = ranges.map(r => `${r.time} (${r.duration}min)`).join(', ');
                    return `<div class="time-range-detail"><strong>${tmpl}:</strong> ${rangeStrs}</div>`;
                }).join('');
            }

            html += `
                <tr class="${calTimeRanges.length > 0 ? 'expandable-row' : ''}" onclick="${calTimeRanges.length > 0 ? 'toggleTimeRanges(this)' : ''}">
                    <td>${pt.id}</td>
                    <td>${pt.name}</td>
                    <td>${defaultDurHtml}</td>
                    <td>${calDurHtml}</td>
                    <td>${daysHtml}</td>
                    <td class="template-cell">${templatesHtml}</td>
                    <td>${validationHtml}</td>
                </tr>
            `;

            if (timeRangeDetail) {
                html += `
                    <tr class="time-range-row hidden">
                        <td colspan="7">
                            <div class="time-ranges-container">
                                <div class="time-ranges-title">📅 Calendar Time Slots</div>
                                ${timeRangeDetail}
                            </div>
                        </td>
                    </tr>
                `;
            }
        });

        html += '</tbody></table>';
        els.durationContainer.innerHTML = html;
        els.durationBadge.textContent = `${validCount} match, ${mismatchCount} mismatch, ${noCalendarCount} unconfigured`;
    }

    // Toggle time range details
    window.toggleTimeRanges = function(row) {
        const nextRow = row.nextElementSibling;
        if (nextRow && nextRow.classList.contains('time-range-row')) {
            nextRow.classList.toggle('hidden');
            row.classList.toggle('expanded');
        }
    };


    // ============================
    // STEP 4: VALIDATION SUMMARY
    // ============================

    function renderValidationSummary() {
        const providers = getSelectedProviders();
        const pts = getSelectedProductionTypes();
        const ops = appData.operatories;
        const selectedLocs = getSelectedLocationIds();

        const providerInsights = {};
        const ptInsights = {};
        const generalInsights = { errors: [], warnings: [], infos: [] };

        providers.forEach(p => providerInsights[p.id] = { name: p.name, errors: [], warnings: [], infos: [] });
        pts.forEach(pt => ptInsights[pt.id] = { name: pt.name, errors: [], warnings: [], infos: [] });

        // 1. Specialty mismatch check
        providers.forEach(prov => {
            if (!prov.specialityId) {
                providerInsights[prov.id].warnings.push(`No specialty ID assigned.`);
                return;
            }
            const matchingPTs = pts.filter(pt =>
                (pt.providerSpecialities || []).includes(prov.specialityId)
            );
            if (matchingPTs.length === 0) {
                providerInsights[prov.id].errors.push(`No matching production types for Specialty #${prov.specialityId}.`);
            }
        });

        // 2. Operatory check per location
        selectedLocs.forEach(lid => {
            const locOps = ops.filter(op => op.locationId === lid);
            const loc = appData.locations.find(l => l.id === lid);
            const locName = loc ? loc.name : `Location #${lid}`;
            if (locOps.length === 0) {
                generalInsights.errors.push(`Location "${locName}" has no operatories.`);
            }
        });

        // 3. Duration check — compare default duration vs calendar durations
        const calDurations = appData.calendarPtDurations || {};
        const dayNames = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
        
        pts.forEach(pt => {
            const defaultDuration = pt.durationMinutes || 0;
            const calData = calDurations[String(pt.id)];
            const calDurs = calData ? calData.durations : [];
            const calDays = calData ? calData.days.map(d => dayNames[d] || d) : [];
            const calTemplates = calData ? calData.templates : [];

            // Check if default duration is set
            if (defaultDuration === 0) {
                ptInsights[pt.id].warnings.push(`No default duration configured (slotLength = 0).`);
            }

            // Calendar duration validation
            if (calDurs.length === 0) {
                ptInsights[pt.id].warnings.push(`Not found in any production calendar template slots.`);
                pt._scheduledDays = 'None';
                pt._scheduledTemplates = 'None';
                pt._computedDurations = [defaultDuration];
            } else {
                // Show calendar schedule info
                const dayStr = calDays.join(', ') || 'None';
                const schedStr = calTemplates.join(', ');
                ptInsights[pt.id].infos.push(`Scheduled on: ${dayStr} (Templates: ${schedStr})`);
                pt._scheduledDays = dayStr;
                pt._scheduledTemplates = schedStr;
                pt._computedDurations = calDurs;

                // Compare default vs calendar durations
                // Calendar durations can be valid multiples of the default
                if (defaultDuration > 0) {
                    const isMultiple = (d) => d > 0 && d % defaultDuration === 0;
                    const allMultiples = calDurs.every(isMultiple);
                    const someMultiples = calDurs.some(isMultiple);
                    const invalidDurs = calDurs.filter(d => !isMultiple(d));

                    if (allMultiples) {
                        const multiples = calDurs.map(d => `${d / defaultDuration}×`).join(', ');
                        ptInsights[pt.id].infos.push(`Calendar durations are valid multiples of default ${defaultDuration} min (${multiples}). ✓`);
                    } else if (someMultiples) {
                        ptInsights[pt.id].warnings.push(
                            `Calendar has mixed durations: ${invalidDurs.join(', ')} min are not multiples of default ${defaultDuration} min.`
                        );
                    } else {
                        ptInsights[pt.id].errors.push(
                            `Calendar duration mismatch: none of ${calDurs.join(', ')} min are multiples of default ${defaultDuration} min.`
                        );
                    }
                } else {
                    ptInsights[pt.id].infos.push(
                        `Calendar durations: ${calDurs.join(', ')} min (no default to compare against).`
                    );
                }
            }
        });

        // 4. Production types with no specialties configured or multiple
        pts.forEach(pt => {
            const specCount = (pt.providerSpecialities || []).length;
            if (specCount === 0) {
                ptInsights[pt.id].warnings.push(`No provider specialty configured.`);
            } else if (specCount > 1) {
                ptInsights[pt.id].warnings.push(`Multiple specialty IDs mapped (${specCount}).`);
            } else {
                ptInsights[pt.id].infos.push(`Exactly one specialty mapped.`);
            }
        });

        // 5. Provider concurrent appointments from availability templates
        const provTemplates = appData.raw_provider_availability_templates || [];
        const provConcurrent = {};
        provTemplates.forEach(t => {
            const isConcurrent = t.isConcurrent || t.allowConcurrentAppointments || t.concurrentAppointments || t.concurrent || false;
            const pIds = t.providerId ? [t.providerId] : (t.providerIds || []);
            pIds.forEach(pid => {
                if (isConcurrent) provConcurrent[pid] = true;
            });
        });

        providers.forEach(prov => {
            const hasConcurrent = provConcurrent[prov.id] === true;
            prov._isConcurrent = hasConcurrent; // save for export
            if (hasConcurrent) {
                providerInsights[prov.id].infos.push(`Concurrent appointments enabled in availability templates.`);
            }
        });

        // 7. Render Grouped Summary
        let html = '';

        function renderGroup(title, icon, insightsDict) {
            let groupHtml = '';
            let hasContent = false;
            
            Object.values(insightsDict).forEach(item => {
                if (item.errors.length === 0 && item.warnings.length === 0 && item.infos.length === 0) return;
                hasContent = true;
                
                groupHtml += `<div style="margin-bottom: 12px; padding: 12px; border-radius: var(--radius-sm); background: rgba(255,255,255,0.02); border: 1px solid var(--border-subtle);">
                    <div style="font-weight: 600; font-size: 14px; margin-bottom: 8px; color: var(--text-primary);">${item.name}</div>`;
                
                item.errors.forEach(e => {
                    groupHtml += `<div class="validation-item error"><span class="v-icon">❌</span><span>${e}</span></div>`;
                });
                item.warnings.forEach(w => {
                    groupHtml += `<div class="validation-item warning"><span class="v-icon">⚠️</span><span>${w}</span></div>`;
                });
                item.infos.forEach(i => {
                    groupHtml += `<div class="validation-item info" style="background-color: var(--surface-bg); border-left: 4px solid var(--accent-blue);">
                        <span class="v-icon" style="color: var(--accent-blue);">ℹ️</span><span>${i}</span></div>`;
                });
                groupHtml += `</div>`;
            });

            if (hasContent) {
                html += `
                <div style="margin-bottom: 24px;">
                    <div style="font-size: 15px; font-weight: 600; color: var(--text-primary); margin-bottom: 12px; display: flex; align-items: center; gap: 8px;">
                        <span>${icon}</span> ${title}
                    </div>
                    ${groupHtml}
                </div>`;
            }
        }

        // General insights (Locations)
        if (generalInsights.errors.length > 0 || generalInsights.warnings.length > 0) {
            html += `
            <div style="margin-bottom: 24px;">
                <div style="font-size: 15px; font-weight: 600; color: var(--text-primary); margin-bottom: 12px; display: flex; align-items: center; gap: 8px;">
                    <span>📍</span> Locations
                </div>
                <div style="padding: 12px; border-radius: var(--radius-sm); background: rgba(255,255,255,0.02); border: 1px solid var(--border-subtle);">`;
            
            generalInsights.errors.forEach(e => {
                html += `<div class="validation-item error"><span class="v-icon">❌</span><span>${e}</span></div>`;
            });
            generalInsights.warnings.forEach(w => {
                html += `<div class="validation-item warning"><span class="v-icon">⚠️</span><span>${w}</span></div>`;
            });
            
            html += `</div></div>`;
        }

        renderGroup('Providers', '👤', providerInsights);
        renderGroup('Production Types', '⚡', ptInsights);

        if (!html) {
            html = `<div class="validation-item success">
                <span class="v-icon">✅</span>
                <span>All checks passed — configuration looks good!</span>
            </div>`;
        }

        // Overall stats
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
        const selectedProviders = getSelectedProviders();
        // For export, map all matching PTs to each provider
        selectedProviders.forEach(prov => {
            const matchingPTs = getSelectedProductionTypes().filter(pt =>
                (pt.providerSpecialities || []).includes(prov.specialityId)
            );
            if (matchingPTs.length > 0) {
                selectedProductionTypeIds[prov.id] = matchingPTs.map(pt => pt.id);
            }
        });

        const payload = {
            locations: getSelectedLocationIds().map(String),
            providers: selectedProviders.map(p => String(p.id)),
            productionTypes: selectedProductionTypeIds,
            excludedInsurance: document.getElementById('excludedInsurance').value,
            notes: document.getElementById('additionalNotes').value,
            botEnabled: document.getElementById('botFunctionality').checked,
            full_locations: appData.locations,
            full_providers: selectedProviders.map(p => ({
                ...p,
                concurrentFromTemplate: !!p._isConcurrent
            })),
            full_production_types: getSelectedProductionTypes().map(pt => {
                const calData = appData.calendarPtDurations[String(pt.id)];
                const calDayNames = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
                return {
                    ...pt,
                    computedDurations: pt._computedDurations || [],
                    scheduledDays: pt._scheduledDays || 'None',
                    scheduledTemplates: pt._scheduledTemplates || 'None',
                    specialtyCount: (pt.providerSpecialities || []).length,
                    calendarDurations: calData ? calData.durations : [],
                    calendarDays: calData ? calData.days.map(d => calDayNames[d] || d).join(', ') : 'None',
                    calendarTemplates: calData ? calData.templates.join(', ') : 'None',
                };
            }),
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
