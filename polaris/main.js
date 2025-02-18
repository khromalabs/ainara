const { app, Tray, Menu, dialog, globalShortcut } = require('electron');
const yargs = require('yargs/yargs');
const { hideBin } = require('yargs/helpers');
const path = require('path');
const ConfigManager = require('./utils/config');
const { WindowManager } = require('./windows/WindowManager');
const ComRingWindow = require('./windows/ComRingWindow');
const ChatDisplayWindow = require('./windows/ChatDisplayWindow');
const Logger = require('./utils/logger');

const config = new ConfigManager();
let windowManager = null;
let tray = null;
let shortcutRegistered = false;
const shortcutKey = config.get('shortcuts.toggle', 'Super+K');

async function checkServerHealth(url, serviceName) {
    try {
        Logger.log(`Checking ${serviceName} server at: ${url}`);
        const response = await fetch(url);
        if (!response.ok) {
            throw new Error(`${serviceName} server returned status ${response.status}`);
        }
        Logger.log(`${serviceName} server is available`);
        return true;
    } catch (error) {
        Logger.error(`${serviceName} server not available at ${url}:`, error.message);
        return false;
    }
}


async function appInitialization() {
    try {
        // Parse command line arguments
        const argv = yargs(hideBin(process.argv))
            .option('debug', {
                alias: 'd',
                type: 'boolean',
                description: 'Enable debug logging'
            })
            .argv;

        Logger.setDebugMode(true);

        // // Get base URLs from config
        // const whisperUrl = config.get('stt.modules.whisper.custom.apiUrl', 'http://127.0.0.1:8080');
        // console.log("------" + whisperUrl);
        // const pybridgeUrl = config.get('pybridge.api_url', 'http://localhost:5001');
        //
        // // Clean up URLs to get base addresses
        // const whisperBaseUrl = whisperUrl.replace('/inference', '');
        // const pybridgeBaseUrl = pybridgeUrl.replace(/\/+$/, '');
        //
        // const [whisperHealth, pybridgeHealth] = await Promise.all([
        //     checkServerHealth(whisperBaseUrl, 'Whisper'),
        //     checkServerHealth(pybridgeBaseUrl, 'Pybridge')
        // ]);
        //
        // if (!whisperHealth || !pybridgeHealth) {
        //     const missingServices = [];
        //     if (!whisperHealth) missingServices.push('Whisper');
        //     if (!pybridgeHealth) missingServices.push('Pybridge');
        //
        //     throw new Error(`Required services not available: ${missingServices.join(', ')}\n` +
        //                   `Please ensure the following servers are running:\n` +
        //                   `- Whisper server at ${whisperBaseUrl}\n` +
        //                   `- Pybridge server at ${pybridgeBaseUrl}`);
        // }

        app.isQuitting = false;
        await app.whenReady();

        if (process.platform === 'darwin') {
            app.dock.hide();
        }

        windowManager = new WindowManager(config);
        windowManager.initialize([ComRingWindow, ChatDisplayWindow]);

        appSetupEventHandlers();
        appSetupShortcuts();
        appCreateTray();

        Logger.info('Polaris initialized successfully');
    } catch (error) {
        appHandleCriticalError(error);
    }
}

function appSetupShortcuts() {
    if (!shortcutRegistered) {
        shortcutRegistered = globalShortcut.register(shortcutKey, () => {
            Logger.log('Shortcut pressed'); // Keep as debug log
            if (!windowManager.isAnyVisible()) {
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
        });

        if (shortcutRegistered) {
            Logger.info('Successfully registered shortcut:', shortcutKey);
        } else {
            Logger.error('Failed to register shortcut:', shortcutKey);
        }
    }
}

// Convert other methods to regular functions (keeping their existing logic)
function appCreateTray() {
    const iconPath = path.join(__dirname, 'assets', 'tray-icon.png');
    tray = new Tray(iconPath);

    const contextMenu = Menu.buildFromTemplate([
        {
            label: 'Show',
            click: () => windowManager.showAll()
        },
        {
            label: 'Hide',
            click: () => windowManager.hideAll()
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

    tray.setToolTip('Polaris');
    tray.setContextMenu(contextMenu);

    // Optional: Single click to toggle windows
    tray.on('click', () => windowManager.toggleVisibility());
}

function appSetupEventHandlers() {
    // Prevent app from closing when all windows are closed
    app.on('window-all-closed', (e) => {
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
    app.on('before-quit', () => {
        globalShortcut.unregisterAll();
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
    });
}

function appHandleCriticalError(error) {
    Logger.error('Critical error:', error);

    // Show error dialog to user
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
