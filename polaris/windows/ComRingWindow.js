const BaseWindow = require('./BaseWindow');
const Logger = require('../utils/logger');

class ComRingWindow extends BaseWindow {
    static getHandlers() {
        return {
            onShow: (manager) => {
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
            onBlur: (window) => {
                // Don't auto-hide if in typing mode
                if (window.prefix === 'comRing' && window.isVisible()) {
                    window.window.webContents.send('window-hide');
                    window.hide();
                    // const chatDisplay = manager.getWindow('chatDisplay');
                    // if (!window.isTypingMode && !chatDisplay?.isFocused()) {
                    //     window.hide();
                    //     window.window.webContents.send('window-hide');
                    //     window.window.webContents.send('stopRecording');
                    // }
                }
            }
        };
    }

    constructor(config, screen) {
        const { width: screenWidth, height: screenHeight } = screen.getPrimaryDisplay().workAreaSize;
        const windowWidth = config.get('comRing.width', 300);
        const windowHeight = config.get('comRing.height', 200);


        const options = {
            width: windowWidth,
            height: windowHeight,
            x: config.get('comRing.x', (screenWidth / 2) - (windowWidth / 2)),
            y: config.get('comRing.y', (screenHeight / 2) - (windowHeight / 2)),
            type: 'normal',  // Override to normal for keyboard focus
            focusable: true  // Explicitly set focusable
        };

        super(config, 'comRing', options);
        this.isTypingMode = false;
        this.loadContent('./components/com-ring.html');
        this.setupEventHandlers();
    }

    setupEventHandlers() {
        super.setupBaseEventHandlers();

        const { ipcMain } = require('electron');

        // Handle typing mode state changes
        ipcMain.on('enter-typing-mode', () => {
            this.isTypingMode = true;
        });

        // // In setupEventHandlers()
        ipcMain.on('process-typed-message', (event, message) => {
            Logger.log('Received typed message:', message);
            this.window.webContents.send('process-typed-message', message);
        });

        ipcMain.on('exit-typing-mode', () => {
            Logger.log('ComRingWindow: Exiting typing mode');
            this.isTypingMode = false;
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
