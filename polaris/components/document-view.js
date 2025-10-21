/* global BaseComponent */
/* eslint no-undef: "error" */
class DocumentView extends BaseComponent {

    constructor() {
        super();
        this.isVisible = false;
    }

    async connectedCallback() {
        try {
            const template = this.requireTemplate('document-view-template');
            await this.loadStyles('./document-view.css');
            this.shadowRoot.appendChild(template.content.cloneNode(true));

            this.container = this.shadowRoot.querySelector('.document-container');

            this.hide(); // Initially hidden
        } catch (error) {
            this.showError(error);
        }
    }

    addDocument(content, format = 'text', title) {
        const documentElement = document.createElement('div');
        documentElement.className = 'document-item';

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
            const prevButton = document.createElement('button');
            prevButton.className = 'nav-button prev';
            prevButton.innerHTML = '&lt;';
            prevButton.title = 'Previous Day';
            prevButton.addEventListener('click', () => this.emitEvent('history-prev-clicked'));
            controls.appendChild(prevButton);

            const nextButton = document.createElement('button');
            nextButton.className = 'nav-button next';
            nextButton.innerHTML = '&gt;';
            nextButton.title = 'Next Day';
            nextButton.addEventListener('click', () => this.emitEvent('history-next-clicked'));
            controls.appendChild(nextButton);

            // Add scroll to top button
            const scrollTopButton = document.createElement('button');
            scrollTopButton.className = 'nav-button scroll-top';
            scrollTopButton.innerHTML = '▲';
            scrollTopButton.title = 'Scroll to Top';
            scrollTopButton.addEventListener('click', () => {
                const contentArea = documentElement.querySelector('.document-content');
                contentArea?.scrollTo({ top: 0, behavior: 'auto' });
            });
            controls.appendChild(scrollTopButton);

            // Add scroll to bottom button
            const scrollBottomButton = document.createElement('button');
            scrollBottomButton.className = 'nav-button scroll-bottom';
            scrollBottomButton.innerHTML = '▼';
            scrollBottomButton.title = 'Scroll to Bottom';
            scrollBottomButton.addEventListener('click', () => {
                const contentArea = documentElement.querySelector('.document-content');
                contentArea.scrollTo({ top: contentArea.scrollHeight, behavior: 'auto' });
            });
            controls.appendChild(scrollBottomButton);
        }

        if (format !== 'nexus') {
            const formatBadge = document.createElement('span');
            formatBadge.className = 'format-badge';
            formatBadge.textContent = format;
            docInfo.appendChild(formatBadge);

            const copyButton = document.createElement('button');
            copyButton.className = 'copy-button';
            copyButton.textContent = 'Copy';
            copyButton.addEventListener('click', () => this.copyToClipboard(content));
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
            } else {
                contentArea.innerHTML = "<pre>" + content + "</pre>";
                contentArea.className += ` language-${format}`;
                if (window.hljs) {
                    window.hljs.highlightElement(contentArea);
                }
            }
            documentElement.appendChild(contentArea);
            contentArea.focus();
            // setTimeout(() => {
            //     contentArea.focus();
            // }, 2000);
        }

        this.container.appendChild(documentElement);
    }

    copyToClipboard(content) {
        navigator.clipboard.writeText(content).then(() => {
            // Find the button that was clicked and update its text
            const button = event.target;
            const originalText = button.textContent;
            button.textContent = 'Copied!';
            setTimeout(() => {
                button.textContent = originalText;
            }, 2000);
        }).catch(err => {
            console.error('Failed to copy text: ', err);
            const button = event.target;
            const originalText = button.textContent;
            button.textContent = 'Error';
            setTimeout(() => {
                button.textContent = originalText;
            }, 2000);
        });
    }

    show() {
        this.classList.add('visible');
        this.isVisible = true;
    }

    hide() {
        this.classList.remove('visible');
        this.isVisible = false;
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
