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

const shortcutKey = config.get('shortcuts.show', 'F1');

// Check if this is the first run of the application
function isFirstRun() {
    return !config.get('setup.completed', false);
}

// Show the setup wizard for first-time users
function showSetupWizard() {
    Logger.info('First run detected, showing setup wizard');

    // Get the appropriate icon based on theme
    const theme = nativeTheme.shouldUseDarkColors ? 'dark' : 'light';
    const iconPath = path.resolve(__dirname, 'assets', `tray-icon-active-${theme}.png`);

    wizardActive = true;
    globalShortcut.unregister(shortcutKey);

    // Create setup window
    setupWindow = new BrowserWindow({
        width: 950,
        // width: 1350,
        height: 650,
        webPreferences: {
            nodeIntegration: true,
            contextIsolation: false
        },
        title: 'Polaris Setup',
        show: false,
        center: true,
        resizable: false,
        frame: false,
        skipTaskbar: true,
        transparent: true,
        iconPath: iconPath
    });

    setupWindow.setIcon(iconPath);

    // Load the setup page
    setupWindow.loadFile(path.join(__dirname, 'windows', 'setup', 'index.html'));

    setupWindow.once('ready-to-show', () => {
        setupWindow.show();
    });

    // setupWindow.webContents.openDevTools();
    async function setupComplete() {
        Logger.info('Setup completed, starting application');
        try {
            setupWindow?.close();
        } catch (error) {
            Logger.error('Error closing setupWindow:' + error);
        }
        wizardActive = false;
        appSetupShortcuts();
        updateProviderSubmenu();
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
        const timeout = 40000; // 40 seconds timeout
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
            splashWindow?.destroy();
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
            splashWindow.updateProgress('Downloading required resources...', 87);
            // Start the initialization process
            const initResult = await ServiceManager.initializeResources();
            if (!('status' in initResult) || initResult.status != "success" ) {
                splashWindow.close();
                Logger.error('Failed to initialize resources:', initResult.error);
                dialog.showErrorBox(
                    'Service Error',
                    'Failed to download required resources.'
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
        // Check if this is the first run
        if (isFirstRun()) {
            showSetupWizard();
            return;
        } else {
            showWindows(true);
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

async function appInitialization() {
    try {
        Logger.setDebugMode(debugMode);
        app.isQuitting = false;
        await app.whenReady();

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
        appSetupShortcuts();
        await appCreateTray();
        await waitForWindowsAndComponentsReady();

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
                // Start the initialization process
                const initResult = await ServiceManager.initializeResources();
                if (!('status' in initResult) || initResult.status != "success" ) {
                    Logger.error('Failed to initialize resources:', initResult.error);
                    dialog.showErrorBox(
                        'Service Error',
                        'Failed to download required resources.'
                    );
                    app.exit(1);
                }
            } else {
                Logger.info('All required resources are already initialized');
            }
            await updateProviderSubmenu();

            // Check if this is the first run
            !debugDisableWizard && isFirstRun() ?
                showSetupWizard()
            :
                showWindows(true);

            initializeAutoUpdater();
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
        const timeout = 40000; // 40 seconds timeout
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
            splashWindow.updateProgress('Downloading required resources...', 87);

            // Start the initialization process
            const initResult = await ServiceManager.initializeResources();

            if (!('status' in initResult) || initResult.status != "success" ) {
                splashWindow.close();
                Logger.error('Failed to initialize resources:', initResult.error);
                dialog.showErrorBox(
                    'Service Error',
                    'Failed to download required resources.'
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
        // Check if this is the first run
        if (isFirstRun()) {
            showSetupWizard();
            return;
        } else {
            showWindows(true);
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
        {
            label: 'Check for Updates',
            click: () => checkForUpdates(true)
        },
        {
            label: 'Auto-update',
            type: 'checkbox',
            checked: config.get('autoUpdate.enabled', true),
            click: (menuItem) => {
                config.set('autoUpdate.enabled', menuItem.checked);
                autoUpdater.autoInstallOnAppQuit = menuItem.checked;
            }
        },
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
            {
                label: 'LLM Models',
                submenu: [
                    {
                        label: 'Configure LLM Models',
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
        Logger.log("checkForUpdates: Auto-update disabled and not interactive, skipping check.");
        return;
    }

    autoUpdater.checkForUpdates().then(result => {
        Logger.log("checkForUpdates .then() received result:", result);
        // Log the crucial updateInfo part if it exists
        if (result && result.updateInfo) {
            Logger.log("checkForUpdates .then() updateInfo:", result.updateInfo);
        } else {
            Logger.log("checkForUpdates .then(): No updateInfo in result.");
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
    Logger.log(`AutoUpdater: Initializing. autoDownload=${autoUpdater.autoDownload}, allowPrerelease=${autoUpdater.allowPrerelease}`);
    Logger.log(`AutoUpdater: Current config - autoUpdate.enabled=${config.get('autoUpdate.enabled', true)}, updates.ignoredVersion=${config.get('updates.ignoredVersion', null)}`);

    autoUpdater.on('update-available', (info) => {
        Logger.log('AutoUpdater: update-available event handler START', info);
        const newVersion = info.version;
        const ignoredVersion = config.get('updates.ignoredVersion', null);

        // Only proceed if the new version is strictly greater than the ignored version
        if (ignoredVersion && semver.lte(newVersion, ignoredVersion)) {
            Logger.log(`Update available (${newVersion}) but ignored version (${ignoredVersion}) is same or newer. Skipping notification.`);
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
                Logger.log(`User chose to download update ${newVersion}`);
                // Create and show the progress window BEFORE starting download
                if (updateProgressWindow && !updateProgressWindow.isDestroyed()) {
                    updateProgressWindow.close(); // Close any existing instance
                }
                updateProgressWindow = new UpdateProgressWindow(config);
                updateProgressWindow.show();
                autoUpdater.downloadUpdate();
            } else if (response === 1) { // Ignore This Version
                Logger.log(`User chose to ignore update version ${newVersion}`);
                config.set('updates.ignoredVersion', newVersion);
                updateAvailable = null; // Clear update info as it's ignored
                showWindows(true);
            } else { // Later (or closed dialog)
                Logger.log(`User chose to postpone update ${newVersion}`);
                updateAvailable = null; // Clear update info for this session
                showWindows(true);
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

    autoUpdater.on('update-downloaded', () => {
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
        const iconPath = path.join(__dirname, 'assets', `tray-icon-active-${theme}.png`);

        // Update application icon
        if (process.platform === 'darwin' && !app.dock.isHidden()) {
            app.dock.setIcon(path.join(__dirname, 'assets', `tray-icon-active-${theme}.png`));
        }

        // Update all windows' icons
        if (windowManager) {
            windowManager.windows.forEach(window => {
                if (window.window && !window.window.isDestroyed()) {
                    window.window.setIcon(
                        path.join(__dirname, 'assets', `tray-icon-active-${theme}.png`)
                    );
                }
            });
            windowManager.updateTheme();
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
