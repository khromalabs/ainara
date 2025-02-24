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
const ConfigManager = require('../utils/config');
const BaseComponent = require('./base');
const electron = require('electron');

var ipcRenderer = electron.ipcRenderer;
console.log('com-ring.js loaded');

class ComRing extends BaseComponent {
    constructor() {
        try {
            super();
            this.ignoreIncomingEvents = false;
            console.log('ComRing: Initializing constructor');
            this.config = new ConfigManager();
            this.isTypingMode = false;
            this.text = null;

            // Get pybridge API endpoint from config
            this.pybridgeEndpoint = this.config.get('pybridge.api_url', 'http://localhost:5001');
            this.pybridgeEndpoints = {
                chat: `${this.pybridgeEndpoint}/framework/chat`,
            };

            this.isWindowVisible = false;
            this.isProcessingUserMessage = false;
            this.keyCheckInterval = null;
            console.log('ComRing: Config manager initialized');
            this.state = {
                keyPressed: false,
                isRecording: false,
                isAwaitingResponse: false,
                isProcessingLLM: false,
                volume: this.config.get('ring.volume', 0)
            };
            console.log('ComRing: State initialized');

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


    async connectedCallback() {
        try {
            console.log('ComRing: connectedCallback started');
            // Component is added to the DOM
            this.dispatchEvent(new CustomEvent('com-ring-connected'));
            console.log('ComRing: connected event dispatched');

            console.log('ComRing: Initializing STT');
            // Initialize STT
            await this.stt.initialize();
            console.log('ComRing: STT initialized');

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

            this.audioContext = null;
            this.mediaStream = null;
            this.analyser = null;
            this.animationFrame = null;

            this.initializeEventListeners();
            this.emitEvent('ready');

        } catch (error) {
            this.showError(error);
            throw error;
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
        ipcRenderer.on('window-show', () => {
            console.log('ComRing: Received window-show event');
            this.isWindowVisible = true;
        });

        ipcRenderer.on('window-hide', () => {
            console.log('ComRing: Received window-hide event');
            this.isWindowVisible = false;
            if (this.state.isRecording) {
                console.log('Window hidden while recording - stopping recording');
                this.stopRecording();
            }

            if (this.state.isProcessingLLM) {
                this.abortLLMResponse();
                this.cleanAudio();
                this.state.isAwaitingResponse = false;
            }
        });

        ipcRenderer.on('process-typed-message', async (event, message) => {
            if (!this.isProcessingUserMessage) {
                this.isProcessingUserMessage = true;
                await this.processUserMessage(message, true);
                this.isProcessingUserMessage = false;
            } else {
                console.log("process-typed-message: Avoiding concurrent entry");
            }
        });

        ipcRenderer.on('exit-typing-mode', () => {
            console.log("RECEIVED COMRING EXIT TYPING MODE");
            this.exitTypingMode();
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
        document.addEventListener('keydown', (event) => {
            // console.log("EVENT KEYDOWN");
            if (this.isWindowVisible) {
                if (!this.isTypingMode && event.code === this.triggerKey) {
                    this.state.keyPressed = true;
                    if (!this.state.isRecording) {
                        console.log('ComRing: Shortcut detected - starting recording');
                        this.startRecording();
                    }
                } else if (
                    !this.state.isRecording &&
                    event.key.length === 1 &&
                    /[a-zA-Z0-9]/.test(event.key)
                ) {
                    // Only handle the first keystroke to enter typing mode
                    console.log('ComRing: Entering typing mode');
                    this.enterTypingMode();
                    // Send first key and trigger focus change
                    ipcRenderer.send('typing-key-pressed', event.key);
                    ipcRenderer.send('focus-chat-display');
                    // Prevent further key handling
                    event.preventDefault();
                }
            }
            if (event.key === 'Escape') {
                console.log("EVENT ESCAPE");
                if (this.state.isProcessingLLM) {
                    console.log('Aborting LLM response');
                    this.abortLLMResponse();
                } else {
                    console.log("Escape triggers hide-window-all");
                    ipcRenderer.send('hide-window-all');
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

        console.log('ComRing: Event listeners initialized');
        console.log('ComRing: Sending ready confirmation to main process');
        ipcRenderer.send('com-ring-ready');
    }


    async processUserMessage(message, typed = false) {
        console.log('processUserMessage:', message);
        if (!typed) {
            // Show user message in display window
            ipcRenderer.send('transcription-received', message);
        }
        try {
            await this.processAIResponse(message);
            this.circle.classList.add('faded');
        } catch (error) {
            console.error('LLM Processing Error:', error);
            ipcRenderer.send('llm-error', error.message);
            this.circle.classList.add('error');
        }
        this.state.isAwaitingResponse = false;
        this.circle.classList.remove('awaiting');
    }


    setupTranscriptionHandler() {
        this.stt.onTranscriptionResult = async (transcription) => {
            if (transcription) {
                await this.processUserMessage(transcription);
            }
        };
    }


    async startRecording() {
        if (this.state.isRecording || !this.isWindowVisible) return;

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


    enterTypingMode() {
        this.text = "";
        this.isTypingMode = true;
        this.circle.style.opacity = '0.4';
        ipcRenderer.send('enter-typing-mode');
    }

    exitTypingMode() {
        this.text = "";
        this.isTypingMode = false;
        this.circle.style.opacity = '1';
        this.isWindowVisible = true;
        this.window.focus();
        // ipcRenderer.send('exit-typing-mode');
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
            this.showError(event.content.message + " " + error);
            this.state.isProcessingLLM = false;
        } finally {
            this.state.isProcessingLLM = false;
            this.window.focus();
        }
    }

    showError(error) {
        console.error('Error:', error);
        this.circle.classList.add('error');
        ipcRenderer.send('chat-error', error.toString());

        // Remove error state after a delay
        setTimeout(() => {
            this.circle.classList.remove('error');
        }, 3000);
    }


    abortLLMResponse() {
        // Set flag to ignore incoming events
        this.ignoreIncomingEvents = true;

        // Stop any playing audio
        if (this.currentAudio) {
            this.currentAudio.pause();
            this.currentAudio.src = '';
            this.currentAudio = null;
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


    async handleEvent(event) {
        // Ignore events if flag is set
        if (this.ignoreIncomingEvents) {
            console.log('Ignoring event due to abort:', event);
            return;
        }

        console.log("\n--- EVENT ---\nevent: " + event.event + "\ntype:" + event.type + "\ncontent:"+ JSON.stringify(event.content));
        switch(event.event) {
            case 'stream':
                if (event.type === 'message') {
                    const content = event.content.content;
                    if (content.flags.skill) {
                        // Check flag again before showing skill status
                        if (this.ignoreIncomingEvents) return;

                        // Show skill request message in status
                        const sttStatus = this.shadowRoot.querySelector('.stt-status');
                        // Add loading state to both status and ring
                        sttStatus.textContent = `${content.content}`;
                        sttStatus.classList.add('active');

                        // Remove after 3 seconds
                        setTimeout(() => {
                            if (!this.ignoreIncomingEvents) {  // Check flag before removing
                                sttStatus.classList.remove('active');
                                sttStatus.textContent = '';
                            }
                        }, 3000);
                    }
                    if (content.flags.audio && content.audio) {
                        const audioUrl = this.pybridgeEndpoint + content.audio.url;
                        try {
                            const audio = new Audio(audioUrl);

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

                            // Wait for previous audio to finish if any
                            if (this.currentAudio) {
                                if (!this.currentAudio.paused && !this.currentAudio.ended) {
                                    try {
                                        await Promise.race([
                                            new Promise(resolve => {
                                                this.currentAudio.addEventListener('ended', resolve, { once: true });
                                            }),
                                            new Promise(resolve => setTimeout(resolve, 10000))
                                        ]);
                                    } catch (error) {
                                        console.error('Error waiting for audio to finish:', error);
                                    }
                                }
                                this.cleanAudio();
                            }

                            // Check flag one final time before playing
                            if (this.ignoreIncomingEvents) return;

                            // Store current audio and play it
                            this.currentAudio = audio;
                            audio.addEventListener('play', () => {
                                if (!content.flags.skill && !this.ignoreIncomingEvents) {
                                    ipcRenderer.send('llm-stream', event);
                                }
                                updateTTSVisualization();
                            });
                            await audio.play();

                        } catch (error) {
                            console.error('ERROR playing audio:', error);
                            // console.log('Audio element state:', {
                            //     readyState: audio?.readyState,
                            //     paused: audio?.paused,
                            //     src: audio?.src
                            // });
                        }
                    }
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
                        sttStatus.textContent = 'Thinking...';
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

            case 'error':
                if (event.type === 'signal') {
                    this.showError(event.content.message);
                    ipcRenderer.send('chat-error', event.content.message);
                }
                break;
        }
    }
}

// Register the custom element
customElements.define('com-ring', ComRing);
