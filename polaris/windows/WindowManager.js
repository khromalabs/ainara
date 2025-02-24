// windows/WindowManager.js
const { screen, ipcMain } = require('electron');
const Logger = require('../utils/logger');

class WindowManager {
    constructor(config) {
        this.config = config;
        this.windows = new Map();
        this.handlers = {
            onBlur: () => {},
            onShow: () => {},
            onHide: () => {},
            beforeHide: () => {},
        };
    }

    initialize(windowClasses) {
        this.handlers = this.collectHandlers(windowClasses);
        this.createWindows(windowClasses);
        this.setupWindowEvents();
    }

    collectHandlers(windowClasses) {
        const baseHandlers = {
            onBlur: () => {},
            onShow: () => {},
            onHide: () => {},
            beforeHide: () => {},
        };

        return windowClasses.reduce((handlers, WindowClass) => {
            const classHandlers = WindowClass.getHandlers();
            Object.entries(classHandlers).forEach(([event, handler]) => {
                if (!handlers[event]) {
                    handlers[event] = handler;
                } else {
                    // Combine handlers if multiple windows define the same event
                    const existingHandler = handlers[event];
                    handlers[event] = (...args) => {
                        existingHandler(...args);
                        handler(...args);
                    };
                }
            });
            return handlers;
        }, baseHandlers);
    }

    createWindows(windowClasses) {
        windowClasses.forEach(WindowClass => {
            const window = new WindowClass(this.config, screen);
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
            window.on('blur', () => {
                // Add delay to allow focus to settle on another window
                setTimeout(() => {
                    if (!this.isAnyApplicationWindowFocused()) {
                        Logger.log('WindowManager: Focus lost to external window - hiding all windows');
                        this.hideAll();
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
            });

            window.window.on('hide', () => {
                window.window.webContents.send('window-hide');
                window.window.webContents.send('stopRecording');
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
            const shortcutKey = this.config.get('shortcuts.toggle', 'Super+K');
            require('electron').globalShortcut.unregister(shortcutKey);
            global.shortcutRegistered = false;
            Logger.log('Disabled global shortcut while windows shown');
        }

        this.windows.forEach(window => window.show());
        this.handlers.onShow(this);
    }

    hideAll(force = false) {
        if (force || !this.isAnyApplicationWindowFocused()) {
            this.windows.forEach(window => {
                if (window.isVisible()) {
                    this.handlers.beforeHide(window, this);
                    window.hide();
                }
            });
            this.handlers.onHide(this);
        }
    }

    toggleVisibility() {
        if (this.isAnyVisible()) {
            this.hideAll();
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
}

module.exports = { WindowManager };

