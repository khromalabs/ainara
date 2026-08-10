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

const { app, Tray, Menu, dialog, globalShortcut, BrowserWindow, ipcMain, shell, screen, Notification, net } = require('electron');
const { autoUpdater } = require('electron-updater');
const { EventEmitter } = require('events');
const semver = require('semver');
// const yargs = require('yargs/yargs');
// const { hideBin } = require('yargs/helpers');
const path = require('path');
const { migrateToSavedGamesIfNeeded } = require('./framework/WindowsMigration');
const ConfigManager = require('./framework/config');
const { WindowManager } = require('./windows/WindowManager');
const ComRingWindow = require('./windows/ComRingWindow');
const ChatDisplayWindow = require('./windows/ChatDisplayWindow');
const SplashWindow = require('./windows/SplashWindow');
const UpdateProgressWindow = require('./windows/UpdateProgressWindow');
const ServiceManager = require('./framework/ServiceManager');
const ConfigHelper = require('./framework/ConfigHelper');
const Logger = require('./framework/logger');
const process = require('process');
const { nativeTheme } = require('electron');
const debugMode = true;
const ollama = require('ollama');

// // Add this helper function near other helpers
// async function checkInternetConnection() {
//     const dns = require('dns').promises;
//     try {
//         await dns.resolve('google.com');
//         return true;
//     } catch (err) {
//         try {
//             // Fallback check
//             await dns.resolve('cloudflare.com');
//             return true;
//         } catch (err2) {
//             return false;
//         }
//     }
// }


const config = new ConfigManager();
let updateAvailable = null;
let windowManager = null;
let tray = null;
let shortcutRegistered = false;
let splashWindow = null;
let setupWindow = null;
let wizardActive = false;
let updateProgressWindow = null;
let ollamaClient = null;
let appReady = false;
let docsSites = [];

const shortcutKey = config.get('shortcuts.show', 'F1');
const triggerKey = config.get('shortcuts.trigger', 'Space');
const hideKey = config.get('shortcuts.hide', 'Escape');
const myEmitter = new EventEmitter();

let trayState = null;
let trayListening = null;
let trayNotifications = null;

// TODO delayed to v0.10
// function applyAutoStartSetting() {
//     const autoStartEnabled = config.get('startup.autoStart', false);
//     Logger.info(`Applying auto-start setting. Enabled: ${autoStartEnabled}`);
//     // This API is cross-platform and handles the underlying OS specifics.
//     app.setLoginItemSettings({
//         openAtLogin: autoStartEnabled,
//         path: app.getPath('exe') // This is used by Windows and ignored by others.
//     });
// }

// Check if this is the first run of the application
function isFirstRun() {
    return !config.get('setup.completed', false);
}

var executingSetupComplete = false;

async function setupComplete() {
    if (executingSetupComplete) {
        return;
    }
    executingSetupComplete = true;
    Logger.info('Setup completed, starting application');
    wizardActive = false;
    // Notify com-ring wizard not active anymore
    BrowserWindow.getAllWindows().forEach(window => {
        if (!window.isDestroyed()) {
            window.webContents.send('wizard-status', false);
        }
    });

    // Close setup window
    try {
        setupWindow?.close();
        setupWindow?.destroy();
    } catch (error) {
        Logger.error('Error closing setupWindow:' + error);
        app.quit();
        executingSetupComplete = false;
        return;
    }

    if (! await ServiceManager.stopServices() ) {
        splashWindow.close();
        dialog.showErrorBox(
            'Service Error',
            'Failed to stop required services. Please check the logs for details.'
        );
        app.quit();
        executingSetupComplete = false;
        return;
    }

    // Restart application
    Logger.info('Reinitializing application (firstInitialization=false)');
    await appInitialization(false);
    executingSetupComplete = false;
}


// Show the setup wizard for first-time users
function showSetupWizard(validationErrors = []) {
    // console.trace();
    if (validationErrors && validationErrors.length > 0 && config.get("setup.completed", false)) {
        Logger.warn('Configuration validation failed, invalidating setup.complete because of these errors:', validationErrors);
        config.set("setup.completed", false);
    } else {
        Logger.info('Showing setup wizard');
    }

    // Notify com-ring wizard active
    BrowserWindow.getAllWindows().forEach(window => {
        if (!window.isDestroyed()) {
            window.webContents.send('wizard-status', true);
        }
    });

   // Disable tray icon
    if (tray) {
        tray.destroy();
        tray = null;
    }

    config.set('setup.completed', false)

    // Get the appropriate icon based on theme
    const theme = nativeTheme.shouldUseDarkColors ? 'dark' : 'light';
    const iconPath = path.resolve(__dirname, 'assets', `tray-icon-active-${theme}.png`);

    wizardActive = true;
    console.log("showSetupWizard: Disabled shortcutKey")
    globalShortcut.unregisterAll();
    shortcutRegistered = false;

    const { width: screenWidth, height: screenHeight } = screen.getPrimaryDisplay().workAreaSize;
    Logger.info("Screen X:" + screenWidth + " Screen Y:" + screenWidth)

    // Create setup window
    setupWindow = new BrowserWindow({
        width: Math.floor(screenWidth * 0.7),
        height: Math.floor(screenHeight * 0.95),
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
        iconPath: iconPath,
        hasShadow: false
    });
    setupWindow.webContents.openDevTools();

    setupWindow.setIcon(iconPath);
    // updateTrayIcon();

    // Load the setup page
    setupWindow.loadFile(path.join(__dirname, 'components', 'setup.html'));

    setupWindow.once('ready-to-show', () => {
        if (validationErrors && validationErrors.length > 0 && config.get("setup.completed", false)) {
            dialog.showErrorBox(
                'Configuration Error',
                'The configuration is missing some required values. The setup wizard will now launch. Error(s):\n\n' + validationErrors,
                // 'The configuration file contains the following errors:\n\n' + validationErrors + "\n\nThe setup wizard will be opened now."
            );
        }
        setupWindow.show();
        // // Pass validation errors to the wizard window
        // if (validationErrors && validationErrors.length > 0) {
        //     setupWindow.webContents.send('config-validation-errors', validationErrors);
        // }
    });


    // If the user closes the setup window without completing setup
    ipcMain.on('close-setup-window', async () => {
        Logger.info('close-setup-window event');
        setupWindow?.close();
        if (config.get('setup.completed', false)) {
            // TODO: Don't know what this means, setupComplete is needed here
            // Correction: Prevented re-entrant call to setupComplete.
            Logger.info('Setup complete, window closed by user. Main flow will continue.');
            setupComplete();
        } else {
            Logger.info('Setup incomplete - forcing immediate exit');
            await ServiceManager.stopServices();
            app.quit(); // Hard exit without cleanup
        }
    });

    // Handle setup completion
    ipcMain.on('setup-complete', setupComplete);
}

async function checkConfigAndProceed() {
    const pybridgeUrl = config.get('pybridge.api_url', 'http://127.0.0.1:8101');
    try {
        // Use Electron's net module for requests to avoid external dependencies
        const { net } = require('electron');
        const response = await net.fetch(`${pybridgeUrl}/config/status`);

        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        const configStatus = await response.json();

        // Show wizard if it's the first run or if the original config was invalid
        if (isFirstRun() || !configStatus.initial_config_valid) {
            if (splashWindow && !splashWindow.window.isDestroyed()) {
                splashWindow.close();
            }
            showSetupWizard(configStatus.errors);
            return false; // Indicates we should stop normal startup
        }
        return true; // Indicates we should proceed
    } catch (error) {
        appHandleCriticalError(new Error(`Could not verify configuration with PyBridge service. ${error.message}`));
        return false;
    }
}

function initializeOllamaClient() {
    const serverIp = config.get('ollama.serverIp', '127.0.0.1');
    const port = config.get('ollama.port', 11434);
    ollamaClient = new ollama.Ollama({ host: `http://${serverIp}:${port}` });
    Logger.info(`Ollama client initialized with server: ${serverIp}:${port}`);
}

function isRunningAsAppX() {
    // This is a reliable way to check for APPX/MSIX packaged environments.
    return !!process.env.PackageFamilyName;
}

async function appFirstInitializationTasks() {
    const singleInstanceLock = app.requestSingleInstanceLock();

    if (!singleInstanceLock) {
        // App is already running this will force visibility
        app.quit();
        return;
    }

    app.on('second-instance', () => {
        if (windowManager && appReady) {
            windowManager.showAll();
        }
    });

    Logger.setDebugMode(debugMode);
    app.isQuitting = false;
    app.isRefreshing = false;
    app.commandLine.appendSwitch('ozone-platform', 'x11');
    await app.whenReady();

    // // Apply auto-start setting on launch
    // applyAutoStartSetting();

    // Initialize Ollama client
    initializeOllamaClient();

    // Initialize window manager and windows
    windowManager = new WindowManager(config);
    windowManager.initialize(
        [ComRingWindow, ChatDisplayWindow],
        __dirname
    );

    let firstTimeShow = true;

    // Listen for visibility changes to handle tray, shortcuts, and focus
    windowManager.on('visibility-changed', (state) => {
        if(updateTrayIcon) {
            updateTrayIcon(state);
        }

        if (state === 'active') {
            // Unregister shortcut and focus comRing (original showWindowsBackend logic)
            globalShortcut.unregister(shortcutKey);
            shortcutRegistered = false;
            Logger.log('visibility-changed (active): unregistered globalShortcut');
            const comRing = windowManager.getWindow('comRing');
            setTimeout(() => {
                if (comRing) {
                    if(firstTimeShow) {
                        // ugly hack to force focus
                        comRing.minimize();
                        comRing.restore();
                        firstTimeShow = false;
                    }
                    comRing.window.setAlwaysOnTop(true);
                    comRing.focus();
                    Logger.log('visibility-changed (active): focused comRing');
                }
            }, 300);
        } else if (state === 'inactive' && !wizardActive) {
            // Register shortcut (original hideWindowsBackend logic)
            if (!shortcutRegistered) {
                shortcutRegistered = globalShortcut.register(
                    shortcutKey,
                    () => windowManager.showAll(true)
                );
                if (shortcutRegistered) {
                    Logger.info('visibility-changed (inactive): Successfully registered shortcut:', shortcutKey);
                } else {
                    Logger.error('visibility-changed (inactive): Failed to register shortcut:', shortcutKey);
                }
            }
        }
    });
    appSetupEventHandlers();
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
}

async function appInitialization(firstInitialization = true) {
    try {
        // reset tray vars
        trayState = null;
        trayListening = null;
        trayNotifications = null;

        if (firstInitialization) {
            await appFirstInitializationTasks();
        }
        // app.commandLine.appendSwitch('disable-gpu');

        // Create splash window
        splashWindow = new SplashWindow(config, null, null, __dirname);
        splashWindow.show();

        // Windows data location migration (must happen before services start)
        if (process.platform === 'win32') {
            splashWindow.updateProgress('Checking data location...', 5);
            const migrationResult = await migrateToSavedGamesIfNeeded();
            if (!migrationResult.success) {
                splashWindow.close();
                dialog.showErrorBox(
                    'Migration Error',
                    `Failed to set up data location. Polaris cannot continue.\n\nError: ${migrationResult.error}`
                );
                app.quit();
                return;
            }
            if (migrationResult.migrated) {
                // Notify user and restart the app to pick up new paths
                const notification = new Notification({
                    title: 'Ainara AI',
                    body: 'Data successfully migrated to the Saved Games folder for better performance and safety. The app will now restart.',
                    icon: path.join(__dirname, 'assets', 'icon.png')
                });
                notification.show();
                await new Promise(resolve => setTimeout(resolve, 3000));
                app.relaunch();
                app.exit();
                return; // Will not reach due to exit
            }
        }

        // If services are being managed externally alternate start without splash
        // Alternate application start for dev purposes
        if (process.env.AINARA_ONLY_POLARIS) {
            if (!firstInitialization) {
                Logger.warning("Externally managed services need manual restart. Exiting.");
                app.quit();
            }
            Logger.warning('AINARA_ONLY_POLARIS: Avoiding services launch');
            splashWindow.close();
            if(!await ServiceManager.checkServicesHealth()) {
                Logger.error('Services are not healthy');
                app.quit()
            }

            // Check config validity before proceeding
            if (!await checkConfigAndProceed()) {
                return;
            }
            startOllamaKeepAlive();
            await updateProviderSubmenu(); // Must be before initializeAutoUpdater
            if (!isRunningAsAppX()) {
                initializeAutoUpdater();
            }
            // Set shortcut just before showing windows
            appSetupShortcuts();
            await appCreateTray();
            // Read the start minimized setting
            const startMinimized = config.get('startup.startMinimized', false);
            if (!startMinimized) {
                Logger.info('Starting with windows visible.');
                windowManager.showAll(true);
            } else {
                Logger.info('Starting minimized as per configuration.');
            }
            return;
        }

        // Set up service manager progress callback
        ServiceManager.setProgressCallback((status, progress) => {
            splashWindow.updateProgress(status, progress);
        });

        // Start services
        splashWindow.updateProgress('Starting services...', 10);
        const { success: servicesStarted, message } =
            await ServiceManager.startServices();

        if (!servicesStarted) {
            splashWindow.close();
            const options = {
                type: 'question',
                buttons: ['Yes', 'No'],
                title: 'Startup Error',
                message: 'Error: ' + message  + '. Do you want to open the setup wizard? Maybe the LLM is not responding, please try another LLM provider, if possible a faster one.'
            };
            const response = dialog.showMessageBoxSync(
                null,
                options,
            );
            if (response === 0) { // Yes
                showSetupWizard();
            } else { // No
                app.quit();
            }
            return;
        }

        // Wait for services to be healthy
        splashWindow.updateProgress('Waiting for services to be ready...', 40);

        // Poll until all services are healthy or timeout
        const startTime = Date.now();
        const timeout = 900000; // 900 seconds/15 min timeout
        let servicesHealthy = false;
        while (Date.now() - startTime < timeout) {
            if (await ServiceManager.checkServicesHealth()) {
                servicesHealthy = true;
                break;
            }
            await new Promise(resolve => setTimeout(resolve, 5000));
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

        // Start background health monitoring now that services are up
        ServiceManager.startHealthCheck();

        // Load documentation sites list from backend
        try {
            const response = await net.fetch('http://127.0.0.1:8101/docs/list');
            if (response.ok) {
                docsSites = await response.json();
                Logger.info(`Found ${docsSites.length} documentation sites.`);
            } else {
                Logger.warn('Failed to retrieve documentation sites list.');
            }
        } catch (e) {
            Logger.error('Error fetching documentation sites:', e);
        }

        // AUTHENTICATION CHECK
        splashWindow.updateProgress('Verifying Access...', 70);

        // // Check Internet Connection before Auth
        // while (!await checkInternetConnection()) {
        //     const response = dialog.showMessageBoxSync({
        //         type: 'error',
        //         buttons: ['Retry', 'Quit'],
        //         title: 'No Internet Connection',
        //         message: 'Polaris requires an active internet connection to verify your access.',
        //         detail: 'Please check your connection and try again.'
        //     });
        //     if (response === 1) { // Quit
        //         app.quit();
        //         return;
        //     }
        // }

        if (!await checkBackendAuth(splashWindow)) {
            return; // Stop initialization, Setup Wizard has been triggered
        }

        // Services are ready, check config and initialize the rest of the app
        splashWindow.updateProgress('Verifying configuration...', 75);

        // Check config validity before proceeding
        if (!await checkConfigAndProceed()) {
            return;
        }

        splashWindow.updateProgress('Initializing application...', 80);

        // Update the provider submenu
        await updateProviderSubmenu();

        // Start Ollama keep-alive mechanism
        startOllamaKeepAlive();

        // Close splash and show main window
        splashWindow.updateProgress('Ready!', 100);
        await new Promise(resolve => setTimeout(resolve, 1000));
        await splashWindow.close();

        // Read the start minimized setting
        await appCreateTray();
        let llmProviders = await ConfigHelper.getLLMProviders();
        if (llmProviders) {
            tray.setToolTip('Ainara Polaris v' + config.get('setup.version') + " - " + truncateMiddle(llmProviders.selected_provider, 44));
        }

        if (!isRunningAsAppX()) {
            initializeAutoUpdater();
        }

        /**
         * New Backend-Centric Gatekeeper
         */
        async function checkBackendAuth(splash) {
            const pybridgeUrl = config.get('pybridge.api_url', 'http://127.0.0.1:8101');
            const { net } = require('electron');

            // Loop to handle retryable network errors from backend
            while (true) {
                try {
                    Logger.info("Auth: Checking status with backend...");
                    const response = await net.fetch(`${pybridgeUrl}/auth/status`);

                    if (response.ok) {
                        const status = await response.json();
                        if (status.authorized) {
                            Logger.info(`Auth: Authorized (Wallet: ${status.wallet})`);
                            return true;
                        }

                        // Handle Network Error specifically (Backend couldn't reach Solana)
                        if (status.reason === 'network_error') {
                            const response = dialog.showMessageBoxSync({
                                type: 'error',
                                buttons: ['Retry', 'Quit'],
                                title: 'Connection Error',
                                message: 'Unable to reach Solana network to verify ownership.',
                                detail: 'Please check your connection and try again.'
                            });
                            if (response === 1) { // Quit
                                app.quit();
                                return false;
                            }
                            continue; // Retry loop
                        }

                        Logger.warn(`Auth: Unauthorized (${status.reason}). Launching Setup.`);
                        break; // Exit loop to show setup
                    }
                } catch (error) {
                    Logger.error("Auth: Failed to contact backend.", error);
                    break; // Fall through to setup
                }
            }

            // If we get here, we are not authorized
            splash.close();
            showSetupWizard();
            return false;
        }

        checkFirstRunTasks();

        // Set shortcut just before showing windows
        appSetupShortcuts();

        // Show windows if not startMinimized
        if (!config.get('startup.startMinimized', false)) {
            Logger.info('Starting with windows visible.');
            windowManager.showAll(true);
        } else Logger.info('Starting minimized as per configuration.');
        Logger.info('Polaris initialized successfully');
        appReady = true;
    } catch (error) {
        appHandleCriticalError(error);
    }
}


function checkFirstRunTasks() {
    // New: Show one-time tray guidance notification on Windows
    // if (process.platform === 'win32' && config.get('setup.firstLaunch', true)) {
    if (config.get('setup.firstLaunch', true)) {
        const notification2 = new Notification({
            title: 'Ainara AI',
            body: `Press ${shortcutKey} to show Ainara Polaris, ${hideKey} to hide it and enter in background mode, ${triggerKey} to push-to-talk to Ainara`,
            icon: path.join(__dirname, 'assets/icon.png')  // Use your app icon
        });
        notification2.on('click', () => windowManager.showAll());  // Click notification to show UI
        notification2.show();
        const notification = new Notification({
            title: 'Ainara AI',
            body: 'On top of the available keyboard shortcuts, click the tray icon (left button) to toggle visibility, right button will show a contextual menu.',
            icon: path.join(__dirname, 'assets/icon.png')  // Use your app icon
        });
        notification.on('click', () => windowManager.showAll());  // Click notification to show UI
        notification.show();
        config.set('setup.firstLaunch', false);  // Mark as shown
        config.saveConfig();
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
    app.quit();
}


function appSetupShortcuts() {
    if (!wizardActive && !shortcutRegistered) {
        shortcutRegistered = globalShortcut.register(
            shortcutKey,
            () => windowManager.showAll(true));

        if (shortcutRegistered) {
           Logger.info('Successfully registered shortcut:', shortcutKey);
        } else {
            Logger.error('Failed to register shortcut:', shortcutKey);
            app.quit();
        }
    }
}

// Convert other methods to regular functions (keeping their existing logic)
async function appCreateTray() {
    const { nativeImage } = require('electron'); // Ensure nativeImage is required
    const iconBasePath = path.join(__dirname, 'assets');
    const theme = nativeTheme.shouldUseDarkColors ? 'dark' : 'light';

    Logger.info(`appCreateTray: Called. wizardActive = ${wizardActive}, theme = ${theme}`);

    if (wizardActive) {
        Logger.info('appCreateTray: Wizard is active, skipping tray creation.');
        return;
    }
    if (trayListening === null) {
        trayListening = config.get('wakeword.enabled', false);
    }
    let listeningTail = trayListening ? "-green" : "";
    // Set initial tray icon based on service health
    const iconStatus = 'inactive';
    // Use platform-specific icon naming
    let iconFileName;
    if (process.platform === 'darwin') {
        // On macOS, use a template image with the proper naming convention
        iconFileName = `tray-icon-${iconStatus}-Template.png`;
    } else {
        // On other platforms, continue using theme-specific icons
        iconFileName = `tray-icon-${iconStatus}-${theme}${listeningTail}.png`;
    }
    const fullIconPath = path.join(iconBasePath, iconFileName);

    Logger.info(`appCreateTray: Attempting to use icon: ${fullIconPath}`);

    let image = nativeImage.createFromPath(fullIconPath);

    if (image.isEmpty()) {
        Logger.error(`appCreateTray: Failed to load image at ${fullIconPath}. Image is empty.`);
        // Try fallback to theme-specific icon if template image fails
        if (process.platform === 'darwin') {
            const fallbackPath = path.join(iconBasePath, `tray-icon-${iconStatus}-${theme}.png`);
            Logger.info(`appCreateTray: Trying fallback icon: ${fallbackPath}`);
            image = nativeImage.createFromPath(fallbackPath);
        }

        if (image.isEmpty()) {
            Logger.error('appCreateTray: Fallback image also empty or not applicable. Tray icon will likely not appear.');
            return; // Can't create tray without a valid image
        }
    } else {
        Logger.info(`appCreateTray: Image loaded successfully from ${fullIconPath}. Size: ${JSON.stringify(image.getSize())}`);
    }

    // Only resize for Windows - macOS uses properly sized template images
    // and Linux can handle various sizes
    if (process.platform === 'win32') {
        const size = image.getSize();
        // Windows: 16x16 (standard) or 32x32 (high DPI)
        // Windows typically expects small icons for the system tray
        if (size.width > 32 || size.height > 32) {
            Logger.info(`appCreateTray: Resizing image for Windows (${size.width}x${size.height} → 16x16)`);
            image = image.resize({ width: 16, height: 16 });
            Logger.info(`appCreateTray: Image resized. New size: ${JSON.stringify(image.getSize())}`);
        }
    } else if (process.platform === 'linux') {
        const size = image.getSize();
        // Linux tray implementations typically expect 22-24px icons
        if (size.width > 24 || size.height > 24) {
            Logger.info(`appCreateTray: Resizing image for Linux (${size.width}x${size.height} → 24x24)`);
            image = image.resize({ width: 24, height: 24 });
            Logger.info(`appCreateTray: Image resized. New size: ${JSON.stringify(image.getSize())}`);
        }
    }

    try {
        tray = new Tray(image);
        Logger.info('appCreateTray: Tray object created successfully.');

        // For macOS, set highlight mode
        if (process.platform === 'darwin') {
            tray.setHighlightMode('selection');
            Logger.info('appCreateTray: Set macOS highlight mode to selection');
        }


        // tray.setContextMenu(contextMenu);
        await updateProviderSubmenu();
        Logger.info('appCreateTray: Context menu set.');

        // A 'click' event now reliably corresponds to a left-click on all platforms.
        tray.on('click', () => {
            Logger.info('Tray clicked.');
            if (wizardActive) {
                Logger.info('Wizard active, skipping visibility toggle');
                return
            }
            windowManager.toggleVisibility();
        });
        Logger.info('appCreateTray: Click listeners added.');

        // Set initial tooltip
        let llmProviders = await ConfigHelper.getLLMProviders();
        if (llmProviders && llmProviders.selected_provider) {
            tray.setToolTip('Ainara Polaris v' + config.get('setup.version') + " - " + truncateMiddle(llmProviders.selected_provider, 44));
        } else {
            tray.setToolTip('Ainara Polaris v' + config.get('setup.version'));
        }
    } catch (error) {
        Logger.error(`appCreateTray: Error during tray setup: ${error.message}`, error);
    }
}

function updateTrayIcon(state, listening=null, notifications=null) {
    const { nativeImage } = require('electron');
    const theme = nativeTheme.shouldUseDarkColors ? 'dark' : 'light';
    if (tray && !tray.isDestroyed()) {
        let iconFileName, listeningTail, notificationsTail;
        if (trayListening === null) {
            trayListening = config.get('wakeword.enabled', false);
        }
        listeningTail = trayListening ? "-green" : "";
        if (state !== null) {
            trayState = state;
        }
        if (notifications !== null) {
            trayNotifications = notifications;
        }
        notificationsTail = trayNotifications ? "-notifications" : "";
        if (process.platform === 'darwin') {
            // TODO darwin green icon
            iconFileName = `tray-icon-${trayState}-Template.png`;
        } else {
            iconFileName = `tray-icon-${trayState}-${theme}${listeningTail}${notificationsTail}.png`;
        }
        const iconPath = path.join(__dirname, 'assets', iconFileName);
        try {
            let image = nativeImage.createFromPath(iconPath);
            if (image.isEmpty()) {
                Logger.error(`updateTrayIcon: Failed to load image at ${iconPath}`);
                return;
            }

            // Resize for platforms that expect small tray icons
            if (process.platform === 'linux') {
                const size = image.getSize();
                if (size.width > 24 || size.height > 24) {
                    image = image.resize({ width: 24, height: 24 });
                }
            } else if (process.platform === 'win32') {
                const size = image.getSize();
                if (size.width > 32 || size.height > 32) {
                    image = image.resize({ width: 16, height: 16 });
                }
            }

            tray.setImage(image);
        } catch (e) {
            Logger.error(`Failed to set tray icon for state ${state}:`, e);
        }
    }
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
async function startOllamaKeepAlive() {
    try {
        const { selected_provider } = await ConfigHelper.getLLMProviders();
        if (selected_provider && selected_provider.startsWith('ollama/')) {
            const modelId = selected_provider.split('/')[1];
            Logger.info(`startOllamaKeepAlive: ping to selected_provider: ${selected_provider}.`);
            await loadOllamaModel(modelId);
        }
        setTimeout(startOllamaKeepAlive, 290000);
    } catch (error) {
        Logger.error('Error in Ollama keep-alive:', error);
    }
}


// Add function to update provider submenu
async function updateProviderSubmenu() {
    try {
        if (!tray) {
            Logger.warn('updateProviderSubmenu: tray not available yet, skipping.');
            return;
        }

        const updateItems = isRunningAsAppX() ? [] : [
            { type: 'separator' },
            {
                label: 'Check for Updates',
                click: () => checkForUpdates(true)
            },
        ];

        // Logger.info('UPDATING PROVIDER SUBMENU');

        // Get the current providers
        const { providers, selected_provider } = await ConfigHelper.getLLMProviders();

        if (!providers || providers.length === 0) {
            return;
        }

        function truncateToDecimals(num, dec = 1) {
            const calcDec = Math.pow(10, dec);
            return Math.trunc(num * calcDec) / calcDec;
        }

        // Create menu items for each provider
        const providerItems = providers.map(provider => {
            const model = provider.model || 'Unknown model';
            const context_window = provider.context_window ?
                "(C" + truncateToDecimals(provider.context_window / 1024) + "K)" :
                '';
            return {
                label: `${model} ${context_window}`,
                type: 'radio',
                checked: selected_provider === model,
                click: async () => {
                    windowManager.showAll(true);
                    myEmitter.emit('visibility-changed', 'active');
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

        providerItems.sort((a,b) => a.label.localeCompare(b.label));

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
            ...updateItems,
            { type: 'separator' },
            {
                label: 'Help',
                click: () => {
                    const comRing = windowManager.getWindow('comRing');
                    if (comRing) {
                        if (!comRing.isVisible()) {
                            windowManager.showAll(true);
                        }
                        comRing.send('show-help');
                    }
                }
            },
            ...(docsSites.length > 0 ? [{
                label: 'Nexus Apps Documentation',
                submenu: docsSites.map(site => ({
                    label: `${capitalize(site.application)} by ${capitalize(site.publisher)}`,
                    click: () => shell.openExternal(`http://127.0.0.1:8101/docs/${site.publisher}/${site.application}/`)
                }))
            }] : []),
            {
                label: 'About',
                click: () => {
                    const comRing = windowManager.getWindow('comRing');
                    if (comRing) {
                        if (!comRing.isVisible()) {
                            windowManager.showAll(true);
                        }
                        comRing.send('show-about');
                    }
                }
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

const capitalize = (str) => str.charAt(0).toUpperCase() + str.slice(1);

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
    autoUpdater.allowPrerelease = config.get('autoUpdate.allowPrerelease', false);
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

        const comRing = windowManager.getWindow('comRing');
        if ( comRing )
            comRing.hide();

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
                    windowManager.showAll(true);
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
    // Add handler for Wake Word status updates from com-ring
    ipcMain.on('wakeword-status', (event, status) => {
        // // status can be: 'listening', 'active' (recording), 'inactive'
        // var active = null, green = null;
        // if (status === 'listening') {
        //     // active = false;
        //     green = true;
        // } else if(status === 'active')  {
        //     // active = true;
        //     green = true;
        // } else if(status === 'inactive') {
        //     // active = false;
        //     green = false;
        // }
        // if (!windowManager.isAnyVisible()) {
        //     updateTrayIcon(active, green); // 2nd param green icon
        // }
    });

    ipcMain.on('notifications-available', (event, status) => {
        // Logger.info('Notifications available:' + status);
        updateTrayIcon(null, null, status);
    });

    ipcMain.on('refresh-frontend', () => {
        Logger.info('Refreshing frontend...');
        app.isRefreshing = true;
        app.relaunch();
        app.quit();
    });

    // Handle opening external links in the system browser
    ipcMain.on('open-external-url', (event, url) => {
        shell.openExternal(url);
    });

    // // Handle auto-start setting changes from setup wizard
    // ipcMain.on('set-auto-start', () => {
    //     applyAutoStartSetting();
    // });

    // Handle backup directory selection from setup wizard
    ipcMain.on('select-backup-directory', async (event) => {
        const window = BrowserWindow.fromWebContents(event.sender);
        if (window) {
            const result = await dialog.showOpenDialog(window, {
                properties: ['openDirectory']
            });

            if (!result.canceled && result.filePaths.length > 0) {
                event.sender.send('backup-directory-selected', result.filePaths[0]);
            }
        }
    });

    // Handle user skills directory selection from setup wizard
    ipcMain.handle('select-user-skills-directory', async (event) => {
        const result = await dialog.showOpenDialog({
            title: 'Select User Skills Directory',
            properties: ['openDirectory']
        });
        return result;
    });

    // Correction: Modified 'window-all-closed' handler for tray application behavior.
    // Improvement: A tray application should not quit when all its windows are closed.
    // This handler is changed to do nothing, aligning with the app's design to run
    // in the background. Individual window 'close' events are already handled to hide
    // windows instead of quitting.
    app.on('window-all-closed', () => { });

    // Handle app activation (e.g., clicking dock icon on macOS)
    app.on('activate', () => {
        // Correction: Simplified the 'activate' event handler.
        // Improvement: The `windowManager.isEmpty()` check is unreachable because windows are
        // created at startup and never destroyed, only hidden. This simplifies the logic to
        // always handle the case where the app is running but may not have visible windows.
        // Update tray icon to active when app is activated via taskbar/dock click
        updateTrayIcon('active');
        // Ensure windows are shown if they were hidden or minimized
        if (!windowManager.isAnyVisible()) {
            windowManager.showAll();
        }
    });

    // Cleanup before quit
    app.on('before-quit', async () => {
        globalShortcut.unregisterAll();
        shortcutRegistered = false;

        if (!app.isRefreshing) {
            // Stop services
            try {
                await ServiceManager.stopServices();
                Logger.info('Services stopped successfully');
            } catch (error) {
                Logger.error('Error stopping services:', error);
            }
        }

        if (windowManager) {
            windowManager.cleanup();
        }
    });

    // Remove browser-window-focus handler as it conflicts with hide/show logic
    app.removeAllListeners('browser-window-focus');

    // Correction: Removed redundant 'hide' event handler.
    // Improvement: Shortcut registration is now solely managed by the 'visibility-changed'
    // event on the WindowManager, simplifying logic and preventing potential race conditions.
    windowManager.windows.forEach(window => {
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

        // Update tray based on current visibility (query WindowManager)
        const currentState = windowManager.isAnyVisible() ? 'active' : 'inactive';
        updateTrayIcon(currentState);

        // Update setup window icon if it exists
        if (setupWindow && !setupWindow.isDestroyed()) {
            const iconPath = path.join(__dirname, 'assets', `tray-icon-${currentState}-${theme}.png`);
            setupWindow.setIcon(iconPath);
        }
    });

    // Add: Handler to open the auth portal
    ipcMain.on('open-auth-portal', () => {
        const pybridgeUrl = config.get('pybridge.api_url', 'http://127.0.0.1:8101');
        shell.openExternal(`${pybridgeUrl}/auth/portal`);
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
    app.quit();
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
    app.quit();
  }
});

app.on('before-quit', async (event) => {
  if (isForceShutdown) {
      event.preventDefault();
      return;
  }
  try {
      if (!app.isRefreshing) {
          await ServiceManager.stopServices();
      }
      // force
      app.exit(0);
  } catch (err) {
      Logger.error('Graceful shutdown failed:', err);
  }
});


// Initialize and start the application
appInitialization().catch(err => {
    Logger.error('Failed to initialize app:', err);
    app.quit();
});
