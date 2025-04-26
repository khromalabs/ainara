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

const { spawn } = require('child_process');
const path = require('path');
const Logger = require('./logger');
const fetch = require('node-fetch');
const fs = require('fs');
const os = require('os');
const { app } = require('electron');
const ConfigManager = require('../utils/config');

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

        // Base directory for executables
        let executablesDir;
        if (isDevMode) {
            // In development, look for executables in a relative path
            executablesDir = path.join(process.cwd(), 'dist', 'servers');
        } else {
            // In production, look in the resources directory
            executablesDir = path.join(process.resourcesPath, 'bin', 'servers');
        }

        // Define services with their executables and health endpoints
        this.services = {
            orakle: {
                process: null,
                url: config.get('orakle.api_url') + '/health',
                healthy: false,
                name: 'Orakle',
                executable: platform === 'win32' ? 'orakle.exe' : 'orakle',
                executablePath: path.join(executablesDir, platform === 'win32' ? 'orakle.exe' : 'orakle'),
                args: []
            },
            pybridge: {
                process: null,
                url: config.get('pybridge.api_url') + '/health',
                healthy: false,
                name: 'Pybridge',
                executable: platform === 'win32' ? 'pybridge.exe' : 'pybridge',
                executablePath: path.join(executablesDir, platform === 'win32' ? 'pybridge.exe' : 'pybridge'),
                args: []
            }
        };

        this.onProgressUpdate = null;
        this.healthCheckInterval = null;
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
        for (const [, service] of Object.entries(this.services)) { // id, service
            if (!fs.existsSync(service.executablePath)) {
                Logger.error(`Executable not found: ${service.executablePath}`);
                this.updateProgress(`Error: ${service.name} executable not found`, 100);
                return false;
            }
        }

        // Start both services in parallel
        const startPromises = [
            this.startService('orakle'),
            this.startService('pybridge')
        ];

        this.updateProgress('Initializing Orakle server...', this.startProgress);

        try {
            await Promise.all(startPromises);
            Logger.info("--- all services started successfully");
            this.updateProgress('Services started successfully', 70);

            // Start health check monitoring
            this.startHealthCheck();

            return true;
        } catch (error) {
            Logger.error('Failed to start services:', error);
            this.updateProgress(`Error: ${error.message}`, 100);
            return false;
        }
    }

    async startService(serviceId) {
        const service = this.services[serviceId];

        return new Promise((resolve, reject) => {
            Logger.log(`Starting ${service.name} service from: ${service.executablePath}`);

            try {
                service.process = spawn(service.executablePath, service.args, {
                    stdio: 'pipe',
                    shell: false
                });

                // Handle process output
                service.process.stdout.on('data', (data) => {
                    Logger.log(`[${service.name}] ${data.toString().trim()}`);
                });

                service.process.stderr.on('data', (data) => {
                    Logger.error(`[${service.name}] ${data.toString().trim()}`);
                });

                // Handle process exit
                service.process.on('exit', (code) => {
                    if (code !== 0 && code !== null) {
                        Logger.error(`${service.name} exited with code ${code}`);
                        // service.healthy = false;
                        //
                        // if (this.healthCheckInterval) {
                        //     this.updateProgress(`${service.name} service crashed`, 100);
                        // }
                    }
                });

                // Check if service starts successfully in a minute top
                this.waitForHealth(serviceId, 60000)
                    .then(() => resolve())
                    .catch(err => reject(err));

            } catch (error) {
                Logger.error(`Failed to spawn ${service.name} process:`, error);
                reject(error);
            }
        });
    }

    async waitForHealth(serviceId, timeout) {
        const service = this.services[serviceId];
        const startTime = Date.now();

        while (Date.now() - startTime < timeout) {
            try {
                const response = await fetch(service.url);
                if (response.ok) {
                    service.healthy = true;
                    Logger.log(`${service.name} is healthy`);
                    return true;
                }
            } catch (error) {
                console.log(error);
                // Ignore errors during startup
            }

            this.startProgress++;
            this.updateProgress('Initializing Orakle server...', this.startProgress);

            // Wait before next attempt
            await new Promise(resolve => setTimeout(resolve, 1000));
        }

        throw new Error(`Timeout waiting for ${service.name} to become healthy`);
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

        for (const [ , service] of Object.entries(this.services)) { // id,
            try {
                const response = await fetch(service.url);
                const wasHealthy = service.healthy;
                service.healthy = response.ok;

                if (service.healthy) {
                    healthyCount++;
                }

                if (!wasHealthy && service.healthy) {
                    Logger.log(`${service.name} is now healthy`);
                }
                else if (wasHealthy && !service.healthy) {
                    Logger.error(`${service.name} is no longer healthy`);
                }

                if (!service.healthy) {
                    allHealthy = false;
                }
            } catch (error) {
                service.healthy = false;
                allHealthy = false;
                Logger.error(`Health check failed for ${service.name}:`, error.message);
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

        const terminationPromises = [];

        for (const [, service] of Object.entries(this.services)) {
            if (service.process && !service.process.killed) {
                terminationPromises.push(new Promise((resolve) => {
                    if (force) {
                        Logger.log(`Force killing ${service.name} immediately (SIGKILL)`);
                        service.process.kill('SIGKILL');
                        service.healthy = false;
                        return resolve();
                    }

                    // Normal graceful shutdown
                    Logger.log(`Gracefully stopping ${service.name} (SIGTERM)`);
                    service.process.kill('SIGTERM');

                    const forceKillTimeout = setTimeout(() => {
                        if (service.process && !service.process.killed) {
                            Logger.log(`${service.name} didn't terminate gracefully, forcing SIGKILL`);
                            service.process.kill('SIGKILL');
                        }
                        resolve();
                    }, 5000);

                    service.process.once('exit', () => {
                        clearTimeout(forceKillTimeout);
                        resolve();
                    });
                }));
            }
        }

        if (terminationPromises.length > 0) {
            Logger.log(`Waiting for ${terminationPromises.length} services to terminate...`);
            await Promise.all(terminationPromises);
            Logger.log('All services stopped successfully');
        } else {
            Logger.log('No active services to stop');
        }

        return true;
    }

    isAllHealthy() {
        return Object.values(this.services).every(service => service.healthy);
    }

    async checkResourcesInitialization() {
        try {
            // Make sure pybridge is healthy before checking resources
            if (!this.services.pybridge.healthy) {
                Logger.error('Cannot check resources: PyBridge service is not healthy');
                return {
                    initialized: false,
                    error: 'PyBridge service is not healthy'
                };
            }

            const response = await fetch(this.services.pybridge.url.replace('/health', '/setup/check'));

            if (!response.ok) {
                Logger.error(`Failed to check resources: ${response.status} ${response.statusText}`);
                return {
                    initialized: false,
                    error: `Failed to check resources: ${response.status} ${response.statusText}`
                };
            }

            const result = await response.json();
            Logger.log('Resource initialization check result:', result);
            return result;
        } catch (error) {
            Logger.error('Error checking resources initialization:', error);
            return {
                initialized: false,
                error: error.message
            };
        }
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

    async initializeResources() {
        try {
            // Make sure pybridge is healthy before initializing resources
            if (!this.services.pybridge.healthy) {
                Logger.error('Cannot initialize resources: PyBridge service is not healthy');
                return {
                    success: false,
                    error: 'PyBridge service is not healthy'
                };
            }

            this.updateProgress('Starting resource initialization...', 0);

            // Start the initialization process
            const response = await fetch(
                this.services.pybridge.url.replace('/health', '/setup/initialize'),
                {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({})
                }
            );

            if (!response.ok) {
                const errorText = await response.text();
                Logger.error(`Failed to initialize resources: ${response.status} ${response.statusText} - ${errorText}`);
                return {
                    success: false,
                    error: `Failed to initialize resources: ${response.status} ${response.statusText}`
                };
            }

            // Start polling for progress updates
            this._pollResourceInitProgress();

            const result = await response.json();
            Logger.log('Resource initialization result:', result);
            return result;
        } catch (error) {
            Logger.error('Error initializing resources:', error);
            return {
                success: false,
                error: error.message
            };
        }
    }

    async _pollResourceInitProgress() {
        // Poll for progress updates
        const pollInterval = setInterval(async () => {
            try {
                if (!this.services.pybridge.healthy) {
                    clearInterval(pollInterval);
                    return;
                }

                const progressResponse = await fetch(
                    this.services.pybridge.url.replace('/health', '/setup/progress')
                );

                if (!progressResponse.ok) {
                    Logger.error(`Failed to get initialization progress: ${progressResponse.status} ${progressResponse.statusText}`);
                    clearInterval(pollInterval);
                    return;
                }

                const progressData = await progressResponse.json();

                // Update progress through the callback
                this.updateProgress(progressData.message, progressData.progress);

                // If initialization is complete or errored, stop polling
                if (progressData.status === 'complete' || progressData.status === 'error') {
                    clearInterval(pollInterval);

                    if (progressData.status === 'error') {
                        Logger.error(`Resource initialization error: ${progressData.message}`);
                    } else {
                        Logger.log('Resource initialization completed successfully');
                    }
                }
            } catch (error) {
                Logger.error('Error polling initialization progress:', error);
                clearInterval(pollInterval);
            }
        }, 1000);
    }
}

module.exports = new ServiceManager();
