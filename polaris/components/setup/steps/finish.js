const shortcuts = require('./shortcuts');

let initialized = false;
let markFinishModifiedFn = null;

function escapeHtml(str) {
    return String(str ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function updateCoreDisabledTip(disabledCoreCount) {
    const section = document.getElementById('capabilities-section');
    if (!section) return;

    let tip = document.getElementById('core-disabled-tip');
    if (disabledCoreCount > 0) {
        if (!tip) {
            tip = document.createElement('div');
            tip.id = 'core-disabled-tip';
            tip.className = 'core-disabled-tip';
            section.insertBefore(tip, document.getElementById('capabilities-list'));
        }
        const noun = disabledCoreCount === 1 ? 'capability is' : 'capabilities are';
        tip.textContent =
            `${disabledCoreCount} core ${noun} currently disabled. Ainara will still work, ` +
            'but that built-in functionality won\'t be available.';
    } else if (tip) {
        tip.remove();
    }
}

function wireCapabilityToggles(ctx, listElement) {
    if (listElement.dataset.togglesWired) return;
    listElement.dataset.togglesWired = '1';

    const { modifiedFields } = ctx;

    listElement.addEventListener('change', (event) => {
        const checkbox = event.target;
        if (!checkbox.classList || !checkbox.classList.contains('capability-toggle')) {
            return;
        }

        if (!checkbox.checked && checkbox.dataset.capCore === '1') {
            const capId = checkbox.dataset.capId;
            const confirmed = window.confirm(
                `'${capId}' is a core capability of Ainara. Disabling it removes` +
                    ' built-in functionality. Disable it anyway?'
            );
            if (!confirmed) {
                checkbox.checked = true;
                return;
            }
        }

        if (markFinishModifiedFn) {
            markFinishModifiedFn({ target: { id: 'capabilities-toggles' } });
        } else {
            modifiedFields.finish.add('capabilities-toggles');
        }
    });
}

async function init(ctx) {
    if (initialized) return;
    initialized = true;

    const { config, modifiedFields, api, ipcRenderer } = ctx;
    if (!modifiedFields.finish) modifiedFields.finish = new Set();

    const markFinishModified = (event) => {
        if (event && event.target) {
            modifiedFields.finish.add(event.target.id);
        }
        const testResult = document.getElementById('test-result');
        if (testResult) testResult.classList.add('hidden');
        const nextButton = document.getElementById('main-next-btn');
        if (nextButton) nextButton.disabled = true;
    };
    markFinishModifiedFn = markFinishModified;

    const startMinimizedCheckbox = document.getElementById('start-minimized-checkbox');
    if (startMinimizedCheckbox) {
        startMinimizedCheckbox.addEventListener('change', markFinishModified);
        startMinimizedCheckbox.checked = config.get('startup.startMinimized');
    }

    const reviewSttSelect = document.getElementById('review-stt-select');
    if (reviewSttSelect) {
        reviewSttSelect.addEventListener('change', markFinishModified);
        reviewSttSelect.value = config.get('stt.review');
    }

    const backgroundNotificationsCheckbox = document.getElementById('background-notifications-checkbox');
    if (backgroundNotificationsCheckbox) {
        backgroundNotificationsCheckbox.addEventListener('change', markFinishModified);
        backgroundNotificationsCheckbox.checked = config.get('ui.backgroundNotifications');
    }

    const lowerVolumeCheckbox = document.getElementById('lower-volume-checkbox');
    if (lowerVolumeCheckbox) {
        lowerVolumeCheckbox.addEventListener('change', markFinishModified);
        lowerVolumeCheckbox.checked = config.get('stt.lowerVolume');
    }

    const wakeWordCheckbox = document.getElementById('wakeword-checkbox');
    if (wakeWordCheckbox) {
        wakeWordCheckbox.addEventListener('change', markFinishModified);
        wakeWordCheckbox.checked = config.get('wakeword.enabled');
    }

    const comringNotificationsCheckbox = document.getElementById('comring-notifications-checkbox');
    if (comringNotificationsCheckbox) {
        comringNotificationsCheckbox.addEventListener('change', markFinishModified);
        comringNotificationsCheckbox.checked = config.get('ui.comringNotifications');
    }

    const autoStartCheckbox = document.getElementById('auto-start-checkbox');
    if (autoStartCheckbox) {
        autoStartCheckbox.addEventListener('change', markFinishModified);
        autoStartCheckbox.checked = config.get('startup.autoStart', false);
    }

    const backupDirectoryInput = document.getElementById('backup-directory-input');
    const browseBackupDirectoryBtn = document.getElementById('browse-backup-directory-btn');

    if (backupDirectoryInput) {
        backupDirectoryInput.addEventListener('input', markFinishModified);

        (async () => {
            try {
                const backendConfig = await api.loadBackendConfig();
                backupDirectoryInput.value = backendConfig?.backup?.directory || '';
            } catch (error) {
                console.error('Error loading backup directory from backend:', error);
            }
        })();

        if (browseBackupDirectoryBtn) {
            backupDirectoryInput.addEventListener('click', () => browseBackupDirectoryBtn.click());
            browseBackupDirectoryBtn.addEventListener('click', () => ipcRenderer.send('select-backup-directory'));
        }
    }

    ipcRenderer.on('backup-directory-selected', (event, directoryPath) => {
        if (backupDirectoryInput) {
            backupDirectoryInput.value = directoryPath;
            backupDirectoryInput.dispatchEvent(new Event('input'));
        }
    });

    // --- Examples section (injected here so it stays contained in this step) ---
    const finishPanelForExamples = document.getElementById('finish-panel');
    const capabilitiesSection = document.getElementById('capabilities-section');
    if (finishPanelForExamples && !document.getElementById('examples-copy-btn')) {
        const examplesBlock = document.createElement('div');
        examplesBlock.className = 'form-group';
        examplesBlock.innerHTML = `
            <h3>Example files</h3>
            <p class="field-description">Ainara ships ready-to-use example files. Copy them to a folder of your choice (your Desktop by default) to explore and reuse them.</p>
            <button type="button" id="examples-copy-btn" class="btn">Copy examples to a folder…</button>
            <div id="examples-copy-status" class="field-description" style="margin-top: 6px; min-height: 18px;"></div>
        `;
        if (capabilitiesSection) {
            finishPanelForExamples.insertBefore(examplesBlock, capabilitiesSection);
        } else {
            finishPanelForExamples.appendChild(examplesBlock);
        }

        const copyButton = examplesBlock.querySelector('#examples-copy-btn');
        const statusEl = examplesBlock.querySelector('#examples-copy-status');
        copyButton.addEventListener('click', async () => {
            copyButton.disabled = true;
            if (statusEl) statusEl.textContent = 'Choose a destination folder in the dialog…';
            try {
                const result = await ipcRenderer.invoke('examples:copy');
                if (result && result.status === 'copied') {
                    if (statusEl) statusEl.textContent = `Examples copied to: ${result.path}`;
                } else if (result && result.status === 'canceled') {
                    if (statusEl) statusEl.textContent = '';
                } else if (statusEl) {
                    statusEl.textContent = 'Could not copy the examples.';
                }
            } catch (error) {
                console.error('Error copying examples:', error);
                if (statusEl) statusEl.textContent = 'Error copying examples. Check the logs for details.';
            } finally {
                copyButton.disabled = false;
            }
        });
    }

    const finishPanel = document.getElementById('finish-panel');
    if (finishPanel && finishPanel.classList.contains('active')) {
        loadAndDisplayCapabilities(ctx).catch(err => {
            console.error('Error loading capabilities:', err);
        });
    }
}

async function loadAndDisplayCapabilities(ctx) {
    const listElement = document.getElementById('capabilities-list');
    if (!listElement) return;

    listElement.innerHTML = '<li class="loading">Loading capabilities...</li>';

    // Current denylist comes from PyBridge (the persistence authority for
    // ainara.yaml), not from Orakle: Orakle only applies skills.disabled at
    // startup, so its view can be stale within a session.
    let disabledSet = new Set();
    try {
        const backendConfig = await ctx.api.loadBackendConfig();
        const disabledList = backendConfig?.skills?.disabled;
        if (Array.isArray(disabledList)) {
            disabledSet = new Set(disabledList);
        }
    } catch (error) {
        // Degrade to all-enabled (matches a fresh Orakle startup) rather
        // than blocking the whole capabilities review.
        console.warn('Could not load backend config for skill toggles:', error);
    }

    try {
        const response = await fetch(ctx.config.get('orakle.api_url') + '/capabilities?view=full');
        if (!response.ok) {
            throw new Error(`Failed to fetch capabilities: ${response.status} ${response.statusText}`);
        }

        const data = await response.json();
        if (!data || typeof data !== 'object' || Object.keys(data).length === 0) {
            listElement.innerHTML = '<li class="info">No specific capabilities listed by the backend.</li>';
            updateCoreDisabledTip(0);
            return;
        }

        const groups = { native: [], nexus: [], mcp: [], user: [], other: [] };

        Object.entries(data).forEach(([skillId, skill]) => {
            const entry = {
                id: skillId,
                description: (skill.description || '').trim().split('\n')[0],
                bundle: skill.bundle || '',
                server: skill.server || '',
                core: skill.type === 'skill',
                disabled: disabledSet.has(skillId)
            };

            switch (skill.type) {
                case 'skill': groups.native.push(entry); break;
                case 'nexus': groups.nexus.push(entry); break;
                case 'mcp': groups.mcp.push(entry); break;
                case 'user_skill': groups.user.push(entry); break;
                default: groups.other.push(entry);
            }
        });

        const renderEntries = (entries) => entries
            .sort((a, b) => a.id.localeCompare(b.id))
            .map(entry => {
                const suffix = entry.server ? ` <em>(server: ${escapeHtml(entry.server)})</em>` : '';
                return `<li class="capability-item${entry.disabled ? ' disabled' : ''}">` +
                    '<label>' +
                    `<input type="checkbox" class="capability-toggle" data-cap-id="${escapeHtml(entry.id)}"` +
                    `${entry.core ? ' data-cap-core="1"' : ''}${entry.disabled ? '' : ' checked'}` +
                    `><code>${escapeHtml(entry.id)}</code> — ${escapeHtml(entry.description)}${suffix}` +
                    '</label></li>';
            })
            .join('');

        const renderGroup = (title, entries) => {
            if (entries.length === 0) return '';
            return `<div class="capability-group"><h3>${title}</h3><ul>${renderEntries(entries)}</ul></div>`;
        };

        const sections = [];
        sections.push(renderGroup('Native Skills', groups.native));

        const nexusByBundle = {};
        groups.nexus.forEach(entry => {
            const bundle = entry.bundle || 'General';
            if (!nexusByBundle[bundle]) nexusByBundle[bundle] = [];
            nexusByBundle[bundle].push(entry);
        });

        Object.keys(nexusByBundle)
            .sort((a, b) => a.localeCompare(b))
            .forEach(bundle => {
                const title = `Nexus Skills — ${bundle.charAt(0).toUpperCase() + bundle.slice(1)}`;
                sections.push(renderGroup(title, nexusByBundle[bundle]));
            });

        sections.push(renderGroup('MCP Servers', groups.mcp));
        sections.push(renderGroup('User Skills', groups.user));
        sections.push(renderGroup('Other Capabilities', groups.other));

        listElement.innerHTML = sections.filter(Boolean).join('') || '<li class="info">No capabilities available.</li>';

        updateCoreDisabledTip(groups.native.filter(entry => entry.disabled).length);
        wireCapabilityToggles(ctx, listElement);
    } catch (error) {
        console.error('Error loading capabilities:', error);
        listElement.innerHTML = `<li class="error">Failed to load capabilities: ${error.message}</li>`;
        updateCoreDisabledTip(0);
    }
}

async function saveFinishStepConfig(ctx) {
    const { config, modifiedFields, api } = ctx;

    if (modifiedFields.finish.size === 0) {
        return true;
    }

    try {
        if (modifiedFields.finish.has('start-minimized-checkbox')) {
            config.set('startup.startMinimized', document.getElementById('start-minimized-checkbox').checked);
        }

        if (modifiedFields.finish.has('review-stt-select')) {
            config.set('stt.review', document.getElementById('review-stt-select').value);
        }

        if (modifiedFields.finish.has('background-notifications-checkbox')) {
            config.set('ui.backgroundNotifications', document.getElementById('background-notifications-checkbox').checked);
        }

        if (modifiedFields.finish.has('backup-directory-input')) {
            const backupDirectory = document.getElementById('backup-directory-input').value.trim();
            const backendConfig = await api.loadBackendConfig();
            if (!backendConfig.backup) backendConfig.backup = {};
            backendConfig.backup.directory = backupDirectory;
            backendConfig.backup.enabled = !!backupDirectory;
            await api.saveBackendConfig(backendConfig, config.get('pybridge.api_url'));
        }

        if (modifiedFields.finish.has('auto-start-checkbox')) {
            config.set('startup.autoStart', document.getElementById('auto-start-checkbox').checked);
            // Notify the main process to apply the setting immediately
            ctx.ipcRenderer.send('set-auto-start');
        }

        if (modifiedFields.finish.has('wakeword-checkbox')) {
            config.set('wakeword.enabled', document.getElementById('wakeword-checkbox').checked);
        }

        if (modifiedFields.finish.has('lower-volume-checkbox')) {
            config.set('stt.lowerVolume', document.getElementById('lower-volume-checkbox').checked);
        }

        if (modifiedFields.finish.has('comring-notifications-checkbox')) {
            config.set('ui.comringNotifications', document.getElementById('comring-notifications-checkbox').checked);
        }

        if (modifiedFields.finish.has('capabilities-toggles')) {
            // Read-modify-write against a fresh load: the denylist is the
            // set of currently unchecked toggles, everything else in the
            // config is preserved as-is.
            const backendConfig = await api.loadBackendConfig();
            if (!backendConfig.skills) backendConfig.skills = {};
            backendConfig.skills.disabled = Array.from(
                document.querySelectorAll('#capabilities-list input.capability-toggle[data-cap-id]')
            )
                .filter(checkbox => !checkbox.checked)
                .map(checkbox => checkbox.dataset.capId);
            await api.saveBackendConfig(backendConfig, config.get('pybridge.api_url'));
        }

        config.saveConfig();
        modifiedFields.finish.clear();
        return true;
    } catch (error) {
        console.error('Error saving finish step config:', error);
        return false;
    }
}

async function save(ctx) {
    return saveFinishStepConfig(ctx);
}

function validate() {
    return true;
}

async function finishSetup(ctx) {
    shortcuts.save(ctx);
    await saveFinishStepConfig(ctx);

    ctx.config.set('setup.completed', true);
    ctx.config.set('setup.version', '0.10.2');
    ctx.config.set('setup.timestamp', new Date().toISOString());
    ctx.config.saveConfig();

    ctx.ipcRenderer.send('setup-complete');
}

module.exports = { id: 'finish', init, save, validate, finishSetup, loadAndDisplayCapabilities };
