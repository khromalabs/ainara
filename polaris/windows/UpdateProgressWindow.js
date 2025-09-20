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
const BaseWindow = require('./BaseWindow'); // Assuming BaseWindow is in the same directory

class UpdateProgressWindow extends BaseWindow {
    constructor(config, parentWindow = null) {
        const windowOptions = {
            width: 350,
            height: 120,
            parent: parentWindow, // Make it modal to the main interaction if needed
            modal: false, // Set to true if it should block parent interaction
            show: false,
            frame: false, // Frameless
            resizable: false,
            movable: true, // Allow moving
            center: true,
            skipTaskbar: true,
            alwaysOnTop: true, // Keep it visible
            webPreferences: {
                nodeIntegration: true,
                contextIsolation: false,
            },
        };
        // Use a unique prefix to avoid conflicts if BaseWindow uses it internally
        super(config, 'updateProgress', windowOptions, path.dirname(__dirname)); // Pass basePath correctly

        this.loadContent('components/update-progress.html'); // Load the new HTML file

        this.window.once('ready-to-show', () => {
            // Optional: Add any logic needed when the window is ready but not yet shown
        });
    }

    updateProgress(percent) {
        if (this.window && !this.window.isDestroyed()) {
            this.send('update-download-progress', percent);
        }
    }

    // Override or add methods as needed, e.g., close handling
    close() {
        if (this.window && !this.window.isDestroyed()) {
            this.window.close();
        }
        // Ensure BaseWindow cleanup runs if necessary
        // super.close(); // Call if BaseWindow has its own close logic
    }

    destroy() {
         if (this.window && !this.window.isDestroyed()) {
            this.window.destroy();
        }
    }
}

module.exports = UpdateProgressWindow;
