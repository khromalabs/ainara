// Ainara AI Companion Framework Project
// Copyright (C) 2025 Rubén Gómez - khromalabs.org
//
// This file is dual-licensed under:
// 1. GNU Lesser General Public License v3.0 (LGPL-3.0)
//    (See the included LICENSE_LGPL3.txt file or look into
//    <https://www.gnu.org/licenses/lgpl-3.0.html> for details)
// 2. Commercial license
//    (Contact: rgomez@khromalabs.org for licensing options)
//
// You may use, distribute and modify this code under the terms of either license.
// This notice must be preserved in all copies or substantial portions of the code.
//
// This program is distributed in the hope that it will be useful,
// but WITHOUT ANY WARRANTY; without even the implied warranty of
// MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
// Lesser General Public License for more details.

const utils = require('../core/utils');

module.exports = {
    id: 'skills',

    async init(ctx) {
        await generateSkillsUI(ctx);
    },

    async save(ctx) {
        await saveSkillsConfig(ctx);
    },

    validate(ctx) {
        return true; // Skills are optional
    },

    updateNextButtonState(ctx) {
        updateSkillsNextButtonState(ctx);
    }
};

async function generateSkillsUI(ctx) {
    // Reset validation status when UI is generated
    ctx.state.initialSkillValues = {};
    ctx.state.skillValidationStatus = {};

    try {
        // Load the sample config from the API instead of the file
        const response = await fetch(
            ctx.config.get('pybridge.api_url') + '/config/defaults'
        );

        if (!response.ok) {
            throw new Error('Failed to load default configuration');
        }

        const sampleConfig = await response.json();

        // Load ACTUAL config to populate email table
        const backendConfig = await ctx.api.loadBackendConfig();

        // Fetch capabilities to find schedulable ones
        const capsResponse = await fetch(ctx.config.get('orakle.api_url') + '/capabilities?view=full');
        const capabilities = await capsResponse.json();

        // Extract API keys
        const apiKeys = utils.extractApiKeysFromConfig(sampleConfig);

        // Add event to load capabilities when navigating to finish step
        const observer = new MutationObserver((mutations) => {
            mutations.forEach((mutation) => {
                if (mutation.type === 'attributes' && mutation.attributeName === 'class') {
                    const finishPanel = document.getElementById('finish-panel');
                    if (finishPanel && finishPanel.classList.contains('active')) {
                        ctx.loadAndDisplayCapabilities().catch(err => {
                            console.error('Error loading capabilities:', err);
                        });
                    }
                }
            });
        });

        const finishPanel = document.getElementById('finish-panel');
        if (finishPanel) {
            observer.observe(finishPanel, { attributes: true });
        }

        // Group keys by category
        const categories = new Map();

        // Ensure Messaging category exists for Email table, even if no other messaging keys exist
        if (!categories.has('messaging')) {
            categories.set('messaging', []);
        }

        // Group by top-level category first
        for (const [parentPath, keyGroup] of Object.entries(apiKeys)) {
            const pathParts = parentPath.split('.');
            const category = pathParts[0];

            // Skip stt and llm categories as they've been processed in previous slides
            if (category === 'stt' || category === 'llm') {
                continue;
            }

            if (!categories.has(category)) {
                categories.set(category, []);
            }

            categories.get(category).push({
                parentPath,
                displayName: keyGroup.displayName,
                keys: keyGroup.keys
            });
        }

        const orderedCategoriesEntries = new Map([...categories.entries()].sort());

        // Prepare content buffers
        let generalApiHtml = '';
        let messagingHtml = '';

        // Generate HTML for each category
        for (const [category, keyGroups] of orderedCategoriesEntries) {
            // Only skip if empty AND not messaging (messaging might need to show email table)
            if (keyGroups.length === 0 && category !== 'messaging') continue;

            let sectionHtml = `
                <div class="skill-category ${category.charAt(0).toUpperCase() + category.slice(1)}">
                    <h3>${category.charAt(0).toUpperCase() + category.slice(1)}</h3>
                    <div class="skill-items">
            `;

            keyGroups.forEach(group => {
                sectionHtml += `
                    <div class="skill-item" data-group-path="${group.parentPath}">
                        <h4>${group.displayName} <span class="skill-validation-status" id="status-${group.parentPath.replace(/\./g, '-')}"></span></h4>
                        <div class="skill-validation-message" id="message-${group.parentPath.replace(/\./g, '-')}"></div>
                `;

                // Use the description from the first key in the group
                if (group.keys.length > 0 && group.keys[0].description) {
                    if (group.keys[0].description.text) {
                        sectionHtml += `<p>${group.keys[0].description.text}</p>`;
                    }

                    if (group.keys[0].description.url) {
                        sectionHtml += `<p>Get API key(s) from: <a href="#" class="external-link" data-url="${group.keys[0].description.url}">${new URL(group.keys[0].description.url).hostname}</a></p>`;
                    }
                }

                // Add all keys for this group
                group.keys.forEach(key => {
                    sectionHtml += `
                        <div class="form-group">
                            <label for="api-key-${key.path.replace(/\./g, '-')}">${key.displayName}:</label>
                            <input type="text" placeholder="${key.keyName}" id="api-key-${key.path.replace(/\./g, '-')}" data-path="${key.path}">
                        </div>
                    `;
                });

                sectionHtml += `</div>`;
            });

            // INJECT EMAIL TABLE FOR MESSAGING CATEGORY
            if (category === 'messaging') {
               sectionHtml += generateEmailTableHtml(backendConfig);
               sectionHtml += `</div></div>`;
               messagingHtml += sectionHtml;
            } else {
               sectionHtml += `</div></div>`;
               generalApiHtml += sectionHtml;
            }
        }

        // Generate Schedule UI
        const scheduleHtml = generateScheduleUI(capabilities, backendConfig);

        // Generate User Skills UI (no validation yet)
        const userSkillsHtml = `
            <div class="skill-category UserSkills">
                <h3>User Skills</h3>
                <p>Select a directory containing your own Python skills.</p>
                <div class="form-group">
                    <label for="user-skills-directory">User Skills Directory:</label>
                    <div style="display:flex; align-items:center; gap:10px;">
                        <input type="text" id="user-skills-directory" placeholder="e.g., ~/my_skills" style="flex:1;">
                        <button id="browse-user-skills-btn" class="btn btn-secondary">Browse…</button>
                    </div>
                    <p class="field-description">Leave empty to disable user skills.</p>
                </div>
            </div>
        `;

        // Construct the Layout with Top Menu
        const layoutHtml = `
            <div class="skills-layout">
                <div class="skills-nav-bar">
                    <div class="skills-nav-item active" data-target="section-api-keys">API Keys</div>
                    <div class="skills-nav-item" data-target="section-messaging">Messaging</div>
                    <div class="skills-nav-item" data-target="section-scheduler">Scheduled Skills</div>
                    <div class="skills-nav-item" data-target="section-user-skills">User Skills</div>
                </div>
                <div class="skills-content-area">
                    <div id="section-api-keys" class="skills-section-anchor">
                        ${generalApiHtml}
                    </div>
                    <div id="section-messaging" class="skills-section-anchor">
                        ${messagingHtml}
                    </div>
                    <div id="section-scheduler" class="skills-section-anchor">
                        ${scheduleHtml}
                    </div>
                    <div id="section-user-skills" class="skills-section-anchor">
                        ${userSkillsHtml}
                    </div>

                    <div class="validate-all-container" style="text-align: center; margin-top: 40px; margin-bottom: 10px; display: flex; justify-content: center; gap: 10px;">
                        <button id="reset-skills-btn" class="btn btn-secondary">Reset Changes</button>
                        <button id="validate-all-keys-btn" class="btn">Validate API Keys</button>
                    </div>
                </div>
            </div>
        `;

        // Update the skills list container
        const skillsListContainer = document.querySelector('.skills-list');
        if (skillsListContainer) {
            skillsListContainer.innerHTML = layoutHtml;
        }

        // Setup Navigation Logic
        setupSkillsNavigation();

        // Add event listeners to all input fields
        document.querySelectorAll('.skills-list input[data-path]').forEach(input => {
            input.addEventListener('input', (event) => ctx.handleInputChange(event));
        });

        // Add event listener for the main validation button
        document.getElementById('validate-all-keys-btn').addEventListener('click', () => validateAllApiKeys(ctx));

        // Add event listener for the reset button
        document.getElementById('reset-skills-btn').addEventListener('click', () => resetApiKeys(ctx));

        // SETUP EMAIL TABLE LISTENERS
        setupEmailTableListeners(ctx);

        // SETUP SCHEDULE LISTENERS
        setupScheduleListeners(ctx);

        // SETUP USER SKILLS DIRECTORY LISTENERS
        const userSkillsInput = document.getElementById('user-skills-directory');
        const browseUserSkillsBtn = document.getElementById('browse-user-skills-btn');

        if (userSkillsInput) {
            // Load existing value from backend config
            if (backendConfig?.user_skills?.directory) {
                userSkillsInput.value = backendConfig.user_skills.directory;
            }

            userSkillsInput.addEventListener('input', () => {
                ctx.modifiedFields.skills.add('user_skills');
                updateSkillsNextButtonState(ctx);
            });

            if (browseUserSkillsBtn) {
                browseUserSkillsBtn.addEventListener('click', () => {
                    ctx.ipcRenderer.send('select-user-skills-directory');
                });
            }
        }

        // Load existing values from config
        await loadExistingApiKeys(ctx);

        // Store initial values and set initial validation status
        document.querySelectorAll('.skills-list input[data-path]').forEach(input => {
            ctx.state.initialSkillValues[input.dataset.path] = input.value;
        });
        document.querySelectorAll('.skill-item').forEach(item => {
            const groupPath = item.dataset.groupPath;
            // Initially, all skills are considered valid for navigation until changed.
            ctx.state.skillValidationStatus[groupPath] = 'success';
        });

        updateSkillsNextButtonState(ctx);

    } catch (error) {
        console.error('Error generating skills UI:', error);
        const skillsListContainer = document.querySelector('.skills-list');
        if (skillsListContainer) {
            skillsListContainer.innerHTML = `
                <div class="error">
                    Error loading API keys: ${error.message}
                </div>
            `;
        }
    }
}

function resetApiKeys(ctx) {
    // Restore input values from stored initial state
    document.querySelectorAll('.skills-list input[data-path]').forEach(input => {
        const path = input.dataset.path;
        input.value = ctx.state.initialSkillValues[path] || '';
    });

    // Reset all validation statuses and UI indicators
    document.querySelectorAll('.skill-item').forEach(item => {
        const groupPath = item.dataset.groupPath;
        ctx.state.skillValidationStatus[groupPath] = 'success';

        const statusElement = document.getElementById(`status-${groupPath.replace(/\./g, '-')}`);
        if (statusElement) {
            statusElement.className = 'skill-validation-status';
        }
        const messageElement = document.getElementById(`message-${groupPath.replace(/\./g, '-')}`);
        if (messageElement) {
            messageElement.textContent = '';
            messageElement.className = 'skill-validation-message';
        }
    });

    // Clear the set of modified fields for skills
    ctx.modifiedFields.skills.clear();

    // Re-enable the next button
    updateSkillsNextButtonState(ctx);
}

async function loadExistingApiKeys(ctx) {
    try {
        // Load backend config
        const backendConfig = await ctx.api.loadBackendConfig();

        // Helper function to get value at path
        function getValueAtPath(obj, path) {
            const parts = path.split('.');
            let current = obj;

            for (const part of parts) {
                if (current === undefined || current === null || typeof current !== 'object') {
                    return undefined;
                }
                current = current[part];
            }

            return current;
        }

        // Find all API key inputs
        document.querySelectorAll('input[data-path]').forEach(input => {
            const path = input.dataset.path;
            const value = getValueAtPath(backendConfig, path);

            if (value && value !== '<key>') {
                input.value = value;
            }
        });

    } catch (error) {
        console.error('Error loading existing API keys:', error);
    }
}

async function validateAllApiKeys(ctx) {
    const validateButton = document.getElementById('validate-all-keys-btn');
    validateButton.disabled = true;
    validateButton.textContent = 'Validating...';

    const validationPromises = [];
    const groupsToValidate = [];

    document.querySelectorAll('.skill-item').forEach(item => {
        const groupPath = item.dataset.groupPath;
        const serviceName = groupPath.split('.').pop();
        const statusElement = document.getElementById(`status-${groupPath.replace(/\./g, '-')}`);
        const messageElement = document.getElementById(`message-${groupPath.replace(/\./g, '-')}`);
        if (messageElement) {
            messageElement.textContent = '';
            messageElement.className = 'skill-validation-message';
        }

        let hasValue = false;
        const keys = {};
        item.querySelectorAll('input[data-path]').forEach(input => {
            const value = input.value.trim();
            if (value) {
                hasValue = true;
            }
            const keyName = input.dataset.path.split('.').pop();
            keys[keyName] = value;
        });

        if (hasValue) {
            groupsToValidate.push({ groupPath, serviceName, keys, statusElement, messageElement });
        } else {
            // If no value, it's considered valid for progression, clear status
            if (statusElement) statusElement.className = 'skill-validation-status';
            if (messageElement) messageElement.textContent = '';
            ctx.state.skillValidationStatus[groupPath] = 'success';
        }
    });

    groupsToValidate.forEach(group => {
        if (group.statusElement) {
            group.statusElement.className = 'skill-validation-status pending';
        }
        ctx.state.skillValidationStatus[group.groupPath] = 'validating';

        const promise = fetch(
            ctx.config.get('pybridge.api_url') + '/test-skill-key',
            {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ service: group.serviceName, keys: group.keys })
            }
        )
        .then(response => response.json())
        .then(result => ({ ...group, result }))
        .catch(error => ({ ...group, result: { success: false, message: error.message } }));

        validationPromises.push(promise);
    });

    const results = await Promise.all(validationPromises);

    results.forEach(res => {
        if (res.result.success) {
            if (res.statusElement) res.statusElement.className = 'skill-validation-status success';
            ctx.state.skillValidationStatus[res.groupPath] = 'success';
            if (res.messageElement) {
                res.messageElement.textContent = 'Success!';
                res.messageElement.className = 'skill-validation-message success';
            }
        } else {
            if (res.statusElement) res.statusElement.className = 'skill-validation-status error';
            ctx.state.skillValidationStatus[res.groupPath] = 'error';
            if (res.messageElement) {
                res.messageElement.textContent = `Failed: ${res.result.message || 'Unknown error'}`;
                res.messageElement.className = 'skill-validation-message error';
            }
        }
    });

    updateSkillsNextButtonState(ctx);

    validateButton.disabled = false;
    validateButton.textContent = 'Validate API Keys';
}

function updateSkillsNextButtonState(ctx) {
    const nextButton = document.getElementById('main-next-btn');
    if (!nextButton) return;

    const allValid = Object.values(ctx.state.skillValidationStatus).every(status => status === 'success');
    nextButton.disabled = !allValid;
}

async function saveSkillsConfig(ctx) {
    const userSkillsInput = document.getElementById('user-skills-directory');
    // If no skill fields were modified and there's no user skills field, skip saving
    if (ctx.modifiedFields.skills.size === 0 && !userSkillsInput) {
        return;
    }

    try {
        // Load current backend config
        const backendConfig = await ctx.api.loadBackendConfig();

        // Helper function to set value at path
        function setValueAtPath(obj, path, value) {
            const parts = path.split('.');
            let current = obj;

            for (let i = 0; i < parts.length - 1; i++) {
                const part = parts[i];
                if (!(part in current)) {
                    current[part] = {};
                }
                current = current[part];
            }

            current[parts[parts.length - 1]] = value;
        }

        // Only update modified API keys
        document.querySelectorAll('input[data-path]').forEach(input => {
            const path = input.dataset.path;
            if (ctx.modifiedFields.skills.has(path)) {
                const value = input.value.trim();
                // Save the value, even if it's empty, to allow clearing keys.
                setValueAtPath(backendConfig, path, value);
            }
        });

        // SAVE EMAIL ACCOUNTS
        if (ctx.modifiedFields.skills.has('apis.messaging.email')) {
            const emailAccounts = [];
            const rows = document.querySelectorAll('#email-accounts-table .email-row:not(.ghost)');

            rows.forEach(row => {
                const id = row.querySelector('.email-id').value.trim();
                const host = row.querySelector('.email-host').value.trim();
                const port = row.querySelector('.email-port').value.trim();
                const user = row.querySelector('.email-user').value.trim();
                const pass = row.querySelector('.email-pass').value.trim();

                if (id && host && user && pass) {
                    const accountObj = {
                        id: id,
                        imap_host: host,
                        username: user,
                        password: pass
                    };
                    if (port) accountObj.imap_port = parseInt(port);
                    emailAccounts.push(accountObj);
                }
            });

            // Ensure structure exists
            if (!backendConfig.apis) backendConfig.apis = {};
            if (!backendConfig.apis.messaging) backendConfig.apis.messaging = {};
            if (!backendConfig.apis.messaging.email) backendConfig.apis.messaging.email = {};

            backendConfig.apis.messaging.email.accounts = emailAccounts;
        }

        // SAVE SCHEDULE OVERRIDES (Updated Logic)
        if (ctx.modifiedFields.skills.has('scheduler')) {
            if (!backendConfig.scheduler) backendConfig.scheduler = {};
            if (!backendConfig.scheduler.overrides) backendConfig.scheduler.overrides = {};

            document.querySelectorAll('.schedule-row').forEach(row => {
                const skillName = row.dataset.skill;
                const isEnabled = row.querySelector('.schedule-enable').checked;
                const minutes = parseInt(row.querySelector('.schedule-interval').value);
                const isDefaultDefault = row.dataset.defaultDefault === "true";

                if (!isEnabled) {
                    // If disabled:
                    // - If default was enabled (true), we must explicitly set false.
                    // - If default was disabled (false), we can just remove the override key.
                    if (isDefaultDefault) {
                        backendConfig.scheduler.overrides[skillName] = false;
                    } else {
                        delete backendConfig.scheduler.overrides[skillName];
                    }
                } else {
                    // If enabled, we construct the full config object

                    // 1. Harvest Kwargs from UI
                    const uiKwargs = {};
                    const paramInputs = document.querySelectorAll(`.param-input[data-skill="${skillName}"]`);

                    paramInputs.forEach(input => {
                        const key = input.dataset.key;
                        const type = input.dataset.type;
                        let val = input.value;

                        if (type === 'boolean') {
                            val = (val === 'true');
                        } else if (type === 'integer') {
                            val = parseInt(val);
                            if (isNaN(val)) val = null; // Handle empty
                        } else if (type === 'number') {
                            val = parseFloat(val);
                            if (isNaN(val)) val = null;
                        } else if (type === 'array') {
                            // Split by comma and trim
                            val = val ? val.split(',').map(s => s.trim()).filter(s => s !== '') : [];
                        }

                        // Only add if not object placeholder (which is disabled)
                        if (!input.disabled) {
                            uiKwargs[key] = val;
                        }
                    });

                    // 2. Merge with existing kwargs to preserve hidden/complex objects
                    const existingOverride = backendConfig.scheduler.overrides[skillName];
                    const existingKwargs = (existingOverride && existingOverride !== false && existingOverride.kwargs)
                                           ? existingOverride.kwargs
                                           : {};

                    const finalKwargs = { ...existingKwargs, ...uiKwargs };

                    backendConfig.scheduler.overrides[skillName] = {
                        trigger: 'interval',
                        minutes: minutes,
                        kwargs: finalKwargs
                    };
                }
            });
        }

        // Save the updated backend config
        await ctx.api.saveBackendConfig(backendConfig, ctx.config.get('pybridge.api_url'));
        await ctx.api.saveBackendConfig(backendConfig, ctx.config.get('orakle.api_url'));

        // Clear modified fields after successful save
        ctx.modifiedFields.skills.clear();
    } catch (error) {
        console.error('Error updating skills config:', error);
    }
}

function generateEmailTableHtml(config) {
    const accounts = config?.apis?.messaging?.email?.accounts || [];

    let rowsHtml = '';

    const createRow = (acc, isGhost = false) => `
        <div class="email-row ${isGhost ? 'ghost' : ''}">
            <div class="email-cell"><input type="text" class="email-id" placeholder="ID (e.g. gmail)" value="${acc.id || ''}" ${isGhost ? '' : 'required'}></div>
            <div class="email-cell"><input type="text" class="email-host" placeholder="imap.email.com" value="${acc.imap_host || ''}" ${isGhost ? '' : 'required'}></div>
            <div class="email-cell"><input type="number" class="email-port" placeholder="993" value="${acc.imap_port || ''}"></div>
            <div class="email-cell"><input type="text" class="email-user" placeholder="user@email.com" value="${acc.username || ''}" ${isGhost ? '' : 'required'}></div>
            <div class="email-cell">
                <div class="password-wrapper">
                    <input type="password" class="email-pass" placeholder="Password" value="${acc.password || ''}" ${isGhost ? '' : 'required'}>
                    <button class="password-toggle" type="button" tabindex="-1">Show</button>
                </div>
            </div>
            <div class="email-cell">
                ${!isGhost ? '<button class="remove-email-btn" title="Remove account">&times;</button>' : ''}
            </div>
        </div>
    `;

    accounts.forEach(acc => {
        rowsHtml += createRow(acc, false);
    });

    rowsHtml += createRow({}, true);

    return `
        <div class="skill-item email-config-section" data-group-path="apis.messaging.email">
            <div class="email-config-header">
                <h4>Email Accounts</h4>
                <p>Configure IMAP accounts for email integration.</p>
            </div>
            <div class="email-config-table" id="email-accounts-table">
                <div class="email-col-header">ID</div>
                <div class="email-col-header">IMAP Host</div>
                <div class="email-col-header">Port</div>
                <div class="email-col-header">Username</div>
                <div class="email-col-header">Password</div>
                <div class="email-col-header"></div>
                ${rowsHtml}
            </div>
        </div>
    `;
}

function setupEmailTableListeners(ctx) {
    const table = document.getElementById('email-accounts-table');
    if (!table) return;

    table.addEventListener('click', (e) => {
        if (e.target.closest('.remove-email-btn')) {
            if (confirm('Remove this email account?')) {
                e.target.closest('.email-row').remove();
                ctx.modifiedFields.skills.add('apis.messaging.email');
                updateSkillsNextButtonState(ctx);
            }
        }

        if (e.target.classList.contains('password-toggle')) {
            const btn = e.target;
            const input = btn.previousElementSibling;
            if (input.type === 'password') {
                input.type = 'text';
                btn.textContent = 'Hide';
            } else {
                input.type = 'password';
                btn.textContent = 'Show';
            }
        }
    });

    table.addEventListener('input', (e) => {
        const row = e.target.closest('.email-row');
        if (!row) return;

        ctx.modifiedFields.skills.add('apis.messaging.email');
        updateSkillsNextButtonState(ctx);

        if (row.classList.contains('ghost')) {
            row.classList.remove('ghost');
            row.querySelectorAll('input').forEach(input => input.required = true);
            row.querySelector('.email-port').required = false;

            const actionCell = row.lastElementChild;
            actionCell.innerHTML = '<button class="remove-email-btn" title="Remove account">&times;</button>';

            const newGhostHtml = `
                <div class="email-row ghost">
                    <div class="email-cell"><input type="text" class="email-id" placeholder="ID (e.g. gmail)"></div>
                    <div class="email-cell"><input type="text" class="email-host" placeholder="imap.email.com"></div>
                    <div class="email-cell"><input type="number" class="email-port" placeholder="993"></div>
                    <div class="email-cell"><input type="text" class="email-user" placeholder="user@email.com"></div>
                    <div class="email-cell">
                        <div class="password-wrapper">
                            <input type="password" class="email-pass" placeholder="Password">
                            <button class="password-toggle" type="button" tabindex="-1">Show</button>
                        </div>
                    </div>
                    <div class="email-cell"></div>
                </div>
            `;
            table.insertAdjacentHTML('beforeend', newGhostHtml);
        }
    });
}

function generateScheduleUI(capabilities, backendConfig) {
    let rows = '';
    let hasSchedulable = false;

    const styles = `
        <style>
            .schedule-details-row { display: none; background-color: #f8f9fa; }
            .schedule-details-row.active { display: table-row; }
            .schedule-details-panel { padding: 15px; display: grid; grid-template-columns: repeat(auto-fill, minmax(250px, 1fr)); gap: 15px; border-bottom: 1px solid #eee; }
            .param-group { display: flex; flex-direction: column; }
            .param-group label { font-size: 0.85em; font-weight: bold; margin-bottom: 4px; color: #444; }
            .param-group .param-desc { font-size: 0.75em; color: #666; margin-top: 4px; line-height: 1.2; }
            .param-group input, .param-group select { padding: 6px; border: 1px solid #ddd; border-radius: 4px; font-size: 0.9em; }
            .settings-btn { background: none; border: none; cursor: pointer; font-size: 1.2em; padding: 0 10px; opacity: 0.6; transition: opacity 0.2s; }
            .settings-btn:hover, .settings-btn.active { opacity: 1; }
            .schedule-table td { vertical-align: middle; }
        </style>
    `;

    for (const [name, cap] of Object.entries(capabilities)) {
        if (cap.default_schedule) {
            hasSchedulable = true;
            const override = backendConfig.scheduler?.overrides?.[name];
            const defaultSched = cap.default_schedule;

            let isEnabled;
            if (defaultSched.default) {
                isEnabled = !(override === false);
            } else {
                isEnabled = typeof override !== "undefined" && override !== false;
            }

            const currentKwargs = (override && override !== false && override.kwargs)
                                  ? override.kwargs
                                  : (defaultSched.kwargs || {});

            const minutes = (override && override.minutes) ? override.minutes : (defaultSched.minutes || 10);
            const hasParams = cap.run_info?.parameters && Object.keys(cap.run_info.parameters).length > 0;

            rows += `
                <tr class="schedule-row" data-skill="${name}" data-default-default=${defaultSched.default || false} data-default-minutes="${defaultSched.minutes || 10}">
                    <td style="max-width: 100px">
                        <i>${name}</i>
                        <p style="font-size:0.8em; margin: 2px 0 0 0; color: #666;">${cap.description ? cap.description.trim().split('\n')[0] : ""}</p>
                    </td>
                    <td>
                        <label class="schedule-toggle">
                            <input type="checkbox" class="schedule-enable" ${isEnabled ? 'checked' : ''}>
                            Enable
                        </label>
                    </td>
                    <td>
                        Run every <input type="number" class="schedule-interval schedule-interval-input" value="${minutes}" min="1" ${isEnabled ? '' : 'disabled'} style="width: 60px;"> minutes
                    </td>
                    <td style="text-align: center;">
                        ${hasParams ? `<button class="settings-btn" style="display:none" data-skill="${name}" title="Configure Parameters">⚙️</button>` : ''}
                    </td>
                </tr>
                ${hasParams ? `
                <tr class="schedule-details-row" id="details-${name}">
                    <td colspan="4" style="padding: 0;">
                        <div class="schedule-details-panel">
                            ${utils.renderSkillParameters(name, cap, currentKwargs)}
                        </div>
                    </td>
                </tr>
                ` : ''}
            `;
        }
    }

    if (!hasSchedulable) return '';

    return `
        ${styles}
        <div class="schedule-config-section">
            <h3>Scheduled Skills</h3>
            <p>Configure automatic execution intervals and parameters for supported skills.</p>
            <table class="schedule-table">
                <thead>
                    <tr>
                        <th>Skill</th>
                        <th>Status</th>
                        <th>Frequency</th>
                        <th style="width: 50px;"></th>
                    </tr>
                </thead>
                <tbody>
                    ${rows}
                </tbody>
            </table>
        </div>
    `;
}

function setupScheduleListeners(ctx) {
    document.querySelectorAll('.schedule-row').forEach(row => {
        const checkbox = row.querySelector('.schedule-enable');
        const input = row.querySelector('.schedule-interval');
        const skillName = row.dataset.skill;

        checkbox.addEventListener('change', () => {
            input.disabled = !checkbox.checked;
            ctx.modifiedFields.skills.add('scheduler');
            updateSkillsNextButtonState(ctx);
        });

        input.addEventListener('input', () => {
            ctx.modifiedFields.skills.add('scheduler');
            updateSkillsNextButtonState(ctx);
        });

        const settingsBtn = row.querySelector('.settings-btn');
        if (settingsBtn) {
            settingsBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                const detailsRow = document.getElementById(`details-${skillName}`);
                const isActive = detailsRow.classList.contains('active');

                document.querySelectorAll('.schedule-details-row').forEach(el => el.classList.remove('active'));
                document.querySelectorAll('.settings-btn').forEach(el => el.classList.remove('active'));

                if (!isActive) {
                    detailsRow.classList.add('active');
                    settingsBtn.classList.add('active');
                }
            });
        }
    });

    document.querySelectorAll('.param-input').forEach(input => {
        input.addEventListener('change', () => {
            ctx.modifiedFields.skills.add('scheduler');
            updateSkillsNextButtonState(ctx);
        });
        if (input.tagName === 'INPUT' && input.type === 'text') {
             input.addEventListener('input', () => {
                ctx.modifiedFields.skills.add('scheduler');
             });
        }
    });
}

function setupSkillsNavigation() {
    const navItems = document.querySelectorAll('.skills-nav-item');
    const sections = document.querySelectorAll('.skills-section-anchor');
    const scrollContainer = document.querySelector('.step-content');

    navItems.forEach(item => {
        item.addEventListener('click', () => {
            const targetId = item.dataset.target;
            const targetElement = document.getElementById(targetId);
            if (targetElement) {
                targetElement.scrollIntoView({ behavior: 'smooth', block: 'start' });
            }
        });
    });

    if (scrollContainer) {
        scrollContainer.addEventListener('scroll', () => {
            let currentSectionId = '';

            sections.forEach(section => {
                const rect = section.getBoundingClientRect();
                if (rect.top < 200 && rect.bottom > 0) {
                    currentSectionId = section.id;
                }
            });

            if (currentSectionId) {
                navItems.forEach(item => {
                    if (item.dataset.target === currentSectionId) {
                        item.classList.add('active');
                    } else {
                        item.classList.remove('active');
                    }
                });
            }
        });
    }
}
