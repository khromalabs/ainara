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

const { BrowserWindow } = require('electron');
const path = require('path');
const Logger = require('../framework/logger');

class RestartModal {
    constructor(parentWindow) {
        this.window = new BrowserWindow({
            parent: parentWindow,
            modal: true,
            show: false,
            width: 300,
            height: 150,
            resizable: false,
            frame: false,
            webPreferences: {
                nodeIntegration: true,
                contextIsolation: false
            }
        });

        this.window.loadFile(path.join(__dirname, '../../static/restart-modal.html'));
        this.window.on('close', () => this.window = null);
    }

    show(show) {
        if (this.window) {
            if (show) {
                this.window.center();
                this.window.show();
            } else {
                this.window.hide();
            }
        }
    }
}

module.exports = RestartModal;