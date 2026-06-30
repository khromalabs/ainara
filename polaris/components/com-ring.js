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

/**
 * Com-Ring Interface Design
 * Original concept and implementation by Rubén Gómez for Ainara/Polaris Project
 * Copyright (c) 2025 Rubén Gómez - khromalabs.org
 *
 * This program is free software; you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation; version 2.
 *
 * The Com-Ring interface design is additionally licensed under
 * Creative Commons Attribution 4.0 International License.
 * To view a copy of this license, visit http://creativecommons.org/licenses/by/4.0/
 *
 * When using or adapting this design, please provide attribution:
 * "Com-Ring Interface Design by Rubén Gómez - Ainara/Polaris Project (ainara.app)"
 */

const WhisperSTT = require('../services/stt/whisper');
const ConfigManager = require('../framework/config');
const ConfigHelper = require('../framework/ConfigHelper');
const BaseComponent = require('./base');
const electron = require('electron');

var ipcRenderer = electron.ipcRenderer;
console.log('com-ring.js loaded');

const ERROR_WITH_CALL_TRACE = false

var me;

class ComRing extends BaseComponent {
    constructor() {
        try {
            super();
            me = this;

            /*
             * TODO: REFACTORING PROPOSAL - STATE MACHINE
             * The current implementation relies on multiple boolean flags (isRecording, isProcessingLLM,
             * wakeWordEnabled, etc.) which leads to complex edge cases and race conditions, particularly
             * with audio resource management.
             *
             * Future refactoring should implement a Finite State Machine (FSM) with explicit states:
             * - IDLE: Waiting for input (WakeWord active if enabled)
             * - LISTENING: Active recording (PTT or WakeWord triggered)
             * - PROCESSING: Sending audio/text to LLM
             * - SPEAKING: Playing TTS response
             *
             * This would decouple the UI state from the underlying audio resource management and
             * prevent issues where stopping TTS accidentally kills the microphone input loop.
             */

            this.ignoreIncomingEvents = false;
            this.showInitialMessages = true;
            console.log('ComRing: Initializing constructor');
            this.config = new ConfigManager();
            this.text = null;
            this.memoryEnabled = null;
            this.notificationCount = 0;

            // Add tracking for animations and message queue
            this.pendingAnimations = new Map();  // Track pending animations by message ID
            this.messageQueue = [];              // Queue for combined text and audio messages
            this.isProcessingMessage = false;    // Flag to track if a message is being processed
            this.currentMessageId = null;        // Track the ID of the current message being processed
            this.animationResolvers = new Map(); // Store animation completion resolvers
            this.animationTimeouts = new Map();  // Store animation timeouts
            this.audioTimeouts = new Map();      // Store audio timeouts

            // Get pybridge API endpoint from config
            this.pybridgeEndpoint = this.config.get('pybridge.api_url', 'http://127.0.0.1:8101');
            this.pybridgeEndpoints = {
                chat: `${this.pybridgeEndpoint}/framework/chat`,
                history: `${this.pybridgeEndpoint}/framework/chat/history`,
                notifications: `${this.pybridgeEndpoint}/framework/notifications/status`
            };
            this.isWindowVisible = false;
            this.isProcessingUserMessage = false;
            this.keyCheckInterval = null;
            console.log('ComRing: Config manager initialized');
            this.currentView = 'ring';
            this.docFormat = 'text';
            this.navigatingHistory = false;

            this.state = {
                keyPressed: false,
                isRecording: false,
                isAwaitingResponse: false,
                isProcessingLLM: false,
                volume: this.config.get('ring.volume', 0)
            };
            console.log('ComRing: State initialized');
            this.historyDate = null;
            this.lastMessageTimestamp = null;

            // Setup keyboard shortcut configuration
            this.triggerKey = this.config.get('shortcuts.trigger', 'Space');
            this.showKey = this.config.get('shortcuts.show', 'F1');
            console.log('ComRing: Keyboard shortcuts initialized:', { trigger: this.triggerKey });

            this.stt = new WhisperSTT();
            console.log('ComRing: WhisperSTT initialized');

            this.llmClient = null;
            this.setupTranscriptionHandler();
            this.onAnimation = false;

            // Add Wake Word configuration
            this.wakeWordEnabled = this.config.get('wakeword.enabled', false);
            this.wakeWordSocket = null;
            this.audioProcessor = null;
            this.isListeningForWakeWord = false;

            // VAD Configuration
            this.vadThreshold = 0.30; // Volume threshold (0.0 - 1.0)
            this.silenceStartTimestamp = null;
            this.maxSilenceDuration = 2000; // 2 seconds

            // Media Recorder for the new flow
            this.mediaRecorder = null;
            this.audioChunks = [];

            this.wizardActive = false;

        } catch (error) {
            console.error('ComRing constructor error:', error);
            throw error;
        }
    }

    async connectedCallback(recursion=null) {
        try {
            console.log('ComRing: connectedCallback started');

            console.log('ComRing: Initializing STT');
            // Initialize STT
            // TODO disabled this check as doesn't allow early component load
            // (before services are started)
            // await this.stt.initialize();
            console.log('ComRing: STT initialized');

            // Component is added to the DOM
            this.dispatchEvent(new CustomEvent('com-ring-connected'));
            console.log('ComRing: connected event dispatched');

            const template =
                this.requireTemplate('com-ring-template');
            await this.loadStyles('com-ring.css');

            // Attach template content
            this.shadowRoot.appendChild(template.content.cloneNode(true));

            console.log('ComRing: Looking for ring elements');
            // Get required elements
            this.circle = this.assert(
                this.shadowRoot.querySelector('.ring-circle'),
                'ring-circle element not found'
            );
            console.log('ComRing: Found ring-circle element');
            this.innerCircle = this.assert(
                this.shadowRoot.querySelector('.inner-circle'),
                'inner-circle element not found'
            );
            this.ringContainer = this.assert(
                this.shadowRoot.querySelector('.ring-container'),
                'ring-container element not found'
            );
            this.documentView = this.assert(document.querySelector('document-view'), 'document-view element not found');
            this.llmProviderDisplay = this.assert(
                this.shadowRoot.querySelector('.llm-provider-display'),
                'llm-provider-display element not found'
            );

            this.audioContext = null;
            this.mediaStream = null;
            this.analyser = null;
            this.animationFrame = null;

            this.initializeEventListeners();
            await this.updateLLMProviderDisplay();

            // Initialize Audio Stream immediately if Wake Word is enabled
            if (this.wakeWordEnabled) {
                async function checkPybridgeAndInitializeAudio() {
                    let retries = 0;
                    while (retries < 20) {
                        // console.log('RUBEN Attempt connection to pybridge health:' + retries);
                        const url = me.config.get('pybridge.api_url') + '/health';
                        // console.log('RUBEN url: ' + url);
                        try {
                            const response = await fetch(url);
                            // console.log('RUBEN response');
                            console.log(response);
                            if (response.ok) {
                                me.initializeAudioStream();
                                break;
                            }
                        } catch (error) {
                            // console.log('RUBEN failed to fetch');
                            console.log(error);
                        }
                        await new Promise(resolve => setTimeout(resolve, 5000));
                        retries++;
                    }
                }
                // Launch parallel process
                setTimeout(() => checkPybridgeAndInitializeAudio(), 10);
            }

            this.emitEvent('ready');

        } catch (error) {
            if (recursion < 10) {
                recursion++;
                // wait two seconds and try again if an error happened
                console.log('ComRing: Attempt ' + recursion + ' in connectedCallback...')
                await new Promise(resolve => setTimeout(resolve, 3000));
                await this.connectedCallback(recursion)
            } else {
                this.showInfo(error, true);
                throw error;
            }
        }
    }


    disconnectedCallback() {
        console.log('ComRing: Disconnecting and cleaning up resources');
        // Clean up when component is removed
        if (this.keyCheckInterval) {
            clearInterval(this.keyCheckInterval);
            this.keyCheckInterval = null;
        }

        // Force cleanup of audio resources
        this.stopRecording();

        // Additional cleanup
        if (this.stt) {
            console.log('Cleaning up STT resources');
            this.stt.cleanup && this.stt.cleanup();
        }

        if (this.mediaStream) {
            console.log('Ensuring media stream is stopped');
            this.mediaStream.getTracks().forEach(track => {
                if (track.readyState === 'live') {
                    track.stop();
                }
            });
            this.mediaStream = null;
        }

        console.log('ComRing: Cleanup complete');
    }

    setMemoryState(enabled) {
        this.memoryEnabled = enabled;
        if (enabled) {
            this.ringContainer.classList.remove('no-memory');
        } else {
            this.ringContainer.classList.add('no-memory');
        }
    }

    _formatProviderName(provider) {
        if (!provider) return '';
        // Take the last part of the path (e.g., "deepseek/deepseek-chat" -> "deepseek-chat")
        const parts = provider.split('/');
        const modelName = parts[parts.length - 1];

        // Capitalize each word separated by a hyphen (e.g., "deepseek-chat" -> "Deepseek-Chat")
        return modelName
            .split('-')
            .map(word => word.charAt(0).toUpperCase() + word.slice(1))
            .join('-');
    }

    async updateLLMProviderDisplay() {
        try {
            const { selected_provider } = await ConfigHelper.getLLMProviders();

            if (selected_provider) {
                const displayName = this._formatProviderName(selected_provider);
                this.llmProviderDisplay.textContent = displayName;
            } else {
                this.llmProviderDisplay.textContent = 'No LLM Provider';
            }
        } catch (error) {
            console.error('Error updating LLM provider display:', error);
            this.llmProviderDisplay.textContent = 'Provider Unknown';
        }
    }

    initializeEventListeners() {
        console.log('ComRing: Initializing event listeners');
        console.log('ComRing: Setting up IPC event listeners');

        // Add debug logs for keyboard setup
        console.log('ComRing: Keyboard setup:', {
            modifierKey: this.modifierKey,
            mainKey: this.mainKey
        });

        try {
            console.log('ComRing: Successfully imported electron and got ipcRenderer');
        } catch (error) {
            console.error('ComRing: Failed to get ipcRenderer:', error);
            return;
        }

        // Add window visibility listeners
        ipcRenderer.on('window-show', async () => {
            console.log('ComRing: Received window-show event');
            this.isWindowVisible = true;
            console.log('window-show: isWindowVisible true');
            var backendConfig;
            try {
                backendConfig = await ConfigHelper.fetchBackendConfig();
            } catch {
                this.showInfo("Couldn't read backend configuration", true);
                this.showInfo("Please reboot the application", true);
            }

            // console.log('MEMORYINFO 1');
            // console.log(JSON.stringify(backendConfig));

            if (this.showInitialMessages &&
                backendConfig &&
                backendConfig.memory &&
                backendConfig.backup) {

                // console.log('MEMORYINFO 2');
                // this.showInfo("MEMORYINFO 2");
                this.memoryEnabled = backendConfig.memory.enabled || false;
                this.setMemoryState(this.memoryEnabled);
                if (this.memoryEnabled === false) {
                    // console.log('MEMORYINFO 3');
                    // this.showInfo("MEMORYINFO 3");
                    this.showInfo("Memory is disabled, to enable type: /memory");
                }
                if (!backendConfig.backup.enabled) {
                    this.showInfo("Backups are disabled. Use Setup Wizard to enable.");
                }
                this.showInitialMessages = false;
            }

            // Check for backup configuration on first show
            // if (this.isFirstShow) {
            //     this.showInfo("MEMORYINFO 2");
            //     this.isFirstShow = false; // Ensure this only runs once
            //     if (!backendConfig?.backup?.enabled) {
            //         this.showInfo("Backups are disabled. Use Setup Wizard to enable.");
            //     }
            //     if (this.memoryEnabled == false) {
            //         this.showInfo("Memory is disabled, to enable type: /memory");
            //     }
            //     this.showInfo("MEMORYINFO 3");
            // }

        });

        ipcRenderer.on('set-memory-state', (event, enabled) => {
            console.log('ComRing: Received set-memory-state event');
            this.setMemoryState(enabled);
        });

        function truncateMiddle(str, maxLength) {
            if (str.length <= maxLength) {
                return str;
            }

            const startLength = Math.ceil((maxLength - 3) / 2);
            const endLength = Math.floor((maxLength - 3) / 2);

            const start = str.substring(0, startLength);
            const end = str.substring(str.length - endLength);

            return start + '...' + end;
        }

        ipcRenderer.on('wizard-status', async (event, wizardStatus) => {
            console.log('ComRing: Setup Wizard is ', wizardStatus);
            this.wizardActive = wizardStatus;
        });

        // Add listener for LLM provider changes
        ipcRenderer.on('llm-provider-changed', async (event, providerName) => {
            console.log('ComRing: LLM provider changed to', providerName);
            await this.updateLLMProviderDisplay();
            if (this.isWindowVisible) {
                // Show provider change notification
                const sttStatus = this.shadowRoot.querySelector('.stt-status');
                sttStatus.innerHTML = `Switched LLM model to:<br><i>${truncateMiddle(providerName, 44)}</i>`;
                sttStatus.classList.add('active2');

                // Hide the message after 4 seconds
                setTimeout(() => {
                    sttStatus.classList.remove('active2');
                    sttStatus.textContent = '';
                    this.updateIdleStatus();
                }, 4000);
            }
        });

        ipcRenderer.on('window-hide', () => {
            console.log('ComRing: Received window-hide event');
            this.isWindowVisible = false;
            console.log('window-hide: isWindowVisible false');
            if (this.state.isRecording) {
                console.log('Window hidden while recording - stopping recording');
                this.stopRecording();
            }

            // if (this.state.isProcessingLLM) {
            //     this.abortLLMResponse();
            //     this.cleanAudio();
            //     this.state.isAwaitingResponse = false;
            // }

            this.exitTypingMode();

            // TODO Unsure about what to do here
            // if (!this.onAnimation &&
            //     this.currentView === 'document' &&
            //     this.docFormat === "chat-history") {
            //     // auto shrink if on chat-history mode
            //     this.switchToRingView();
            // }
        });

        ipcRenderer.on('not-on-animation', () => {
            this.onAnimation = false;
        });

        ipcRenderer.on('on-animation', () => {
            this.onAnimation = true;
        });

        ipcRenderer.on('process-typed-message', async (event, message) => {
            if (this.isProcessingUserMessage) {
                console.log("process-typed-message: Avoiding concurrent entry");
                return;
            }
            this.isProcessingUserMessage = true;

            if (message.trim() === '/history') {
                console.log('Handling /history command');
                if (!this.onAnimation) {
                    await this.fetchAndDisplayChatHistory();
                }
            } else if (message.trim() === '/provider') {
                console.log('Handling /provider command');
                await this.updateLLMProviderDisplay();
                this.llmProviderDisplay.classList.add('visible');
                setTimeout(() => {
                    this.llmProviderDisplay.classList.remove('visible');
                }, 4000);
            } else if (message.trim() === '/documents') {
                if (this.documentView && this.documentView.shadowRoot.querySelector('.document-container').childElementCount > 0 && this.docFormat !== 'chat-history') {
                    this.switchToDocumentView(this.docFormat);
                } else {
                    this.showInfo('No documents to display.');
                }
            } else if (message.trim() === '/help') {
                console.log('Handling /help command');
                await this.showHelp();
            } else if (message.trim() === '/about') {
                console.log('Handling /about command');
                await this.showAbout();
            } else if (message.trim() === '/refresh') {
                console.log('Handling /refresh command');
                ipcRenderer.send('refresh-frontend');
            } else {
                await this.processUserMessage(message, true);
            }
            this.isProcessingUserMessage = false;
        });

        ipcRenderer.on('exit-typing-mode', () => {
            console.log("ComRing: exit typing mode");
            this.exitTypingMode();
        });

        // Add listener for typing mode changes from window
        ipcRenderer.on('typing-mode-changed', (event, isTypingMode) => {
            console.log('ComRing: Typing mode changed to', isTypingMode);
            // Update UI based on typing mode
            this.circle.style.opacity = isTypingMode ? '0.3' : '1';
        });

        // Listen for document-view becoming empty (all items closed)
        this.documentView.addEventListener('documentview-empty', () => {
            if (!this.onAnimation) {
                this.switchToRingView();
            }
        });

        // Listen for history navigation events from the document-view component
        this.documentView.addEventListener('documentview-history-prev-clicked', () => this.navigateHistory('prev'));
        this.documentView.addEventListener('documentview-history-next-clicked', () => this.navigateHistory('next'));
        this.documentView.addEventListener('documentview-history-today-clicked', () => this.fetchAndDisplayChatHistory());

        // Listen for search events
        this.documentView.addEventListener('documentview-search-requested', async (e) => {
            const query = e.detail.query;
            if (!query) return;

            try {
                // Use the new search endpoint
                const response = await fetch(`${this.pybridgeEndpoints.chat}/search?q=${encodeURIComponent(query)}&limit=20`);
                const data = await response.json();
                if (data.results) {
                    this.documentView.showSearchResults(data.results);
                }
            } catch (err) {
                console.error('Search failed', err);
                this.showInfo('Search failed: ' + err.message, true);
            }
        });

        this.documentView.addEventListener('documentview-search-result-selected', async (e) => {
            const { date, timestamp } = e.detail;
            // Load history for that date, but don't auto-scroll to bottom (pass false)
            await this.fetchAndDisplayChatHistory(date, false);

            // Scroll to the specific message
            // Give the DOM a moment to render the markdown
            setTimeout(() => {
                this.documentView.scrollToTimestamp(timestamp);
            }, 500);
        });

        // Add event listeners for animation events
        ipcRenderer.on('animation-started', (event, data) => {
            console.log('Animation started:', data);
            this.pendingAnimations.set(data.messageId, true);
        });

        ipcRenderer.on('animation-completed', async (event, data) => {
            console.log('Animation completed:', data, 'Current message:', this.currentMessageId);
            this.pendingAnimations.set(data.messageId, false);

            // Resolve the animation promise if it exists
            const resolver = this.animationResolvers.get(data.messageId);
            if (resolver) {
                console.log(`Resolving animation promise for message: ${data.messageId}`);
                resolver();
                this.animationResolvers.delete(data.messageId);
            } else {
                console.warn(`No resolver found for message: ${data.messageId}`);
            }

            // Only try to process the next message if we're not already processing one
            // and this is not for the current message being processed
            if (!this.isProcessingMessage && data.messageId !== this.currentMessageId) {
                console.log('Not currently processing a message, trying to process next one');
                this.processMessageQueue();
            } else {
                console.log('Still processing a message or this is for the current message, not starting next one yet');
            }
        });

        // // Helper function to check if a character is printable
        // function isPrintableChar(key) {
        //     // First check if it's a single character
        //     if (key.length !== 1) return false;
        //
        //     // Get the character code
        //     const charCode = key.charCodeAt(0);
        //
        //     // Check if it's a control character
        //     if (charCode < 32 || // ASCII control characters
        //         (charCode >= 127 && charCode <= 159)) { // Extended ASCII control characters
        //         return false;
        //     }
        //
        //     // Check if it's a printable character
        //     // This includes all Unicode printable characters
        //     return true;
        // }

        // Debug keyboard events
        document.addEventListener('keydown', async (event) => {
            // console.log("EVENT KEYDOWN");
            // console.log(event);
            if (this.currentView === 'document' && event.key === this.config.get('shortcuts.hide', 'Escape')) {
                if (this.messageQueue.length > 0) {
                    this.abortLLMResponse();
                } else {
                    console.log('Escape in document view: switching back to ring view.');
                    this.switchToRingView();
                }
                event.preventDefault();
                event.stopPropagation();
                return;
            }

            if (event.key === this.config.get('shortcuts.hide', 'Escape')) {
                // console.log("EVENT ESCAPE");
                // Always abort any ongoing LLM response first
                if (this.state.isProcessingLLM || this.isProcessingMessage || this.messageQueue.length > 0) {
                    console.log('Escape triggers abort LLM response');
                    this.abortLLMResponse();
                    event.preventDefault();
                    event.stopPropagation();
                    ipcRenderer.send('com-ring-focus');
                    return;
                } else {
                    console.log("Escape triggers hide-window-all");
                    this.ignoreIncomingEvents = true;
                    ipcRenderer.send('hide-window-all');
                }
            }

            if (this.isWindowVisible) {
                // Get current typing mode state from window
                const isTypingMode = await ipcRenderer.invoke('get-typing-mode-state');

                if (event.key === 'Tab' && !isTypingMode) {
                    event.preventDefault();
                    event.stopPropagation();
                    if (!this.onAnimation) {
                        if (this.currentView === 'ring') {
                            await this.fetchAndDisplayChatHistory();
                        } else if (this.currentView === 'document') {
                            this.switchToRingView();
                        }
                    }
                    return;
                }

                // console.log('ComRing: key detected: ' + event.key);
                if (!isTypingMode && event.code === this.triggerKey) {
                    this.state.keyPressed = true;
                    if (!this.state.isRecording) {
                        console.log('ComRing: Shortcut detected - starting recording');
                        this.startRecording();
                    }
                } else if (
                    !isTypingMode &&
                    !this.state.isRecording &&
                    !event.ctrlKey &&
                    // don't process control+v
                    ( !(event.key.toLowerCase() === 'v' && event.ctrlKey) ) &&
                    (
                        // process arrows
                        event.key == "ArrowUp" ||
                        event.key == "ArrowDown" ||
                        // process alphanumeric keys
                        ( event.key.length === 1 && /[a-zA-Z0-9/]/.test(event.key) )
                    )
                ) {
                    // console.log("EVENT KEYDOWN");
                    // Only handle the first keystroke to enter typing mode
                    console.log('ComRing: Entering typing mode');
                    await this.enterTypingMode();
                    // Send first key and trigger focus change
                    ipcRenderer.send('typing-key-pressed', event.key);
                    ipcRenderer.send('focus-chat-display');
                    // Prevent further key handling
                    event.preventDefault();
                }
            }
        });


        document.addEventListener('keyup', (event) => {
            // console.log("keyup");
            // If we were recording and the modifier key was released
            if (this.state.isRecording &&
                event.code === this.triggerKey) {
                console.log('ComRing: stopping recording');
                this.state.keyPressed = false;
                this.stopRecording();
            }
        });

        // Handle click outside
        document.addEventListener('click', (event) => {
            if (event.target === document.body && !this.state.isRecording) {
                console.log('ComRing: Escape pressed - hiding window');
                ipcRenderer.send('hide-window');
            }
        });

        document.addEventListener('paste', async (event) => {
            const isTypingMode = await ipcRenderer.invoke('get-typing-mode-state');
            if (!isTypingMode) {
                await this.enterTypingMode();
                let clipboardText = electron.clipboard.readText();
                ipcRenderer.send(
                    'typing-key-pressed',
                    clipboardText
                );
                ipcRenderer.send('focus-chat-display');
                event.preventDefault();
            }
        });

        console.log('ComRing: Event listeners initialized');
        console.log('ComRing: Sending ready confirmation to main process');
        ipcRenderer.send('com-ring-ready');
        ipcRenderer.send('comRing-ready');

        ipcRenderer.on('show-help', async () => {
            await this.showHelp();
        });
        ipcRenderer.on('show-about', async () => {
            await this.showAbout();
        });

        // Start polling for notifications every minute
        this.doingNotificationPolling = false;
        this.notificationPollingInterval =
            setInterval(this.notificationPolling, 60000);
    }

    updateIdleStatus() {
        const sttStatus = this.shadowRoot.querySelector('.stt-status');
        if (!sttStatus) return;

        // Check if busy with higher priority states
        // Note: isProcessingLLM is excluded so notifications can show while text streams (after thinking stops)
        const isBusy = this.state.isRecording ||
                       this.isShowingInfo ||
                       this.circle.classList.contains('loading') ||
                       this.circle.classList.contains('skill-active');

        if (isBusy)
            return;

        if (!this.config.get('ui.comringNotifications', false))
            return;
        if (this.notificationCount > 0) {
            ipcRenderer.send('notifications-available', true);
            sttStatus.textContent = `${this.notificationCount} notification${this.notificationCount > 1 ? 's' : ''}`;
            sttStatus.classList.remove('active2', 'active3', 'error');
            sttStatus.classList.add('notification');
        } else {
            ipcRenderer.send('notifications-available', false);
            sttStatus.classList.remove('notification');
            setTimeout(() => {
                sttStatus.textContent = '';
            }, 4000);
        }
    }

    async notificationPolling() {
        if (me.doingNotificationPolling) {
            // avoid re-entry
            return;
        }
        me.doingNotificationPolling = true;
        try {
            console.log(me.pybridgeEndpoints)
            const response = await fetch(me.pybridgeEndpoints.notifications);
            if (response.ok) {
                const data = await response.json();
                // // Send to main process to update tray
                // ipcRenderer.send('update-tray-icon', {
                //     hasNotifications: data.pending
                // });
                // Update local state and UI
                me.notificationCount = data.pending || 0;
                me.updateIdleStatus();
            }
        } catch (e) {
            console.error('Notification Error:', e);
            console.error(e.stack);
        }
        me.doingNotificationPolling = false;
    }


    async processUserMessage(message, typed = false) {
        console.log('processUserMessage:', message);
        if (!typed) {
            // Show user message in display window
            ipcRenderer.send('transcription-received', message);
        }
        try {
            if (message) {
                await this.processAIResponse(message);
                this.circle.classList.add('faded');
            }
        } catch (error) {
            await this.showInfo('LLM Processing Error in message "' + message + '": ' + error.message, true)
            ipcRenderer.send('llm-error', error.message);
        }
        this.state.isAwaitingResponse = false;
        this.circle.classList.remove('awaiting');
    }


    // [NEW] Helper to determine if we should review based on settings and confidence
    shouldReview(text, confidence) {
        const reviewSetting = this.config.get('stt.review', 'on');
        const threshold = this.config.get('stt.smart_send_threshold', 0.80);

        // Legacy boolean support
        if (reviewSetting === 'on')
            return true;
        if (reviewSetting === 'off')
            return false;
        // Smart mode ('auto')
        if (reviewSetting === 'auto') {
            // If we have no confidence data (e.g. OpenAI direct), default to review for safety
            if (confidence === undefined || confidence === null) return true;
            // If confidence is high, skip review
            if (confidence >= threshold) {
                console.log(`Smart Send: Confidence ${confidence.toFixed(2)} >= ${threshold}. Auto-sending.`);
                return false;
            }
            console.log(`Smart Send: Confidence ${confidence.toFixed(2)} < ${threshold}. Reviewing.`);
            return true;
        }

        return true; // Default safe fallback
    }

    setupTranscriptionHandler() {
        this.stt.onTranscriptionResult = async (result) => {
            // [MODIFIED] Handle both object (new) and string (legacy) formats
            let text = '';
            let confidence = undefined;

            if (typeof result === 'object' && result !== null) {
                text = result.text;
                confidence = result.confidence;
            } else if (typeof result === 'string') {
                text = result;
            }

            if (text) {
                if (this.shouldReview(text, confidence)) {
                    await this.enterTypingMode();
                    ipcRenderer.send('typing-key-pressed', text);
                    ipcRenderer.send('focus-chat-display');
                } else {
                    await this.processUserMessage(text);
                }
            }
        };
    }



    // NEW: Persistent Audio Stream Initialization
    // TODO Falla lógica ahora esto no se muestra en segunda grabación
    async initializeAudioStream() {
        try {
            if (this.mediaStream) return; // Already initialized

            console.log('ComRing: Initializing persistent audio stream...');
            this.mediaStream = await navigator.mediaDevices.getUserMedia({
                audio: {
                    channelCount: 1,
                    echoCancellation: true,
                    noiseSuppression: true,
                    autoGainControl: true
                }
            });

            this.audioContext = new AudioContext();
            this.analyser = this.audioContext.createAnalyser();
            this.analyser.fftSize = this.config.get('ring.fftSize', 256);

            const source = this.audioContext.createMediaStreamSource(this.mediaStream);
            source.connect(this.analyser);

            // Start Wake Word Processing
            if (this.wakeWordEnabled) {
                this.setupWakeWordProcessing(source);
            }

            // Start visualization loop (runs continuously for VAD)
            this.startVisualizationLoop();

        } catch (error) {
            console.error('Audio Initialization Error:', error);
            this.showInfo('Microphone access failed', true);
        }
    }

    // NEW: Wake Word WebSocket & Processing
    async setupWakeWordProcessing(source) {
        try {
            console.log(`WakeWord: Setting up processing. AudioContext SampleRate: ${this.audioContext.sampleRate}`);
        // Connect to WebSocket
        const wsUrl = this.pybridgeEndpoint.replace('http', 'ws') + '/wakeword';
        this.wakeWordSocket = new WebSocket(wsUrl);
        } catch (error) {
            console.error("Can't start WakeWord WebSocket!: " + error);
            return false;
        }

        this.wakeWordSocket.onopen = () => {
            console.log('WakeWord: WebSocket connected');
            this.isListeningForWakeWord = true;
            // this.circle.classList.add('listening');
            this.emitEvent('wakeword-active');
            ipcRenderer.send('wakeword-status', 'listening');
        };

        this.wakeWordSocket.onmessage = (event) => {
            const data = JSON.parse(event.data);
            // Strict check: Don't trigger if recording, processing, or awaiting response
            if (data.detected &&
                !this.state.isRecording &&
                !this.state.isProcessingLLM &&
                !this.state.isAwaitingResponse &&
                !this.wizardActive
            ) {

                console.log(`WakeWord: Detected (${data.score})`);
                this.triggerWakeWordActivation();
            } else if (data.detectd) {
                console.log(`WakeWord: Detected (${data.score}) but bad environment: wizardActive: ${this.wizardActive}`);
            }
        };

        this.wakeWordSocket.onclose = () => {
            console.log('WakeWord: WebSocket disconnected');
            this.isListeningForWakeWord = false;
            // this.circle.classList.remove('listening');
            this.emitEvent('wakeword-inactive');
        };

        // Audio Processing (Downsampling to 16kHz)
        // Note: ScriptProcessor is deprecated but widely supported.
        // For production, AudioWorklet is preferred but requires separate file loading.
        this.audioProcessor = this.audioContext.createScriptProcessor(4096, 1, 1);

        this.audioProcessor.onaudioprocess = (e) => {
            const inputData = e.inputBuffer.getChannelData(0);

            // Only send if we are listening (socket is open/intended)
            // We REMOVE the checks for isRecording/isProcessingLLM/isAwaitingResponse
            // to ensure continuous stream to server, preventing timeouts and buffer issues.
            if (!this.isListeningForWakeWord) {
                return;
            }

            const downsampled = this.downsampleBuffer(inputData, this.audioContext.sampleRate, 16000);

            if (this.wakeWordSocket && this.wakeWordSocket.readyState === WebSocket.OPEN) {
                this.wakeWordSocket.send(downsampled);
            }
        };

        source.connect(this.audioProcessor);
        this.audioProcessor.connect(this.audioContext.destination); // Necessary for the processor to run
    }

    // NEW: Downsampling Utility
    downsampleBuffer(buffer, sampleRate, outSampleRate) {
        if (outSampleRate === sampleRate) {
            return buffer;
        }
        if (outSampleRate > sampleRate) {
            throw new Error("Downsampling rate show be smaller than original sample rate");
        }
        const sampleRateRatio = sampleRate / outSampleRate;
        const newLength = Math.round(buffer.length / sampleRateRatio);
        const result = new Int16Array(newLength);
        let offsetResult = 0;
        let offsetBuffer = 0;
        while (offsetResult < result.length) {
            const nextOffsetBuffer = Math.round((offsetResult + 1) * sampleRateRatio);
            let accum = 0, count = 0;
            for (let i = offsetBuffer; i < nextOffsetBuffer && i < buffer.length; i++) {
                accum += buffer[i];
                count++;
            }
            // Convert float to 16-bit PCM
            let s = Math.max(-1, Math.min(1, accum / count));
            result[offsetResult] = s < 0 ? s * 0x8000 : s * 0x7FFF;
            offsetResult++;
            offsetBuffer = nextOffsetBuffer;
        }
        return result;
    }

    // NEW: Trigger Activation
    async triggerWakeWordActivation() {
        // 1. Visual Feedback
        this.circle.classList.add('recording'); // Pulse effect
        // 2. Audio Feedback (Generated Beep)
        this.playFeedbackSound();
        // 3. Show Window
        ipcRenderer.send('show-window');
        // 4. Start Recording
        await this.startRecording();
    }

    playFeedbackSound() {
        if (!this.audioContext) return;
        const oscillator = this.audioContext.createOscillator();
        const gainNode = this.audioContext.createGain();

        oscillator.connect(gainNode);
        gainNode.connect(this.audioContext.destination);

        oscillator.type = 'sine';
        oscillator.frequency.setValueAtTime(880, this.audioContext.currentTime); // A5
        oscillator.frequency.exponentialRampToValueAtTime(1760, this.audioContext.currentTime + 0.1); // A6

        gainNode.gain.setValueAtTime(0.1, this.audioContext.currentTime);
        gainNode.gain.exponentialRampToValueAtTime(0.01, this.audioContext.currentTime + 0.1);

        oscillator.start();
        oscillator.stop(this.audioContext.currentTime + 0.1);
    }

    // REFACTORED: Start Recording (Uses existing stream)
    async startRecording() {
        if (this.state.isRecording) return;

        // Ensure audio is initialized
        if (!this.mediaStream) {
            await this.initializeAudioStream();
        }

        ipcRenderer.send('ptt-start');
        ipcRenderer.send('wakeword-status', 'active'); // Update tray to purple

        this.ignoreIncomingEvents = false;
        this.state.isRecording = true;
        this.state.isAwaitingResponse = false;
        this.silenceStartTimestamp = null; // Reset VAD

        // this.circle.classList.remove('faded', 'listening');
        this.circle.classList.remove('faded');
        this.circle.classList.add('recording');
        this.innerCircle.style.opacity = 0;

        try {
            console.log('Starting MediaRecorder...');
            this.audioChunks = [];
            this.mediaRecorder = new MediaRecorder(this.mediaStream, { mimeType: 'audio/webm' });

            this.mediaRecorder.ondataavailable = (event) => {
                if (event.data.size > 0) {
                    this.audioChunks.push(event.data);
                }
            };

            this.mediaRecorder.onstop = async () => {
                console.log('MediaRecorder stopped, processing audio...');
                const audioBlob = new Blob(this.audioChunks, { type: 'audio/webm' });

                // Send to STT (Passive Mode)
                try {
                    const result = await this.stt.transcribe(audioBlob);

                    // [MODIFIED] Handle both object (new) and string (legacy) formats
                    let text = '';
                    let confidence = undefined;

                    if (typeof result === 'object' && result !== null) {
                        text = result.text;
                        confidence = result.confidence;
                    } else if (typeof result === 'string') {
                        text = result;
                    }

                    // Handle result via existing logic
                    if (text && text.trim()) {
                        if (this.shouldReview(text, confidence)) {
                            await this.enterTypingMode();
                            ipcRenderer.send('typing-key-pressed', text);
                            ipcRenderer.send('focus-chat-display');
                            // Reset awaiting state since we are now typing
                            this.state.isAwaitingResponse = false;
                            this.circle.classList.remove('awaiting');
                        } else {
                            await this.processUserMessage(text);
                        }
                    } else {
                        // Empty transcription - reset state
                        console.log('Empty transcription, resetting state');
                        this.state.isAwaitingResponse = false;
                        this.circle.classList.remove('awaiting');
                    }
                } catch (e) {
                    console.error('Transcription failed:', e);
                    this.showInfo('Transcription failed', true);
                    // Error - reset state
                    this.state.isAwaitingResponse = false;
                    this.circle.classList.remove('awaiting');
                }
            };

            this.mediaRecorder.start();

            // Visuals
            const ringContainer = this.shadowRoot.querySelector('.ring-container');
            ringContainer.style.setProperty('--border-color', 'rgba(255, 255, 255, 1)');
            ringContainer.classList.add('recording-active');

        } catch (error) {
            console.error('Recording Error:', error);
            this.stopRecording();
        }
    }

    async enterTypingMode() {
        this.ignoreIncomingEvents = false;
        this.text = "";
        // Set state in window
        await ipcRenderer.invoke('set-typing-mode-state', true);
        // Update UI
        this.circle.style.opacity = '0.4';
        ipcRenderer.send('enter-typing-mode');
    }

    async exitTypingMode() {
        this.text = "";
        // Set state in window
        await ipcRenderer.invoke('set-typing-mode-state', false);
        // Update UI
        this.circle.style.opacity = '1';
        // this.isWindowVisible = true;
        // console.log('exitTypingMode: isWindowVisible true');
        ipcRenderer.send('com-ring-focus');
    }

    // NEW: Helper to stop only the TTS output without killing input resources
    stopTTSPlayback() {
        if (this.currentAudio) {
            this.currentAudio.pause();
            this.currentAudio.src = '';
            this.currentAudio = null;
        }
    }

    // REFACTORED: Clean Audio (Don't kill context if Wake Word is on)
    cleanAudio() {
        if (this.keyCheckInterval) {
            clearInterval(this.keyCheckInterval);
            this.keyCheckInterval = null;
            console.log('Cleared key check interval');
        }

        // Clean up audio visualization
        if (this.animationFrame) {
            console.log('Canceling animation frame');
            cancelAnimationFrame(this.animationFrame);
            this.animationFrame = null;
        }

        // Clean up current audio
        this.stopTTSPlayback();

        // Only fully kill audio if we are destroying the component or disabling wake word
        if (!this.wakeWordEnabled) {
            // Cleanup analyser node
            if (this.analyser) {
                console.log('Cleaning up analyser node');
                this.analyser.disconnect();
                this.analyser = null;
            }

            // Enhanced MediaStream cleanup
            if (this.mediaStream) {
                console.log('MediaStream cleanup starting');
                try {
                    const tracks = this.mediaStream.getTracks();
                    console.log(`Found ${tracks.length} tracks to clean up`);

                    tracks.forEach((track, index) => {
                        console.log(`Track ${index}: kind=${track.kind}, state=${track.readyState}, enabled=${track.enabled}`);
                        track.stop();
                        console.log(`Track ${index} stopped, new state=${track.readyState}`);
                    });

                    this.mediaStream = null;
                    console.log('MediaStream cleanup completed');
                } catch (error) {
                    console.error('Error during MediaStream cleanup:', error);
                }
            }

            // Enhanced AudioContext cleanup
            if (this.audioContext) {
                console.log(`AudioContext cleanup starting (current state: ${this.audioContext.state})`);
                try {
                    this.audioContext.close().then(() => {
                        console.log('AudioContext closed successfully');
                    }).catch(error => {
                        console.error('Error closing AudioContext:', error);
                    });
                } catch (error) {
                    console.error('Error during AudioContext cleanup:', error);
                } finally {
                    this.audioContext = null;
                }
            }
        }
        // If Wake Word is enabled, we keep the stream/context alive!
    }


    // REFACTORED: Stop Recording
    stopRecording() {
        if (!this.state.isRecording) return;
        console.log('Stopping recording...');
        this.state.isRecording = false;
        ipcRenderer.send('ptt-stop');

        // Stop MediaRecorder
        if (this.mediaRecorder && this.mediaRecorder.state !== 'inactive') {
            this.mediaRecorder.stop();
        }

        // UI Updates
        const ringContainer = this.shadowRoot.querySelector('.ring-container');
        ringContainer.classList.remove('recording-active');
        this.circle.classList.remove('recording');
        this.circle.classList.add('awaiting');

        this.state.isAwaitingResponse = true;
        this.innerCircle.style.opacity = 0;

        // Resume Wake Word Listening state (if enabled)
        if (this.wakeWordEnabled) {
            // this.circle.classList.add('listening');
            ipcRenderer.send('wakeword-status', 'listening');
        } else {
            ipcRenderer.send('wakeword-status', 'inactive');
        }
    }

    // REFACTORED: Visualization & VAD Loop
    // TODO Not showing 2nd time
    startVisualizationLoop() {
        // Ensure we don't start multiple loops
        if (this.animationFrame) {
            cancelAnimationFrame(this.animationFrame);
        }

        const bufferLength = this.analyser.frequencyBinCount;
        const dataArray = new Uint8Array(bufferLength);

        const update = () => {
            // console.log("startVisualizationLoop 1")
            if (!this.analyser) {
                // Skip logic but run again
                this.animationFrame = requestAnimationFrame(update);
                return;
            }

            // console.log("startVisualizationLoop PROCESSING")

            this.analyser.getByteFrequencyData(dataArray);
            const average = dataArray.reduce((a, b) => a + b) / bufferLength;
            const volume = Math.pow(average / 255, 0.4); // Normalize 0-1

            // 1. Update Visuals
            if (this.state.isRecording) {
                const finalOpacity = volume < 0.4 ? 0 : Math.min(1, volume * 1.2);
                this.innerCircle.style.opacity = finalOpacity;
            }

            // 2. VAD Logic (Auto-stop on silence)
            if (this.state.isRecording && !this.state.keyPressed) {
                if (volume < this.vadThreshold) {
                    if (this.silenceStartTimestamp === null) {
                        this.silenceStartTimestamp = Date.now();
                    } else {
                        const silenceDuration = Date.now() - this.silenceStartTimestamp;
                        if (silenceDuration > this.maxSilenceDuration) {
                            console.log(`VAD: Silence detected (${silenceDuration}ms), stopping recording.`);
                            this.stopRecording();
                        }
                    }
                } else {
                    this.silenceStartTimestamp = null;
                }
            } else {
                this.silenceStartTimestamp = null;
            }

            this.animationFrame = requestAnimationFrame(update);
        };
        update();
    }


    updateVisualization(type, volume) {
        if (type === 'mic') {
            // User's microphone volume affects inner circle
            const finalOpacity = volume < 0.4 ? 0 : Math.min(1, volume * 1.2);
            this.innerCircle.style.opacity = finalOpacity;
        } else if (type === 'tts') {
            // TTS volume affects outer ring glow
            const ringCircle = this.shadowRoot.querySelector('.ring-circle');
            if (volume > 0.1) {  // Only show effect if volume is significant
                ringCircle.classList.add('tts-active');
            } else {
                ringCircle.classList.remove('tts-active');
            }
        }
    }

    async processAIResponse(userInput) {
        // Reset ignore flag when starting new request
        this.ignoreIncomingEvents = false;
        this.state.isProcessingLLM = true;
        try {
            const response = await fetch(this.pybridgeEndpoints.chat, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    message: userInput,
                    use_tts: true
                })
            });

            // Refresh notifications immediately as they were likely consumed by this request
            if (this.notificationCount > 0) {
                this.notificationPolling();
            }

            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';

            while (true) {
                // Check if processing was aborted
                if (!this.state.isProcessingLLM) {
                    reader.cancel();
                    break;
                }

                const {value, done} = await reader.read();
                if (done) break;

                buffer += decoder.decode(value, {stream: true});
                const lines = buffer.split('\n');
                buffer = lines.pop();

                for (const line of lines) {
                    if (line.trim()) {
                        const event = JSON.parse(line);
                        await this.handleEvent(event);
                    }
                }
            }
        } catch (error) {
            // await this.showError(event.content.message + " " + error);
            await this.showInfo(error, true);
            this.state.isProcessingLLM = false;
        } finally {
            this.state.isProcessingLLM = false;
            // this.window.focus();
        }
    }

    async showInfo(info, isError = false) {
        if (ERROR_WITH_CALL_TRACE) {
            let callstack = null;
            try {
                throw new Error('Stack Trace');
            } catch (e) {
                callstack = e.stack;
            }
            console.error('Info:', info, callstack);
        }
        if (isError) {
            ipcRenderer.send('chat-error', info.toString());
        }

        // Create error queue if it doesn't exist
        if (!this.infoQueue) {
            this.infoQueue = [];
            this.infoQueueIndex = 0;
            this.isShowingInfo = false;
        }

        // Add info to queue
        this.infoQueueIndex++;
        if (isError) {
            this.infoQueue.push(
                "Error #" +
                this.infoQueueIndex +
                ": " +
                info.toString()
            );
        } else {
            this.infoQueue.push(info.toString());
        }

        // Start processing the queue if not already doing so
        if (!this.isShowingInfo) {
            this.processInfoQueue();
        }
    }

    async processInfoQueue() {
        // If queue is empty or already showing an error, return
        if (this.infoQueue.length === 0 || this.isShowingInfo) {
            return;
        }

        // Set flag to indicate we're showing an error
        this.isShowingInfo = true;

        // Get the next error from the queue
        const infoMessage = this.infoQueue.shift();
        let isError = infoMessage.startsWith("Error #")

        // Show the info message/error
        const sttStatus = this.shadowRoot.querySelector('.stt-status');
        sttStatus.innerHTML = infoMessage;
        if (isError) {
            sttStatus.classList.add('active3');
        } else {
            sttStatus.classList.add('active2');
        }

        // Keep the message visible by refreshing it periodically
        const refreshInterval = 1000; // 1 second
        const totalDuration = 4000;   // 5 seconds total
        const refreshCount = Math.floor(totalDuration / refreshInterval);

        // Use a single interval instead of multiple timeouts
        let count = 0;
        const intervalId = setInterval(() => {
            count++;
            // Refresh the message
            const sttStatus = this.shadowRoot.querySelector('.stt-status');
            sttStatus.innerHTML = infoMessage;
            if (isError) {
                sttStatus.classList.add('active3');
            } else {
                sttStatus.classList.add('active2');
            }

            // If we've reached the desired duration, clean up
            if (count >= refreshCount) {
                clearInterval(intervalId);
                if (isError) {
                    sttStatus.classList.remove('active3');
                } else {
                    sttStatus.classList.remove('active2');
                }
                this.isShowingInfo = false;

                // Process next error in queue if any
                if (this.infoQueue.length > 0) {
                    setTimeout(() => this.processInfoQueue(), 100);
                } else {
                    this.updateIdleStatus();
                }
            }
        }, refreshInterval);
    }

    async showHelp() {
        const helpTitle = 'Help & Shortcuts';
// - **/refresh**: Refresh the frontend application.
        const helpContent = `
### Keyboard Shortcuts
- **${this.showKey}**: Show the UI interface (Also clicking on tray icon).
- **${this.triggerKey}**: Hold to record your voice.
- **Tab**: Toggle between Ring and Document Mode chat history view.
- **Escape**: Abort current action, hide Polaris, in document view exit view."
- **ArrowUp** / **ArrowDown**: Navigate command history in typing mode.
- **Control+v**: Paste clipboard content on input control.
- **Typing mode**: Type any letter/number key to bring up the text input control, press <Esc> to close it.
### Commands
- **/help**: Shows this help message.
- **/history**: View your chat history.
- **/documents**: Switch to the document view.
- **/provider**: Show the current LLM provider.
- **/memory**: Toggle conversation memory on.
- **/nomemory**: Toggle conversation memory off.
### Tips
- Click the tray icon (left button) to toggle visibility.
- You can switch to another application while typing in the input control and recover your edited text later with the arrow up key.
        `.trim().replace(/^\s+/gm, '');

        this.switchToDocumentView('help');
        this.documentView.clear();
        this.documentView.addDocument(helpContent, 'help', helpTitle);
    }

    async showAbout() {
        const helpTitle = 'About Ainara Polaris';
        const helpContent = `
### About Ainara Polaris v${this.config.get("setup.version")} (testing)
Copyright 2025 &copy; Rubén Gómez - https://khromalabs.org
Visit our project site at: https://ainara.app
        `.trim().replace(/^\s+/gm, '');

        this.switchToDocumentView('help');
        this.documentView.clear();
        this.documentView.addDocument(helpContent, 'help', helpTitle);
    }

    async fetchAndAppendNewChatMessages() {
        if (!this.lastMessageTimestamp) {
            console.log('No last message timestamp, skipping append.');
            return;
        }

        try {
            const url = `${this.pybridgeEndpoints.history}?since=${this.lastMessageTimestamp}`;
            const response = await fetch(url);

            if (!response.ok) {
                console.error(`Failed to fetch new messages: ${response.status}`);
                return;
            }

            const data = await response.json();

            if (data.error) {
                console.error('Error fetching new messages:', data.error);
                return;
            }

            const historyContent = data.history ? data.history.substring(data.history.indexOf('\n')).trim() : '';

            if (historyContent) {
                this.documentView.appendDocumentContent(historyContent, 'chat-history');
                this.lastMessageTimestamp = data.last_timestamp; // Update timestamp
            }
        } catch (error) {
            console.error('Error fetching new chat messages:', error);
        }
    }

    async fetchAndDisplayChatHistory(date = null, scrollBottom = true) {
        try {
            const sttStatus = this.shadowRoot.querySelector('.stt-status');
            sttStatus.textContent = 'Loading chat history...';
            sttStatus.classList.add('active');

            const url = date
                ? `${this.pybridgeEndpoints.history}?date=${date}`
                : this.pybridgeEndpoints.history;

            const response = await fetch(url);

            if (!response.ok) {
                throw new Error(`Failed to fetch history: ${response.status}, is memory enabled?`);
            }

            const data = await response.json();

            if (data.error) {
                throw new Error(data.error);
            }

            // Check if the history content exists beyond just a potential header
            const historyContent = data.history ? data.history.substring(data.history.indexOf('\n')).trim() : '';

            if (historyContent) {
                this.historyDate = data.date;
                this.lastMessageTimestamp = data.last_timestamp;
                this.switchToDocumentView('chat-history');
                this.documentView.clear();
                this.documentView.addDocument(
                    data.history,
                    'chat-history',
                    `Chat History: ${this.historyDate}`,
                    scrollBottom
                );
                this.documentView.updateNavControls({
                    prev: data.has_previous,
                    next: data.has_next
                });
                sttStatus.classList.remove('active');
                sttStatus.textContent = '';
                this.updateIdleStatus();
            } else {
                // If no history, just show a message and don't switch view
                sttStatus.textContent = 'No chat history for this day.';
                this.lastMessageTimestamp = null;
                setTimeout(() => {
                    sttStatus.classList.remove('active');
                    sttStatus.textContent = '';
                    this.updateIdleStatus();
                }, 4000);
            }
        } catch (error) {
            console.error('Error fetching chat history:', error);
            const sttStatus = this.shadowRoot.querySelector('.stt-status');
            sttStatus.textContent = `Error: ${error.message}`;
            sttStatus.classList.add('active', 'error');

            setTimeout(() => {
                sttStatus.classList.remove('active', 'error');
                sttStatus.textContent = '';
            }, 3000);
        }
    }


    async navigateHistory(direction) {
        if (this.navigatingHistory) {
            // prevent reentry
            return;
        }
        this.navigatingHistory = true;
        if (this.currentView != 'document') {
            this.navigatingHistory = false;
            return;
        }
        if (!this.historyDate) {
            this.navigatingHistory = false;
            return;
        }

        // The 'T12:00:00Z' avoids timezone-related date change issues
        const currentDate = new Date(`${this.historyDate}T12:00:00Z`);

        if (direction === 'prev') {
            currentDate.setUTCDate(currentDate.getUTCDate() - 1);
        } else {
            currentDate.setUTCDate(currentDate.getUTCDate() + 1);
        }

        const newDateStr = currentDate.toISOString().split('T')[0];
        await this.fetchAndDisplayChatHistory(newDateStr, false);
        this.navigatingHistory = false;
    }

    switchToDocumentView(format) {
        this.currentView = 'document';
        this.docFormat = format;
        if (format != 'chat-history') {
            // ensure we don't mix content windows with chat-history windows
            this.documentView.closeChatHistory();
        }
        ipcRenderer.send('set-view-mode', { view: 'document' });
        this.ringContainer.classList.add('document-view');
        this.documentView.show();
    }

    switchToRingView() {
        this.currentView = 'ring';
        this.ringContainer.classList.remove('document-view');
        ipcRenderer.send('set-view-mode', { view: 'ring', fixMouse: false });
        this.documentView.hide();
    }

    abortLLMResponse() {
        console.log('Aborting LLM response');

        // Set flag to ignore incoming events
        this.ignoreIncomingEvents = true;

        // Clear message queue
        this.messageQueue = [];
        this.isProcessingMessage = false;
        this.currentMessageId = null;

        // Clear all animation and audio tracking
        this.pendingAnimations.clear();

        // Resolve all pending animation promises to unblock any waiting code
        this.animationResolvers.forEach(resolver => resolver());
        this.animationResolvers.clear();

        // Clear all timeouts
        this.animationTimeouts.forEach(timeout => clearTimeout(timeout));
        this.animationTimeouts.clear();

        this.audioTimeouts.forEach(timeout => clearTimeout(timeout));
        this.audioTimeouts.clear();

        // Stop any playing audio
        if (this.currentAudio) {
            this.currentAudio.pause();
            this.currentAudio.src = '';
            this.currentAudio = null;
        }

        // // If in document view, switch back to ring view
        // if (this.currentView === 'document') {
        //     this.switchToRingView();
        // }

        // Reset visual states
        this.circle.classList.remove('loading', 'skill-active', 'awaiting');
        const ringContainer = this.shadowRoot.querySelector('.ring-container');
        ringContainer.classList.remove('loading');

        // Reset status message
        const sttStatus = this.shadowRoot.querySelector('.stt-status');
        sttStatus.classList.remove('active');
        sttStatus.textContent = '';

        // Reset state
        this.state.isProcessingLLM = false;
        this.state.isAwaitingResponse = false;

        // Notify chat-display about the abort
        ipcRenderer.send('llm-aborted');

        // Add brief "Aborted" feedback
        sttStatus.textContent = 'Aborted';
        sttStatus.classList.add('active');
        setTimeout(() => {
            sttStatus.classList.remove('active');
            sttStatus.textContent = '';
            this.updateIdleStatus();
        }, 1000);
    }


    // Process message queue - handle text and audio in parallel
    async processMessageQueue() {
        // Add diagnostic logging
        console.log(`Queue status: length=${this.messageQueue.length}, isProcessing=${this.isProcessingMessage}, ignoreEvents=${this.ignoreIncomingEvents}`);

        // If already processing a message or queue is empty, return
        if (this.isProcessingMessage || this.messageQueue.length === 0 || this.ignoreIncomingEvents) {
            return;
        }

        // Start processing the next message
        this.isProcessingMessage = true;
        const nextMessage = this.messageQueue.shift();
        const { event, audio, content, messageId } = nextMessage;

        try {
            console.log(`Processing message: ${messageId}`);
            this.currentMessageId = messageId;

            // Check if processing was aborted
            if (this.ignoreIncomingEvents) {
                throw new Error('Processing aborted');
            }

            // Create promises for both animation and audio
            const promises = [];

            // 1. Send message to chat display if not a skill
            if (!content.flags.skill && !this.ignoreIncomingEvents && this.isWindowVisible) {
                console.log(`Sending message to chat display: ${messageId}`);
                console.log(`isWindowVisible: ${this.isWindowVisible}`);

                // Create animation completion promise
                const animationPromise = new Promise((resolve) => {
                    // Store the message ID and its resolve function
                    this.animationResolvers.set(messageId, () => {
                        console.log(`Animation resolve function called for message: ${messageId}`);

                        // Clear the timeout when resolving
                        if (this.animationTimeouts.has(messageId)) {
                            clearTimeout(this.animationTimeouts.get(messageId));
                            this.animationTimeouts.delete(messageId);
                        }

                        // Call the original resolve
                        resolve();
                    });

                    // Add a timeout to prevent getting stuck
                    const timeout = setTimeout(() => {
                        console.warn(`Animation timeout for message ${messageId}`);
                        // Still resolve to continue processing
                        const resolver = this.animationResolvers.get(messageId);
                        if (resolver) {
                            resolver();
                            this.animationResolvers.delete(messageId);
                        }
                    }, 30000);

                    // Store timeout to clear it if animation completes
                    this.animationTimeouts.set(messageId, timeout);
                });

                // Send the message to chat display
                ipcRenderer.send('llm-stream', event);

                // Add animation promise to the list
                promises.push(animationPromise);
            } else {
                // console.log("send-notification event-------------------");
                // console.log("send-notification " + JSON.stringify(event));
                // console.log("send-notification content-------------------");
                // console.log("send-notification " + JSON.stringify(content));
                if (this.config.get("ui.backgroundNotifications", false)) {
                    ipcRenderer.send('send-notification', content.content);
                }
            }

            // 2. Start playing audio if available (in parallel with animation)
            if (audio && !this.ignoreIncomingEvents) {
                console.log(`Playing audio for: ${messageId}`);

                // Create audio completion promise
                const audioPromise = new Promise((resolve) => {
                    // Clean up previous audio
                    if (this.currentAudio) {
                        this.stopTTSPlayback();
                    }

                    // Set up audio completion handler
                    audio.onended = () => {
                        console.log(`Audio completed for: ${messageId}`);

                        // Clear the timeout when audio ends
                        if (this.audioTimeouts.has(messageId)) {
                            clearTimeout(this.audioTimeouts.get(messageId));
                            this.audioTimeouts.delete(messageId);
                        }

                        // Call resolve
                        resolve();
                    };

                    // Set up error handler
                    audio.onerror = (error) => {
                        console.error(`Audio error for message ${messageId}:`, error);

                        // Clear the timeout on error
                        if (this.audioTimeouts.has(messageId)) {
                            clearTimeout(this.audioTimeouts.get(messageId));
                            this.audioTimeouts.delete(messageId);
                        }

                        // Still resolve to continue processing
                        resolve();
                    };

                    // Calculate timeout based on audio duration if available
                    let timeoutDuration = 18100; // Default 15 seconds
                    if (nextMessage.audioDuration) {
                        // Add a buffer of 3 seconds to the actual duration
                        timeoutDuration = (nextMessage.audioDuration * 1000) + 3000;
                        console.log(`Setting timeout to ${timeoutDuration}ms based on audio duration of ${nextMessage.audioDuration}s`);
                    }

                    // Add a timeout in case audio never completes
                    const timeout = setTimeout(() => {
                        console.warn(`Audio timeout ${timeoutDuration} for message ${messageId}`);

                        // Force audio to stop if it's still playing
                        if (audio && !audio.paused) {
                            audio.pause();
                            audio.currentTime = 0;
                        }

                        resolve();
                    }, timeoutDuration);

                    // Store timeout to clear it if audio completes
                    this.audioTimeouts.set(messageId, timeout);

                    // Start playing the audio
                    this.currentAudio = audio;
                    audio.play().catch(error => {
                        console.error(`Error playing audio for message ${messageId}:`, error);

                        // Clear the timeout on play error
                        if (this.audioTimeouts.has(messageId)) {
                            clearTimeout(this.audioTimeouts.get(messageId));
                            this.audioTimeouts.delete(messageId);
                        }

                        resolve();
                    });
                });

                // Add audio promise to the list
                promises.push(audioPromise);
            }

            // Wait for both animation and audio to complete
            if (promises.length > 0) {
                console.log(`Starting to wait for ${promises.length} promises for message: ${messageId}`);
                promises.forEach((p, i) => {
                    p.then(() => console.log(`Promise ${i} resolved for message: ${messageId}`))
                     .catch(e => console.error(`Promise ${i} rejected for message: ${messageId}:`, e));
                });

                console.log(`Waiting for all processes to complete for message: ${messageId}`);
                try {
                    await Promise.all(promises);
                    console.log(`All processes completed for message: ${messageId}`);
                } catch (error) {
                    console.error(`Error in Promise.all for message ${messageId}:`, error);
                    // Continue processing even if there's an error
                }
            }

        } catch (error) {
            if (error.message === 'Processing aborted') {
                console.log('Message processing aborted:', messageId);
            } else {
                console.error('Error processing message:', error);
            }
        } finally {
            console.log(`Finishing processing for message: ${messageId}, queue length: ${this.messageQueue.length}`);

            // Ensure all timeouts are cleared
            if (this.animationTimeouts.has(messageId)) {
                clearTimeout(this.animationTimeouts.get(messageId));
                this.animationTimeouts.delete(messageId);
            }
            if (this.audioTimeouts.has(messageId)) {
                clearTimeout(this.audioTimeouts.get(messageId));
                this.audioTimeouts.delete(messageId);
            }

            // Ensure any remaining resolvers are removed
            if (this.animationResolvers.has(messageId)) {
                this.animationResolvers.delete(messageId);
            }

            // Reset processing state
            this.isProcessingMessage = false;
            this.currentMessageId = null;

            // Process next message if available and not aborted
            if (this.messageQueue.length > 0 && !this.ignoreIncomingEvents) {
                console.log(`Scheduling next message processing, queue length: ${this.messageQueue.length}`);
                setTimeout(() => this.processMessageQueue(), 10);
            } else {
                console.log(`No more messages to process or processing aborted. Queue length: ${this.messageQueue.length}, ignoreEvents: ${this.ignoreIncomingEvents}`);
            }
        }
    }

    async handleEvent(event) {
        // Ignore events if flag is set
        if (this.ignoreIncomingEvents) {
            console.log('Ignoring incoming events');
            return;
        }

        // console.log("\n--- EVENT ---\nevent: " + event.event + "\ntype:" + event.type + "\ncontent:"+ JSON.stringify(event.content));
        switch(event.event) {
            case 'stream':
                if (event.type === 'message') {
                    const content = event.content.content;
                    const messageId = `msg-${Date.now()}-${Math.floor(Math.random() * 1000)}`;

                    if (event.content && event.content.content) {
                        event.content.content.messageId = messageId;
                    }

                    if (content.flags.skill) {
                        // Check flag again before showing skill status
                        if (this.ignoreIncomingEvents) return;
                    }

                    // Add message ID to the event
                    if (event.content && event.content.content) {
                        event.content.content.messageId = messageId;
                    }

                    if (content.flags.audio && content.audio) {
                        const audioUrl = this.pybridgeEndpoint + content.audio.url;
                        try {
                            // Create audio but don't play it yet
                            const audio = new Audio();

                            // Add error handling for audio loading
                            audio.onerror = (error) => {
                                console.error(`Error loading audio from ${audioUrl}:`, error);
                            };

                            // Set source after adding error handler
                            audio.src = audioUrl;

                            // Set up audio analysis for TTS
                            const audioContext = new AudioContext();
                            const source = audioContext.createMediaElementSource(audio);
                            const analyser = audioContext.createAnalyser();
                            analyser.fftSize = 256;
                            source.connect(analyser);
                            source.connect(audioContext.destination);

                            const bufferLength = analyser.frequencyBinCount;
                            const dataArray = new Uint8Array(bufferLength);

                            const updateTTSVisualization = () => {
                                // Check flag before updating visualization
                                if (this.ignoreIncomingEvents) {
                                    audio.pause();
                                    this.updateVisualization('tts', 0);
                                    return;
                                }

                                analyser.getByteFrequencyData(dataArray);
                                const average = dataArray.reduce((a, b) => a + b) / bufferLength;
                                const volume = average / 255;
                                this.updateVisualization('tts', volume);

                                if (!audio.paused) {
                                    requestAnimationFrame(updateTTSVisualization);
                                } else {
                                    // Reset glow when audio ends
                                    this.updateVisualization('tts', 0);
                                }
                            };

                            // Add visualization listener
                            audio.addEventListener('play', () => {
                                updateTTSVisualization();
                            });

                            // Store the audio duration if available in the content
                            const audioDuration = content.flags.duration || null;

                            // console.log(JSON.stringify(content));

                            // Add to message queue with audio
                            this.messageQueue.push({
                                event,
                                audio,
                                content,
                                audioDuration,
                                messageId
                            });

                        } catch (error) {
                            console.error('ERROR creating audio:', error);

                            // Add to message queue without audio if there was an error
                            this.messageQueue.push({
                                event,
                                audio: null,  // No audio for this message
                                content,
                                messageId
                            });
                        }

                    } else {
                        // Add message to queue without audio
                        this.messageQueue.push({
                            event,
                            audio: null,
                            content,
                            messageId
                        });
                    }

                    // Try to process queue
                    this.processMessageQueue();
                }
                break;

            case 'thinking':
                if (event.type === 'signal') {
                    const sttStatus = this.shadowRoot.querySelector('.stt-status');
                    if (event.content.state === 'start') {
                        sttStatus.textContent = 'Reasoning...';
                        sttStatus.classList.add('active');
                    } else if (event.content.state === 'stop') {
                        sttStatus.classList.remove('active');
                        sttStatus.textContent = '';
                    }
                }
                break;

            case 'setMemoryState':
                if (event.type === 'ui') {
                    this.setMemoryState(event.content.enabled);
                }
                break;

            case 'command':
                if (event.type === 'signal') {
                    const command = event.content.name;
                    this.circle.classList.add('skill-active');
                    ipcRenderer.send('command-execution', command);
                }
                break;

            case 'loading':
                if (event.type === 'signal') {
                    const sttStatus = this.shadowRoot.querySelector('.stt-status');
                    if (event.content.state === 'start') {
                        this.circle.classList.add('loading');
                        // Also add loading state to container for border effect
                        const ringContainer = this.shadowRoot.querySelector('.ring-container');
                        ringContainer.classList.add('loading');
                        if (event.content?.type == "skill") {
                            sttStatus.innerHTML = 'Using Skill:<br><i>' + event.content.skill_id + '</i>';
                        } else {
                            if ( event.content.reasoning ) {
                                sttStatus.textContent = 'Reasoning...';
                            } else {
                                sttStatus.textContent = 'Thinking...';
                            }
                        }
                        sttStatus.classList.add('active');
                    } else if (event.content.state === 'stop') {
                        this.circle.classList.remove('loading');
                        const ringContainer = this.shadowRoot.querySelector('.ring-container');
                        ringContainer.classList.remove('loading');
                        // Hide the message
                        sttStatus.classList.remove('active');
                        sttStatus.textContent = '';
                    }
                }
                break;

            case 'completed':
                if (event.type === 'signal') {
                    this.circle.classList.remove('skill-active');
                    if (this.currentView === 'document' && this.docFormat === 'chat-history') {
                        await this.fetchAndAppendNewChatMessages();
                    }
                }
                break;

            case 'infoMessage':
                if (event.type === 'signal') {
                    await this.showInfo(event.content.message);
                }
                break;

            case 'error':
                if (event.type === 'signal') {
                    await this.showInfo(event.content.message, true);
                    ipcRenderer.send('chat-error', event.content.message);
                }
                break;

            case 'setView':
                if (event.type === 'ui' && event.content.view === 'document') {
                    // Only clear documents if we are starting a new document view session
                    // from the main ring. This allows accumulating documents.
                    if (this.currentView !== 'document') {
                        this.documentView.clear();
                    }
                    this.switchToDocumentView(event.content.format);
                }
                break;

            case 'renderNexus':
                if (event.type === 'ui') {
                    const orakleUrl = this.config.get('orakle.api_url');
                    if (!orakleUrl) {
                        this.showInfo('Orakle API URL not configured.', true);
                        return;
                    }
                    const fullUrl = orakleUrl + event.content.component_path;
                    const pathParts = event.content.component_path.split('/');
                    const componentName = pathParts[pathParts.length - 2];
                    this.switchToDocumentView('nexus');
                    console.log("EVENT")
                    console.log(JSON.stringify(event))
                    this.documentView.addDocument(
                        {
                            url: fullUrl,
                            data: event.content.data
                        },
                        'nexus',
                        componentName + "—" + event.content.query
                    );
                }
                break;

            case 'full':
                // console.log(JSON.stringify(event));
                if (event.type === 'content') {
                    if (this.currentView === 'document' &&
                        // avoid injecting new documents if chat-history is opened
                        this.docFormat != 'chat-history') {
                        const title =
                            event.content.title ||
                            this.docFormat.charAt(0).toUpperCase() + this.docFormat.slice(1);
                        this.documentView.addDocument(event.content.content, this.docFormat, title);
                    } else {
                        console.warn('Received full content but not in document view. Ignoring.');
                    }
                }
                break;
        }
    }
}

// Register the custom element
customElements.define('com-ring', ComRing);
