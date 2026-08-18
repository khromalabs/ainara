const shortcuts = require('./shortcuts');

let initialized = false;

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

    // Trading automation checkboxes: listeners only, here. Unlike the checkboxes
    // above these read/write the BACKEND config (ainara.yaml, shared with
    // Orakle/the executor/watchdog), not the local polaris.json, so their
    // `.checked` state can't be set synchronously at page load —
    // initializeTradingAutomationSection() populates it once backendConfig is
    // fetched, whenever the finish panel becomes active.
    const executorAutostartCheckbox = document.getElementById('executor-autostart-checkbox');
    if (executorAutostartCheckbox) {
        executorAutostartCheckbox.addEventListener('change', markFinishModified);
    }
    const watchdogActiveCheckbox = document.getElementById('watchdog-active-checkbox');
    if (watchdogActiveCheckbox) {
        watchdogActiveCheckbox.addEventListener('change', markFinishModified);
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

    const finishPanel = document.getElementById('finish-panel');
    if (finishPanel && finishPanel.classList.contains('active')) {
        loadAndDisplayCapabilities(ctx).catch(err => {
            console.error('Error loading capabilities:', err);
        });
        initializeTradingAutomationSection(ctx).catch(err => {
            console.error('Error initializing trading automation section:', err);
        });
    }
}

// Shows the Trading Automation section only once real Hyperliquid + dYdX
// credentials are present (both venues are required for a delta-neutral hedge),
// and populates the two checkboxes from the backend config (ainara.yaml) — unlike
// their sibling checkboxes on this step, these read/write trading.executor.autostart
// and trading.watchdog.mode, not the local polaris.json.
async function initializeTradingAutomationSection(ctx) {
    const section = document.getElementById('trading-automation-section');
    if (!section) return;

    const { modifiedFields, api } = ctx;

    try {
        const backendConfig = await api.loadBackendConfig();
        const hlAddr = backendConfig?.apis?.hyperliquid?.mainnet?.account_address
            || backendConfig?.apis?.hyperliquid?.testnet?.account_address;
        const dydxAddr = backendConfig?.apis?.dydx?.mainnet?.account_address
            || backendConfig?.apis?.dydx?.testnet?.account_address;
        // extractApiKeysFromConfig treats an unset key as the literal placeholder
        // "<key>", not an empty string — an unconfigured field is NOT truthy-but-set.
        const isSet = (v) => !!v && v !== '<key>';
        const tradingConfigured = isSet(hlAddr) && isSet(dydxAddr);

        section.classList.toggle('hidden', !tradingConfigured);
        if (!tradingConfigured) return;

        // Skip re-setting a checkbox the user already toggled this session — the
        // finish panel can be re-activated by navigating back and forward before
        // clicking Finish, and re-fetching the SAVED backend value would silently
        // discard an in-progress, unsaved change.
        const executorCheckbox = document.getElementById('executor-autostart-checkbox');
        if (executorCheckbox && !modifiedFields.finish.has('executor-autostart-checkbox')) {
            executorCheckbox.checked = !!backendConfig?.trading?.executor?.autostart;
        }
        const watchdogCheckbox = document.getElementById('watchdog-active-checkbox');
        if (watchdogCheckbox && !modifiedFields.finish.has('watchdog-active-checkbox')) {
            watchdogCheckbox.checked = backendConfig?.trading?.watchdog?.mode === 'active';
        }
    } catch (error) {
        console.error('Error initializing trading automation section:', error);
    }
}

async function loadAndDisplayCapabilities(ctx) {
    const listElement = document.getElementById('capabilities-list');
    if (!listElement) return;

    listElement.innerHTML = '<li class="loading">Loading capabilities...</li>';

    try {
        const response = await fetch(ctx.config.get('orakle.api_url') + '/capabilities');
        if (!response.ok) {
            throw new Error(`Failed to fetch capabilities: ${response.status} ${response.statusText}`);
        }

        const data = await response.json();
        if (!data || typeof data !== 'object' || Object.keys(data).length === 0) {
            listElement.innerHTML = '<li class="info">No specific capabilities listed by the backend.</li>';
            return;
        }

        const groups = { native: [], nexus: [], mcp: [], user: [], other: [] };

        Object.entries(data).forEach(([skillId, skill]) => {
            const entry = {
                id: skillId,
                description: (skill.description || '').trim().split('\n')[0],
                bundle: skill.bundle || '',
                server: skill.server || ''
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
                const suffix = entry.server ? ` <em>(server: ${entry.server})</em>` : '';
                return `<li><code>${entry.id}</code> — ${entry.description}${suffix}</li>`;
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
    } catch (error) {
        console.error('Error loading capabilities:', error);
        listElement.innerHTML = `<li class="error">Failed to load capabilities: ${error.message}</li>`;
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

        if (modifiedFields.finish.has('executor-autostart-checkbox')
            || modifiedFields.finish.has('watchdog-active-checkbox')) {
            // Backend keys (ainara.yaml), not local polaris.json — read by
            // scripts/scheduler.py (executor.autostart) and the standalone
            // watchdog process (watchdog.mode), neither of which orakle/pybridge
            // hot-reload for: both take effect the next time those processes
            // (re)start, which the wizard copy says explicitly.
            const backendConfig = await api.loadBackendConfig();
            if (!backendConfig.trading) {
                backendConfig.trading = {};
            }

            if (modifiedFields.finish.has('executor-autostart-checkbox')) {
                const isChecked = document.getElementById('executor-autostart-checkbox').checked;
                if (!backendConfig.trading.executor) {
                    backendConfig.trading.executor = {};
                }
                backendConfig.trading.executor.autostart = isChecked;
            }

            if (modifiedFields.finish.has('watchdog-active-checkbox')) {
                const isChecked = document.getElementById('watchdog-active-checkbox').checked;
                if (!backendConfig.trading.watchdog) {
                    backendConfig.trading.watchdog = {};
                }
                backendConfig.trading.watchdog.mode = isChecked ? 'active' : 'monitor';
            }

            await api.saveBackendConfig(backendConfig, config.get('pybridge.api_url'));
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
