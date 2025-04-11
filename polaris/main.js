const { app, Tray, Menu, dialog, globalShortcut, BrowserWindow, ipcMain, shell } = require('electron');
// const yargs = require('yargs/yargs');
// const { hideBin } = require('yargs/helpers');
const path = require('path');
const ConfigManager = require('./utils/config');
const { WindowManager } = require('./windows/WindowManager');
const ComRingWindow = require('./windows/ComRingWindow');
const ChatDisplayWindow = require('./windows/ChatDisplayWindow');
const SplashWindow = require('./windows/SplashWindow');
const ServiceManager = require('./utils/ServiceManager');
const ConfigHelper = require('./utils/ConfigHelper');
const Logger = require('./utils/logger');
const process = require('process');
const { nativeTheme } = require('electron');

const debugMode = true;
const debugDisableWizard = false;

const config = new ConfigManager();
let windowManager = null;
let tray = null;
let shortcutRegistered = false;
let splashWindow = null;
let setupWindow = null;

const shortcutKey = config.get('shortcuts.toggle', 'F1');

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

    // Create setup window
    setupWindow = new BrowserWindow({
        width: 950,
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

    // Handle setup completion
    ipcMain.once('setup-complete', () => {
        Logger.info('Setup completed, starting application');
        try {
            setupWindow?.close();
        } catch (error) {
            Logger.error('Error closing setupWindow:' + error);
        }
        showWindows(true);
    });

    ipcMain.on('close-setup-window', () => {
        Logger.info('Setup window close requested');
        if (!config.get('setup.completed', false)) {
            Logger.info('Setup was not completed, exiting application');
            app.quit();
        } else {
            try {
                setupWindow?.close();
            } catch (error) {
                Logger.error('Error closing setupWindow:' + error);
            }
        }
    });

    // If the user closes the setup window without completing setup
    setupWindow.on('closed', () => {
        setupWindow = null;
        if (!config.get('setup.completed', false)) {
            Logger.info('setup.completed value:' + config.get('setup.completed'));
            Logger.info('Setup was not completed, exiting application');
            app.quit();
        } else {
            showWindows(true);
        }
    });
}

async function appInitialization() {
    try {
        Logger.setDebugMode(debugMode);
        app.isQuitting = false;
        await app.whenReady();

        if (process.platform === 'darwin') {
            app.dock.hide();
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

        // If services are being managed externally finish the setup
        await ServiceManager.checkServicesHealth();
        if (ServiceManager.isAllHealthy()) {
            // Check if this is the first run
            !debugDisableWizard && isFirstRun() ?
                showSetupWizard()
            :
                showWindows(true);
            return;
        }

        // Create splash window
        splashWindow = new SplashWindow(config, null, null, __dirname);
        splashWindow.show();

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

        // Close splash and show main window
        splashWindow.updateProgress('Ready! Launching com-ring...', 100);
        await new Promise(resolve => setTimeout(resolve, 2000));
        splashWindow.close();
        // Check if this is the first run
        if (isFirstRun()) {
            showSetupWizard();
            return;
        } else {
            showWindows(true);
        }
        let llmProviders = await ConfigHelper.getLLMProviders();
        tray.setToolTip('Ainara Polaris v' + config.get('setup.version') + " - " + truncateMiddle(llmProviders.selected_provider, 44));
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
    if (!shortcutRegistered) {
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

    // let llmProviders = await ConfigHelper.getLLMProviders();
    // tray.setToolTip('Ainara Polaris v' + config.get('setup.version') + " - " + truncateMiddle(llmProviders.selected_provider, 44));
    tray.setToolTip('Ainara Polaris v' + config.get('setup.version'));
    tray.setContextMenu(contextMenu);

    // Update the provider submenu
    updateProviderSubmenu();

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
        // Get the current providers
        const { providers, selected_provider } = await ConfigHelper.getLLMProviders();

        if (!providers || providers.length === 0) {
            return;
        }

        // Create menu items for each provider
        const providerItems = providers.map(provider => {
            const model = provider.model || 'Unknown model';
            const context_window = "C" + (provider.context_window / 1024) + "K" || '';
            return {
                label: `${model} (${context_window})`,
                type: 'radio',
                checked: selected_provider === model,
                click: async () => {
                    const success = await ConfigHelper.selectLLMProvider(model);
                    if (success) {
                        // Update the menu
                        updateProviderSubmenu();
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
            ServiceManager.stopServices();
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

// Initialize and start the application
appInitialization().catch(err => {
    Logger.error('Failed to initialize app:', err);
    app.exit(1);
});
