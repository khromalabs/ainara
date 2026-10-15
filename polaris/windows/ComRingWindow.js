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

const BaseWindow = require('./BaseWindow');
const Logger = require('../framework/logger');
const ConfigHelper = require('../framework/ConfigHelper');
const Notifier = require('../framework/notifier');
const KeyState = require('../framework/key-state');
const loudness = require('loudness');
// const { EventEmitter } = require('events');

// const myEmitter = new EventEmitter();

class ComRingWindow extends BaseWindow {
    static getHandlers() {
        return {
            onShow: (window, manager) => {
                const comRing = manager.getWindow('comRing');
                if (comRing) {
                    // comRing.focus();
                    comRing.window.webContents.send('window-show');
                }
            },
            beforeHide: (window) => {
                if (window.prefix === 'comRing') {
                    window.window.webContents.send('window-hide');
                    window.window.webContents.send('stopRecording');
                    window.stopPTTKeyWatch();
                }
            },
            onBlur: async (window, manager) => {
                const chatDisplay = manager.getWindow('chatDisplay');
                // Don't auto-hide if in typing mode
                if (window.prefix === 'comRing' &&
                    window.isVisible() && !chatDisplay.isTypingMode) {
                    window.window.webContents.send('window-hide');
                    window.hide();
                }
            },
            onFocus: () => {
                Logger.log('ComRingWindow RECEIVED FOCUS');
            }
        };
    }

    constructor(config, screen, manager, basePath) {
        const { width: screenWidth, height: screenHeight } = screen.getPrimaryDisplay().workAreaSize;
        const windowWidth = config.get('comRing.width', 300);
        const windowHeight = config.get('comRing.height', 200);
        const options = {
            width: windowWidth,
            height: windowHeight,
            x: config.get('comRing.x', (screenWidth / 2) - (windowWidth / 2)),
            y: config.get('comRing.y', (screenHeight / 2) - (windowHeight / 2)),
            skipTaskbar: false, // Show taskbar icon for ComRingWindow
            type: 'normal',  // Override to normal for keyboard focus
            focusable: true,  // Explicitly set focusable
            alwaysOnTop: true
        };

        super(config, 'comRing', options, basePath);

        this.manager = manager; // Store reference to window manager
        this.loadContent('./components/com-ring.html');
        this.setupEventHandlers();
        this.originalSize = [windowWidth, windowHeight];
        this.originalPosition = [options.x, options.y];
        this.isDocumentView = false;
        this.originalVolume = null;
        this.onAnimation = false;
        // Session-level backend trust for the PTT key watch (#19 item 5): set
        // once the OS key-state backend has ever reported the trigger key
        // down. From then on an "up" report is trusted even within a
        // recording that never showed a down (e.g. the key was released
        // before the first poll after a fast tap).
        this.pttKeyWatchTrusted = false;
    }

    setupEventHandlers() {
        super.setupBaseEventHandlers();

        const { ipcMain, screen } = require('electron');

        ipcMain.on('show-window', async () => {
            if (this.manager && !this.isVisible()) {
                this.manager.showAll(true);
            }
        });

        ipcMain.on('ptt-start', async () => {
            // Arm the OS key-state watcher (#19 item 5): if Electron drops
            // the Space keyup, this is what forces the release. The paired
            // stop happens in the 'ptt-stop' handler / beforeHide.
            this.startPTTKeyWatch();
            if (this.config.get('stt.lowerVolume', true)) {
                try {
                    this.originalVolume = await loudness.getVolume();
                    const newVolume = 0; // Math.round(this.originalVolume * 0.2);
                    await loudness.setVolume(newVolume);
                    Logger.log(`Volume lowered to ${newVolume}% (from ${this.originalVolume}%)`);
                } catch (err) {
                    Logger.error('Failed to lower system volume:', err);
                    this.originalVolume = null; // Reset on error
                }
            }
        });

        ipcMain.on('ptt-stop', async () => {
            this.stopPTTKeyWatch();
            if (this.config.get('stt.lowerVolume', true) && this.originalVolume !== null) {
                try {
                    await loudness.setVolume(this.originalVolume);
                    Logger.log(`Volume restored to ${this.originalVolume}%`);
                } catch (err) {
                    Logger.error('Failed to restore system volume:', err);
                } finally {
                    this.originalVolume = null;
                }
            }
        });

        ipcMain.on('set-view-mode', (event, args) => {
            if (this.onAnimation) {
                // prevent reentry
                return;
            }
            if (args.view === 'document' && !this.isDocumentView) {
                const { width: screenWidth, height: screenHeight } = screen.getPrimaryDisplay().size;

                // const docWidth = this.config.get('documentView.width', 800);
                // const docWidth = this.config.get('documentView.width', 800);
                const docHeight = screenHeight * .90
                const docWidth = screenWidth * .90

                // Store current position before resizing
                if (!this.isDocumentView) {
                    const [currentX, currentY] = this.window.getPosition();
                    this.originalPosition = [currentX, currentY];
                }

                const targetX = Math.round((screenWidth - docWidth) / 2);
                const targetY = Math.round((screenHeight - docHeight) / 2);

                this.window.setResizable(true);
                this.window.setMinimumSize(400, 300);
                this.animateBounds({ x: targetX, y: targetY, width: docWidth, height: docHeight }, 400);
                this.isDocumentView = true;

            } else if (args.view === 'ring' && this.isDocumentView) {
                // Restore original size and position
                const [originalWidth, originalHeight] = this.originalSize;
                this.window.setMinimumSize(originalWidth, originalHeight);
                let fixMouse = 'fixMouse' in args ? args.fixMouse : true;
                this.animateBounds({ x: this.originalPosition[0], y: this.originalPosition[1], width: originalWidth, height: originalHeight }, 400, fixMouse);
                this.window.setResizable(false);
                this.isDocumentView = false;
            }
        });

        ipcMain.on('com-ring-focus', () => {
            this.window.focus();
        });

        ipcMain.on('process-typed-message', (event, message) => {
            Logger.log('Received typed message:', message);
            this.window.webContents.send('process-typed-message', message);
        });

        ipcMain.on('exit-typing-mode', () => {
            Logger.log('ComRingWindow: Exiting typing mode');
            this.window.focus();
            this.window.webContents.send('exit-typing-mode');
            Logger.log('ComRingWindow: Focusing window');
        });

        ipcMain.on('send-notification', (event, message) => {
            Notifier.show(message);
        });

        // ipcMain.on('ready-to-show', (event, message) => {
        //     this.window.focus();
        // });

        this.window.webContents.on('did-finish-load', async () => {
            this.backendConfig = await ConfigHelper.fetchBackendConfig();
            const memoryEnabled = this.backendConfig?.memory?.enabled || false;
            this.window.webContents.send('set-memory-state', memoryEnabled);
            // this.window.webContents.openDevTools();
        });

        // Add ComRing specific IPC handlers
        this.window.webContents.on('ipc-message', (event, channel, ...args) => {
            switch (channel) {
                case 'recording-started':
                    Logger.log('Recording started');
                    break;
                case 'recording-stopped':
                    Logger.log('Recording stopped');
                    break;
                case 'recording-error':
                    Logger.error('Recording error:', ...args);
                    break;
                case 'typing-mode-changed':
                    Logger.log('Typing mode changed:', ...args);
                    break;
            }
        });
    }

    /**
     * Polls the OS-level state of the PTT trigger key while recording.
     *
     * Electron can silently drop the DOM keyup event (see #19 item 5), leaving
     * push-to-talk stuck. This watcher is the games-style fix: instead of
     * trusting the event stream, it samples the physical key state and forces
     * a stop when the OS reports the key up.
     *
     * The watcher "arms" either immediately (the renderer only sends
     * 'ptt-start' in response to a physical keydown, so the key is down *now*
     * - an immediate first poll confirms it) or on the first poll that
     * observes the key down. If the platform backend cannot actually see the
     * key (e.g. XWayland not seeing native Wayland clients, unmapped key), it
     * never trusts a "no" answer and degrades to the pre-existing event-only
     * behavior instead of force-stopping valid recordings. However, once the
     * backend has proven it can see the trigger key at any point in this
     * session (pttKeyWatchTrusted), an "up" report is trusted even if this
     * particular recording never showed a down - that means the key was
     * released before the first poll (fast tap, delayed start), and if the
     * recording is still going the keyup event was dropped and the force-stop
     * is exactly what is needed.
     */
    startPTTKeyWatch() {
        this.stopPTTKeyWatch();
        if (!KeyState.isAvailable()) {
            Logger.warn('PTT key watch: no OS key-state backend available, '
                + 'relying on keyup events only');
            return;
        }
        const triggerKey = this.config.get('shortcuts.trigger', 'Space');
        const pollMs = 250;
        const armTimeoutPolls = 4; // 1s to observe the key down, else untrust
        // Immediate first poll: arm without waiting for the first interval
        // tick, so a short tap or a delayed ptt-start cannot slip past.
        let armed = KeyState.isDown(triggerKey) === true;
        if (armed) this.pttKeyWatchTrusted = true;
        let polls = 0;
        Logger.log(`PTT key watch: polling state of ${triggerKey} every ${pollMs}ms`
            + (armed ? ' (armed immediately)' : ''));
        this.pttKeyWatcher = setInterval(() => {
            const down = KeyState.isDown(triggerKey);
            if (down === null) {
                Logger.warn('PTT key watch: key state query failed, disarming');
                this.stopPTTKeyWatch();
                return;
            }
            if (down) {
                if (!armed) Logger.log('PTT key watch: armed (key observed down)');
                armed = true;
                this.pttKeyWatchTrusted = true;
                return;
            }
            if (armed || this.pttKeyWatchTrusted) {
                Logger.log('PTT key watch: OS reports key released '
                    + '(keyup event missed?) - stopping recording');
                this.window.webContents.send('stopRecording');
                this.stopPTTKeyWatch();
            } else if (++polls >= armTimeoutPolls) {
                Logger.warn('PTT key watch: backend never reported ' + triggerKey
                    + ' down, disabling force-stop (untrustworthy backend)');
                this.stopPTTKeyWatch();
            }
        }, pollMs);
    }

    stopPTTKeyWatch() {
        if (this.pttKeyWatcher) {
            clearInterval(this.pttKeyWatcher);
            this.pttKeyWatcher = null;
        }
    }

    animateBounds(targetBounds, duration, fixMouse = true) {
        return new Promise(resolve => {
            const startBounds = this.window.getBounds();
            const startTime = Date.now();

            this.onAnimation = true;
            this.window.webContents.send('on-animation');

            const animationInterval = setInterval(() => {
                const elapsedTime = Date.now() - startTime;
                const progress = Math.min(elapsedTime / duration, 1);

                // Ease-out function for a smoother stop
                const easeOutProgress = 1 - Math.pow(1 - progress, 3);

                const newBounds = {
                    x: Math.round(startBounds.x + (targetBounds.x - startBounds.x) * easeOutProgress),
                    y: Math.round(startBounds.y + (targetBounds.y - startBounds.y) * easeOutProgress),
                    width: Math.round(startBounds.width + (targetBounds.width - startBounds.width) * easeOutProgress),
                    height: Math.round(startBounds.height + (targetBounds.height - startBounds.height) * easeOutProgress)
                };

                // Use animate: false because we are creating the animation frames manually
                this.window.setBounds(newBounds, false);

                if (progress >= 1) {
                    clearInterval(animationInterval);
                    // Ensure the final size is exact
                    this.window.setBounds(targetBounds, false);

                    if (fixMouse) {
                        // Fix for mouse event capture post-animation
                        this.window.hide();
                        this.window.show();
                        this.window.focus();
                        this.window.setFocusable(true);
                        this.window.setIgnoreMouseEvents(false, { forward: false });
                    }
                    this.onAnimation = false;
                    this.window.webContents.send('not-on-animation');
                    resolve();
                }
            }, 16); // ~60 FPS
        });
    }
}

module.exports = ComRingWindow;
