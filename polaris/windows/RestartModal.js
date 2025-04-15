const { BrowserWindow } = require('electron');
const path = require('path');
const Logger = require('../utils/logger');

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
