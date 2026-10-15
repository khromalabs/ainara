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
        // In-progress draft stashed when ArrowUp leaves the end of the
        // history, restored when ArrowDown returns there (#19): an accidental
        // ArrowUp while editing a long message must never destroy it.
        this.stashedDraft = null;
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

    // Add paste event listener for proper resize handling
    pasteHandler = () => {
        // Use setTimeout to ensure the value is updated before resizing
        setTimeout(() => this.autoResizeTextArea(), 1);
    };

    async enterTypingMode() {
        // Set state in window first
        await this.ipcRenderer.invoke('set-typing-mode-state', true);

        // Then update UI
        this.typingArea.style.opacity = '1';
        this.textInput.style.display = 'block';
        this.textInput.focus();
        this.container.style.marginBottom = '60px';

        this.textInput.addEventListener('input', this.inputHandler);
        this.textInput.addEventListener('paste', this.pasteHandler);
        this.autoResizeTextArea();


        this.keydownHandler = async (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                const text = this.textInput.value.trim();
                if (text) {
                    this.messageHistory.push(text);
                    this.historyIndex = this.messageHistory.length;
                    this.stashedDraft = null; // draft became a history entry
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
                    // Leaving the draft position (end of history): stash the
                    // message being edited so it can be restored with
                    // ArrowDown. Never overwrite the stash with the draft
                    // currently restored from it, so an accidental edit +
                    // ArrowUp cannot destroy the original either.
                    if (this.historyIndex === this.messageHistory.length &&
                        this.textInput.value &&
                        this.textInput.value !== this.stashedDraft) {
                        this.stashedDraft = this.textInput.value;
                    }
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
                        // Back at the draft position: restore the message
                        // that was being edited when ArrowUp was pressed.
                        this.textInput.value = this.stashedDraft !== null ? this.stashedDraft : '';
                    }
                    this.textInput.selectionStart = this.textInput.selectionEnd = this.textInput.value.length;
                    this.autoResizeTextArea();
                } else if (this.stashedDraft !== null && !this.textInput.value) {
                    // Already at the draft position with an emptied box:
                    // ArrowDown brings the draft back.
                    this.textInput.value = this.stashedDraft;
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
        this.textInput.removeEventListener('paste', this.inputHandler);

        // Set state in window first
        await this.ipcRenderer.invoke('set-typing-mode-state', false);

        // Then update UI
        this.typingArea.style.opacity = '0';
        this.textInput.style.display = 'none';
        this.textInput.value = '';
        // Exiting typing mode is either an explicit send (draft became a
        // history entry) or an explicit discard (Escape): the stash is not
        // meant to survive either.
        this.stashedDraft = null;
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
                                const textContent = this.sanitizeText(
                                    content.content.content
                                );
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

                ipcRenderer.on('focus-pending-input', () => {
                    // Deferred-restore focus (#19): background work landed
                    // while the app was hidden and the user returned with a
                    // review decision pending (typing mode).
                    this.textInput.focus();
                });

                ipcRenderer.on('hide', () => {
                    console.log('ChatDisplay: Saving message in history');
                    const text = this.textInput.value.trim();
                    // Push only genuinely new drafts: an unmodified recalled
                    // entry (value === history[historyIndex]) or a value
                    // identical to the last pushed one must not create
                    // phantom duplicates in the history (#19).
                    if (text &&
                        text !== this.messageHistory[this.historyIndex] &&
                        text !== this.messageHistory[this.messageHistory.length - 1]) {
                        console.log('ChatDisplay: Saving message in history');
                        this.messageHistory.push(text);
                        // #19 item 7: let the ring flash the recovery hint
                        // when the UI comes back. Gate lives main-side
                        // (ui.educationalHints) so educative reminders are
                        // disabled in one place. Only when something new was
                        // actually stashed.
                        ipcRenderer.send('draft-stashed');
                    }
                    // The draft lives in history now: start the next session
                    // with a clean box, anchored at the end, and no stash.
                    this.historyIndex = this.messageHistory.length;
                    this.stashedDraft = null;
                    this.textInput.value = '';
                    this.autoResizeTextArea();
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
                            // Injected text (transcription or first keystroke)
                            // is a fresh draft at the end of the history:
                            // re-anchor the navigation index so ArrowUp stashes
                            // it instead of navigating from a stale position.
                            // Only for text: arrow keys must keep the position
                            // the navigation just moved to (#19).
                            this.historyIndex = this.messageHistory.length;
                        }
                    } else {
                        this.textInput.value += key;
                        this.historyIndex = this.messageHistory.length;
                    }
                    this.autoResizeTextArea();
                    this.textInput.focus();
                });

                ipcRenderer.on('save-text', () => {
                });

                // Keyboard focus recovery (#19): a click on this surface (including
                // one that passes through the transparent ComRing above it) blurs
                // the textarea while the window keeps OS focus, leaving the app
                // with no focused editable element - every key dead until an
                // external blur resets everything.
                //
                // The listener must live on the shadowRoot, NOT on document:
                // events retargeted across the shadow boundary arrive with
                // e.target = the custom element host, so a document-level
                // guard can never match the inner textarea (or .message),
                // and preventDefault() fired on every click, killing caret
                // placement for mouse-based text correction entirely.
                this.shadowRoot.addEventListener('mousedown', (e) => {
                    if (this.textInput.style.display !== 'block') return;
                    // Let clicks on rendered messages behave normally (text selection)
                    if (e.target.closest && e.target.closest('.message')) return;
                    if (e.target !== this.textInput) {
                        // Keep the textarea focused
                        e.preventDefault();
                    }
                });
                document.addEventListener('keydown', (e) => {
                    // Escape exits typing mode even when the textarea lost focus
                    // (its own keydown handler covers the focused case).
                    // Use composedPath()[0] for the real target: e.target is
                    // retargeted to the host for events from the shadow DOM.
                    const realTarget = e.composedPath ? e.composedPath()[0] : e.target;
                    if (e.key === 'Escape' && realTarget !== this.textInput &&
                        this.textInput.style.display === 'block') {
                        this.exitTypingMode();
                    }
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
