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

const { app, Tray, Menu, dialog, globalShortcut, BrowserWindow, ipcMain, shell } = require('electron');
const { autoUpdater } = require('electron-updater');
const semver = require('semver');
// const yargs = require('yargs/yargs');
// const { hideBin } = require('yargs/helpers');
const path = require('path');
const ConfigManager = require('./utils/config');
const { WindowManager } = require('./windows/WindowManager');
const ComRingWindow = require('./windows/ComRingWindow');
const ChatDisplayWindow = require('./windows/ChatDisplayWindow');
const SplashWindow = require('./windows/SplashWindow');
const UpdateProgressWindow = require('./windows/UpdateProgressWindow');
const ServiceManager = require('./utils/ServiceManager');
const ConfigHelper = require('./utils/ConfigHelper');
const Logger = require('./utils/logger');
const process = require('process');
const { nativeTheme } = require('electron');
const debugMode = true;
const debugDisableWizard = false;
const ollama = require('ollama');


const config = new ConfigManager();
let updateAvailable = null;
let windowManager = null;
let tray = null;
let shortcutRegistered = false;
let splashWindow = null;
let setupWindow = null;
let wizardActive = false;
let externallyManagedServices = false;
let updateProgressWindow = null;
let ollamaClient = null;

const shortcutKey = config.get('shortcuts.show', 'F1');

// Check if this is the first run of the application
function isFirstRun() {
    return !config.get('setup.completed', false);
}

// Show the setup wizard for first-time users
function showSetupWizard() {
    Logger.info('First run detected, showing setup wizard');

   // Disable tray icon
    if (tray) {
        tray.setContextMenu(null);
        tray.removeAllListeners('click');
    }

    // Get the appropriate icon based on theme
    const theme = nativeTheme.shouldUseDarkColors ? 'dark' : 'light';
    const iconPath = path.resolve(__dirname, 'assets', `tray-icon-active-${theme}.png`);

    wizardActive = true;
    globalShortcut.unregister(shortcutKey);

    // Create setup window
    setupWindow = new BrowserWindow({
        width: 950,
        // width: 1350,
        height: 750,
        webPreferences: {
            nodeIntegration: true,
            contextIsolation: false
        },
        title: 'Polaris Setup',
        show: false,
        center: true,
        resizable: false,
        frame: false,
        skipTaskbar: false, // Show taskbar icon for setup window
        transparent: true,
        iconPath: iconPath
    });
    // setupWindow.webContents.openDevTools();

    setupWindow.setIcon(iconPath);

    // Load the setup page
    setupWindow.loadFile(path.join(__dirname, 'windows', 'setup', 'index.html'));

    setupWindow.once('ready-to-show', () => {
        setupWindow.show();
    });


    async function setupComplete() {
        Logger.info('Setup completed, starting application');
        try {
            setupWindow?.close();
            setupWindow?.destroy();
        } catch (error) {
            Logger.error('Error closing setupWindow:' + error);
        }
        wizardActive = false;
        appSetupShortcuts();
        updateProviderSubmenu();
        // Re-enable tray icon
        if (tray) {
            tray.destroy();
            await appCreateTray();
        }

        await restartWithSplash();
    }

    // Handle setup completion
    ipcMain.once('setup-complete', setupComplete);

    // relies in external executables
    // TODO Unify this with splash window in appInitialization
    async function restartWithSplash() {
        if (externallyManagedServices) {
            Logger.info("Externally managed services need manual restart. Exiting.");
            app.exit(1);
        }
        // Create splash window
        splashWindow = new SplashWindow(config, null, null, __dirname);
        splashWindow.show();
        if (! await ServiceManager.stopServices() ) {
            splashWindow.close();
            dialog.showErrorBox(
                'Service Error',
                'Failed to stop required services. Please check the logs for details.'
            );
            app.exit(1);
            return;
        }
        // Set up service manager progress callback
        ServiceManager.setProgressCallback((status, progress) => {
            splashWindow.updateProgress(status, progress);
        });
        // Start services
        splashWindow.updateProgress('Starting services...', 10);
        const servicesStarted = await ServiceManager.startServices();
        if (!servicesStarted) {
            splashWindow.close();
            dialog.showErrorBox(
                'Service Error',
                'Failed to start required services. Please check the logs for details.'
            );
            app.exit(1);
            return;
        }
        // Wait for services to be healthy
        splashWindow.updateProgress('Waiting for services to be ready...', 40);
        // Poll until all services are healthy or timeout
        const startTime = Date.now();
        const timeout = 120000; // 120 seconds timeout
        let servicesHealthy = false;
        while (Date.now() - startTime < timeout) {
            if (ServiceManager.isAllHealthy()) {
                servicesHealthy = true;
                break;
            }
            await new Promise(resolve => setTimeout(resolve, 1000));
        }
        if (!servicesHealthy) {
            splashWindow?.close();
            dialog.showErrorBox(
                'Service Error',
                'Services did not become healthy within the timeout period. Please check the logs for details.'
            );
            app.exit(1);
            return;
        }
        // Services are ready, initialize the rest of the app
        splashWindow.updateProgress('Initializing application...', 80);
        // Check if required resources are available
        splashWindow.updateProgress('Checking required resources...', 85);
        const resourceCheck = await ServiceManager.checkResourcesInitialization();
        // If resources are not initialized, initialize them
        if (resourceCheck && !resourceCheck.initialized) {
            Logger.info('Some resources need initialization, starting download process...');
            // Start the initialization process
            try {
                Logger.info('Starting resource initialization via SSE (restartWithSplash)...');
                // Progress updates are handled internally by ServiceManager via callback
                const initResult = await ServiceManager.initializeResources();
                Logger.info('Resource initialization successful (restartWithSplash):', initResult.message);
            } catch (errorResult) {
                splashWindow.close();
                Logger.error('Failed to initialize resources (restartWithSplash):', errorResult.error || 'Unknown error');
                dialog.showErrorBox(
                    'Initialization Error',
                    `Failed to download required resources: ${errorResult.error || 'Unknown error'}`
                );
                app.exit(1);
            }
        } else {
            Logger.info('All required resources are already initialized');
        }
        // Update the provider submenu
        await updateProviderSubmenu();
        // Close splash and show main window
        splashWindow.updateProgress('Ready!', 100);
        await new Promise(resolve => setTimeout(resolve, 500));
        splashWindow.close();

        // Set shortcut just before showing windows
        appSetupShortcuts();

        // Check if this is the first run
        if (isFirstRun()) {
            showSetupWizard();
            return;
        } else {
            // Read the start minimized setting
            if (!config.get('startup.startMinimized', false)) {
                Logger.info('Starting with windows visible.');
                showWindows(true);
            } else Logger.info('Starting minimized as per configuration.');
        }
    }

    // If the user closes the setup window without completing setup
    ipcMain.on('close-setup-window', async () => {
        Logger.info('close-setup-window event');
        if (!config.get('setup.completed', false)) {
            Logger.info('Setup incomplete - forcing immediate exit');
            await ServiceManager.stopServices();
            app.exit(1); // Hard exit without cleanup
        } else {
            splashWindow.close();
            await setupComplete();
        }
    });
}

function initializeOllamaClient() {
    const serverIp = config.get('ollama.serverIp', 'localhost');
    const port = config.get('ollama.port', 11434);
    ollamaClient = new ollama.Ollama({ host: `http://${serverIp}:${port}` });
    Logger.info(`Ollama client initialized with server: ${serverIp}:${port}`);
}

async function appInitialization() {
    try {
        Logger.setDebugMode(debugMode);
        app.isQuitting = false;
        await app.whenReady();

        // Initialize Ollama client
        initializeOllamaClient();

        if (process.platform === 'darwin') {
            app.dock.hide()
        }

        // Set application icon
        const theme = nativeTheme.shouldUseDarkColors ? 'dark' : 'light';
        if (process.platform === 'darwin' && !app.dock.isHidden()) {
            app.dock.setIcon(path.join(__dirname, 'assets', `tray-icon-active-${theme}.png`));
        }

        // Initialize window manager and windows
        windowManager = new WindowManager(config);
        windowManager.initialize([ComRingWindow, ChatDisplayWindow], __dirname);
        appSetupEventHandlers();
        await appCreateTray();

        await waitForWindowsAndComponentsReady();

        // --- Port Availability Check (Packaged App Only) ---
        if (app.isPackaged) {
            const portCheckResult = await ServiceManager.checkPortsAvailability();
            if (!portCheckResult.available) {
                // Port is in use or an error occurred during check
                handlePortConflictError(portCheckResult.port, portCheckResult.serviceName);
                return; // Stop initialization
            }
            // If we reach here, ports are available.
        }
        // --- End Port Availability Check ---

        // Create splash window
        splashWindow = new SplashWindow(config, null, null, __dirname);
        splashWindow.show();


        // If services are being managed externally alternate start without splash
        await ServiceManager.checkServicesHealth();
        if (ServiceManager.isAllHealthy()) {
            splashWindow.close();
            // Alternate application start for dev purposes
            externallyManagedServices = true;
            const resourceCheck = await ServiceManager.checkResourcesInitialization();
            // If resources are not initialized, initialize them
            if (resourceCheck && !resourceCheck.initialized) {
                Logger.info('Some resources need initialization, starting download process...');
                try {
                    Logger.info('Starting resource initialization via SSE (external services)...');
                    // Progress updates are handled internally by ServiceManager via callback
                    const initResult = await ServiceManager.initializeResources();
                    Logger.info('Resource initialization successful (external services):', initResult.message);
                } catch (errorResult) {
                    Logger.error('Failed to initialize resources (external services):', errorResult.error || 'Unknown error');
                    dialog.showErrorBox(
                        'Initialization Error',
                        `Failed to download required resources: ${errorResult.error || 'Unknown error'}`
                    );
                    app.exit(1);
                }
            } else {
                Logger.info('All required resources are already initialized');
            }
            await updateProviderSubmenu();
            initializeAutoUpdater();

            // Set shortcut just before showing windows
            appSetupShortcuts();

            // Read the start minimized setting
            const startMinimized = config.get('startup.startMinimized', false);

            // Check if this is the first run
            if (!debugDisableWizard && isFirstRun()) {
                showSetupWizard();
            } else {
                if (!startMinimized) {
                    Logger.info('Starting with windows visible.');
                    showWindows(true);
                } else Logger.info('Starting minimized as per configuration.');
            }

            return;
        }

        // Set up service manager progress callback
        ServiceManager.setProgressCallback((status, progress) => {
            splashWindow.updateProgress(status, progress);
        });

        // Start services
        splashWindow.updateProgress('Starting services...', 10);
        const servicesStarted = await ServiceManager.startServices();

        if (!servicesStarted) {
            splashWindow?.close();
            dialog.showErrorBox(
                'Service Error',
                'Failed to start required services. Please check the logs for details.'
            );
            app.exit(1);
            return;
        }

        // Wait for services to be healthy
        splashWindow.updateProgress('Waiting for services to be ready...', 40);

        // Poll until all services are healthy or timeout
        const startTime = Date.now();
        const timeout = 120000; // 120 seconds timeout
        let servicesHealthy = false;

        while (Date.now() - startTime < timeout) {
            if (ServiceManager.isAllHealthy()) {
                servicesHealthy = true;
                break;
            }
            await new Promise(resolve => setTimeout(resolve, 1000));
        }

        if (!servicesHealthy) {
            splashWindow?.close();
            dialog.showErrorBox(
                'Service Error',
                'Services did not become healthy within the timeout period. Please check the logs for details.'
            );
            app.quit();
            return;
        }

        // Services are ready, initialize the rest of the app
        splashWindow.updateProgress('Initializing application...', 80);

        // Check if required resources are available
        splashWindow.updateProgress('Checking required resources...', 85);
        const resourceCheck = await ServiceManager.checkResourcesInitialization();

        // If resources are not initialized, initialize them
        if (resourceCheck && !resourceCheck.initialized) {
            Logger.info('Some resources need initialization, starting download process...');
            // Start the initialization process
            try {
                Logger.info('Starting resource initialization via SSE (normal start)...');
                // Progress updates are handled internally by ServiceManager via callback
                const initResult = await ServiceManager.initializeResources();
                Logger.info('Resource initialization successful (normal start):', initResult.message);
            } catch (errorResult) {
                splashWindow.close();
                Logger.error('Failed to initialize resources (normal start):', errorResult.error || 'Unknown error');
                dialog.showErrorBox(
                    'Initialization Error',
                    `Failed to download required resources: ${errorResult.error || 'Unknown error'}`
                );
                app.exit(1);
            }
        } else {
            Logger.info('All required resources are already initialized');
        }

        // Update the provider submenu
        await updateProviderSubmenu();

        // Start Ollama keep-alive mechanism
        startOllamaKeepAlive();

        // Close splash and show main window
        splashWindow.updateProgress('Ready!', 100);
        await new Promise(resolve => setTimeout(resolve, 500));
        splashWindow.close();

        // Set shortcut just before showing windows
        appSetupShortcuts();

        // Check if this is the first run
        if (isFirstRun()) {
            showSetupWizard();
            return;
        } else {
            // Read the start minimized setting
            if (!config.get('startup.startMinimized', false)) {
                Logger.info('Starting with windows visible.');
                showWindows(true);
            } else Logger.info('Starting minimized as per configuration.');
        }

        let llmProviders = await ConfigHelper.getLLMProviders();
        if (llmProviders) {
            tray.setToolTip('Ainara Polaris v' + config.get('setup.version') + " - " + truncateMiddle(llmProviders.selected_provider, 44));
        }

        initializeAutoUpdater();
        Logger.info('Polaris initialized successfully');
    } catch (error) {
        appHandleCriticalError(error);
    }
}

/**
 * Handles the situation where a required port is already in use.
 * Shows an error dialog and quits the application.
 * @param {number} port The port number that is in use.
 * @param {string} serviceName The name of the service requiring the port.
 */
function handlePortConflictError(port, serviceName) {
    const message = port > 0
        ? `Port ${port} required by the ${serviceName} service is already in use.`
        : `Could not check port for ${serviceName}.`; // Handle error case from check
    const detail = port > 0
        ? `Polaris cannot start because another application is using port ${port}. Please close the conflicting application or configure the service to use a different port if possible, then restart Polaris.`
        : `An error occurred while checking port availability for ${serviceName}. Please check the logs.`;
    Logger.error(`${message} ${detail}`);
    // Ensure splash screen is closed if it exists
    if (splashWindow && splashWindow.window && !splashWindow.window.isDestroyed()) {
        splashWindow.close();
    }
    dialog.showErrorBox(
        'Application Startup Error',
        message + '\n\n' + detail
    );
    app.exit(1);
}

function showWindows(force=false) {
    Logger.log('Shortcut pressed'); // Keep as debug log
    if (force || !windowManager.isAnyVisible()) {
        Logger.log('Windows were hidden - showing'); // Keep as debug log
        // Disable shortcut before showing windows
        globalShortcut.unregister(shortcutKey);
        shortcutRegistered = false;
        windowManager.showAll();
        const comRing = windowManager.getWindow('comRing');
        if (comRing) {
            comRing.focus();
        }
        Logger.log('shown and focused, unregistered globalShortcut'); // Keep as debug log
    }
}

function appSetupShortcuts() {
    if (!wizardActive && !shortcutRegistered) {
        shortcutRegistered = globalShortcut.register(shortcutKey, showWindows);

        if (shortcutRegistered) {
           Logger.info('Successfully registered shortcut:', shortcutKey);
        } else {
            Logger.error('Failed to register shortcut:', shortcutKey);
            app.exit(1);
        }
    }
}

// Convert other methods to regular functions (keeping their existing logic)
async function appCreateTray() {
    const iconPath = path.join(__dirname, 'assets');
    const theme = nativeTheme.shouldUseDarkColors ? 'dark' : 'light';

     if (wizardActive) {
        Logger.info('Can\'t create the tray while the wizard is active');
        return;
     }

    // Set initial tray icon based on service health
    const iconStatus =  'inactive';
    tray = new Tray(path.join(iconPath, `tray-icon-${iconStatus}-${theme}.png`));

    windowManager.setTray(tray, iconPath);

    // Add service management to tray menu
    const contextMenu = Menu.buildFromTemplate([
        {
            label: 'Setup',
            click: () => { windowManager.hideAll(true); showSetupWizard(); }
        },
        { type: 'separator' },
        // {
        //     label: 'Auto-update',
        //     type: 'checkbox',
        //     checked: config.get('autoUpdate.enabled', true),
        //     click: (menuItem) => {
        //         config.set('autoUpdate.enabled', menuItem.checked);
        //         autoUpdater.autoInstallOnAppQuit = menuItem.checked;
        //     }
        // },
        {
            label: 'LLM Models',
            submenu: [
                {
                    label: 'Configure Providers',
                    click: () => showSetupWizard()
                },
                { type: 'separator' },
                {
                    label: 'Loading providers...',
                    enabled: false
                }
            ]
        },
        { type: 'separator' },
        {
            label: 'Show',
            click: () => windowManager.showAll()
        },
        {
            label: 'Hide',
            click: () => windowManager.hideAll(true)
        },
        { type: 'separator' },
        {
            label: 'Check for Updates',
            click: () => checkForUpdates(true)
        },
        { type: 'separator' },
        {
            label: 'Quit',
            click: () => {
                app.isQuitting = true;
                app.quit();
            }
        }
    ]);

    tray.setContextMenu(contextMenu);

    // Optional: Single click to toggle windows
    tray.on('click', () => windowManager.toggleVisibility());
}

function truncateMiddle(str, maxLength) {
    if (str.length <= maxLength) {
        return str;
    }

    const startLength = Math.ceil((maxLength - 3) / 2);
    const endLength = Math.floor((maxLength - 3) / 2);

    const start = str.substring(0, startLength);
    const end = str.substring(str.length - endLength);

    return start + '...' + end;
}

// Add function to load Ollama model into memory
async function loadOllamaModel(modelId) {
    if (!ollamaClient) {
        initializeOllamaClient();
    }
    try {
        // Send a simple request to ensure the model is loaded and ready
        await ollamaClient.chat({
            model: modelId,
            messages: [{ role: 'user', content: 'Hello, are you ready?' }],
            stream: false
        });
        Logger.info(`Model ${modelId} loaded and ready.`);
    } catch (error) {
        Logger.error(`Error loading model ${modelId}:`, error);
    }
}

// Add a keep-alive mechanism to ensure the selected Ollama model remains loaded
function startOllamaKeepAlive() {
    setInterval(async () => {
        try {
            const { selected_provider } = await ConfigHelper.getLLMProviders();
            if (selected_provider && selected_provider.startsWith('ollama/')) {
                const modelId = selected_provider.split('/')[1];
                await loadOllamaModel(modelId);
            }
        } catch (error) {
            Logger.error('Error in Ollama keep-alive:', error);
        }
    }, 300000); // Check every 5 minutes
}

// Add function to update provider submenu
async function updateProviderSubmenu() {
    try {

        // Logger.info('UPDATING PROVIDER SUBMENU');

        // Get the current providers
        const { providers, selected_provider } = await ConfigHelper.getLLMProviders();

        if (!providers || providers.length === 0) {
            return;
        }

        // Create menu items for each provider
        const providerItems = providers.map(provider => {
            const model = provider.model || 'Unknown model';
            const context_window = provider.context_window ?
                "(C" + (provider.context_window / 1024) + "K)" :
                '';
            return {
                label: `${model} ${context_window}`,
                type: 'radio',
                checked: selected_provider === model,
                click: async () => {
                    const success = await ConfigHelper.selectLLMProvider(model);
                    if (success) {
                        // Update the menu
                        await updateProviderSubmenu();
                        // Notify com-ring about provider change
                        BrowserWindow.getAllWindows().forEach(window => {
                            if (!window.isDestroyed()) {
                                window.webContents.send('llm-provider-changed', model);
                            }
                        });
                        tray.setToolTip('Ainara Polaris v' + config.get('setup.version') + " - " + truncateMiddle(model, 44));

                        // If it's an Ollama model, ensure it's loaded
                        if (model.startsWith('ollama/')) {
                            const modelId = model.split('/')[1];
                            await loadOllamaModel(modelId);
                        }
                    }
                }
            };
        });


        // Create a new menu template
        const menuTemplate = [
            {
                label: 'Setup',
                click: () => showSetupWizard()
            },
            { type: 'separator' },
            {
                label: 'LLM Models',
                submenu: [
                    {
                        label: 'Switch LLM Model',
                        click: () => showSetupWizard()
                    },
                    { type: 'separator' },
                    ...providerItems
                ]
            },
            { type: 'separator' },
            {
                label: 'Show',
                click: () => windowManager.showAll()
            },
            {
                label: 'Hide',
                click: () => windowManager.hideAll(true)
            },
            { type: 'separator' },
            {
                label: 'Check for Updates',
                click: () => checkForUpdates(true)
            },
            { type: 'separator' },
            {
                label: 'Quit',
                click: () => {
                    app.isQuitting = true;
                    app.quit();
                }
            }
        ];

        // Create a new menu and set it
        const newContextMenu = Menu.buildFromTemplate(menuTemplate);
        tray.setContextMenu(newContextMenu);
    } catch (error) {
        Logger.error('Error updating provider submenu:', error);
    }
}

function checkForUpdates(interactive = false) {
    Logger.info(`checkForUpdates called. Interactive: ${interactive}`);
    if (!config.get('autoUpdate.enabled', true) && !interactive) {
        Logger.info("checkForUpdates: Auto-update disabled and not interactive, skipping check.");
        return;
    }

    Logger.info(`Checking for updates from: ${autoUpdater.getFeedURL()}`);

    autoUpdater.checkForUpdates().then(result => {
        Logger.info("checkForUpdates .then() received result:", JSON.stringify(result));
        // Log the crucial updateInfo part if it exists
        if (result && result.updateInfo) {
            Logger.info("checkForUpdates .then() updateInfo:", JSON.stringify(result.updateInfo));
        } else {
            Logger.info("checkForUpdates .then(): No updateInfo in result.");
        }

        if (!result?.updateInfo) {
            if (interactive) {
                dialog.showMessageBox({
                    type: 'info',
                    title: 'No Updates Available',
                    message: 'You\'re running the latest version of Polaris.'
                });
            }
        }
    }).catch(error => {
        Logger.error('Update check failed:', error);
        Logger.error("checkForUpdates .catch() full error object:", error);
        if (interactive) {
            dialog.showMessageBox({
                type: 'error',
                title: 'Update Error',
                message: 'Failed to check for updates. Please check your internet connection.'
            });
        }
    });
}

function initializeAutoUpdater() {
    autoUpdater.autoDownload = false;
    autoUpdater.allowPrerelease = config.get('autoUpdate.allowPrerelease', true);
    autoUpdater.logger = Logger;

    Logger.info(`AutoUpdater: Initializing with version ${app.getVersion()}`);
    Logger.info(`AutoUpdater: autoDownload=${autoUpdater.autoDownload}, allowPrerelease=${autoUpdater.allowPrerelease}`);
    Logger.info(`AutoUpdater: Current config - autoUpdate.enabled=${config.get('autoUpdate.enabled', true)}, updates.ignoredVersion=${config.get('updates.ignoredVersion', null)}`);

    autoUpdater.on('update-available', (info) => {
        Logger.info('AutoUpdater: update-available event handler START', JSON.stringify(info));
        const newVersion = info.version;
        const ignoredVersion = config.get('updates.ignoredVersion', null);

        // Only proceed if the new version is strictly greater than the ignored version
        if (ignoredVersion && semver.lte(newVersion, ignoredVersion)) {
            Logger.info(`Update available (${newVersion}) but ignored version (${ignoredVersion}) is same or newer. Skipping notification.`);
            return;
        }

        // Clear any previously ignored version since a newer one is available
        if (ignoredVersion) {
            config.set('updates.ignoredVersion', null);
        }

        updateAvailable = info; // Keep track of the available update info

        dialog.showMessageBox({
            type: 'info',
            buttons: ['Download Now', 'Ignore This Version', 'Later'],
            title: 'Update Available',
            message: `A new version of Polaris is available: ${newVersion}`,
            detail: `You are currently running version ${app.getVersion()}. Would you like to update?`
        }).then(({ response }) => {
            if (response === 0) { // Download Now
                Logger.info(`User chose to download update ${newVersion}`);
                // Create and show the progress window BEFORE starting download
                if (updateProgressWindow && !updateProgressWindow.isDestroyed()) {
                    updateProgressWindow.close(); // Close any existing instance
                }
                updateProgressWindow = new UpdateProgressWindow(config);
                updateProgressWindow.show();
                autoUpdater.downloadUpdate();
            } else {
                if (response === 1) { // Ignore This Version
                    Logger.info(`User chose to ignore update version ${newVersion}`);
                    config.set('updates.ignoredVersion', newVersion);
                    updateAvailable = null; // Clear update info as it's ignored
                } else { // Later (or closed dialog)
                    Logger.info(`User chose to postpone update ${newVersion}`);
                    updateAvailable = null; // Clear update info for this session
                }
                // Read the start minimized setting
                if (!config.get('startup.startMinimized', false)) {
                    Logger.info('Starting with windows visible.');
                    showWindows(true);
                } else {
                    Logger.info('Starting minimized as per configuration.');
                }
            }
        }).catch(err => {
            Logger.error('Error showing update dialog:', err);
        });
    });

    autoUpdater.on('download-progress', (progress) => {
        // updateDownloadProgress = progress.percent;
        // Send progress to the dedicated window
        if (updateProgressWindow && updateProgressWindow.window && !updateProgressWindow.window.isDestroyed()) {
            updateProgressWindow.updateProgress(progress.percent);
        }
        // windowManager.getWindow('comRing').webContents.send('update-progress', progress);
    });

    autoUpdater.on('update-downloaded', (info) => {
        Logger.info(`Update downloaded: ${JSON.stringify(info)}`);
        // Close the progress window first
        if (updateProgressWindow && updateProgressWindow.window && !updateProgressWindow.window.isDestroyed()) {
            updateProgressWindow.close();
            updateProgressWindow = null;
        }

        dialog.showMessageBox({
            type: 'info',
            buttons: ['Restart Now', 'Later'],
            title: 'Update Ready',
            message: 'A new version has been downloaded. Restart the application to apply the update.',
            detail: `Version ${updateAvailable.version} is ready to install.`
        }).then(({ response }) => {
            if (response === 0) autoUpdater.quitAndInstall();
        });
    });

    autoUpdater.on('error', (error) => {
        Logger.error('Auto-update error:', error);
        // Close the progress window on error
        if (updateProgressWindow && updateProgressWindow.window && !updateProgressWindow.window.isDestroyed()) {
            updateProgressWindow.close();
            updateProgressWindow = null;
        }
        let error_msg = 'Failed to download the update. Please try again later.';
        Logger.warning(error_msg);
        // // Optionally show an error message to the user
        // dialog.showMessageBox({
        //     type: 'error',
        //     title: 'Update Error',
        //     message: error_msg,
        //     detail: error.message || String(error)
        // });
    });

    // Check every 6 hours
    // setInterval(() => checkForUpdates(), 6 * 60 * 60 * 1000);
    checkForUpdates();
}

function appSetupEventHandlers() {
    // Handle opening external links in the system browser
    ipcMain.on('open-external-url', (event, url) => {
        shell.openExternal(url);
    });

    // Prevent app from closing when all windows are closed
    app.on('window-all-closed', () => {
        if (process.platform !== 'darwin') {
            app.quit();
        }
    });

    // Handle app activation (e.g., clicking dock icon on macOS)
    app.on('activate', () => {
        if (windowManager.isEmpty()) {
            appInitialization();
        } else {
            // Update tray icon to active when app is activated via taskbar/dock click
            windowManager.updateTrayIcon('active');
            // Ensure windows are shown if they were hidden or minimized
            if (!windowManager.isAnyVisible()) {
                windowManager.showAll();
            }
        }
    });

    // Cleanup before quit
    app.on('before-quit', async () => {
        globalShortcut.unregisterAll();

        // Stop services
        try {
            await ServiceManager.stopServices();
            Logger.info('Services stopped successfully');
        } catch (error) {
            Logger.error('Error stopping services:', error);
        }

        if (windowManager) {
            windowManager.cleanup();
        }
    });

    // Remove browser-window-focus handler as it conflicts with hide/show logic
    app.removeAllListeners('browser-window-focus');

    // Add handler for window hide
    windowManager.windows.forEach(window => {
        window.window.on('hide', () => {
            if (!shortcutRegistered) {
                appSetupShortcuts();
                Logger.log('Re-enabled global shortcut after window hide'); // Keep as debug log
            }
        });

        // Handle Alt+F4 and other OS window close events
        window.window.on('close', (event) => {
            // If this is not part of the app quitting process, prevent default and hide instead
            if (!app.isQuitting) {
                event.preventDefault();
                window.hide();
                return false;
            }
        });
    });

    nativeTheme.on('updated', () => {
        const theme = nativeTheme.shouldUseDarkColors ? 'dark' : 'light';
        Logger.info('System theme changed:', theme);
        const iconStatus = windowManager && windowManager.currentState ? windowManager.currentState : 'inactive';
        const iconPath = path.join(__dirname, 'assets', `tray-icon-${iconStatus}-${theme}.png`);

        // Update tray icon
        if (tray && !tray.isDestroyed()) {
            tray.setImage(iconPath);
        }

        // Update setup window icon if it exists
        if (setupWindow && !setupWindow.isDestroyed()) {
            setupWindow.setIcon(iconPath);
        }
    });
}


// Wait for all windows to be fully loaded and ready
async function waitForWindowsAndComponentsReady() {
    Logger.info('Waiting for all windows and components to be ready...');
    const windows = windowManager.getWindows();
    const readyPromises = windows.map(window => {
        // Outer promise resolves when both loading and component ready are done for this window
        return new Promise(resolveOuter => {
            // Inner promise for the basic 'did-finish-load' event
            const loadPromise = new Promise(resolveLoad => {
                if (window.window && window.window.webContents) {
                    if (window.window.webContents.isLoading()) {
                        Logger.log(`Waiting for ${window.prefix} window to finish loading...`);
                        window.window.webContents.once('did-finish-load', () => {
                            Logger.log(`${window.prefix} window finished loading`);
                            resolveLoad(); // Resolve loadPromise when loaded
                        });
                    } else {
                        Logger.log(`${window.prefix} window already loaded`);
                        resolveLoad(); // Resolve loadPromise immediately if already loaded
                    }
                } else {
                    Logger.log(`${window.prefix} window not properly initialized, resolving anyway`);
                    resolveLoad(); // Resolve loadPromise even if window is weird
                }
            });

            // Create an additional promise to wait for the component's specific ready signal
            const readySignal = `${window.prefix}-ready`;
            const componentReadyPromise = new Promise(resolveComponent => {
                // IMPORTANT: Attach the listener only *after* this window's load is complete
                loadPromise.then(() => {
                    Logger.log(`Waiting for ${readySignal} signal from ${window.prefix}...`);
                    ipcMain.once(readySignal, () => {
                        Logger.log(`${readySignal} signal received from ${window.prefix}`);
                        resolveComponent(); // Resolve componentReadyPromise when signal received
                    });
                    // Consider adding a timeout for this ipcMain.once listener here
                    // for extra robustness, in case a component never sends its signal.
                });
            });

            // Resolve the outer promise only when BOTH load and component ready are done
            Promise.all([loadPromise, componentReadyPromise]).then(resolveOuter);
        });
    });

    // Wait for all windows to complete both loading and component ready signal
    await Promise.all(readyPromises);

    Logger.info('All windows and components are ready');
}

function appHandleCriticalError(error) {
    Logger.error('Critical error:', error);

    // Show error dialog to user
    splashWindow?.close();
    dialog.showErrorBox(
        'Critical Error',
        `Polaris encountered a critical error and needs to close.\n\nError: ${error.message}`
    );

    // Cleanup and exit
    if (windowManager) {
        windowManager.cleanup();
    }
    app.exit(1);
}

let isForceShutdown = false;

process.on('SIGINT', async () => {
  if (isForceShutdown) return;

  isForceShutdown = true;
  Logger.info('Ctrl+C detected - initiating forced shutdown');

  try {
    await ServiceManager.stopServices({ force: true });
    app.exit(0);
  } catch (err) {
    Logger.error('Forced shutdown failed:', err);
    app.exit(1);
  }
});

app.on('before-quit', async (event) => {
  if (isForceShutdown) {
    event.preventDefault();
    return;
  }

  try {
    await ServiceManager.stopServices();
  } catch (err) {
    Logger.error('Graceful shutdown failed:', err);
  }
});

// Initialize and start the application
appInitialization().catch(err => {
    Logger.error('Failed to initialize app:', err);
    app.exit(1);
});
