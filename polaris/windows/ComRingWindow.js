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
            beforeHide: (window, manager) => {
                if (window.prefix === 'comRing') {
                    window.window.webContents.send('window-hide');
                    window.window.webContents.send('stopRecording');
                }
            },
            onBlur: (window, manager) => {
                if (window.prefix === 'comRing' && window.isVisible()) {
                    window.hide();
                    window.window.webContents.send('window-hide');
                    window.window.webContents.send('stopRecording');
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
        this.loadContent('./components/com-ring.html');
        this.setupEventHandlers();
    }

    setupEventHandlers() {
        super.setupBaseEventHandlers();

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
            }
        });
    }
}

module.exports = ComRingWindow;
