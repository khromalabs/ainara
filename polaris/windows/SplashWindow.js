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
// const path = require('path');
const Logger = require('../framework/logger');

class SplashWindow extends BaseWindow {
    constructor(config, screen, windowManager, basePath) {
        const splashOptions = {
            width: 500,
            height: 500,
            frame: false,
            transparent: true,
            // transparent: false,
            resizable: false,
            center: true,
            skipTaskbar: true,
            backgroundColor: '#000000FF',
            alwaysOnTop: true,
            opacity: 1,
            webPreferences: {
                nodeIntegration: true,
                contextIsolation: false
            }
        };

        super(config, 'splash', splashOptions, basePath);
        this.setupBaseEventHandlers();
        this.loadContent('html/splash.html');

        // // Windows-specific fix for transparency issues
        // if (process.platform === 'win32') {
        //     this.window.setBackgroundColor('#000000FF');
        // }
    }

    updateProgress(status, progress) {
        if (this.window && !this.window.isDestroyed()) {
            this.send('update-progress', { status, progress });
        }
    }

    // Override the close method to ensure forceful destruction
    close() {
        if (this.window && !this.window.isDestroyed()) {
            try {
                Logger.log(`Force destroying SplashWindow (${this.name})`);
                this.window.destroy(); // Directly call destroy
            } catch (err) {
                Logger.error(`Error destroying SplashWindow (${this.name}):`, err);
                // Attempt destroy again just in case, though unlikely to help if first failed
                if (this.window && !this.window.isDestroyed()) this.window.destroy();
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

module.exports = SplashWindow;
