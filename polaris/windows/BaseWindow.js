// windows/BaseWindow.js
const { BrowserWindow } = require('electron');
const Logger = require('../utils/logger');

class BaseWindow {
    constructor(config, prefix, options = {}) {
        this.config = config;
        this.prefix = prefix;
        this.name = `${prefix}Window`;

        this.defaultOptions = {
            webPreferences: {
                nodeIntegration: true,
                contextIsolation: false,
                webSecurity: false
            },
            show: false,
            frame: config.get(`${prefix}.frame`, false),
            transparent: config.get(`${prefix}.transparent`, true),
            alwaysOnTop: config.get(`${prefix}.alwaysOnTop`, true),
            skipTaskbar: config.get(`${prefix}.skipTaskbar`, true),
            focusable: config.get(`${prefix}.focusable`, true),
            type: config.get(`${prefix}.type`, 'toolbar'), // Back to toolbar default
            backgroundColor: config.get(`${prefix}.backgroundColor`, '#00000000'),
            hasShadow: config.get(`${prefix}.hasShadow`, false),
            vibrancy: config.get(`${prefix}.vibrancy`, 'blur'),
            visualEffectState: config.get(`${prefix}.visualEffectState`, 'active'),
            opacity: config.get(`${prefix}.opacity`, 0.8)
        };

        this.windowOptions = { ...this.defaultOptions, ...options };
        this.window = new BrowserWindow(this.windowOptions);
        Logger.log(`Created ${this.name}`);
    }

    setupBaseEventHandlers() {
        // Keyboard event logging
        this.window.webContents.on('before-input-event', (event, input) => {
            // Logger.log(`[${this.name}] Keyboard event:`, input);
        });

        // Window state events
        this.window.on('show', () => {
            Logger.log(`${this.name} shown`);
            if (this.window.webContents.isLoading()) {
                this.window.webContents.once('did-finish-load', () => {
                    this.send('window-show');
                });
            } else {
                this.send('window-show');
            }
        });

        this.window.on('hide', () => {
            Logger.log(`${this.name} hidden`);
        });

        this.window.on('blur', () => {
            Logger.log(`${this.name} lost focus`);
        });

        this.window.on('focus', () => {
            Logger.log(`[${this.name}] gained focus - window state:`, {
                isVisible: this.window.isVisible(),
                isFocused: this.window.isFocused(),
                isDestroyed: this.window.isDestroyed()
            });
        });

        // Renderer events
        this.window.webContents.on('console-message', (event, level, message, line, sourceId) => {
            Logger.log(`[${this.name}] Renderer Console: [${sourceId}][${line}] ${message}`);
        });

        this.window.webContents.on('crashed', () => {
            Logger.error(`[${this.name}] Renderer process crashed`);
        });

        this.window.webContents.on('did-finish-load', () => {
            Logger.log(`[${this.name}] Window finished loading`);
        });

        this.window.webContents.on('dom-ready', () => {
            Logger.log(`[${this.name}] DOM is ready`);
        });

        this.window.on('unresponsive', () => {
            Logger.error(`[${this.name}] Window became unresponsive`);
        });
    }

    loadContent(filePath) {
        Logger.log(`${this.name} loading content from: ${filePath}`);
        this.window.loadFile(filePath);
    }

    show() {
        this.window.show();
        this.window.focus();
    }

    hide() {
        this.window.hide();
    }

    isVisible() {
        return this.window.isVisible();
    }

    focus() {
        this.window.focus();
    }

    isFocused() {
        return this.window.isFocused();
    }

    send(channel, ...args) {
        this.window.webContents.send(channel, ...args);
    }

    on(event, callback) {
        this.window.on(event, callback);
    }

    close() {
        Logger.log(`Closing ${this.name}`);
        this.window.close();
    }

    static getHandlers() {
        return {
            onBlur: () => {},
            onShow: () => {},
            onHide: () => {},
            beforeHide: () => {},
        };
    }
}

module.exports = BaseWindow;
