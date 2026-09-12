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

const { spawn, exec } = require('child_process');
const { EventEmitter } = require('events');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { app } = require('electron');

const ConfigManager = require('./config');
const Logger = require('./logger');

const config = new ConfigManager();
const GRACEFUL_STOP_TIMEOUT_MS = 8000;
const ANSI_RE = /\x1b\[[0-9;]*[A-Za-z]/g;

class SentinelRunner extends EventEmitter {
    constructor() {
        super();
        if (SentinelRunner.instance) {
            return SentinelRunner.instance;
        }
        SentinelRunner.instance = this;
        this.child = null;
        // Dedicated line emitters, one per process, so a one-shot child's
        // partial lines can never merge with the daemon's.
        this._emitOut = this._makeLineEmitter();
        this._emitErr = this._makeLineEmitter();
        this._ephemeral = new Set();
    }

    // Mirrors ServiceManager's packaged/dev/source conventions.
    resolveCommand() {
        const platform = os.platform();
        const isDevMode = !app.isPackaged;
        const useSource = (
            process.env.AINARA_USE_SOURCE === 'true' ||
            process.env.AINARA_USE_SOURCE === '1'
        );

        if (isDevMode && useSource) {
            const pythonExecutable = platform === 'win32'
                ? path.join(process.cwd(), 'venv', 'Scripts', 'python.exe')
                : path.join(process.cwd(), 'venv', 'bin', 'python');
            return {
                command: pythonExecutable,
                args: ['-u', path.join(process.cwd(), 'scripts', 'scheduler.py')]
            };
        }

        const serversDir = isDevMode
            ? path.join(process.cwd(), 'dist', 'servers')
            : path.join(process.resourcesPath, 'bin', 'servers');
        const exeName = platform === 'win32' ? 'sentinel.exe' : 'sentinel';
        return { command: path.join(serversDir, exeName), args: [] };
    }

    isRunning() {
        return this.child !== null && this.child.exitCode === null;
    }

    start() {
        return new Promise((resolve, reject) => {
            if (this.isRunning()) {
                return resolve();
            }
            const { command, args } = this.resolveCommand();
            if (!fs.existsSync(command)) {
                return reject(new Error(`Sentinel executable not found: ${command}`));
            }

            Logger.info(`Starting Sentinel: ${command} ${args.join(' ')}`);
            this.child = spawn(command, args, {
                stdio: ['ignore', 'pipe', 'pipe'],
                windowsHide: true,
                env: {
                    ...process.env,
                    // Belt-and-braces: dev mode passes `-u`; in packaged
                    // mode the frozen exe needs this to stream line-by-line
                    // into Sentinel's UI.
                    PYTHONUNBUFFERED: '1',
                    PYTHONIOENCODING: 'utf-8'
                }
            });

            this.child.stdout.on('data', (d) => this._onData('out', d));
            this.child.stderr.on('data', (d) => this._onData('err', d));
            this.child.on('error', (err) => {
                Logger.error('Sentinel process error:', err);
                reject(err);
            });
            this.child.on('exit', (code, signal) => {
                Logger.info(`Sentinel process exited (code=${code}, signal=${signal})`);
                this._flushBuffers();
                this.emit('exit', code);
            });

            resolve();
        });
    }

    _makeLineEmitter() {
        let buf = '';
        const strip = (s) => s.replace(ANSI_RE, '').replace(/\r$/, '');
        return {
            push: (chunk) => {
                const text = buf + chunk.toString();
                const parts = text.split('\n');
                buf = parts.pop();
                for (const part of parts) {
                    const line = strip(part);
                    if (line.trim()) this.emit('output', line);
                }
            },
            flush: () => {
                const line = strip(buf || '');
                if (line.trim()) this.emit('output', line);
                buf = '';
            },
        };
    }

    _onData(stream, chunk) {
        (stream === 'out' ? this._emitOut : this._emitErr).push(chunk);
    }

    _flushBuffers() {
        this._emitOut.flush();
        this._emitErr.flush();
    }

    // Spawn a short-lived scheduler.py invocation. With { collect: true }
    // stdout/stderr are returned as strings and NOT emitted as log lines
    // (used for --list-plans); otherwise the output streams into the pane.
    runOnce(extraArgs, { collect = false } = {}) {
        const { command, args } = this.resolveCommand();
        return new Promise((resolve) => {
            if (!fs.existsSync(command)) {
                return resolve({
                    ok: false,
                    message: `Sentinel executable not found: ${command}`,
                });
            }
            const child = spawn(command, [...args, ...extraArgs], {
                stdio: ['ignore', 'pipe', 'pipe'],
                windowsHide: true,
                env: {
                    ...process.env,
                    PYTHONUNBUFFERED: '1',
                    PYTHONIOENCODING: 'utf-8',
                },
            });
            this._ephemeral.add(child);

            let stdout = '';
            let stderr = '';
            if (collect) {
                child.stdout.on('data', (d) => { stdout += d.toString(); });
                child.stderr.on('data', (d) => { stderr += d.toString(); });
            } else {
                const emit = this._makeLineEmitter();
                child.stdout.on('data', emit.push);
                child.stderr.on('data', emit.push);
            }

            child.on('exit', (code) => {
                this._ephemeral.delete(child);
                resolve({ ok: code === 0, code, stdout, stderr });
            });
            child.on('error', (err) => {
                this._ephemeral.delete(child);
                resolve({ ok: false, message: err.message, stdout, stderr });
            });
        });
    }

    // scheduler.py only handles SIGINT (KeyboardInterrupt) and then stops
    // orakle/bureau itself; SIGTERM would orphan them. On Windows signals
    // are hard kills, so use taskkill /T to take the whole tree down.
    async stop({ force = false } = {}) {
        // Reap any one-shot children first so app exit can't orphan them.
        for (const child of [...this._ephemeral]) {
            try {
                child.kill(force ? 'SIGKILL' : 'SIGTERM');
            } catch (e) { /* already gone */ }
        }
        this._ephemeral.clear();

        const child = this.child;
        if (!child || child.exitCode !== null) return true;

        return new Promise((resolve) => {
            let settled = false;
            const finish = () => {
                if (!settled) { settled = true; resolve(true); }
            };
            // On Windows the tree-kill must run while the root PID is still
            // alive (taskkill /T walks downward from it), so taskkill's
            // completion — not the root's exit — is what resolves stop().
            // Guard the exit listener so the root's exit does not resolve the
            // promise early during a tree kill.
            let treeKilling = false;
            const onExit = () => { if (!treeKilling) finish(); };
            child.once('exit', onExit);

            const hardKill = () => {
                const finalKill = () => {
                    // Backstop: ensure the root itself is gone even if
                    // taskkill failed or was partial.
                    try { child.kill('SIGKILL'); } catch (e) { /* already gone */ }
                    finish();
                };

                if (process.platform === 'win32' && child.pid) {
                    treeKilling = true;
                    exec(
                        `taskkill /PID ${child.pid} /T /F`,
                        { windowsHide: true, timeout: 5000 },
                        (err) => {
                            if (err) {
                                Logger.error(`taskkill for Sentinel tree failed: ${err.message}`);
                            }
                            finalKill();
                        }
                    );
                    // Safety net in case exec never invokes its callback.
                    setTimeout(finalKill, 6000);
                    return;
                }
                finalKill();
            };

            if (force || process.platform === 'win32') {
                hardKill();
                return;
            }

            try {
                child.kill('SIGINT');
            } catch (e) {
                Logger.error('Error signaling Sentinel process:', e);
                hardKill();
                return;
            }
            setTimeout(() => {
                if (child.exitCode === null) {
                    Logger.warning('Sentinel did not exit gracefully, force killing');
                    hardKill();
                } else {
                    finish();
                }
            }, GRACEFUL_STOP_TIMEOUT_MS);
        });
    }
}

module.exports = new SentinelRunner();
