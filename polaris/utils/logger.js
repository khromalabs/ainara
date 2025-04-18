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

const util = require('util');

class Logger {
    static debugMode = false;
    static className = "LOGGER";

    static setDebugMode(enabled) {
        Logger.debugMode = enabled;
    }

    static getCallerInfo() {
        const error = new Error();
        const stack = error.stack.split('\n')[3]; // Skip getCallerInfo, log/error, and caller
        const match = stack.match(/at\s+(?:.*\s+\()?(.+):(\d+):\d+\)?/);
        if (match) {
            const [, file, line] = match;
            return `${file.split('/').slice(-2).join('/')}:${line}`;
        }
        return 'unknown:0';
    }

    static log(...args) {
        if (!Logger.debugMode) return; // Skip debug logs unless enabled
        const timestamp = new Date().toISOString();
        const message = util.format(...args);
        const caller = this.getCallerInfo();
        process.stdout.write(`[${timestamp}][${this.className}][${caller}] ${message}\n`);
    }

    static info(...args) {
        const timestamp = new Date().toISOString();
        const message = util.format(...args);
        const caller = this.getCallerInfo();
        process.stdout.write(`[${timestamp}][${this.className}][${caller}] INFO: ${message}\n`);
    }

    static error(...args) {
        const timestamp = new Date().toISOString();
        const message = util.format(...args);
        const caller = this.getCallerInfo();
        process.stderr.write(`[${timestamp}][${this.className}][${caller}] ERROR: ${message}\n`);
    }
}

module.exports = Logger;