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

const path = require('path');
const fs = require('fs');
const os = require('os');
const { app } = require('electron');
const net = require('net');

const ConfigManager = require('../framework/config');
const Logger = require('./logger');
const Service = require('./Service');


const config = new ConfigManager();

class ServiceManager {
    constructor() {

        // Singleton pattern
        if (ServiceManager.instance) {
            return ServiceManager.instance;
        }
        ServiceManager.instance = this;


        // Determine executable paths based on platform
        const platform = os.platform();
        const isDevMode = !app.isPackaged;
        this.startProgress = 30
        this.initializeMsg = "Initializing services..."

        // Base directory for executables
        let executablesDir;
        if (isDevMode) { // dev-compiled mode (Polaris is source, no Electron bundle)
            // In development, look for executables in a relative path
            executablesDir = path.join(process.cwd(), 'dist', 'servers');
        } else {
            // In production, look in the resources directory
            executablesDir = path.join(process.resourcesPath, 'bin', 'servers');
        }

        // Define services with their executables and health endpoints
        if (useSourcePythonModules) {
            Logger.info('Using Python modules for services (dev-source mode)');
            const pythonExecutable = platform === 'win32'
                ? path.join(process.cwd(), 'venv', 'Scripts', 'python.exe')
                : path.join(process.cwd(), 'venv', 'bin', 'python');

            this.services = {
                orakle: new Service('orakle', {
                    url: config.get('orakle.api_url') + '/health',
                    name: 'Orakle',
                    executablePath: pythonExecutable,
                    args: ['-u', '-m', 'ainara.orakle.server']
                }),
                pybridge: new Service('pybridge', {
                    url: config.get('pybridge.api_url') + '/health',
                    name: 'Pybridge',
                    executablePath: pythonExecutable,
                    args: ['-u', '-m', 'ainara.framework.pybridge']
                })
            };
        } else {
            this.services = {
                orakle: new Service('orakle', {
                    url: config.get('orakle.api_url') + '/health',
                    name: 'Orakle',
                    executablePath: path.join(executablesDir, platform === 'win32' ? 'orakle.exe' : 'orakle'),
                    args: []
                }),
                pybridge: new Service('pybridge', {
                    url: config.get('pybridge.api_url') + '/health',
                    name: 'Pybridge',
                    executablePath: path.join(executablesDir, platform === 'win32' ? 'pybridge.exe' : 'pybridge'),
                    args: []
                })
            };
        }

        this.onProgressUpdate = null;
        this.healthCheckInterval = null;
    }

    /**
     * Checks if a specific TCP port is already in use on 127.0.0.1.
     * @param {number} port The port number to check.
     * @returns {Promise<boolean>} A promise that resolves to true if the port is in use, false otherwise.
     * @private Internal helper method.
     */
    _checkPortInUse(port) {
        return new Promise((resolve, reject) => {
            const server = net.createServer();
            server.once('error', (err) => {
                if (err.code === 'EADDRINUSE') {
                    server.close();
                    resolve(true); // Port is in use
                } else {
                    reject(err); // Other error
                }
            });
            server.once('listening', () => {
                server.close(() => {
                    resolve(false); // Port is free
                });
            });
            // Listen on 127.0.0.1 which should detect conflicts even if service binds to 0.0.0.0
            server.listen(port, '127.0.0.1');
        });
    }

    /**
     * Checks if the configured ports for all managed services are available.
     * @returns {Promise<{available: boolean, port?: number, serviceName?: string}>}
     *          Resolves to {available: true} if all ports are free.
     *          Resolves to {available: false, port: number, serviceName: string} if a port is in use.
     */
    async checkPortsAvailability() {
        Logger.info('Checking availability of required network ports...');
        // for (const [serviceId, service] of Object.entries(this.services)) {
        for (const service of Object.values(this.services)) {
            try {
                const url = new URL(service.url.replace('/health', '')); // Use base URL
                const port = parseInt(url.port, 10);

                if (isNaN(port) || port <= 0 || port > 65535) {
                    Logger.warn(`Could not parse a valid port from URL for service ${service.name}: ${service.url}. Skipping check for this service.`);
                    continue; // Skip this service if port is invalid
                }

                Logger.info(`Checking port ${port} for ${service.name}...`);
                const isUsed = await this._checkPortInUse(port);
                if (isUsed) {
                    Logger.error(`Port ${port} for ${service.name} is already in use.`);
                    return { available: false, port: port, serviceName: service.name };
                }
                Logger.info(`Port ${port} for ${service.name} is available.`);
            } catch (error) {
                Logger.error(`Error checking port for service ${service.name} (URL: ${service.url}):`, error);
                // Treat errors during check as potentially fatal, return unavailable
                return { available: false, port: -1, serviceName: `${service.name} (Error during check: ${error.message})` };
            }
        }
        Logger.info('All required network ports appear to be available.');
        return { available: true };
    }

    setProgressCallback(callback) {
        this.onProgressUpdate = callback;
    }

    updateProgress(status, progress) {
        if (this.onProgressUpdate) {
            this.onProgressUpdate(status, progress);
        }
    }
    async startServices() {
        this.updateProgress('Starting services...', 10);
        Logger.info("--- starting services");

        // Check if executables exist
        for (const service of Object.values(this.services)) {
            if (!fs.existsSync(service.executablePath)) {
                const error_msg = `Executable not found: ${service.executablePath}`;
                Logger.error(error_msg);
                this.updateProgress(error_msg, 100);
                return { success: false, message: error_msg };
            }
        }

        let errorMsg = null;

        // Setup event listeners before starting
        for (const service of Object.values(this.services)) {
            service.on('stderr', (data) => {
                let msg = `[${service.name}] ${data.toString().trim()}`;
                if(msg.includes("CRITICAL")) {
                    Logger.error(msg);
                    errorMsg += ", " + msg;
                }
            });

            service.on('stdout', (output) => {
                // PyBridge can send structured progress updates
                if (service.id === 'pybridge' && output.startsWith('PYBRIDGE_PROGRESS:')) {
                    try {
                        const jsonString = output.substring('PYBRIDGE_PROGRESS:'.length);
                        const progressUpdate = JSON.parse(jsonString);
                        Logger.log(`[${service.name} Progress] ${progressUpdate.message} (${progressUpdate.progress}%)`);
                        this.updateProgress(progressUpdate.message || null, progressUpdate.progress);
                    } catch (e) {
                        Logger.error(`[${service.name}] Failed to parse progress update: ${output} ${e}`);
                    }
                } else {
                    // Log standard output from other services
                    output.trim().split('\n').forEach(line => {
                        if (line) { Logger.log(`[${service.name}] ${line}`); }
                    });
                }
            });

            service.on('progress-tick', () => {
                this.startProgress += 0.25;
                this.updateProgress(null, this.startProgress);
            });
        }

        // Start both services in parallel
        const startPromises = Object.values(this.services).map(service => service.start(600000));

        this.startProgress = 10;

        this.updateProgress(this.initializeMsg, this.startProgress);

        try {
            await Promise.all(startPromises);
            Logger.info("--- all services started successfully");
            this.updateProgress('Services started successfully', 70);
            // Start health check monitoring
            this.startHealthCheck();
            return { success: true };
        } catch (error) {
            let error_msg = 'Failed to start services: ' + error.message;
            if (errorMsg) {
                error_msg += " - " + errorMsg;
            }
            Logger.error(error_msg);
            this.updateProgress(error_msg);
            return { success: false, message: error_msg };
        }
    }

    startHealthCheck() {
        if (this.healthCheckInterval) {
            clearInterval(this.healthCheckInterval);
        }

        this.healthCheckInterval = setInterval(async () => {
            await this.checkServicesHealth();
        }, 5000);
    }

    async checkServicesHealth() {
        let allHealthy = true;
        let healthyCount = 0;
        const totalServices = Object.keys(this.services).length;

        for (const service of Object.values(this.services)) {
            const wasHealthy = service.healthy;
            service.healthy = await service.checkHealth();

                if (service.healthy) {
                    healthyCount++;
                }

                if (!wasHealthy && service.healthy) {
                    Logger.log(`${service.name} is now healthy`);
                }
                else if (wasHealthy && !service.healthy) {
                    // Only log error if it wasn't already unhealthy
                    Logger.error(`${service.name} is no longer healthy`);
                }

                if (!service.healthy) {
                    allHealthy = false;
                }
        }

        // Update progress based on health status
        if (allHealthy) {
            this.updateProgress('All services are ready', 100);
        } else {
            // Calculate progress: 40% for starting + up to 60% for health checks
            const healthProgress = Math.floor((healthyCount / totalServices) * 60);
            this.updateProgress('Waiting for services to be ready...', 40 + healthProgress);
        }

        return allHealthy;
    }

    async stopServices({ force = false } = {}) {
        if (this.healthCheckInterval) {
            clearInterval(this.healthCheckInterval);
            this.healthCheckInterval = null;
        }

        const terminationPromises = Object.values(this.services).map(service => service.stop({ force }));

        if (terminationPromises.length > 0) {
            Logger.log(`Waiting for ${terminationPromises.length} services to terminate...`);
            try {
                await Promise.all(terminationPromises);
                Logger.log('All services stopped successfully');
                // console.trace();
                return true;
            } catch (error) {
                Logger.error(`Error stopping services: ${error.message}`);
                // If we're in force mode, we should have already killed everything
                if (force) {
                    return true;
                }

                // If graceful shutdown failed, try force kill as a last resort
                Logger.log('Attempting force kill of remaining services...');
                return await this.stopServices({ force: true });
            }
        } else {
            Logger.log('No active services to stop');
            return true;
        }
    }

    isAllHealthy() {
        return Object.values(this.services).every(service => service.healthy);
    }

    async restartServices() {
        this.updateProgress('Restarting services...', 0);

        try {
            // First stop all services
            await this.stopServices();

            // Then start them again
            const success = await this.startServices();

            if (!success) {
                throw new Error('Failed to restart services');
            }

            return true;
        } catch (error) {
            Logger.error('Error restarting services:', error);
            this.updateProgress(`Error: ${error.message}`, 100);
            return false;
        }
    }

    setWindowManager(wm) {
        this.windowManager = wm;
    }

}

const useSourcePythonModules = (
        process.env.AINARA_USE_SOURCE === 'true' ||
        process.env.AINARA_USE_SOURCE === '1'
    );
module.exports = new ServiceManager();
