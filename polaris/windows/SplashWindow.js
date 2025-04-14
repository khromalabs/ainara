const BaseWindow = require('./BaseWindow');
// const path = require('path');
// const Logger = require('../utils/logger');

class SplashWindow extends BaseWindow {
    constructor(config, screen, windowManager, basePath) {
        const splashOptions = {
            width: 500,
            height: 500,
            frame: false,
            transparent: false,
            resizable: false,
            center: true,
            skipTaskbar: true,
            backgroundColor: '#000000FF',
            alwaysOnTop: true,
            webPreferences: {
                nodeIntegration: true,
                contextIsolation: false
            }
        };

        super(config, 'splash', splashOptions, basePath);
        this.setupBaseEventHandlers();
        this.loadContent('html/splash.html');

        // // Windows-specific fix for transparency issues
        if (process.platform === 'win32') {
            this.window.setBackgroundColor('#000000FF');
        }
    }

    updateProgress(status, progress) {
        if (this.window && !this.window.isDestroyed()) {
            this.send('update-progress', { status, progress });
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

module.exports = SplashWindow;
