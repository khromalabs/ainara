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

const { BrowserWindow, nativeTheme } = require('electron');
const Logger = require('../utils/logger');
const path = require('path');
const process = require('process');

class BaseWindow {
    constructor(config, prefix, options = {}, basePath) {
        this.config = config;
        this.prefix = prefix;
        this.name = `${prefix}Window`;
        this.basePath = basePath;

        this.defaultOptions = {
            webPreferences: {
                nodeIntegration: true,
                contextIsolation: false,
                webSecurity: false
            },
            icon: path.join(
                this.basePath, 
                'assets', 
                // `tray-icon-active-${nativeTheme.shouldUseDarkColors ? 'dark' : 'light'}.png`
                'icon.png'
            ),
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
            const myfilepath = `${sourceId}`.replace("file://", "");
            const currentDirectory = process.cwd();
            const relativePath = path.relative(currentDirectory, myfilepath);
            Logger.log(`[${relativePath}:${line}] ${message}`);
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
        const fullPath = path.join(this.basePath, filePath);
        Logger.log(`${this.name} loading content from: ${fullPath}`);
        this.window.loadFile(fullPath);
    }

    show() {
        this.window.show();
        // Disable background throttling when window is shown
        if (this.window.webContents) {
            this.window.webContents.setBackgroundThrottling(false);
            // Restore normal frame rate
            this.window.webContents.setFrameRate(60);
            Logger.log(`${this.name} background throttling disabled, frame rate restored`);
        }
    }

    hide() {
        this.window.hide();
        // Enable background throttling when window is hidden
        if (this.window.webContents) {
            this.window.webContents.setBackgroundThrottling(true);
            // Set minimum possible frame rate when hidden
            this.window.webContents.setFrameRate(1); // 1 FPS is the minimum
            Logger.log(`${this.name} background throttling enabled, frame rate set to minimum`);
        }
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
        if (this.window && !this.window.isDestroyed()) {
            try {
                Logger.log(`Closing window ${this.name}`);
                if (this.window.isClosable()) {
                    this.window.close();
                } else {
                    this.window.destroy();
                }
            } catch (err) {
                Logger.error(`Error closing, forzing destroy on window ${this.name}:`, err);
                this.window.destroy();
            }
        }
    }

    static getHandlers() {
        return {
            onBlur: () => {},
            onShow: () => {},
            onHide: () => {},
            beforeHide: () => {},
            onFocus: () => {},
        };
    }
}

module.exports = BaseWindow;
