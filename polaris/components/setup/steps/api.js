const utils = require('../core/utils');

module.exports = {
    id: 'api',

    async init(ctx) {
        await generateApiUI(ctx);
    },

    async save(ctx) {
        await saveApiConfig(ctx);
    },

    validate(ctx) {
        return true; // All API keys are optional
    },

    updateNextButtonState(ctx) {
        updateApiNextButtonState(ctx);
    }
};

function isSensitivePath(path) {
    const keyName = path.split('.').pop().toLowerCase();
    const sensitiveKeys = ['api_key', 'apikey', 'secret', 'password', 'token'];
    return sensitiveKeys.some(key => keyName.includes(key));
}

async function generateApiUI(ctx) {
    // Reset validation state
    ctx.state.initialApiValues = {};
    ctx.state.apiValidationStatus = {};

    try {
        const response = await fetch(
            ctx.config.get('pybridge.api_url') + '/config/defaults'
        );
        if (!response.ok) throw new Error('Failed to load default configuration');
        const sampleConfig = await response.json();

        const backendConfig = await ctx.api.loadBackendConfig();

        const apiKeys = utils.extractApiKeysFromConfig(sampleConfig);

        // Group keys by category
        const categories = new Map();
        if (!categories.has('messaging')) categories.set('messaging', []);

        for (const [parentPath, keyGroup] of Object.entries(apiKeys)) {
            const category = parentPath.split('.')[0];
            if (category === 'stt' || category === 'llm') continue;
            if (!categories.has(category)) categories.set(category, []);
            categories.get(category).push({
                parentPath,
                displayName: keyGroup.displayName,
                keys: keyGroup.keys
            });
        }

        const orderedCategories = new Map([...categories.entries()].sort());

        let generalApiHtml = '';
        let messagingHtml = '';

        for (const [category, keyGroups] of orderedCategories) {
            if (keyGroups.length === 0 && category !== 'messaging') continue;

            let sectionHtml = `
                <div class="api-category ${category.charAt(0).toUpperCase() + category.slice(1)}">
                    <h3>${category.charAt(0).toUpperCase() + category.slice(1)}</h3>
                    <div class="api-items">
            `;

            keyGroups.forEach(group => {
                sectionHtml += `
                    <div class="api-group" data-group-path="${group.parentPath}">
                        <h4>${group.displayName} <span class="api-validation-status" id="api-status-${group.parentPath.replace(/\./g, '-')}"></span></h4>
                        <div class="api-validation-message" id="api-message-${group.parentPath.replace(/\./g, '-')}"></div>
                `;

                if (group.keys.length > 0 && group.keys[0].description) {
                    if (group.keys[0].description.text) {
                        sectionHtml += `<p>${group.keys[0].description.text}</p>`;
                    }
                    if (group.keys[0].description.url) {
                        sectionHtml += `<p>Get API key(s) from: <a href="#" class="external-link" data-url="${group.keys[0].description.url}">${new URL(group.keys[0].description.url).hostname}</a></p>`;
                    }
                }

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

            if (category === 'messaging') {
                sectionHtml += generateEmailTableHtml(backendConfig);
                sectionHtml += `</div></div>`;
                messagingHtml += sectionHtml;
            } else {
                sectionHtml += `</div></div>`;
                generalApiHtml += sectionHtml;
            }
        }

        const layoutHtml = `
            <div class="api-content">
                ${generalApiHtml}
                ${messagingHtml}
                <div class="api-actions">
                    <button id="reset-api-keys-btn" class="btn btn-secondary">Reset Changes</button>
                    <button id="validate-all-keys-btn" class="btn">Validate API Keys</button>
                </div>
            </div>
        `;

        const apiListContainer = document.getElementById('api-list');
        if (apiListContainer) {
            apiListContainer.innerHTML = layoutHtml;
        }

        // Input listeners
        document.querySelectorAll('#api-list input[data-path]').forEach(input => {
            input.addEventListener('input', (event) => ctx.handleInputChange(event));
        });

        // Action buttons
        document.getElementById('validate-all-keys-btn').addEventListener('click', () => validateAllApiKeys(ctx));
        document.getElementById('reset-api-keys-btn').addEventListener('click', () => resetApiKeys(ctx));

        // Email table listeners
        setupEmailTableListeners(ctx);

        // Load existing values
        await loadExistingApiKeys(ctx);

        // Store initial values and set initial validation status
        document.querySelectorAll('#api-list input[data-path]').forEach(input => {
            ctx.state.initialApiValues[input.dataset.path] = input.value;
        });
        document.querySelectorAll('.api-group').forEach(item => {
            const groupPath = item.dataset.groupPath;
            ctx.state.apiValidationStatus[groupPath] = 'success';
        });

        updateApiNextButtonState(ctx);

    } catch (error) {
        console.error('Error generating API UI:', error);
        const apiListContainer = document.getElementById('api-list');
        if (apiListContainer) {
            apiListContainer.innerHTML = `
                <div class="error">Error loading API configuration: ${error.message}</div>
            `;
        }
    }
}

function updateApiNextButtonState(ctx) {
    const nextButton = document.getElementById('main-next-btn');
    if (!nextButton) return;

    const allValid = Object.values(ctx.state.apiValidationStatus).every(status => status === 'success');
    nextButton.disabled = !allValid;
}

async function saveApiConfig(ctx) {
    const backendConfig = await ctx.api.loadBackendConfig();

    function getValueAtPath(obj, path) {
        const parts = path.split('.');
        let current = obj;
        for (const part of parts) {
            if (current === undefined || current === null || typeof current !== 'object') return undefined;
            current = current[part];
        }
        return current;
    }

    function setValueAtPath(obj, path, value) {
        const parts = path.split('.');
        let current = obj;
        for (let i = 0; i < parts.length - 1; i++) {
            const part = parts[i];
            if (!(part in current)) current[part] = {};
            current = current[part];
        }
        current[parts[parts.length - 1]] = value;
    }

    // Determine if there is anything to save:
    // - any modified field
    // - any plaintext sensitive field (for migration)
    const plaintextSensitiveExists = Array.from(
        document.querySelectorAll('#api-list input[data-path]')
    ).some(input => {
        const path = input.dataset.path;
        const value = getValueAtPath(backendConfig, path);
        return (
            value &&
            typeof value === 'string' &&
            !value.startsWith('enc:v1:') &&
            isSensitivePath(path)
        );
    });

    if (ctx.modifiedFields.api.size === 0 && !plaintextSensitiveExists) {
        return;
    }

    // Apply modified fields from inputs
    document.querySelectorAll('#api-list input[data-path]').forEach(input => {
        const path = input.dataset.path;
        if (ctx.modifiedFields.api.has(path)) {
            setValueAtPath(backendConfig, path, input.value.trim());
        }
    });

    // Save email accounts if modified (unchanged — passwords stay plaintext for now)
    // TODO(secrets): Encrypt email account passwords once ConfigManager path
    // resolution supports list indices (e.g. apis.messaging.email.accounts.0.password).
    // At that point, route them through vault.encrypt()/get_secret() just like
    // the api_key/secret fields above.
    if (ctx.modifiedFields.api.has('apis.messaging.email')) {
        const emailAccounts = [];
        const rows = document.querySelectorAll('#email-accounts-table .email-row:not(.ghost)');

        rows.forEach(row => {
            const id = row.querySelector('.email-id').value.trim();
            const host = row.querySelector('.email-host').value.trim();
            const port = row.querySelector('.email-port').value.trim();
            const user = row.querySelector('.email-user').value.trim();
            const pass = row.querySelector('.email-pass').value.trim();

            if (id && host && user && pass) {
                const accountObj = { id, imap_host: host, username: user, password: pass };
                if (port) accountObj.imap_port = parseInt(port);
                emailAccounts.push(accountObj);
            }
        });

        if (!backendConfig.apis) backendConfig.apis = {};
        if (!backendConfig.apis.messaging) backendConfig.apis.messaging = {};
        if (!backendConfig.apis.messaging.email) backendConfig.apis.messaging.email = {};
        backendConfig.apis.messaging.email.accounts = emailAccounts;
    }

    // Encrypt all plaintext sensitive fields (new or legacy) via the vault
    const vaultUrl = ctx.config.get('pybridge.api_url');
    const encryptPromises = [];
    document.querySelectorAll('#api-list input[data-path]').forEach(input => {
        const path = input.dataset.path;
        const value = getValueAtPath(backendConfig, path);

        if (
            value &&
            typeof value === 'string' &&
            !value.startsWith('enc:v1:') &&
            isSensitivePath(path)
        ) {
            encryptPromises.push(
                fetch(vaultUrl + '/vault/encrypt', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ path, value })
                })
                .then(response => response.json())
                .then(result => {
                    if (result.success) {
                        setValueAtPath(backendConfig, path, result.blob);
                    } else {
                        console.warn(`Vault encrypt failed for ${path}: ${result.error}`);
                    }
                })
                .catch(error => console.warn(`Vault encrypt error for ${path}:`, error))
            );
        }
    });

    await Promise.all(encryptPromises);

    // Save to both servers
    await ctx.api.saveBackendConfig(backendConfig, ctx.config.get('pybridge.api_url'));
    await ctx.api.saveBackendConfig(backendConfig, ctx.config.get('orakle.api_url'));

    ctx.modifiedFields.api.clear();
}

function resetApiKeys(ctx) {
    // Restore input values from stored initial state
    document.querySelectorAll('#api-list input[data-path]').forEach(input => {
        const path = input.dataset.path;
        input.value = ctx.state.initialApiValues[path] || '';
    });

    // Reset all validation statuses and UI indicators
    document.querySelectorAll('.api-group').forEach(item => {
        const groupPath = item.dataset.groupPath;
        ctx.state.apiValidationStatus[groupPath] = 'success';

        const statusElement = document.getElementById(`api-status-${groupPath.replace(/\./g, '-')}`);
        if (statusElement) {
            statusElement.className = 'api-validation-status';
        }
        const messageElement = document.getElementById(`api-message-${groupPath.replace(/\./g, '-')}`);
        if (messageElement) {
            messageElement.textContent = '';
            messageElement.className = 'api-validation-message';
        }
    });

    // Clear the set of modified fields for api
    ctx.modifiedFields.api.clear();

    // Re-enable the next button
    updateApiNextButtonState(ctx);
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

        // Collect all input paths and raw values
        const inputs = document.querySelectorAll('#api-list input[data-path]');
        const rawValues = {};
        const encryptedPaths = [];

        inputs.forEach(input => {
            const path = input.dataset.path;
            const value = getValueAtPath(backendConfig, path);
            rawValues[path] = value;

            if (
                value &&
                typeof value === 'string' &&
                value.startsWith('enc:v1:') &&
                isSensitivePath(path)
            ) {
                encryptedPaths.push(path);
            }
        });

        // Batch-decrpyt encrypted sensitive values
        let decryptedValues = {};
        if (encryptedPaths.length > 0) {
            try {
                const response = await fetch(
                    ctx.config.get('pybridge.api_url') + '/vault/reveal',
                    {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ paths: encryptedPaths })
                    }
                );
                const result = await response.json();
                if (result.success) {
                    decryptedValues = result.values;
                } else {
                    console.warn('Vault reveal failed:', result.errors);
                }
            } catch (error) {
                console.warn('Vault reveal error:', error);
            }
        }

        // Fill inputs with decrypted (or raw) values
        inputs.forEach(input => {
            const path = input.dataset.path;
            let value = decryptedValues[path] || rawValues[path];
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

    document.querySelectorAll('.api-group').forEach(item => {
        const groupPath = item.dataset.groupPath;
        const serviceName = groupPath.split('.').pop();
        const statusElement = document.getElementById(`api-status-${groupPath.replace(/\./g, '-')}`);
        const messageElement = document.getElementById(`api-message-${groupPath.replace(/\./g, '-')}`);
        if (messageElement) {
            messageElement.textContent = '';
            messageElement.className = 'api-validation-message';
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
            if (statusElement) statusElement.className = 'api-validation-status';
            if (messageElement) messageElement.textContent = '';
            ctx.state.apiValidationStatus[groupPath] = 'success';
        }
    });

    groupsToValidate.forEach(group => {
        if (group.statusElement) {
            group.statusElement.className = 'api-validation-status pending';
        }
        ctx.state.apiValidationStatus[group.groupPath] = 'validating';

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
            if (res.statusElement) res.statusElement.className = 'api-validation-status success';
            ctx.state.apiValidationStatus[res.groupPath] = 'success';
            if (res.messageElement) {
                res.messageElement.textContent = 'Success!';
                res.messageElement.className = 'api-validation-message success';
            }
        } else {
            if (res.statusElement) res.statusElement.className = 'api-validation-status error';
            ctx.state.apiValidationStatus[res.groupPath] = 'error';
            if (res.messageElement) {
                res.messageElement.textContent = `Failed: ${res.result.message || 'Unknown error'}`;
                res.messageElement.className = 'api-validation-message error';
            }
        }
    });

    updateApiNextButtonState(ctx);

    validateButton.disabled = false;
    validateButton.textContent = 'Validate API Keys';
}

function generateEmailTableHtml(config) {
    const accounts = config?.apis?.messaging?.email?.accounts || [];

    let rowsHtml = '';

    const createRow = (acc, isGhost = false) => `
        <div class="email-row ${isGhost ? 'ghost' : ''}">
            <div class="email-cell"><input type="text" class="email-id" placeholder="ID (e.g. gmail)" value="${acc.id || ''}" ${isGhost ? '' : 'required'}></div>
            <div class="email-cell"><input type="text" class="email-host" placeholder="imap.email.com" value="${acc.imap_host || ''}" ${isGhost ? '' : 'required'}></div>            <div class="email-cell"><input type="number" class="email-port" placeholder="993" value="${acc.imap_port || ''}"></div>
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
        <div class="api-group email-config-section" data-group-path="apis.messaging.email">
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
                ctx.modifiedFields.api.add('apis.messaging.email');
                updateApiNextButtonState(ctx);
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

        ctx.modifiedFields.api.add('apis.messaging.email');
        updateApiNextButtonState(ctx);

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
