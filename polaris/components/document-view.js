/* global BaseComponent */
/* eslint no-undef: "error" */


class DocumentView extends BaseComponent {

    constructor() {
        super();
        this.isVisible = false;
        this.selectedText = null;
    }

    async connectedCallback() {
        try {
            const template = this.requireTemplate('document-view-template');
            await this.loadStyles('./document-view.css');
            this.shadowRoot.appendChild(template.content.cloneNode(true));
            this.container = this.shadowRoot.querySelector('.document-container');

            // Inject styles for search popup
            const style = document.createElement('style');
            style.textContent = `
                .search-container {
                    position: relative;
                    display: flex;
                    align-items: center;
                    margin-right: 10px;
                }
                .search-input {
                    background: rgba(0, 0, 0, 0.3);
                    border: 1px solid rgba(255, 255, 255, 0.2);
                    color: white;
                    padding: 4px 8px;
                    border-radius: 4px;
                    outline: none;
                    font-family: inherit;
                    width: 190px;
                    transition: width 0.2s, background 0.2s;
                }
                .search-input:focus {
                    width: 240px;
                    border-color: rgba(255, 255, 255, 0.5);
                    background: rgba(0, 0, 0, 0.6);
                }
                .search-results-popup {
                    position: absolute;
                    top: 100%;
                    right: 0;
                    width: 300px;
                    max-height: 400px;
                    overflow-y: auto;
                    background: #1a1a1a;
                    border: 1px solid #444;
                    border-radius: 4px;
                    box-shadow: 0 4px 12px rgba(0,0,0,0.5);
                    z-index: 1000;
                    display: none;
                    margin-top: 5px;
                }
                .search-results-popup.visible {
                    display: block;
                }
                .search-result-item {
                    padding: 8px 12px;
                    border-bottom: 1px solid #333;
                    cursor: pointer;
                    display: flex;
                    flex-direction: column;
                    gap: 2px;
                }
                .search-result-item:last-child {
                    border-bottom: none;
                }
                .search-result-item:hover {
                    background: #333;
                }
                .search-result-date {
                    font-size: 0.75em;
                    color: #888;
                }
                .search-result-text {
                    font-size: 0.9em;
                    color: #eee;
                    white-space: nowrap;
                    overflow: hidden;
                    text-overflow: ellipsis;
                }
                .highlight-flash {
                    animation: flash-highlight 2s ease-out;
                }
                @keyframes flash-highlight {
                    0% { background-color: rgba(255, 255, 0, 0.3); }
                    100% { background-color: transparent; }
                }
            `;
            this.shadowRoot.appendChild(style);

            this.container = this.shadowRoot.querySelector('.document-container');

            this.hide(); // Initially hidden
        } catch (error) {
            this.showError(error);
        }
    }

    addDocument(content, format = 'text', title, scrollBottom = true) {
        const documentElement = document.createElement('div');
        documentElement.className = 'document-item';
        documentElement.dataset.format = format;

        // Create header for all items
        const header = document.createElement('div');
        header.className = 'document-header';

        const docInfo = document.createElement('div');
        docInfo.className = 'doc-info';

        const titleElement = document.createElement('span');
        titleElement.className = 'doc-title';
        titleElement.textContent = title || (format.charAt(0).toUpperCase() + format.slice(1));
        titleElement.title = titleElement.textContent
        docInfo.appendChild(titleElement);

        const controls = document.createElement('div');
        controls.className = 'doc-controls';

        if (format === 'chat-history') {
            // Add Search Control
            const searchContainer = document.createElement('div');
            searchContainer.className = 'search-container';

            const searchInput = document.createElement('input');
            const tipInfo = document.createElement('div');
            tipInfo.className = 'tipInfo';
            tipInfo.title = "Use ~ as prefix for vectorial (concepts based) search.\nMore keyboard shortcuts:\n- Control+Left: Go to the previous day.\n- Control+Right: Go to the next day.\n- Control+Up: Go to text top.\n- Control+Down: Go to text bottom.";
            searchInput.className = 'search-input';
            searchInput.placeholder = 'Search history (Ctrl+f)';
            searchInput.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') {
                    this.emitEvent('search-requested', { query: e.target.value });
                }
                if (e.key === 'Escape') {
                    this.blur();
                }
            });
            // Prevent keydown propagation to avoid triggering global shortcuts
            searchInput.addEventListener('keydown', (e) => e.stopPropagation());

            const searchPopup = document.createElement('div');
            searchPopup.className = 'search-results-popup';
            this.searchPopup = searchPopup;

            searchContainer.appendChild(searchInput);
            searchContainer.appendChild(tipInfo);
            searchContainer.appendChild(searchPopup);
            controls.appendChild(searchContainer);
            // prevent automatic focus on input element
            document.activeElement.blur();

            // Close popup when clicking outside
            document.addEventListener('click', (e) => {
                const path = e.composedPath();
                if (!path.includes(searchContainer)) {
                    searchPopup.classList.remove('visible');
                }
            });

            document.addEventListener('keydown', (e) => {
                if (e.key === 'f' && e.ctrlKey) {
                    const searchInput = this.shadowRoot.querySelector('.search-input');
                    if (searchInput) {
                        searchInput.focus();
                    }
                }
                if (e.key === 'ArrowLeft' && e.ctrlKey) {
                    this.emitEvent('history-prev-clicked');
                    return;
                }
                if (e.key === 'ArrowRight' && e.ctrlKey) {
                    const nextButton = this.shadowRoot.querySelector('.nav-button.next');
                    if (!nextButton.disabled) {
                        this.emitEvent('history-next-clicked');
                    }
                    return;
                }
                if (e.key === 'ArrowUp' && e.ctrlKey) {
                    const contentArea = documentElement.querySelector('.document-content');
                    contentArea?.scrollTo({ top: 0, behavior: 'auto' });
                    return;
                }
                if (e.key === 'ArrowDown' && e.ctrlKey) {
                    const contentArea = documentElement.querySelector('.document-content');
                    contentArea.scrollTo({ top: contentArea.scrollHeight, behavior: 'auto' });
                    return;
                }
            });

            const prevButton = document.createElement('button');
            prevButton.className = 'nav-button prev';
            prevButton.innerHTML = `
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <polyline points="15 18 9 12 15 6"></polyline>
              </svg>
            `;
            prevButton.title = 'Previous Day';
            prevButton.addEventListener('click', () => this.emitEvent('history-prev-clicked'));
            controls.appendChild(prevButton);

            const nextButton = document.createElement('button');
            nextButton.className = 'nav-button next';
            nextButton.innerHTML = `
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <polyline points="9 18 15 12 9 6"></polyline>
              </svg>
            `;
            nextButton.title = 'Next Day';
            nextButton.addEventListener('click', () => this.emitEvent('history-next-clicked'));
            controls.appendChild(nextButton);

            // // Add scroll to top button
            // const scrollTopButton = document.createElement('button');
            // scrollTopButton.className = 'nav-button scroll-top';
            // scrollTopButton.innerHTML = '▲';
            // scrollTopButton.title = 'Scroll to Top';
            // scrollTopButton.addEventListener('click', () => {
            //     const contentArea = documentElement.querySelector('.document-content');
            //     contentArea?.scrollTo({ top: 0, behavior: 'auto' });
            // });
            // controls.appendChild(scrollTopButton);

            // // Add scroll to bottom button
            // const scrollBottomButton = document.createElement('button');
            // scrollBottomButton.className = 'nav-button scroll-bottom';
            // scrollBottomButton.innerHTML = '▼';
            // scrollBottomButton.title = 'Scroll to Bottom';
            // scrollBottomButton.addEventListener('click', () => {
            //     const contentArea = documentElement.querySelector('.document-content');
            //     contentArea.scrollTo({ top: contentArea.scrollHeight, behavior: 'auto' });
            // });
            // controls.appendChild(scrollBottomButton);
            // documentElement.addEventListener('mouseup', () => {
            //     this.selectedText = window.getSelection().toString();
            //     navigator.clipboard.writeText(this.selectedText);
            // })
        }

        if (format !== 'nexus') {
            const formatBadge = document.createElement('span');
            formatBadge.className = 'format-badge';
            formatBadge.textContent = format;
            docInfo.appendChild(formatBadge);

            const copyButton = document.createElement('button');
            copyButton.className = 'copy-button';
            copyButton.textContent = 'Copy';
            let text = content;
            copyButton.addEventListener('click', () => this.copyToClipboard(text));
            controls.appendChild(copyButton);
        }

        const helpElement = document.createElement('span');
        helpElement.textContent = "Press Escape to exit document view";
        helpElement.title = helpElement.textContent;
        docInfo.appendChild(helpElement);


        const closeButton = document.createElement('button');
        closeButton.className = 'close-button';
        closeButton.innerHTML = '&times;';
        closeButton.title = 'Close';
        closeButton.addEventListener('click', () => {
            const iframe = documentElement.querySelector('iframe');
            if (iframe) {
                iframe.src = 'about:blank';
            }
            documentElement.remove();
        });
        controls.appendChild(closeButton);

        header.appendChild(docInfo);
        header.appendChild(controls);
        documentElement.appendChild(header);

        if (format === 'nexus') {
            // Create iframe for nexus content
            const iframe = document.createElement('iframe');
            iframe.className = 'nexus-frame';
            iframe.sandbox = 'allow-scripts allow-same-origin allow-forms';

            // Post data on load
            iframe.onload = () => {
                if (iframe.contentWindow) {
                    const dataToSend = content.data.result || content.data;
                    iframe.contentWindow.postMessage(dataToSend, '*');
                }
            };

            iframe.src = content.url;
            documentElement.appendChild(iframe);
        } else {
            // Create content area
            const contentArea = document.createElement('div');
            contentArea.className = 'document-content';
            contentArea.tabIndex = 0;

            if (format === "chat-history" || format === "help") {
                contentArea.innerHTML = this.parseMarkdown(content, true);
                // Add this line to hydrate frames
                this.hydrateNexusFrames(contentArea);
            } else {
                contentArea.innerHTML = "<pre>" + content + "</pre>";
                contentArea.className += ` language-${format}`;
                // if (window.hljs) {
                //     window.hljs.highlightElement(contentArea);
                // }
            }
            documentElement.appendChild(contentArea);
            if (format === "chat-history") {
                this.initAllSortableTables();
            }
            contentArea.focus();
        }

        this.container.appendChild(documentElement);
        if (scrollBottom && format === 'chat-history') {
            const contentArea = documentElement.querySelector('.document-content');
            contentArea.scrollTo({ top: contentArea.scrollHeight, behavior: 'auto' });
        }

        if (format === 'chat-history') {
            const contentArea = documentElement.querySelector('.document-content');
            contentArea.focus();
        }
    }

    appendDocumentContent(content, format = 'text') {
        if (format !== 'chat-history') {
            return;
        }

        const chatHistoryItem = this.shadowRoot.querySelector('.document-item');
        if (!chatHistoryItem) {
            return;
        }

        const contentArea = chatHistoryItem.querySelector('.document-content');
        if (!contentArea) {
            return;
        }

        const newContentHtml = this.parseMarkdown(content, true);
        contentArea.insertAdjacentHTML('beforeend', "<BR>" + newContentHtml);
        // Add this line to hydrate frames
        this.hydrateNexusFrames(contentArea);
        this.initAllSortableTables();
        contentArea.scrollTo({ top: contentArea.scrollHeight, behavior: 'smooth' });
    }

    copyToClipboard(content) {
        // Copy selectedText or the whole document if not
        window.getSelection().removeAllRanges();
        // console.log("selectedText: " + this.selectedText);
        navigator.clipboard.writeText(this.selectedText || content);
    }

    show() {
        this.classList.add('visible');
        this.isVisible = true;
    }

    hide() {
        this.classList.remove('visible');
        this.isVisible = false;
        this.blur();
    }

    updateNavControls(state) {
        // state = { prev: boolean, next: boolean }
        const prevButton = this.shadowRoot.querySelector('.nav-button.prev');
        const nextButton = this.shadowRoot.querySelector('.nav-button.next');

        if (prevButton) {
            prevButton.disabled = !state.prev;
        }
        if (nextButton) {
            nextButton.disabled = !state.next;
        }
    }

    showSearchResults(results) {
        if (!this.searchPopup) return;

        this.searchPopup.innerHTML = '';

        if (!results || results.length === 0) {
            const noResults = document.createElement('div');
            noResults.className = 'search-result-item';
            noResults.textContent = 'No results found';
            this.searchPopup.appendChild(noResults);
        } else {
            results.forEach(result => {
                const item = document.createElement('div');
                item.className = 'search-result-item';

                const dateDiv = document.createElement('div');
                dateDiv.className = 'search-result-date';
                // Format timestamp: YYYY-MM-DD HH:MM
                const dateObj = new Date(result.timestamp);
                dateDiv.textContent = dateObj.toLocaleString();

                const textDiv = document.createElement('div');
                textDiv.className = 'search-result-text';
                textDiv.textContent = result.content;

                item.appendChild(dateDiv);
                item.appendChild(textDiv);

                item.addEventListener('click', () => {
                    this.searchPopup.classList.remove('visible');
                    // Extract date part for history loading (YYYY-MM-DD)
                    const dateStr = result.timestamp.split('T')[0];
                    this.emitEvent('search-result-selected', {
                        date: dateStr,
                        timestamp: result.timestamp
                    });
                });

                this.searchPopup.appendChild(item);
            });
        }

        this.searchPopup.classList.add('visible');
    }

    scrollToTimestamp(timestamp) {
        // Extract time part HH:MM:SS from ISO string
        // The markdown parser typically renders timestamps in code blocks like `12:00:00`
        const dateObj = new Date(timestamp);
        const timeStr = String(dateObj.getHours()).padStart(2, '0') + ":" +
            String(dateObj.getMinutes()).padStart(2, '0') + ":" +
            String(dateObj.getSeconds()).padStart(2, '0');

        const contentArea = this.shadowRoot.querySelector('.document-content');
        if (!contentArea) return;

        // Find all code (timestamps) elements
        const codeElements = contentArea.getElementsByTagName('code');
        let targetElement = null;

        for (const el of codeElements) {
            // console.log("Searching '" + timeStr + "' in '" + el.textContent + "'");
            if (el.textContent.includes(timeStr)) {
                targetElement = el;
                break;
            }
        }

        if (targetElement) {
            targetElement.scrollIntoView({ behavior: 'smooth', block: 'center' });
            // Add a visual flash effect
            const parentBlock = targetElement.closest('div');
            if (parentBlock) {
                parentBlock.classList.add('highlight-flash');
                setTimeout(() => parentBlock.classList.remove('highlight-flash'), 20000);
            }
        }
    }

    hydrateNexusFrames(container) {
        const frames = container.querySelectorAll('iframe.nexus-frame');
        frames.forEach(iframe => {
            // Only process frames that have data and haven't been hydrated yet
            if (iframe.dataset.nexusData && !iframe.dataset.hydrated) {
                try {
                    const rawData = decodeURIComponent(iframe.dataset.nexusData);
                    const data = JSON.parse(rawData);
                    // Match the logic from the live view: use result or raw data
                    const dataToSend = data.result || data;

                    const sendData = () => {
                        if (iframe.contentWindow) {
                            iframe.contentWindow.postMessage(dataToSend, '*');
                            iframe.dataset.hydrated = 'true';
                        }
                    };

                    // Send immediately if loaded, otherwise wait for load
                    // Note: Since these are injected via innerHTML, they usually trigger 'load' shortly after
                    iframe.addEventListener('load', sendData);
                } catch (e) {
                    console.error('Failed to hydrate Nexus frame:', e);
                }
            }
        });
    }

    closeChatHistory() {
        const chatHistoryItem = this.container.querySelector('.document-item[data-format="chat-history"]');
        if (chatHistoryItem) {
            const iframe = chatHistoryItem.querySelector('iframe');
            if (iframe) {
                iframe.src = 'about:blank';
            }
            chatHistoryItem.remove();

            if (!this.container.firstElementChild) {
                this.hide();
            }
        }
    }

    clear() {
        // Remove all document items from the container
        while (this.container.firstChild) {
            const child = this.container.firstChild;
            // Clean up iframes
            if (child.querySelector && child.querySelector('iframe')) {
                const iframe = child.querySelector('iframe');
                iframe.src = 'about:blank';
            }
            this.container.removeChild(child);
        }
    }
}

customElements.define('document-view', DocumentView);
