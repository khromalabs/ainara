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
const fetch = require('node-fetch');
const fs = require('fs');
const os = require('os');
const { app } = require('electron');
const { createEventSource } = require('eventsource-client');
const net = require('net');

const ConfigManager = require('../utils/config');
const Logger = require('./logger');


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

    /**
     * Checks if a specific TCP port is already in use on localhost.
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
        for (const [serviceId, service] of Object.entries(this.services)) {
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

        this.updateProgress(this.initializeMsg, this.startProgress);

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
            this.updateProgress(this.initializeMsg, this.startProgress);

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
                terminationPromises.push(new Promise((resolve, reject) => {
                    if (force) {
                        Logger.log(`Force killing ${service.name} immediately (SIGKILL)`);
                        service.process.kill('SIGKILL');
                        service.healthy = false;
                        return resolve();
                    }

                    // Normal graceful shutdown
                    Logger.log(`Gracefully stopping ${service.name} (SIGINT)`);
                    service.process.kill('SIGINT'); // Use SIGINT instead of SIGTERM

                    let pollingInterval = null;
                    const maxWaitTime = 10000; // 10 seconds total wait time
                    const pollIntervalTime = 1000; // Check every 1 second
                    const startTime = Date.now();

                    // Function to clean up polling interval
                    const cleanupPolling = () => {
                        if (pollingInterval) {
                            clearInterval(pollingInterval);
                            pollingInterval = null;
                        }
                    };

                    // Start polling
                    pollingInterval = setInterval(() => {
                        try {
                            // Check if process exists using signal 0
                            Logger.warn(`Forcing ${service.name} to stop (SIGKILL)`);
                            process.kill(service.process.pid, 0);
                            // If no error, process still exists. Check for timeout.
                            if (Date.now() - startTime >= maxWaitTime) {
                                cleanupPolling();
                                Logger.error(`Timeout: ${service.name} (PID: ${service.process.pid}) did not terminate within ${maxWaitTime / 1000} seconds after SIGINT.`);
                                reject(new Error(`${service.name} failed to terminate gracefully`));
                            }
                            // Else: Still alive, continue polling
                        } catch (e) {
                            if (e.code === 'ESRCH') {
                                // Process is gone! Success.
                                cleanupPolling();
                                Logger.log(`${service.name} (PID: ${service.process.pid}) confirmed terminated after SIGINT.`);
                                resolve();
                            } else {
                                // Unexpected error during polling
                                cleanupPolling();
                                Logger.error(`Polling error for ${service.name} (PID: ${service.process.pid}): ${e.message}`);
                                reject(new Error(`Polling error: ${e.message}`));
                            }
                        }
                    }, pollIntervalTime);

                    // Also listen for the 'exit' event for immediate confirmation
                    service.process.once('exit', (code, signal) => {
                        cleanupPolling(); // Stop polling if it exited
                        Logger.log(`${service.name} exited gracefully with code ${code} signal ${signal}`);
                        resolve();
                    });

                    // Handle potential errors during spawn or initial setup
                    service.process.once('error', (err) => {
                        cleanupPolling(); // Stop polling on error
                        Logger.error(`Error on ${service.name} process: ${err.message}`);
                        reject(err); // Reject if the process errors out
                    });
                }));
            }
        }

        if (terminationPromises.length > 0) {
            Logger.log(`Waiting for ${terminationPromises.length} services to terminate...`);
            try {
                await Promise.all(terminationPromises);
                Logger.log('All services stopped successfully');
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
        // Return a Promise that resolves/rejects based on SSE events
        return new Promise((resolve, reject) => {
            let es = null; // Event source instance
            // --- Variables for fake progress ---
            let progressIntervalId = null;
            let lastActualProgress = 0;
            let visualProgress = 0;
            let lastActualMessage = '';
            const maxFakeProgress = 98; // Cap for fake progress
            // --- Helper to clear interval ---
            const clearProgressInterval = () => {
                if (progressIntervalId) {
                    clearInterval(progressIntervalId);
                    progressIntervalId = null;
                    // console.log("Cleared fake progress interval");
                }
            };

            try {
                if (!this.services.pybridge.healthy) {
                    Logger.error('Cannot initialize resources: PyBridge service is not healthy');
                    return {
                        success: false,
                        error: 'PyBridge service is not healthy'
                    };
                }

                // --- Initial UI update ---
                lastActualMessage = 'Connecting to initialization service...';
                this.updateProgress('Downloading resources...', 0);
                Logger.log('Connecting to SSE endpoint for resource initialization...');

                const sseUrl = config.get('pybridge.api_url') + '/setup/initialize';

                const messageHandler = (event) => {
                    try {
                        const data = JSON.parse(event.data);
                        Logger.log('SSE Progress:', data);

                        // Store actual progress and message
                        lastActualProgress = data.progress;
                        lastActualMessage = data.message;
                        visualProgress = lastActualProgress; // Reset visual progress to actual

                        // Clear any existing fake progress timer
                        clearProgressInterval();

                        // Update progress through the callback
                        this.updateProgress(lastActualMessage, visualProgress);

                        // Check for terminal states
                        if (data.status === 'complete') {
                            Logger.log('Resource initialization completed successfully via SSE.');
                            if (es) es.close(); // Close the connection
                            resolve({ success: true, message: lastActualMessage });
                        } else if (data.status === 'error') {
                            Logger.error(`Resource initialization error via SSE: ${lastActualMessage}`);
                            if (es) es.close(); // Close the connection
                            reject({ success: false, error: lastActualMessage });
                        } else if (data.status === 'running' && es && es.readyState === 'open') {
                            // Start the fake progress timer if still running
                            progressIntervalId = setInterval(() => {
                                if (visualProgress < maxFakeProgress) {
                                    visualProgress = Math.min(visualProgress + 1, maxFakeProgress);
                                    // Update UI with fake progress but last real message
                                    this.updateProgress(lastActualMessage, visualProgress);
                                    // console.log(`Fake progress incremented to ${visualProgress}%`);
                                } else {
                                    // Stop incrementing if cap is reached, but keep interval running
                                    // in case a real update resets it later.
                                    // console.log("Fake progress reached cap.");
                                }
                            }, 3000); // Increment every 3 seconds
                            // console.log("Started fake progress interval");
                        }

                    } catch (parseError) {
                        Logger.error('Error parsing SSE message data:', parseError, event.data);
                        // Don't close connection here, might be a transient issue
                    }
                };

                const errorHandler = (error) => {
                    Logger.error('EventSource failed:', error);
                    // Ensure UI shows an error if connection drops unexpectedly
                    clearProgressInterval(); // Stop fake progress
                    this.updateProgress('Connection error during initialization', 100);
                    if (es) es.close(); // Close the connection
                    reject({ success: false, error: 'EventSource connection error' });
                };

                // Create the event source using the new library's function
                es = createEventSource({
                    url: sseUrl,
                    onMessage: messageHandler,
                    onError: errorHandler
                });

            } catch (error) {
                clearProgressInterval(); // Ensure cleanup on initial error
                Logger.error('Error setting up EventSource or initial check:', error);
                if (es) {
                    es.close();
                }
                reject({ success: false, error: error.message });
            }
        }); // End of Promise constructor
    }
}

module.exports = new ServiceManager();
