document.addEventListener('DOMContentLoaded', () => {
    const locationsContainer = document.getElementById('locationsContainer');
    const providersContainer = document.getElementById('providersContainer');
    const productionTypesContainer = document.getElementById('productionTypesContainer');
    const btnValidate = document.getElementById('btnValidate');
    const btnSave = document.getElementById('btnSave');
    const btnReset = document.getElementById('btnReset');
    const validationResults = document.getElementById('validationResults');
    const validationContent = document.getElementById('validationContent');
    const providerSearch = document.getElementById('providerSearch');
    
    // API Config Elements
    const btnFetchApi = document.getElementById('btnFetchApi'); // Now Fetch Locations
    const btnFetchDetails = document.getElementById('btnFetchDetails'); // New Button
    const btnFetchUsers = document.getElementById('btnFetchUsers');
    const btnFetchSchedulerPT = document.getElementById('btnFetchSchedulerPT');
    const btnMatchSpecialty = document.getElementById('btnMatchSpecialty');
    const apiAuthUrl = document.getElementById('apiAuthUrl');
    const apiBaseUrl = document.getElementById('apiBaseUrl');
    const apiClientId = document.getElementById('apiClientId');
    const apiClientSecret = document.getElementById('apiClientSecret');
    const apiUsername = document.getElementById('apiUsername');
    const apiPassword = document.getElementById('apiPassword');
    const fetchStatus = document.getElementById('fetchStatus');

    // Users UI Elements
    const usersCard = document.getElementById('usersCard');
    const usersTableBody = document.getElementById('usersTableBody');
    const schedulerPTCard = document.getElementById('schedulerPTCard');
    const schedulerPTTableBody = document.getElementById('schedulerPTTableBody');
    const matchedSpecialistsCard = document.getElementById('matchedSpecialistsCard');
    const matchedSpecialistsTableBody = document.getElementById('matchedSpecialistsTableBody');

    let allLocations = [];
    let allProviders = [];
    let allProductionTypes = [];
    let allOperatories = [];
    
    // Matched Data Source
    let fetchedUsers = [];
    let fetchedSchedulerPTs = [];

    // State
    let selectedProviders = new Set();

    // Fetch Initial Data (Mock)
    renderLocations();
    renderProviders();

    function getCreds() {
        const authUrl = apiAuthUrl.value.trim();
        const baseUrl = apiBaseUrl.value.trim();
        const clientId = apiClientId.value.trim();
        const clientSecret = apiClientSecret.value.trim();
        const username = apiUsername.value.trim();
        const password = apiPassword.value.trim();

        if (!authUrl || !baseUrl || !clientId || !clientSecret || !username) {
            alert('Please enter Auth URL, API URL, Client ID, Client Secret, and Username.');
            return null;
        }
        return { auth_url: authUrl, base_url: baseUrl, client_id: clientId, client_secret: clientSecret, username, password };
    }

    // Handle Fetch Locations
    btnFetchApi.addEventListener('click', async () => {
        const creds = getCreds();
        if (!creds) return;

        fetchStatus.textContent = 'Fetching Locations...';
        fetchStatus.className = 'ms-2 text-warning';
        btnFetchApi.disabled = true;

        try {
            const res = await fetch('/api/fetch-locations', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(creds)
            });

            if (!res.ok) {
                const err = await res.json();
                throw new Error(err.detail || 'Fetch failed');
            }

            const data = await res.json();
            
            // Update Data
            allLocations = data.locations;
            // Reset downstream data
            allProviders = [];
            allProductionTypes = [];
            allOperatories = [];
            selectedProviders.clear();
            
            // Re-render
            renderLocations();
            renderProviders(); // Clear providers
            renderProductionTypes(); // Clear PTs
            
            fetchStatus.textContent = 'Locations Fetched! Select locations and click Fetch Production Type per Location.';
            fetchStatus.className = 'ms-2 text-success';
            btnFetchDetails.disabled = false;
        } catch (err) {
            console.error(err);
            fetchStatus.textContent = 'Error: ' + err.message;
            fetchStatus.className = 'ms-2 text-danger';
        } finally {
            btnFetchApi.disabled = false;
        }
    });

    // Handle Fetch Details
    if (btnFetchDetails) {
        btnFetchDetails.addEventListener('click', async () => {
            const creds = getCreds();
            if (!creds) return;

            const selectedLocs = Array.from(document.querySelectorAll('.location-checkbox:checked')).map(cb => parseInt(cb.value));

            if (selectedLocs.length === 0) {
                alert('Please select at least one location.');
                return;
            }

            fetchStatus.textContent = 'Fetching Production Types per Location...';
            fetchStatus.className = 'ms-2 text-warning';
            btnFetchDetails.disabled = true;

            try {
                const payload = { ...creds, selected_location_ids: selectedLocs };
                const res = await fetch('/api/fetch-details', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });

                if (!res.ok) {
                    const err = await res.json();
                    throw new Error(err.detail || 'Fetch details failed');
                }

                const data = await res.json();
                allProviders = data.providers;
                allProductionTypes = data.production_types;
                allOperatories = data.operatories;

                renderProviders();
                selectedProviders.clear();
                renderProductionTypes();

                fetchStatus.textContent = 'Production Types & Details Fetched!';
                fetchStatus.className = 'ms-2 text-success';
            } catch (err) {
                console.error(err);
                fetchStatus.textContent = 'Error: ' + err.message;
                fetchStatus.className = 'ms-2 text-danger';
            } finally {
                btnFetchDetails.disabled = false;
            }
        });
    }

    // Handle Fetch Users
    if (btnFetchUsers) {
        btnFetchUsers.addEventListener('click', async () => {
            const creds = getCreds();
            if (!creds) return;

            fetchStatus.textContent = 'Fetching Providers...';
            fetchStatus.className = 'ms-2 text-warning';
            btnFetchUsers.disabled = true;
            
            // Hide previous results
            usersCard.classList.add('d-none');
            usersTableBody.innerHTML = '';

            try {
                const res = await fetch('/api/fetch-users', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(creds)
                });

                if (!res.ok) {
                    const err = await res.json();
                    throw new Error(err.detail || 'Fetch users failed');
                }

                const data = await res.json();
                console.log('Users Data:', data);

                let users = [];
                // Handle different response structures (Array or Grid Response with Items)
                if (Array.isArray(data)) {
                    users = data;
                } else if (data.Items && Array.isArray(data.Items)) {
                    users = data.Items;
                } else if (data.items && Array.isArray(data.items)) {
                    users = data.items;
                }

                if (users.length > 0) {
                    fetchedUsers = users;
                    usersCard.classList.remove('d-none');
                    usersTableBody.innerHTML = users.map(u => `
                        <tr>
                            <td>${u.UserDetailID || u.Id || u.id || 'N/A'}</td>
                            <td>${u.UserFullName || u.Name || u.name || ((u.FirstName || '') + ' ' + (u.LastName || '')).trim() || 'N/A'}</td>
                            <td>${u.UserName || u.userName || u.username || 'N/A'}</td>
                            <td>${u.ProviderID || 'N/A'}</td>
                            <td>${u.ProviderType || 'N/A'}</td>
                            <td>${u.SpecialtyID || 'N/A'}</td>
                            <td>${u.Role || 'N/A'}</td>
                            <td>${u.Location || 'N/A'}</td>
                            <td>${u.MaxConcurrentAppointments || 'N/A'}</td>
                        </tr>
                    `).join('');
                    
                    fetchStatus.textContent = `Fetched ${users.length} providers.`;
                    fetchStatus.className = 'ms-2 text-success';
                } else {
                    fetchStatus.textContent = 'No providers found.';
                    fetchStatus.className = 'ms-2 text-warning';
                }

            } catch (err) {
                console.error(err);
                fetchStatus.textContent = 'Error: ' + err.message;
                fetchStatus.className = 'ms-2 text-danger';
            } finally {
                btnFetchUsers.disabled = false;
            }
        });
    }

    // Handle Fetch Scheduler Production Types
    if (btnFetchSchedulerPT) {
        btnFetchSchedulerPT.addEventListener('click', async () => {
            const creds = getCreds();
            if (!creds) return;

            fetchStatus.textContent = 'Fetching Scheduler Production Types...';
            fetchStatus.className = 'ms-2 text-warning';
            btnFetchSchedulerPT.disabled = true;

            // Hide previous results
            schedulerPTCard.classList.add('d-none');
            schedulerPTTableBody.innerHTML = '';

            try {
                const res = await fetch('/api/fetch-scheduler-production-types', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(creds)
                });

                if (!res.ok) {
                    const err = await res.json();
                    throw new Error(err.detail || 'Fetch failed');
                }

                const data = await res.json();
                console.log('Scheduler PT Data:', data);

                if (data.length > 0) {
                    fetchedSchedulerPTs = data;
                    schedulerPTCard.classList.remove('d-none');
                    schedulerPTTableBody.innerHTML = data.map(pt => `
                        <tr>
                            <td>${pt.id}</td>
                            <td>${pt.name}</td>
                            <td>${pt.providerSpeciality}</td>
                        </tr>
                    `).join('');
                    
                    fetchStatus.textContent = `Fetched ${data.length} production types.`;
                    fetchStatus.className = 'ms-2 text-success';
                } else {
                    fetchStatus.textContent = 'No production types found.';
                    fetchStatus.className = 'ms-2 text-warning';
                }

            } catch (err) {
                console.error(err);
                fetchStatus.textContent = 'Error: ' + err.message;
                fetchStatus.className = 'ms-2 text-danger';
            } finally {
                btnFetchSchedulerPT.disabled = false;
            }
        });
    }

    // Handle Match Specialty
    if (btnMatchSpecialty) {
        btnMatchSpecialty.addEventListener('click', () => {
            if (fetchedUsers.length === 0 || fetchedSchedulerPTs.length === 0) {
                alert('Please fetch both Providers and Scheduler Production Types first.');
                return;
            }

            matchedSpecialistsCard.classList.add('d-none');
            matchedSpecialistsTableBody.innerHTML = '';
            
            const matches = [];

            fetchedUsers.forEach(user => {
                const userSpecId = user.SpecialtyID;
                if (!userSpecId) return;

                const userSpecStr = String(userSpecId);
                
                fetchedSchedulerPTs.forEach(pt => {
                   const ptSpecs = pt.providerSpeciality ? pt.providerSpeciality.split(',').map(s => s.trim()) : [];
                   if (ptSpecs.includes(userSpecStr)) {
                       matches.push({
                           providerName: user.UserFullName || user.Name || user.name || ((user.FirstName || '') + ' ' + (user.LastName || '')).trim(),
                           providerSpecId: userSpecId,
                           ptName: pt.name,
                           ptId: pt.id,
                           ptSpecs: pt.providerSpeciality
                       });
                   }
                });
            });

            if (matches.length > 0) {
                matchedSpecialistsCard.classList.remove('d-none');
                matchedSpecialistsTableBody.innerHTML = matches.map(m => `
                    <tr>
                        <td>${m.providerName}</td>
                        <td>${m.providerSpecId}</td>
                        <td>${m.ptName}</td>
                        <td>${m.ptId}</td>
                        <td>${m.ptSpecs}</td>
                    </tr>
                `).join('');
                fetchStatus.textContent = `Found ${matches.length} matches based on Specialty ID.`;
                fetchStatus.className = 'ms-2 text-success';
            } else {
                 fetchStatus.textContent = 'No matches found based on Specialty ID.';
                 fetchStatus.className = 'ms-2 text-warning';
            }
        });
    }

    // Render Locations
    function renderLocations() {
        locationsContainer.innerHTML = allLocations.map(loc => `
            <div class="form-check">
                <input class="form-check-input location-checkbox" type="checkbox" value="${loc.id}" id="loc-${loc.id}">
                <label class="form-check-label" for="loc-${loc.id}">
                    <strong>${loc.name}</strong> - ${loc.address} (${loc.phone})
                </label>
            </div>
        `).join('');
    }

    // Render Providers
    function renderProviders(filterText = '') {
        const filtered = allProviders.filter(p => 
            p.name.toLowerCase().includes(filterText.toLowerCase()) || 
            p.specialty.toLowerCase().includes(filterText.toLowerCase())
        );

        providersContainer.innerHTML = filtered.map(p => `
            <div class="form-check">
                <input class="form-check-input provider-checkbox" type="checkbox" value="${p.id}" id="prov-${p.id}" ${selectedProviders.has(p.id.toString()) ? 'checked' : ''}>
                <label class="form-check-label" for="prov-${p.id}">
                    <strong>${p.name}</strong> (${p.specialty}) - Concurrency: ${p.concurrency}
                </label>
            </div>
        `).join('');

        // Re-attach event listeners
        document.querySelectorAll('.provider-checkbox').forEach(cb => {
            cb.addEventListener('change', handleProviderChange);
        });
    }

    // Search Providers
    providerSearch.addEventListener('input', (e) => {
        renderProviders(e.target.value);
    });

    // Handle Provider Selection
    function handleProviderChange(e) {
        const providerId = e.target.value;
        if (e.target.checked) {
            selectedProviders.add(providerId);
        } else {
            selectedProviders.delete(providerId);
        }
        renderProductionTypes();
    }

    // Render Production Types per Selected Provider
    function renderProductionTypes() {
        if (selectedProviders.size === 0) {
            productionTypesContainer.innerHTML = '<p class="text-muted">Select providers above to see production types.</p>';
            return;
        }

        productionTypesContainer.innerHTML = Array.from(selectedProviders).map(pid => {
            const provider = allProviders.find(p => p.id == pid);
            if (!provider) return '';
            
            return `
                <div class="mb-3 border-bottom border-secondary pb-2">
                    <h5>${provider.name} <small class="text-muted">(${provider.specialty})</small></h5>
                    <input type="text" class="form-control mb-2 bg-dark text-white border-secondary btn-sm" placeholder="Filter types..." onkeyup="filterPT(this, '${pid}')">
                    <div class="pt-list-container" id="pt-container-${pid}">
                        ${allProductionTypes.map(pt => `
                            <div class="form-check pt-item">
                                <input class="form-check-input pt-checkbox" type="checkbox" value="${pt.id}" data-provider="${pid}" id="pt-${pid}-${pt.id}">
                                <label class="form-check-label" for="pt-${pid}-${pt.id}">
                                    ${pt.name} (${pt.specialty}) - ${pt.duration} mins
                                </label>
                            </div>
                        `).join('')}
                    </div>
                </div>
            `;
        }).join('');
    }

    // Expose filter function globally
    window.filterPT = function(input, pid) {
        const filter = input.value.toLowerCase();
        const container = document.getElementById(`pt-container-${pid}`);
        const items = container.querySelectorAll('.pt-item');
        items.forEach(item => {
            const text = item.textContent.toLowerCase();
            item.style.display = text.includes(filter) ? '' : 'none';
        });
    };

    // Validate
    btnValidate.addEventListener('click', async () => {
        const selectedLocationIds = Array.from(document.querySelectorAll('.location-checkbox:checked')).map(cb => parseInt(cb.value));
        const selectedProviderIds = Array.from(selectedProviders).map(id => parseInt(id));
        
        const selectedProductionTypeIds = {};
        document.querySelectorAll('.pt-checkbox:checked').forEach(cb => {
            const pid = parseInt(cb.dataset.provider);
            const ptid = parseInt(cb.value);
            if (!selectedProductionTypeIds[pid]) selectedProductionTypeIds[pid] = [];
            selectedProductionTypeIds[pid].push(ptid);
        });

        const payload = {
            selected_location_ids: selectedLocationIds,
            selected_provider_ids: selectedProviderIds,
            selected_production_type_ids: selectedProductionTypeIds,
            locations: allLocations,
            providers: allProviders,
            production_types: allProductionTypes,
            operatories: allOperatories
        };

        try {
            const res = await fetch('/api/validate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            const result = await res.json();
            
            showValidationResults(result);
        } catch (err) {
            console.error(err);
            alert('Validation failed to run.');
        }
    });

    function showValidationResults(result) {
        validationResults.classList.remove('d-none');
        validationResults.classList.remove('alert-success', 'alert-danger', 'alert-warning');
        
        if (result.errors.length === 0 && result.warnings.length === 0) {
            validationResults.classList.add('alert-success');
            validationContent.innerHTML = '<strong>Success!</strong> Configuration is valid.';
        } else {
            validationResults.classList.add(result.errors.length > 0 ? 'alert-danger' : 'alert-warning');
            let html = '';
            if (result.errors.length > 0) {
                html += '<h5>Critical Errors:</h5><ul>' + result.errors.map(e => `<li>${e}</li>`).join('') + '</ul>';
            }
            if (result.warnings.length > 0) {
                html += '<h5>Warnings:</h5><ul>' + result.warnings.map(w => `<li>${w}</li>`).join('') + '</ul>';
            }
            validationContent.innerHTML = html;
        }
    }

    // Save
    btnSave.addEventListener('click', async () => {
        const selectedProductionTypeIds = {};
        document.querySelectorAll('.pt-checkbox:checked').forEach(cb => {
            const pid = parseInt(cb.dataset.provider);
            const ptid = parseInt(cb.value);
            if (!selectedProductionTypeIds[pid]) selectedProductionTypeIds[pid] = [];
            selectedProductionTypeIds[pid].push(ptid);
        });

        const payload = {
            locations: Array.from(document.querySelectorAll('.location-checkbox:checked')).map(cb => cb.value),
            providers: Array.from(selectedProviders),
            productionTypes: selectedProductionTypeIds,
            excludedInsurance: document.getElementById('excludedInsurance').value,
            notes: document.getElementById('additionalNotes').value,
            botEnabled: document.getElementById('botFunctionality').checked,
            full_locations: allLocations,
            full_providers: allProviders,
            full_production_types: allProductionTypes
        };
        
        try {
            const res = await fetch('/api/save-config-excel', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            
            if (res.ok) {
                const blob = await res.blob();
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = 'voicebot_config.xlsx';
                document.body.appendChild(a); // Required for firefox
                a.click();
                a.remove();
            } else {
                alert("Failed to generate Excel file.");
            }
        } catch (err) {
            console.error(err);
            alert("Error saving configuration.");
        }
    });

    // Reset
    btnReset.addEventListener('click', () => {
        if(confirm('Reset all selections?')) {
            window.location.reload();
        }
    });

});
