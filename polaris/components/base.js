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
const { marked } = require('marked');
const DOMPurify = require('dompurify');
const Tablesort = require('tablesort');


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

        // TODO Replace local markdown processing with marked
        // // Configure marked
        // marked.setOptions({
        //     gfm: true,
        //     breaks: true,
        // });
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

    renderSortableTable(markdownTable) {
        const html = marked.parse(markdownTable);
        const tempDiv = document.createElement('div');
        tempDiv.innerHTML = html;
        const table = tempDiv.querySelector('table');
        if (!table) return '<p>No table found in markdown.</p>';

        // Mark this as a sortable table and add data-sort to headers
        table.classList.add('sortable-table');
        const headers = table.querySelectorAll('th');
        headers.forEach((th, index) => {
            th.setAttribute('data-sort', `col-${index}`);
            th.classList.add('sortable-header'); // For styling/click targeting
        });

        // Add zebra classes
        const rows = table.querySelectorAll('tbody tr, tr:not(:first-child)');
        rows.forEach((row, index) => {
            if (index % 2 === 0) row.classList.add('zebra-even');
            else row.classList.add('zebra-odd');
        });

        // Return enhanced HTML ready for later JS initialization
        return table.outerHTML;
    }

    // Initialize all sortable tables once DOM is ready
    initAllSortableTables() {
        // Find all shadow roots and search inside them
        const allShadowHosts = document.querySelectorAll('*');
        let totalTables = 0;

        allShadowHosts.forEach(host => {
            if (host.shadowRoot) {
                const tables = host.shadowRoot.querySelectorAll('.sortable-table');
                console.log(`Found ${tables.length} tables in shadow root of`, host);
                totalTables += tables.length;

                tables.forEach(table => {
                    if (!table._tablesortInitialized) {
                        new Tablesort(table, { asc: '▲', desc: '▼' });
                    }
                });
            }
        });

        console.log(`Total tables initialized: ${totalTables}`);
    }

    parseMarkdown(text, generateLinks = false) {
        // Store code blocks temporarily
        const codeBlocks = [];
        let blockIndex = 0;

        // Sanitize HTML to prevent XSS attacks
        text = this.sanitizeText(text);

        // Blocks extracted to prevent markdown parsing on them
        // Extract ORAKLE skills blocks
        text = text.replace(/_orakle_loading_signal_\|([^ \n]+)/gm, (text,skill) => {
            codeBlocks.push(`<span class="orakle-skill" title="Orakle Skill">${skill}</span>`);
            return `%%CODEBLOCK${blockIndex++}%%`;
        });

        if (generateLinks) {
            text = text.replace(/```([^ \n]*)([\s\S]*?)```/gm, (match, codetype, content) => {
                // if (this.isMarkdownTable(content)) {
                // TODO Disabled markdown table process by now
                if (0) { // eslint-disable-line no-constant-condition
                    let html_content = this.renderSortableTable(content);
                    codeBlocks.push(`<div class="code-block-wrapper">
                    <span class="code-type">markdown2html</span>
                    <button class="copy-btn" onclick="navigator.clipboard.writeText(this.nextElementSibling.textContent)">Copy</button>
                    <div>${html_content}</div>
                </div>`);
                } else {
                    codeBlocks.push(`<div class="code-block-wrapper">
                    <span class="code-type">${codetype}</span>
                    <button class="copy-btn" onclick="navigator.clipboard.writeText(this.nextElementSibling.textContent)">Copy</button>
                    <code>${content}</code>
                </div>`);
                    return `%%CODEBLOCK${blockIndex++}%%`;
                }
            });
            // Extract and replace single backtick inline code
            text = text.replace(/`([\s\S]*?)`/gm, (match, content) => {
                codeBlocks.push(`<div class="code-block-wrapper-inline">
                    <code>${content}</code>
                </div>`);
                return `%%CODEBLOCK${blockIndex++}%%`;
            });
        }

        // Extract and replace triple backtick code blocks
        // Define patterns as an array of [regex, replacement] pairs
        const markdownPatterns = [
            [/\*\*(.*?)\*\*|__(.*?)__/gm, '<strong>$1$2</strong>'], // Bold
            [/\*(.*?)\*|_(.*?)_/gm, '<em>$1$2</em>'], // Italic
            [/\n/gm, '<br>'], // Line breaks (CR)
            [/^### (.*?)\n/gm, '<b>$1</b>'], // H3
            [/^## (.*?)\n/gm, '<b>$1</b>'], // H2
            [/^# (.*?)\n/gm, '<b>$1</b>'], // H1
        ];

        // Apply all replacements efficiently
        text = markdownPatterns.reduce((acc, [pattern, repl]) => {
            return acc.replace(pattern, repl);
        }, text);

        // // Handle links [text](url)
        // text = text.replace(/\[(.*?)\]\((.*?)\)/gm, function(match, linkText, url) {
        //     // Extract domain from URL
        //     let domain = "";
        //     try {
        //         domain = new URL(url).hostname.replace(/^www\./, '');
        //         // Truncate if too long
        //         if (domain.length > 20) {
        //             domain = domain.substring(0, 17) + '...';
        //         }
        //     } catch (e) {
        //         // If URL parsing fails, skip domain
        //         console.log("Error parsing: " + e);
        //     }
        //
        //     // Create a properly formatted HTML string
        //     return '"' + linkText + '"' +
        //            (domain ? ' [' + domain + ']' : '');
        // });

        // Autolink URLs
        if (generateLinks) {
            const urlPattern = /((?:https?:\/\/|www\.)[^\s<>"']+)/g;
            text = text.replace(urlPattern, (url) => {
                let cleanUrl = url;
                // Strip trailing punctuation that is unlikely to be part of the URL
                while (/[.,;!?\)\]\}]$/.test(cleanUrl)) { // eslint-disable-line no-useless-escape
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

        // TODO Replace markdown processing with marked (?)
        // text = marked.parse(text);

        return text;
    }

    sanitizeText(text) {
        return DOMPurify.sanitize(text);
    }

    // Function to detect if content is a markdown table
    isMarkdownTable(content) {
      // Clean up whitespace and normalize line endings
      const lines = content.trim().split(/\r?\n/).filter(line => line.trim());

      if (lines.length < 3) return false; // Need at least header, separator, and one row

      // Check header: starts with | and has pipes separating columns
      const header = lines[0].trim();
      if (!header.startsWith('|') || !header.endsWith('|')) return false;

      // Check separator row: |---| patterns (allow spaces around dashes)
      const separator = lines[1].trim();
      if (!separator.startsWith('|') || !separator.endsWith('|')) return false;
      const hasDashes = separator.split('|').slice(1, -1).every(cell =>
        cell.trim().split('-').length > 1 || cell.trim().includes('---')
      );
      if (!hasDashes) return false;

      // Check data rows: similar pipe structure to header
      const dataRows = lines.slice(2);
      if (dataRows.length === 0) return false;

      const colCount = header.split('|').length - 1; // Account for edge pipes
      return dataRows.every(row => {
        const trimmed = row.trim();
        return trimmed.startsWith('|') && trimmed.endsWith('|') &&
               trimmed.split('|').length - 1 === colCount;
      });
    }
}


module.exports = BaseComponent;
