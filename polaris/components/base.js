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

const { shell } = require('electron');

class BaseComponent extends HTMLElement {
    constructor() {
        super();
        this.attachShadow({ mode: 'open' });
        this.state = {};
        this._eventHandlers = new Map();

        // Open external links in the default browser
        this.delegate('click', 'a', (event, target) => {
            const href = target.getAttribute('href');
            if (href && (href.startsWith('http://') || href.startsWith('https://'))) {
                event.preventDefault();
                shell.openExternal(href);
            }
        });
    }

    // Utility methods
    assert(condition, message) {
        if (!condition) {
            throw new Error(`Fatal ${this.constructor.name} Error: ${message}`);
        }
        return condition;
    }

    async requireFetch(url) {
       console.log('Attempting to fetch:', url);
         try {
             const response = await fetch(url);
             console.log('Fetch response:', response.status, response.statusText);
             if (!response.ok) {
                 throw new Error(`Failed to fetch ${url}: ${response.status} ${response.statusText}`);
             }
             return response;
         } catch (error) {
             console.error('Fetch error details:', error);
             throw error;
         }
    }

    async loadStyles(cssPath) {
        const styleSheet = new CSSStyleSheet();
        const css = await (await this.requireFetch(cssPath)).text();
        styleSheet.replaceSync(css);
        this.shadowRoot.adoptedStyleSheets = [styleSheet];
        return styleSheet;
    }

    requireTemplate(templateId) {
        return this.assert(
            document.getElementById(templateId),
            `Template #${templateId} not found in document`
        );
    }

    // Error handling
    showError(error) {
        console.error(`${this.constructor.name} Stack:`, error.stack);
        this.emitEvent('error', { error: error.message });

        this.shadowRoot.innerHTML = `
            <div style="color: red; padding: 10px; border: 1px solid red; border-radius: 4px;">
                ${error.message}
            </div>
        `;
    }

    // Event handling
    emitEvent(eventName, detail = {}) {
        const fullEventName = `${this.constructor.name.toLowerCase()}-${eventName}`;
        this.dispatchEvent(new CustomEvent(fullEventName, {
            detail,
            bubbles: true,
            composed: true
        }));
    }

    delegate(eventName, selector, handler) {
        const wrappedHandler = (event) => {
            const target = event.target.closest(selector);
            if (target) {
                handler.call(this, event, target);
            }
        };

        this.shadowRoot.addEventListener(eventName, wrappedHandler);

        // Store for cleanup
        if (!this._eventHandlers.has(eventName)) {
            this._eventHandlers.set(eventName, new Map());
        }
        this._eventHandlers.get(eventName).set(selector, wrappedHandler);
    }

    // State management
    setState(newState) {
        const oldState = { ...this.state };
        this.state = { ...this.state, ...newState };

        this.stateChanged(this.state, oldState);
        this.render();

        this.emitEvent('state-changed', {
            newState: this.state,
            oldState
        });
    }

    // stateChanged(newState, oldState) {
    stateChanged() {
        // Override in child classes if needed
    }

    // Lifecycle methods
    disconnectedCallback() {
        // Clean up event listeners
        this._eventHandlers.forEach((handlersMap, eventName) => {
            handlersMap.forEach((handler) => {
                this.shadowRoot.removeEventListener(eventName, handler);
            });
        });
        this._eventHandlers.clear();

        this.cleanup();
    }

    cleanup() {
        // Override in child classes if needed
    }

    // Slot management
    getSlotContent(slotName) {
        const slot = this.shadowRoot.querySelector(`slot[name="${slotName}"]`);
        return slot?.assignedElements() || [];
    }

    // Template rendering - override in child classes
    render() {
        throw new Error('Component must implement render method');
    }

    parseMarkdown(text, generateLinks = false) {
        // Store code blocks temporarily
        const codeBlocks = [];
        let blockIndex = 0;

        text = text.replace(/_orakle_loading_signal_\|([^ \n]+)/gm, '<span class="orakle-skill" title="Orakle Skill">$1</span>');

        // Extract and replace triple backtick code blocks
        text = text.replace(/```([^ \n]+)([\s\S]*?)```/gm, (match, codetype, content) => {
            codeBlocks.push(`<div class="code-block-wrapper">
                <span class="code-type">${codetype}</span>
                <button class="copy-btn" onclick="navigator.clipboard.writeText(this.nextElementSibling.textContent)">Copy</button>
                <code>${content}</code>
            </div>`);
            return `%%CODEBLOCK${blockIndex++}%%`;
        });

        // Extract and replace single backtick inline code
        text = text.replace(/`([^ ]+)`/gm, (match, content) => {
            codeBlocks.push(`<code>${content}</code>`);
            return `%%CODEBLOCK${blockIndex++}%%`;
        });

        // Now apply your Markdown formatting safely
        text = text.replace(/\*\*(.*?)\*\*|__(.*?)__/gm, '<strong>$1$2</strong>');
        text = text.replace(/\*(.*?)\*|_(.*?)_/gm, '<em>$1$2</em>');
        text = text.replace(/^### (.*?)\n/gm, '<h3>$1</h3>');
        text = text.replace(/^## (.*?)\n/gm, '<h2>$1</h2>');
        text = text.replace(/^# (.*?)\n/gm, '<h1>$1</h1>');

        // Handle CR
        text = text.replace(/\n/gm, '<br>');

        // Handle links [text](url)
        text = text.replace(/\[(.*?)\]\((.*?)\)/gm, function(match, linkText, url) {
            // Extract domain from URL
            let domain = "";
            try {
                domain = new URL(url).hostname.replace(/^www\./, '');
                // Truncate if too long
                if (domain.length > 20) {
                    domain = domain.substring(0, 17) + '...';
                }
            } catch (e) {
                // If URL parsing fails, skip domain
                console.log("Error parsing: " + e);
            }

            // Create a properly formatted HTML string
            return '"' + linkText + '"' +
                   (domain ? ' [' + domain + ']' : '');
        });

        // Autolink URLs
        if (generateLinks) {
            const urlPattern = /((?:https?:\/\/|www\.)[^\s<>"']+)/g;
            text = text.replace(urlPattern, (url) => {
                let cleanUrl = url;
                // Strip trailing punctuation that is unlikely to be part of the URL
                while (/[.,;!?\)\]\}]$/.test(cleanUrl)) {
                    cleanUrl = cleanUrl.slice(0, -1);
                }
                const trailingChars = url.substring(cleanUrl.length);

                const href = cleanUrl.startsWith('www.') ? `http://${cleanUrl}` : cleanUrl;
                return `<a href="${href}">${cleanUrl}</a>` + trailingChars;
            });
        } else {
            text = text.replace(/\[(.*?)\]\((.*?)\)/g, function(match, linkText, url) {
                // Extract domain from URL
                let domain = "";
                try {
                    domain = new URL(url).hostname.replace(/^www\./, '');
                    // Truncate if too long
                    if (domain.length > 15) {
                        domain = domain.substring(0, 12) + '...';
                    }
                } catch (e) {
                    // If URL parsing fails, skip domain
                    console.log("Error parsing: " + e);
                }

                // Create a properly formatted HTML string
                return '"' + linkText + '"' +
                       (domain ? ' [' + domain + ']' : '');
            });
        }

        // Restore code blocks
        text = text.replace(/%%CODEBLOCK(\d+)%%/g, (match, index) => {
            return codeBlocks[parseInt(index)];
        });

        // console.log("parseMarkdown post:" + text);
        return text;
    }
}

module.exports = BaseComponent;
