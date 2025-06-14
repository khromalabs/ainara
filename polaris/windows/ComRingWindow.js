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

const BaseWindow = require('./BaseWindow');
const Logger = require('../utils/logger');

class ComRingWindow extends BaseWindow {
    static getHandlers() {
        return {
            onShow: (window, manager) => {
                const comRing = manager.getWindow('comRing');
                if (comRing) {
                    comRing.focus();
                    comRing.window.webContents.send('window-show');
                }
            },
            beforeHide: (window) => {
                if (window.prefix === 'comRing') {
                    window.window.webContents.send('window-hide');
                    window.window.webContents.send('stopRecording');
                }
            },
            onBlur: async (window, manager) => {
                const chatDisplay = manager.getWindow('chatDisplay');
                // Don't auto-hide if in typing mode
                if (window.prefix === 'comRing' && window.isVisible() && !chatDisplay.isTypingMode) {
                    window.window.webContents.send('window-hide');
                    window.hide();
                }
            },
            onFocus: () => {
                Logger.log('ComRingWindow RECEIVED FOCUS');
                // Add your focus handling logic here
            }
        };
    }

    constructor(config, screen, manager, basePath) {
        const { width: screenWidth, height: screenHeight } = screen.getPrimaryDisplay().workAreaSize;
        const windowWidth = config.get('comRing.width', 300);
        const windowHeight = config.get('comRing.height', 200);
        const options = {
            width: windowWidth,
            height: windowHeight,
            x: config.get('comRing.x', (screenWidth / 2) - (windowWidth / 2)),
            y: config.get('comRing.y', (screenHeight / 2) - (windowHeight / 2)),
            skipTaskbar: false, // Show taskbar icon for ComRingWindow
            type: 'normal',  // Override to normal for keyboard focus
            focusable: true  // Explicitly set focusable
        };

        super(config, 'comRing', options, basePath);

        this.manager = manager; // Store reference to window manager
        this.loadContent('./components/com-ring.html');
        this.setupEventHandlers();
        this.originalSize = [windowWidth, windowHeight];
        this.originalPosition = [options.x, options.y];
    }

    setupEventHandlers() {
        super.setupBaseEventHandlers();

        const { ipcMain } = require('electron');

        ipcMain.on('set-view-mode', (event, args) => {
            if (args.view === 'document') {
                const docWidth = this.config.get('documentView.width', 800);
                const docHeight = this.config.get('documentView.height', 600);

                // Store current position before resizing
                const [currentX, currentY] = this.window.getPosition();
                this.originalPosition = [currentX, currentY];

                this.window.setResizable(true);
                this.window.setMinimumSize(400, 300);
                this.window.setSize(docWidth, docHeight, true); // Animate
                this.window.center();
                this.window.setOpacity(1.0);
                this.window.setBackgroundColor('#1e1e1e');

            } else if (args.view === 'ring') {
                // Restore original size and position
                const [originalWidth, originalHeight] = this.originalSize;

                this.window.setMinimumSize(originalWidth, originalHeight);
                this.window.setSize(originalWidth, originalHeight, true); // Animate
                this.window.setPosition(this.originalPosition[0], this.originalPosition[1], true);
                this.window.setResizable(false);
                this.window.setOpacity(1.0); // Keep it opaque during transition

                // After a short delay, make it transparent again
                setTimeout(() => {
                    this.window.setBackgroundColor('#00000000'); // Transparent
                }, 300); // Corresponds to transition time
            }
        });

        ipcMain.on('com-ring-focus', () => {
            this.window.focus();
        });

        ipcMain.on('process-typed-message', (event, message) => {
            Logger.log('Received typed message:', message);
            this.window.webContents.send('process-typed-message', message);
        });

        ipcMain.on('exit-typing-mode', () => {
            Logger.log('ComRingWindow: Exiting typing mode');
            this.window.focus();
            this.window.webContents.send('exit-typing-mode');
            Logger.log('ComRingWindow: Focusing window');
        });

        // Add ComRing specific IPC handlers
        this.window.webContents.on('ipc-message', (event, channel, ...args) => {
            switch (channel) {
                case 'recording-started':
                    Logger.log('Recording started');
                    break;
                case 'recording-stopped':
                    Logger.log('Recording stopped');
                    break;
                case 'recording-error':
                    Logger.error('Recording error:', ...args);
                    break;
                case 'typing-mode-changed':
                    Logger.log('Typing mode changed:', ...args);
                    break;
            }
        });
    }
}

module.exports = ComRingWindow;
