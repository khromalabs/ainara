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
const Logger = require('../framework/logger');

class ChatDisplayWindow extends BaseWindow {
    static getHandlers() {
        return {
            onBlur: (window, manager) => {
                const chatDisplay = manager.getWindow('chatDisplay');
                if (chatDisplay.isTypingMode) {
                    chatDisplay.send('set-typing-mode-state', false);
                }
                chatDisplay.window.setFocusable(false);
            },
            onShow: (window, manager) => {
                const chatDisplay = manager.getWindow('chatDisplay');
                chatDisplay.window.setFocusable(true);
                if (chatDisplay) {
                    chatDisplay.send('ready-for-transcription');
                    if (chatDisplay.isTypingMode) {
                        chatDisplay.window.setFocusable(true);
                    }
                }
            },
            onFocus: (window, manager) => {
                const chatDisplay = manager.getWindow('chatDisplay');
                if (!chatDisplay.isTypingMode) {
                    const comRing = manager.getWindow('comRing');
                    comRing.focus();
                }
            },
            onHide: (window, manager) => {
                const chatDisplay = manager.getWindow('chatDisplay');
                chatDisplay.window.setFocusable(false);
            }
        };
    }

    constructor(config, screen, manager, basePath) {
        const { width: screenWidth, height: screenHeight } = screen.getPrimaryDisplay().workAreaSize;
        const windowWidth = Math.floor(screenWidth * 0.7);
        const windowHeight = 600; // config.get('chatDisplay.height', 300);
        const windowX = Math.floor((screenWidth / 2) - (windowWidth / 2));
        // const windowY = Math.floor(screenHeight * (5/6)) - (windowHeight / 2);

        // Adjust position based on OS
        let windowY;
        if (process.platform === 'win32') {
            // Windows: Position higher on screen
            windowY = Math.floor(screenHeight * 0.7) - (windowHeight / 2);
        } else if (process.platform === 'darwin') {
            // macOS: Account for menu bar
            windowY = Math.floor(screenHeight * 0.7) - (windowHeight / 2);
        } else {
            // Linux: Position lower as before
            windowY = Math.floor(screenHeight * (6/7)) - (windowHeight / 2);
        }

        Logger.log(`ChatDisplayWindow: Positioning at Y=${windowY} (${process.platform}, screen height=${screenHeight})`);


        const options = {
            width: windowWidth,
            height: windowHeight,
            x: windowX,
            y: windowY,
            type: 'toolbar',
            focusable: true,
            skipTaskbar: true, // Explicitly hide taskbar icon for ChatDisplayWindow
            frame: false,
            transparent: true,
            backgroundColor: 'rgba(0,0,0,0)', // Explicit transparent background
            opacity: 1.0, // Full window opacity
            alwaysOnTop: true,
            show: false,
            hasShadow: false
        };

        super(config, 'chatDisplay', options, basePath);

        this.manager = manager; // Store reference to window manager
        this.loadContent('./components/chat-display.html');
        this.setupEventHandlers();
        this.isTypingMode = false;

        this.window.webContents.on('did-finish-load', () => {
            Logger.log('ChatDisplayWindow: Window finished loading');
            // Move debug messages here
            // setTimeout(() => {
            //     Logger.log('ChatDisplayWindow: Attempting to send debug messages');
            //     try {
            //         if (!this.window || !this.window.webContents) {
            //             Logger.error('ChatDisplayWindow: Window or WebContents not available!');
            //             return;
            //         }
            //         Logger.log('ChatDisplayWindow: Window and WebContents available, sending messages...');
            //         this.window.webContents.send('add-message', 'Debug: Test Message');
            //         Logger.log('ChatDisplayWindow: Sent user message');
            //         this.window.webContents.send('add-ai-message', 'Debug: AI Response Test');
            //         Logger.log('ChatDisplayWindow: Sent AI message');
            //     } catch (error) {
            //         Logger.error('ChatDisplayWindow: Error sending debug messages:', error);
            //     }
            // }, 1000);
        });
    }

    setupEventHandlers() {
        super.setupBaseEventHandlers();

        // Add ChatDisplay specific IPC handlers
        const { ipcMain } = require('electron');
        Logger.log('ChatDisplayWindow: Setting up IPC handlers');

        // Handle for any component to query typing mode state
        ipcMain.handle('get-typing-mode-state', () => {
            return this.isTypingMode;
        });

        // Handle for setting typing mode state
        ipcMain.handle('set-typing-mode-state', (event, isTyping) => {
            const oldState = this.isTypingMode;
            this.isTypingMode = isTyping;

            // Only broadcast if state actually changed
            if (oldState !== isTyping) {
                Logger.log(`ChatDisplayWindow: Typing mode changed to ${isTyping}`);

                // Broadcast to all relevant components
                this.window.webContents.send('typing-mode-changed', isTyping);
                const comRing = this.manager.getWindow('comRing');
                if (comRing) {
                    comRing.window.webContents.send('typing-mode-changed', isTyping);
                }
            }

            return this.isTypingMode;
        });

        ipcMain.on('transcription-received', (event, text) => {
            Logger.log('ChatDisplayWindow: Transcription received:', text);
            if (!this.window) {
                Logger.error('ChatDisplayWindow: Window not available!');
                return;
            }
            if (!this.window.webContents) {
                Logger.error('ChatDisplayWindow: WebContents not available!');
                return;
            }
            // Show window before sending message
            // this.show();
            this.window.webContents.send('add-message', text);
            Logger.log('ChatDisplayWindow: Message forwarded to chat display');
        });

        ipcMain.on('llm-stream', (event, text) => {
            Logger.log('ChatDisplayWindow: Chat response received:', JSON.stringify(text));
            // Ensure window is visible
            if (!this.window.isVisible()) {
                this.show();
            }
            this.window.webContents.send('add-ai-message', text);
            Logger.log('ChatDisplayWindow: AI message forwarded to chat display');
        });

        // Add handler for LLM abort
        ipcMain.on('llm-aborted', () => {
            Logger.log('ChatDisplayWindow: LLM response aborted');
            // this.hide();
            // Reset window state for next interaction
            this.window.webContents.send('reset-state');
        });

        ipcMain.on('typing-key-pressed', (event, key) => {
            Logger.log('ChatDisplayWindow: Typing key received:', key);
            if (!this.window.isVisible()) {
                this.show();
            }
            this.window.webContents.send('typing-key-pressed', key);
        });

        ipcMain.on('focus-chat-display', () => {
            Logger.log('ChatDisplayWindow: Focusing window');
            this.show();
            this.window.focus();
        });

        // Add handlers for animation events
        ipcMain.on('animation-started', (event, data) => {
            Logger.log('ChatDisplayWindow: Animation started:', data);
            // Forward to ComRing
            const comRing = this.manager?.getWindow('comRing');
            if (comRing) {
                comRing.window.webContents.send('animation-started', data);
            }
        });

        // In ChatDisplayWindow.js
        ipcMain.on('animation-completed', (event, data) => {
            // Logger.log('ChatDisplayWindow: Animation completed event received:', data);

            // Forward to ComRing with additional error handling
            try {
                const comRingWindowWebContents =
                    this.manager?.getWindow('comRing').window.webContents;
                if (!comRingWindowWebContents) {
                    Logger.error('ChatDisplayWindow: ComRing window webContents not available');
                    return;
                }
                comRingWindowWebContents.send('animation-completed', data);
            } catch (error) {
                Logger.error('ChatDisplayWindow: Error forwarding animation-completed event:', error);
            }
        });

    }
}

module.exports = ChatDisplayWindow;
