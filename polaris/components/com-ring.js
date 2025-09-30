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

class ComRing extends BaseComponent {
    constructor() {
        try {
            super();
            this.ignoreIncomingEvents = false;
            this.showInitialMessages = true;
            console.log('ComRing: Initializing constructor');
            this.config = new ConfigManager();
            this.text = null;
            this.memoryEnabled = null;

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
            };

            this.isWindowVisible = false;
            this.isProcessingUserMessage = false;
            this.keyCheckInterval = null;
            console.log('ComRing: Config manager initialized');
            this.currentView = 'ring';
            this.docFormat = 'text';

            this.state = {
                keyPressed: false,
                isRecording: false,
                isAwaitingResponse: false,
                isProcessingLLM: false,
                volume: this.config.get('ring.volume', 0)
            };
            console.log('ComRing: State initialized');
            this.historyDate = null;

            // Setup keyboard shortcut configuration
            this.triggerKey = this.config.get('shortcuts.trigger', 'Space');
            console.log('ComRing: Keyboard shortcuts initialized:', { trigger: this.triggerKey });

            this.stt = new WhisperSTT();
            console.log('ComRing: WhisperSTT initialized');

            this.llmClient = null;
            this.setupTranscriptionHandler();

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
                this.showInfo("Couldn't read Polaris configuration", true);
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
        });

        ipcRenderer.on('process-typed-message', async (event, message) => {
            if (this.isProcessingUserMessage) {
                console.log("process-typed-message: Avoiding concurrent entry");
                return;
            }
            this.isProcessingUserMessage = true;

            if (message.trim() === '/history') {
                console.log('Handling /history command');
                await this.fetchAndDisplayChatHistory();
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

        // Listen for history navigation events from the document-view component
        this.documentView.addEventListener('documentview-history-prev-clicked', () => this.navigateHistory('prev'));
        this.documentView.addEventListener('documentview-history-next-clicked', () => this.navigateHistory('next'));

        // Add event listeners for animation events
        ipcRenderer.on('animation-started', (event, data) => {
            console.log('Animation started:', data);
            this.pendingAnimations.set(data.messageId, true);
        });

        ipcRenderer.on('animation-completed', (event, data) => {
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
            if (this.currentView === 'document' && event.key === this.config.get('shortcuts.hide', 'Escape')) {
                console.log('Escape in document view: switching back to ring view.');
                this.switchToRingView();
                this.abortLLMResponse();
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
                    if (this.currentView === 'ring') {
                        if (this.documentView && this.documentView.shadowRoot.querySelector('.document-container').childElementCount > 0 && this.docFormat !== 'chat-history') {
                            this.switchToDocumentView(this.docFormat);
                        } else {
                            this.showInfo('No documents to display.');
                        }
                    } else if (this.currentView === 'document') {
                        this.switchToRingView();
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


    setupTranscriptionHandler() {
        this.stt.onTranscriptionResult = async (transcription) => {
            const reviewBeforeSend = this.config.get('stt.review', true);
            if (transcription) {
                if (reviewBeforeSend) {
                    await this.enterTypingMode();
                    ipcRenderer.send('typing-key-pressed', transcription);
                    ipcRenderer.send('focus-chat-display');
                } else {
                    await this.processUserMessage(transcription);
                }
            }
        };
    }



    async startRecording() {
        if (this.state.isRecording || !this.isWindowVisible) return;

        // // Force-sync memory state from config to fix color issue
        // const memoryEnabled = this.config.get('memory.enabled', false);
        // this.setMemoryState(memoryEnabled);

        this.ignoreIncomingEvents = false;
        this.state.isRecording = true;
        this.state.isAwaitingResponse = false;
        this.circle.classList.remove('faded');
        this.circle.classList.add('recording');
        this.innerCircle.style.opacity = 0; // Reset inner circle opacity


        try {
            // Setup audio visualization
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            this.mediaStream = stream;  // Store stream reference
            this.audioContext = new AudioContext();
            this.analyser = this.audioContext.createAnalyser();
            const source = this.audioContext.createMediaStreamSource(stream);
            source.connect(this.analyser);

            this.analyser.fftSize = this.config.get('ring.fftSize', 256);
            const bufferLength = this.analyser.frequencyBinCount;
            const dataArray = new Uint8Array(bufferLength);

            console.log('Audio setup complete:', {
                fftSize: this.analyser.fftSize,
                bufferLength,
                contextState: this.audioContext.state
            });

            // Start volume visualization
            const updateVolume = () => {
                if (!this.state.isRecording) {
                    console.log('Stopping volume visualization - not recording');
                    return;
                }

                this.analyser.getByteFrequencyData(dataArray);
                const average = dataArray.reduce((a, b) => a + b) / bufferLength;
                const volume = Math.pow(average / 255, 0.4);
                const finalOpacity = volume < 0.4 ? 0 : Math.min(1, volume * 1.2);

                // console.log('Volume update:', {
                //     average,
                //     volume,
                //     finalOpacity
                // });

                this.innerCircle.style.opacity = finalOpacity;
                this.animationFrame = requestAnimationFrame(updateVolume);
            };

            updateVolume();
            console.log('Volume visualization started');

            // Start recording
            try {
                console.log('Starting recording...');
                // Get the ring container element
                const ringContainer = this.shadowRoot.querySelector('.ring-container');
                ringContainer.style.setProperty('--border-color', 'rgba(255, 255, 255, 1)');
                ringContainer.classList.add('recording-active');
                this.currentRecording = this.stt.listen()

            } catch (error) {
                console.error('Recording Error:', error);
                this.state.isRecording = false;
                const sttStatus = this.shadowRoot.querySelector('.stt-status');
                sttStatus.textContent = 'Error: Could not start recording';
                sttStatus.classList.add('active', 'error');
                setTimeout(() => {
                    sttStatus.classList.remove('active', 'error');
                }, 2000);
            }

        } catch (error) {
            console.error('Recording Error:', error);
            this.isRecording = false;
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

        // Clean up current audio
        if (this.currentAudio) {
            this.currentAudio.pause();
            this.currentAudio.src = '';
            this.currentAudio = null;
        }
    }


    stopRecording() {
        if (!this.state.isRecording) return;

        // Stop the WhisperSTT recording first
        if (this.stt) {
            this.stt.stopRecording();
        }

        // Remove recording active state
        const ringContainer = this.shadowRoot.querySelector('.ring-container');
        ringContainer.classList.remove('recording-active');

        console.log('Stopping recording - starting cleanup process');

        this.cleanAudio();

        this.state.isRecording = false;
        this.state.isAwaitingResponse = true;
        this.circle.classList.remove('recording');
        this.circle.classList.add('awaiting');

        this.innerCircle.style.opacity = 0;
        console.log('Recording stopped and cleanup process completed');
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
                sttStatus.textContent = '';
                this.isShowingInfo = false;

                // Process next error in queue if any
                setTimeout(() => this.processInfoQueue(), 100);
            }
        }, refreshInterval);
    }

    async showHelp() {
        const helpTitle = 'Help & Shortcuts';
        const helpContent = `
### Keyboard Shortcuts
- **${this.triggerKey}**: Hold to record your voice.
- **Tab**: Switch between Ring and Document view.
- **Escape**: Abort current action or hide the window.
- **ArrowUp** / **ArrowDown**: Navigate command history in typing mode.
- **Control+v**: Paste clipboard content on input control.
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

    async fetchAndDisplayChatHistory(date = null) {
        try {
            const sttStatus = this.shadowRoot.querySelector('.stt-status');
            sttStatus.textContent = 'Loading chat history...';
            sttStatus.classList.add('active');

            const url = date
                ? `${this.pybridgeEndpoints.history}?date=${date}`
                : this.pybridgeEndpoints.history;

            const response = await fetch(url);

            if (!response.ok) {
                throw new Error(`Failed to fetch history: ${response.status}`);
            }

            const data = await response.json();

            if (data.error) {
                throw new Error(data.error);
            }

            // Check if the history content exists beyond just a potential header
            const historyContent = data.history ? data.history.substring(data.history.indexOf('\n')).trim() : '';

            if (historyContent) {
                this.historyDate = data.date;
                this.switchToDocumentView('chat-history');
                this.documentView.clear();
                this.documentView.addDocument(
                    data.history,
                    'chat-history',
                    `Chat History: ${this.historyDate}`
                );
                this.documentView.updateNavControls({
                    prev: data.has_previous,
                    next: data.has_next
                });
                sttStatus.classList.remove('active');
                sttStatus.textContent = '';
            } else {
                // If no history, just show a message and don't switch view
                sttStatus.textContent = 'No chat history for this day.';
                setTimeout(() => {
                    sttStatus.classList.remove('active');
                    sttStatus.textContent = '';
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


    navigateHistory(direction) {
        if (!this.historyDate) return;

        // The 'T12:00:00Z' avoids timezone-related date change issues
        const currentDate = new Date(`${this.historyDate}T12:00:00Z`);

        if (direction === 'prev') {
            currentDate.setUTCDate(currentDate.getUTCDate() - 1);
        } else {
            currentDate.setUTCDate(currentDate.getUTCDate() + 1);
        }

        const newDateStr = currentDate.toISOString().split('T')[0];
        this.fetchAndDisplayChatHistory(newDateStr);
    }

    switchToDocumentView(format) {
        this.currentView = 'document';
        this.docFormat = format;
        ipcRenderer.send('set-view-mode', { view: 'document' });
        this.ringContainer.classList.add('document-view');
        this.documentView.show();
    }

    switchToRingView() {
        this.currentView = 'ring';
        ipcRenderer.send('set-view-mode', { view: 'ring' });
        this.ringContainer.classList.remove('document-view');
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

        // If in document view, switch back to ring view
        if (this.currentView === 'document') {
            this.switchToRingView();
        }

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
                        this.cleanAudio();
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
                        // Show "Thinking..." message
                        if (event.content?.type == "skill") {
                            sttStatus.innerHTML = 'Using Skill:<br><i>' + event.content.skill_id + '</i>';
                        } else {
                            // console.log("!!!!!!" + JSON.stringify(event));
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
                    if (this.currentView === 'document') {
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
