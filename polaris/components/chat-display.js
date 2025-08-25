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
        const { ipcRenderer } = require('electron');
        this.ipcRenderer = ipcRenderer;
        this.keydownHandler = null;
        this.inputHandler = this.autoResizeTextArea.bind(this);
        this.messageHistory = [];
        this.historyIndex = 0;
    }

    autoResizeTextArea() {
        const textarea = this.textInput;
        // const initialFontSize = '1.5em';
        // const smallerFontSize = '1.2em';
        const maxHeight = 200; // px

        // Reset height to correctly calculate scrollHeight for line counting
        textarea.style.height = 'auto';

        // TODO temporally disabled
        // const computedStyle = window.getComputedStyle(textarea);
        // const lineHeight = parseFloat(computedStyle.lineHeight);
        // scrollHeight includes padding, so we subtract it to get content height
        // const paddingTop = parseFloat(computedStyle.paddingTop);
        // const paddingBottom = parseFloat(computedStyle.paddingBottom);
        // const contentHeight = textarea.scrollHeight - paddingTop - paddingBottom;
        // const lines = Math.round(contentHeight / lineHeight);
        // // Adjust font size based on lines
        // if (lines > 2) {
        //     textarea.style.fontSize = smallerFontSize;
        // } else {
        //     textarea.style.fontSize = initialFontSize;
        // }

        // After potential font size change, recalculate final height
        textarea.style.height = 'auto';
        const finalScrollHeight = textarea.scrollHeight;

        if (finalScrollHeight > maxHeight) {
            textarea.style.height = `${maxHeight}px`;
            textarea.style.overflowY = 'auto';
        } else {
            textarea.style.height = `${finalScrollHeight}px`;
            textarea.style.overflowY = 'hidden';
        }
    }

    async enterTypingMode() {
        // Set state in window first
        await this.ipcRenderer.invoke('set-typing-mode-state', true);

        // Then update UI
        this.typingArea.style.opacity = '1';
        this.textInput.style.display = 'block';
        this.textInput.focus();
        this.container.style.marginBottom = '60px';

        this.textInput.addEventListener('input', this.inputHandler);
        this.autoResizeTextArea();

        this.keydownHandler = async (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                const text = this.textInput.value.trim();
                if (text) {
                    this.messageHistory.push(text);
                    this.historyIndex = this.messageHistory.length;
                    this.addMessage(text, 1, false);
                    console.log("SENDING process-typed-message");
                    ipcRenderer.send('process-typed-message', text);
                    this.textInput.value = '';
                    this.autoResizeTextArea();
                }
                this.exitTypingMode();
            } else if (e.key === 'Escape') {
                this.exitTypingMode();
            } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                if (this.historyIndex > 0) {
                    this.historyIndex--;
                    this.textInput.value = this.messageHistory[this.historyIndex];
                    this.textInput.selectionStart = this.textInput.selectionEnd = this.textInput.value.length;
                    this.autoResizeTextArea();
                }
            } else if (e.key === 'ArrowDown') {
                e.preventDefault();
                if (this.historyIndex < this.messageHistory.length) {
                    this.historyIndex++;
                    if (this.historyIndex < this.messageHistory.length) {
                        this.textInput.value = this.messageHistory[this.historyIndex];
                    } else {
                        this.textInput.value = '';
                    }
                    this.textInput.selectionStart = this.textInput.selectionEnd = this.textInput.value.length;
                    this.autoResizeTextArea();
                }
            }
        };

        this.textInput.addEventListener('keydown', this.keydownHandler);
    }

    async exitTypingMode() {
        if (this.keydownHandler) {
            this.textInput.removeEventListener('keydown', this.keydownHandler);
            this.keydownHandler = null;
        }
        this.textInput.removeEventListener('input', this.inputHandler);

        // Set state in window first
        await this.ipcRenderer.invoke('set-typing-mode-state', false);

        // Then update UI
        this.typingArea.style.opacity = '0';
        this.textInput.style.display = 'none';
        this.textInput.value = '';
        this.autoResizeTextArea();
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

                // Add listener for typing mode changes from window
                this.ipcRenderer.on('typing-mode-changed', async (event, isTypingMode) => {

                    // Update UI based on state from window
                    if (isTypingMode) {
                        this.typingArea.style.opacity = '1';
                        this.textInput.style.display = 'block';
                        this.container.style.marginBottom = '60px';
                    } else {
                        if (this.keydownHandler) {
                            this.textInput.removeEventListener('keydown', this.keydownHandler);
                            this.keydownHandler = null;
                        }
                        this.typingArea.style.opacity = '0';
                        this.textInput.style.display = 'none';
                        this.textInput.value = '';
                        this.container.style.marginBottom = '0';
                    }
                });

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
                                    // Pass the messageId from the event to addMessage
                                    const messageId = content.content.messageId;
                                    const messageElement = this.addMessage(
                                        textContent,
                                        content.content.flags.duration,
                                        true,
                                        messageId
                                    );
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

                ipcRenderer.on('hide', () => {
                    console.log('ChatDisplay: Saving message in history');
                    const text = this.textInput.value.trim();
                    if (text) {
                        console.log('ChatDisplay: Saving message in history');
                        this.messageHistory.push(text);
                        this.historyIndex = this.messageHistory.length;
                    }
                });

                ipcRenderer.on('typing-key-pressed', async (event, key) => {
                    console.log('ChatDisplay: Received typing key:', key);
                    if (!this.isTypingMode) {
                        await this.enterTypingMode();
                        if (key == "ArrowUp" || key == "ArrowDown") {
                            await this.keydownHandler({
                                key: key, preventDefault: () => {}
                            });
                        } else {
                            this.textInput.value = key;
                        }
                    } else {
                        this.textInput.value += key;
                    }
                    this.textInput.focus();
                });

                ipcRenderer.on('save-text', () => {
                });

                console.log('ChatDisplay: IPC listeners setup complete');
                ipcRenderer.send('chatDisplay-ready');

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

    addMessage(text, duration, isAI = false, messageId = null) {
        this.resetContainerProperties();

        const messageDiv = document.createElement('div');
        messageDiv.className = `message ${isAI ? 'ai' : 'user'}`;

        // Use provided messageId if available, otherwise generate one
        messageDiv.id = messageId || `msg-${Date.now()}-${Math.floor(Math.random() * 1000)}`;

        if (isAI) {
            // Parse markdown and split text into words and spaces
            const parsedText = this.parseMarkdown(text);
            const parts = parsedText.split(/(\s+)/);

            parts.forEach(part => {
                if (part.length === 0) return;

                if (part.match(/\s+/)) {
                    messageDiv.appendChild(document.createTextNode(part));
                } else {
                    // Create a span for the entire word
                    const wordSpan = document.createElement('span');
                    wordSpan.className = 'word';

                    // Check if this word contains HTML tags from markdown parsing
                    if (/<[^>]*>/g.test(part)) {
                        // Create a temporary container to parse HTML
                        const tempContainer = document.createElement('div');
                        tempContainer.innerHTML = part;

                        // Process each node in the parsed HTML
                        this.processNodesForAnimation(tempContainer, wordSpan);
                    } else {
                        // Regular word without formatting - add individual character spans
                        [...part].forEach(char => {
                            const span = document.createElement('span');
                            span.className = 'character';
                            span.textContent = char;
                            wordSpan.appendChild(span);
                        });
                    }

                    messageDiv.appendChild(wordSpan);
                }
            });
        } else {
            // For user messages, we can just render the markdown without animation
            messageDiv.innerHTML = this.parseMarkdown(text);
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

    processNodesForAnimation(container, targetElement) {
        // Process each child node
        Array.from(container.childNodes).forEach(node => {
            if (node.nodeType === Node.TEXT_NODE) {
                // Text node - add character spans
                [...node.textContent].forEach(char => {
                    const span = document.createElement('span');
                    span.className = 'character';
                    span.textContent = char;
                    targetElement.appendChild(span);
                });
            } else if (node.nodeType === Node.ELEMENT_NODE) {
                // Element node (like <strong>, <em>, etc.)
                const wrapper = document.createElement(node.tagName);

                // Copy all attributes
                Array.from(node.attributes).forEach(attr => {
                    wrapper.setAttribute(attr.name, attr.value);
                });

                // Process children of this element
                this.processNodesForAnimation(node, wrapper);

                // Add the element to the target
                targetElement.appendChild(wrapper);
            }
        });
    }

    async animateAIResponse(messageElement, duration) {
        if (!messageElement) return;

        const characters = messageElement.querySelectorAll('.character');
        const charDelay = duration / characters.length;

        // Emit animation start event
        ipcRenderer.send('animation-started', { messageId: messageElement.id });

        for (const char of characters) {
            const timeout = setTimeout(() => {
                char.classList.add('visible');
            }, charDelay * 1000);
            this.animationTimeouts.push(timeout);
            await new Promise(resolve => setTimeout(resolve, charDelay * 1000));
        }

        // Emit animation complete event
        ipcRenderer.send('animation-completed', { messageId: messageElement.id });
    }
}

customElements.define('chat-display', ChatDisplay);
