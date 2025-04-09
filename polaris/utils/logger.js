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
