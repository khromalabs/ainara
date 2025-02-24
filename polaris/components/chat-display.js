const BaseComponent = require('./base')
const electron = require('electron');

var ipcRenderer = electron.ipcRenderer;

class ChatDisplay extends BaseComponent {
    constructor() {
        super();
        this.messages = [];
        this.maxVisibleMessages = 5;
        this.messageTimeouts = [];
        this.animationTimeouts = [];
        this.isTypingMode = false;
        const { ipcRenderer } = require('electron');
        this.ipcRenderer = ipcRenderer;
        this.keydownHandler = null;
    }

    enterTypingMode() {
        this.isTypingMode = true;
        this.typingArea.style.opacity = '1';
        this.textInput.style.display = 'block';
        this.textInput.focus();
        this.container.style.marginBottom = '60px';

        this.keydownHandler = (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                const text = this.textInput.value.trim();
                if (text) {
                    this.addMessage(text, 1, false);
                    console.log("SENDING process-typed-message");
                    ipcRenderer.send('process-typed-message', text);
                    this.textInput.value = '';
                }
                this.exitTypingMode();
            } else if (e.key === 'Escape') {
                this.exitTypingMode();
            }
        };

        this.textInput.addEventListener('keydown', this.keydownHandler);
    }

    exitTypingMode() {
        if (this.keydownHandler) {
            this.textInput.removeEventListener('keydown', this.keydownHandler);
            this.keydownHandler = null;
        }

        this.isTypingMode = false;
        this.typingArea.style.opacity = '0';
        this.textInput.style.display = 'none';
        this.textInput.value = '';
        this.container.style.marginBottom = '0';
        ipcRenderer.send('exit-typing-mode');
    }

    cleanupState() {
        // Clear all timeouts
        if (this.messageTimeouts) {
            this.messageTimeouts.forEach(timeout => clearTimeout(timeout));
        }
        this.exitTypingMode();
        this.messageTimeouts = [];

        // Clear all animation timeouts
        if (this.animationTimeouts) {
            this.animationTimeouts.forEach(timeout => clearTimeout(timeout));
        }
        this.animationTimeouts = [];

        // Reset container
        if (this.container) {
            // Remove all messages
            while (this.container.firstChild) {
                this.container.removeChild(this.container.firstChild);
            }

            // Reset container styles
            this.resetContainerProperties();
        }

        // Reset message array
        this.messages = [];
    }

    async connectedCallback() {
        try {
            console.log('ChatDisplay: Component connecting...');
            const template = this.requireTemplate('chat-display-template');
            await this.loadStyles('./chat-display.css');

            this.shadowRoot.appendChild(template.content.cloneNode(true));
            this.container = this.shadowRoot.querySelector('.chat-container');
            this.typingArea = this.shadowRoot.querySelector('.typing-container');
            this.textInput = this.shadowRoot.querySelector('.typing-area');
            console.log('ChatDisplay: Container initialized:', !!this.container);


            // Add IPC listeners with error handling
            try {
                console.log('ChatDisplay: Attempting to require electron');
                const electron = require('electron');
                console.log('ChatDisplay: Electron required successfully');

                if (!electron.ipcRenderer) {
                    console.error('ChatDisplay: ipcRenderer not available in electron module!');
                    return;
                }

                const { ipcRenderer } = electron;
                console.log('ChatDisplay: Setting up IPC listeners');

                ipcRenderer.on('add-message', (event, text) => {
                    console.log('ChatDisplay: Received user message:', text);
                    this.addMessage(text, 1, false);
                    // messageElement.style.opacity = '1'
                });

                ipcRenderer.on('add-ai-message', (event, streamEvent) => {
                    console.log('ChatDisplay: Received stream event:', JSON.stringify(streamEvent));
                    try {
                        const eventData = typeof streamEvent === 'string' ?
                            JSON.parse(streamEvent) : streamEvent;

                        if (eventData.type === 'message' && eventData.event === 'stream') {
                            const content = eventData.content;

                            // Check if content exists and has actual text content
                            if (content && content.content) {
                                // Handle both string content and object content
                                const textContent = content.content.content;
                                if (textContent) {
                                    const messageElement = this.addMessage(textContent, content.content.flags.duration, true);
                                    this.animateAIResponse(messageElement, content.content.flags.duration);
                                }
                            }
                        }
                    } catch (error) {
                        console.error('ChatDisplay: Error processing stream event:', error);
                    }
                });

                ipcRenderer.on('chat-error', (event, error) => {
                    console.error('ChatDisplay: Error received:', error);
                    this.addMessage(`Error: ${error}`, 3, true);
                });

                ipcRenderer.on('llm-aborted', () => {
                    console.log('ChatDisplay: Received abort signal');
                    this.cleanupState();
                });

                ipcRenderer.on('reset-state', () => {
                    console.log('ChatDisplay: Resetting state');
                    this.cleanupState();
                    this.container.style.opacity = '1';
                });

                ipcRenderer.on('enter-typing-mode', () => {
                    console.log('ChatDisplay: Entering typing mode');
                    this.enterTypingMode();
                });

                ipcRenderer.on('exit-typing-mode', () => {
                    console.log('ChatDisplay: Exiting typing mode');
                    this.exitTypingMode();
                });

                ipcRenderer.on('typing-key-pressed', (event, key) => {
                    console.log('ChatDisplay: Received typing key:', key);
                    if (!this.isTypingMode) {
                        this.enterTypingMode();
                        this.textInput.value = key;
                    } else {
                        this.textInput.value += key;
                    }
                    this.textInput.focus();
                });

                console.log('ChatDisplay: IPC listeners setup complete');
            } catch (error) {
                console.error('ChatDisplay: Error setting up IPC:', error);
            }

            this.emitEvent('ready');
            console.log('ChatDisplay: Component ready');
        } catch (error) {
            this.showError(error);
            throw error;
        }
    }

    resetContainerProperties() {
        // Reset container properties
        this.container.style.display = 'flex';
        this.container.style.flexDirection = 'column';
        this.container.style.alignItems = 'flex-start';
        this.container.style.gap = '8px';
        this.container.style.width = '100%';

        // Clean up any existing messages that might be fading
        const fadingMessages = this.container.querySelectorAll('.message.fading');
        fadingMessages.forEach(msg => msg.remove());
    }

    addMessage(text, duration, isAI = false) {
        this.resetContainerProperties();

        const messageDiv = document.createElement('div');
        messageDiv.className = `message ${isAI ? 'ai' : 'user'}`;

        if (isAI) {
            // Split text into words and spaces
            const parts = text.split(/(\s+)/);
            parts.forEach(part => {
                if (part.length === 0) return;

                if (part.match(/\s+/)) {
                    messageDiv.appendChild(document.createTextNode(part));
                } else {
                    [...part].forEach(char => {
                        const span = document.createElement('span');
                        span.className = 'character';
                        span.textContent = char;
                        messageDiv.appendChild(span);
                    });
                }
            });
        } else {
            messageDiv.textContent = text;
        }

        this.container.appendChild(messageDiv);

        // Track timeouts
        const fadeTimeout = setTimeout(() => {
            messageDiv.classList.add('fading');
            const removeTimeout = setTimeout(() => {
                if (messageDiv.parentNode === this.container) {
                    messageDiv.remove();
                }
            }, 500);
            this.messageTimeouts.push(removeTimeout);
        }, (duration*1000)+1000);

        this.messageTimeouts.push(fadeTimeout);

        return messageDiv;
    }

    async animateAIResponse(messageElement, duration) {
        if (!messageElement) return;

        const characters = messageElement.querySelectorAll('.character');
        const charDelay = duration / characters.length;

        for (const char of characters) {
            const timeout = setTimeout(() => {
                char.classList.add('visible');
            }, charDelay * 1000);
            this.animationTimeouts.push(timeout);
            await new Promise(resolve => setTimeout(resolve, charDelay * 1000));
        }
    }
}

customElements.define('chat-display', ChatDisplay);
