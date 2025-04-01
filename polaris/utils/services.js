const { exec } = require('child_process');
const path = require('path');
const Logger = require('./logger');

class ServiceManager {
    constructor() {
        // Singleton pattern
        if (ServiceManager.instance) {
            return ServiceManager.instance;
        }
        ServiceManager.instance = this;
        
        this.scriptPath = path.join(process.env.HOME, 'lab', 'src', 'ainara', 'bin', 'services.py');
    }
    
    async getServicesStatus() {
        return new Promise((resolve, reject) => {
            exec(`${this.scriptPath} --status --json`, (error, stdout, stderr) => {
                if (error) {
                    Logger.error(`Error getting services status: ${error.message}`);
                    return reject(error);
                }
                
                try {
                    const result = JSON.parse(stdout);
                    resolve(result);
                } catch (e) {
                    Logger.error(`Error parsing services status: ${e.message}`);
                    reject(e);
                }
            });
        });
    }
    
    async startServices(options = {}) {
        const opts = [];
        if (options.skipOrakle) opts.push('--skip-orakle');
        if (options.skipPybridge) opts.push('--skip-pybridge');
        if (options.skipWhisper) opts.push('--skip-whisper');
        
        return new Promise((resolve, reject) => {
            exec(`${this.scriptPath} ${opts.join(' ')} --json`, (error, stdout, stderr) => {
                if (error) {
                    Logger.error(`Error starting services: ${error.message}`);
                    return reject(error);
                }
                
                try {
                    const result = JSON.parse(stdout);
                    resolve(result);
                } catch (e) {
                    Logger.error(`Error parsing start services result: ${e.message}`);
                    reject(e);
                }
            });
        });
    }
    
    async stopServices() {
        return new Promise((resolve, reject) => {
            exec(`${this.scriptPath} --stop --json`, (error, stdout, stderr) => {
                if (error) {
                    Logger.error(`Error stopping services: ${error.message}`);
                    return reject(error);
                }
                
                try {
                    const result = JSON.parse(stdout);
                    resolve(result);
                } catch (e) {
                    Logger.error(`Error parsing stop services result: ${e.message}`);
                    reject(e);
                }
            });
        });
    }
    
    async setupEnvironment(install = false) {
        const installFlag = install ? '--install' : '';
        return new Promise((resolve, reject) => {
            exec(`${this.scriptPath} --setup ${installFlag} --json`, (error, stdout, stderr) => {
                if (error) {
                    Logger.error(`Error setting up environment: ${error.message}`);
                    return reject(error);
                }
                
                try {
                    const result = JSON.parse(stdout);
                    resolve(result);
                } catch (e) {
                    Logger.error(`Error parsing setup result: ${e.message}`);
                    reject(e);
                }
            });
        });
    }
}

module.exports = new ServiceManager();
