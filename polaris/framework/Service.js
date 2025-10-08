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

const { EventEmitter } = require('events');
const { spawn } = require('child_process');
const fetch = require('node-fetch');
const Logger = require('./logger');

class Service extends EventEmitter {
    constructor(id, { name, executablePath, args, url }) {
        super();
        this.id = id;
        this.name = name;
        this.executablePath = executablePath;
        this.args = args;
        this.url = url; // Health check URL
        this.errorMsg = null;

        this.process = null;
        this.healthy = false;
    }

    start(timeout) {
        return new Promise((resolve, reject) => {
            Logger.log(`Starting ${this.name} service from: ${this.executablePath}`);

            try {
                this.process = spawn(this.executablePath, this.args, {
                    stdio: 'pipe',
                    shell: false
                });

                this.process.stdout.on('data', (data) => {
                    this.emit('stdout', data.toString());
                });

                this.process.stderr.on('data', (data) => {
                    this.emit('stderr', data.toString());
                });

                this.process.on('exit', (code) => {
                    this.healthy = false;
                    this.emit('exit', code);
                });

                this.process.on('error', (err) => {
                    this.healthy = false;
                    Logger.error(`Error on ${this.name} process: ${err.message}`);
                    this.errorMsg = err.message;
                    reject(err);
                });

                this.waitForHealth(timeout)
                    .then(() => resolve())
                    .catch(err => { this.errorMsg = err.message; reject(err) });

            } catch (error) {
                Logger.error(`Failed to spawn ${this.name} process:`, error);
                this.errorMsg = error.message;
                reject(error);
            }
        });
    }

    async waitForHealth(timeout) {
        const startTime = Date.now();

        while (Date.now() - startTime < timeout) {
            if (this.process && this.process.exitCode !== null) {
                throw new Error(
                    `${this.name} process exited unexpectedly with code ${this.process.exitCode} before becoming healthy. Error: ${this.errorMsg}`
                );
            }
            try {
                const response = await fetch(this.url);
                if (response.ok) {
                    this.healthy = true;
                    Logger.log(`${this.name} is healthy`);
                    return;
                }
            } catch (error) {
                // Ignore connection errors during startup, just keep polling
                this.errorMsg = error.message;
            }

            this.emit('progress-tick');
            await new Promise(resolve => setTimeout(resolve, 500));
        }

        throw new Error(`Timeout waiting for ${this.name} to become healthy`);
    }

    async checkHealth() {
        try {
            const response = await fetch(this.url);
            return response.ok;
        } catch (error) {
            // Don't log here, as it can be noisy. The caller can log if needed.
            this.errorMsg = error.message;
            return false;
        }
    }

    stop({ force = false } = {}) {
        if (!this.process || this.process.killed) {
            return Promise.resolve();
        }

        return new Promise((resolve, reject) => {
            if (force) {
                Logger.log(`Force killing ${this.name} immediately (SIGKILL)`);
                this.process.kill('SIGKILL');
                this.healthy = false;
                return resolve();
            }

            Logger.log(`Gracefully stopping ${this.name} (SIGINT)`);
            this.process.kill('SIGINT');

            const maxWaitTime = 20000; // 20 seconds
            const timeout = setTimeout(() => {
                Logger.error(`Timeout: ${this.name} (PID: ${this.process.pid}) did not terminate within ${maxWaitTime / 1000} seconds after SIGINT.`);
                if (this.process && !this.process.killed) {
                    this.process.kill('SIGKILL'); // Force kill
                }
                this.errorMsg = "Failed";
                reject(new Error(`${this.name} failed to terminate gracefully`));
            }, maxWaitTime);

            this.process.once('exit', (code, signal) => {
                clearTimeout(timeout);
                Logger.log(`${this.name} exited gracefully with code ${code} signal ${signal}`);
                resolve();
            });

            this.process.once('error', (err) => {
                clearTimeout(timeout);
                Logger.error(`Error on ${this.name} process during stop: ${err.message}`);
                this.errorMsg = err.message;
                reject(err);
            });
        });
    }
}

module.exports = Service;
