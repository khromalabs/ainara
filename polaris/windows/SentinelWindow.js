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

const { app, dialog } = require('electron');
const BaseWindow = require('./BaseWindow');
const Logger = require('../framework/logger');

class SentinelWindow extends BaseWindow {
    constructor(config, screen, basePath) {
        const options = {
            width: 900,
            height: 600,
            frame: true,
            transparent: false,
            resizable: true,
            center: true,
            skipTaskbar: false,
            alwaysOnTop: false,
            focusable: true,
            title: 'Ainara Sentinel',
            backgroundColor: '#1e1e1e',
            autoHideMenuBar: true,
            webPreferences: {
                nodeIntegration: true,
                contextIsolation: false
            }
        };

        super(config, 'sentinel', options, basePath);
        this.setupBaseEventHandlers();

        // Closing the window = stopping Sentinel. Ask for confirmation,
        // but never block the real quit sequence (before-quit handles it).
        this.window.on('close', (event) => {
            if (app.isQuitting) return;
            event.preventDefault();
            const choice = dialog.showMessageBoxSync(this.window, {
                type: 'question',
                buttons: ['Stop Sentinel', 'Cancel'],
                defaultId: 0,
                cancelId: 1,
                title: 'Stop Sentinel?',
                message: 'Stop Sentinel and exit the application?'
            });
            if (choice === 0) {
                Logger.info('SentinelWindow: user confirmed shutdown');
                app.isQuitting = true;
                app.quit();
            }
        });

        this.loadContent('html/sentinel.html');
        this.window.once('ready-to-show', () => this.show());
    }

    appendOutput(line) {
        if (this.window && !this.window.isDestroyed()) {
            this.send('sentinel-output', { line });
        }
    }

    showExited(code) {
        if (this.window && !this.window.isDestroyed()) {
            this.send('sentinel-exited', { code });
        }
    }
}

module.exports = SentinelWindow;
