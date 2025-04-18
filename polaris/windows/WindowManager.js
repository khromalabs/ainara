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

const { screen, ipcMain } = require('electron');
const Logger = require('../utils/logger');
const path = require('path');
const { nativeTheme } = require('electron');

class WindowManager {
    constructor(config) {
        this.config = config;
        this.windows = new Map();
        this.handlers = {
            onBlur: () => {},
            onShow: () => {},
            onHide: () => {},
            beforeHide: () => {},
            onFocus: () => {},
        };
        this.tray = null;
        this.iconPath = null;
        this.currentState = 'inactive';
        this.basePath = null;
    }

    initialize(windowClasses, basePath) {
        this.basePath = basePath;
        this.handlers = this.collectHandlers(windowClasses);
        this.createWindows(windowClasses);
        this.setupWindowEvents();
    }

    setTray(tray, iconPath) {
        this.tray = tray;
        this.iconPath = iconPath;
    }

    collectHandlers() {  // ( windowClasses )
        // Just create empty base handlers - we'll handle window-specific logic directly
        return {
            onBlur: () => {},
            onShow: () => {},
            onHide: () => {},
            beforeHide: () => {},
            onFocus: () => {},
        };
    }

    createWindows(windowClasses) {
        windowClasses.forEach(WindowClass => {
            const window = new WindowClass(this.config, screen, this, this.basePath);
            this.windows.set(window.prefix, window);
        });
    }

    setupWindowEvents() {
        // Add IPC handler for window hiding
        ipcMain.on('hide-window', () => {
            Logger.log('WindowManager: Received hide-window IPC message');
            this.hideAll();
        });

        // Add new handler for transcriptions
        ipcMain.on('new-transcription', (event, transcription) => {
            Logger.log('WindowManager: Received new transcription');
            const chatDisplay = this.getWindow('chatDisplay');
            if (chatDisplay && chatDisplay.window) {
                chatDisplay.window.webContents.send('display-transcription', transcription);
            } else {
                Logger.error('ChatDisplay window not found or not initialized');
            }
        });

        ipcMain.on('hide-window-all', () => {
            Logger.log('WindowManager: Force hiding all windows');
            this.hideAll(true);
        });

        this.windows.forEach(window => {
            // Store the window class handlers directly on the window object for easy access
            window.handlers = window.constructor.getHandlers();

            window.on('blur', () => {
                // Add delay to allow focus to settle on another window
                setTimeout(() => {
                    if (!this.isAnyApplicationWindowFocused()) {
                        Logger.log('WindowManager: Focus lost to external window - hiding all windows');
                        this.hideAll(true);
                        // // Call this window's specific blur handler if it exists
                        // if (window.handlers.onBlur) {
                        //     window.handlers.onBlur(window, this);
                        // }
                    } else {
                        Logger.log('WindowManager: Focus still within application windows');
                    }
                }, 100);

            });

            window.window.webContents.on('crashed', () => {
                Logger.error('Renderer process crashed');
            });

            window.window.on('unresponsive', () => {
                Logger.error('Window became unresponsive');
            });

            window.window.webContents.on('did-finish-load', () => {
                Logger.log(`${window.prefix} finished loading`);
            });

            window.window.webContents.on('dom-ready', () => {
                Logger.log(`${window.prefix} DOM is ready`);
            });

            window.window.on('show', () => {
                Logger.log(`${window.prefix} shown - waiting for window to be ready`);
                if (window.window.webContents.isLoading()) {
                    window.window.webContents.once('did-finish-load', () => {
                        Logger.log(`${window.prefix} loaded - sending window-show event`);
                        window.window.webContents.send('window-show');
                    });
                } else {
                    Logger.log(`${window.prefix} already loaded - sending window-show event`);
                    window.window.webContents.send('window-show');
                }

                // Call this window's specific show handler if it exists
                if (window.handlers.onShow) {
                    window.handlers.onShow(window, this);
                }
            });

            window.window.on('hide', () => {
                window.window.webContents.send('window-hide');
                window.window.webContents.send('stopRecording');

                // Call this window's specific hide handler if it exists
                if (window.handlers.onHide) {
                    window.handlers.onHide(window, this);
                }
            });

            window.on('focus', () => {
                Logger.log(`${window.prefix} gained focus - calling window-specific onFocus handler`);
                // Call this window's specific focus handler if it exists
                if (window.handlers.onFocus) {
                    window.handlers.onFocus(window, this);
                }
            });
        });
    }

    isAnyApplicationWindowFocused() {
        return Array.from(this.windows.values())
            .some(window => window.isFocused());
    }

    showAll() {
        // Disable global shortcut when showing windows
        if (global.shortcutRegistered) {
            const shortcutKey = this.config.get('shortcuts.toggle', 'F1');
            require('electron').globalShortcut.unregister(shortcutKey);
            global.shortcutRegistered = false;
            Logger.log('Disabled global shortcut while windows shown');
        }

        // Remove throttling before showing windows
        this.applyBackgroundThrottling(false);

        this.windows.forEach(window => window.show());
        this.handlers.onShow(this);
        this.updateTrayIcon('active'); // Update tray icon to active state
    }

    hideAll(force = false) {
        if (force || !this.isAnyApplicationWindowFocused()) {
            this.windows.forEach(window => {
                if (window.isVisible()) {
                    // Call window-specific beforeHide handler if it exists
                    if (window.handlers && window.handlers.beforeHide) {
                        window.handlers.beforeHide(window, this);
                    }
                    window.hide();
                    // Background throttling is applied in the window.hide() method
                }
            });
            this.updateTrayIcon('inactive'); // Update tray icon to inactive state

            // Apply additional throttling to all windows
            this.applyBackgroundThrottling(true);
        }
    }

    toggleVisibility() {
        if (this.isAnyVisible()) {
            this.hideAll(true);
        } else {
            this.showAll();
        }
    }

    isAnyVisible() {
        return Array.from(this.windows.values())
            .some(window => window.isVisible());
    }

    isEmpty() {
        return this.windows.size === 0;
    }

    cleanup() {
        this.windows.forEach(window => window.close());
        this.windows.clear();
    }

    getWindow(prefix) {
        return this.windows.get(prefix);
    }

    updateTrayIcon(state) {
        this.currentState = state;
        const theme = nativeTheme.shouldUseDarkColors ? 'dark' : 'light';
        const iconPath = path.join(this.iconPath, `tray-icon-${state}-${theme}.png`);
        Logger.log(`Setting tray icon: ${iconPath} (${theme} theme)`);
        this.tray.setImage(iconPath);
    }

    getWindows() {
        return Array.from(this.windows.values());
    }

    updateTheme() {
        if (this.tray && this.iconPath) {
            this.updateTrayIcon(this.currentState);
        }
    }

    // New method to apply background throttling to all windows
    applyBackgroundThrottling(enable) {
        Logger.log(`${enable ? 'Enabling' : 'Disabling'} background throttling for all windows`);

        this.windows.forEach(window => {
            if (window.window && window.window.webContents) {
                window.window.webContents.setBackgroundThrottling(enable);

                // Set frame rate based on visibility
                if (enable) {
                    // Set to absolute minimum (1 FPS) when hidden
                    window.window.webContents.setFrameRate(1);
                } else {
                    // Restore normal frame rate (60 FPS) when visible
                    window.window.webContents.setFrameRate(60);
                }
            }
        });
    }
}

module.exports = { WindowManager };
