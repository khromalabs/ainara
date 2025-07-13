/* global BaseComponent */
/* eslint no-undef: "error" */
class DocumentView extends BaseComponent {
    constructor() {
        super();
        this.documents = [];
        this.currentIndex = -1;
        this.isVisible = false;
    }

    async connectedCallback() {
        try {
            const template = this.requireTemplate('document-view-template');
            await this.loadStyles('./document-view.css');
            this.shadowRoot.appendChild(template.content.cloneNode(true));

            this.container = this.shadowRoot.querySelector('.document-container');
            this.codeBlock = this.shadowRoot.querySelector('.document-content');
            this.formatBadge = this.shadowRoot.querySelector('.format-badge');
            this.counter = this.shadowRoot.querySelector('.counter');
            this.copyButton = this.shadowRoot.querySelector('.copy-button');
            this.prevButton = this.shadowRoot.querySelector('.prev');
            this.nextButton = this.shadowRoot.querySelector('.next');

            this.copyButton.addEventListener('click', () => this.copyToClipboard());
            this.prevButton.addEventListener('click', () => {
                if (this.formatBadge.textContent === 'chat-history') {
                    this.emitEvent('history-prev-clicked');
                } else {
                    this.navigate(-1);
                }
            });
            this.nextButton.addEventListener('click', () => {
                if (this.formatBadge.textContent === 'chat-history') {
                    this.emitEvent('history-next-clicked');
                } else {
                    this.navigate(1);
                }
            });

            this.hide(); // Initially hidden
        } catch (error) {
            this.showError(error);
        }
    }

    addDocument(content, format = 'text') {
        this.documents.push({ content, format });
        this.currentIndex = this.documents.length - 1;
        this.render();
    }

    navigate(direction) {
        const newIndex = this.currentIndex + direction;
        if (newIndex >= 0 && newIndex < this.documents.length) {
            this.currentIndex = newIndex;
            this.render();
        }
    }

    render() {
        if (this.currentIndex < 0 || this.documents.length === 0) {
            this.codeBlock.textContent = '';
            this.formatBadge.textContent = '';
            this.counter.textContent = '0/0';
            return;
        }

        const doc = this.documents[this.currentIndex];
        this.formatBadge.textContent = doc.format;
        if (doc.format === "chat-history") {
            this.codeBlock.innerHTML = this.parseMarkdown(doc.content);
            // History nav state is set externally via updateNavControls
        } else {
            // Logic for other document types
            this.container.classList.toggle('has-multiple-docs', this.documents.length > 1);
            this.codeBlock.innerHTML = "<pre>" + doc.content + "</pre>";
            this.codeBlock.className = `language-${doc.format}`;
            if (window.hljs) {
                window.hljs.highlightElement(this.codeBlock);
            } else {
                console.warn('highlight.js not found. Code will not be highlighted.');
            }
            // Update counter and button states for multi-doc view
            this.counter.textContent = `${this.currentIndex + 1}/${this.documents.length}`;
            this.prevButton.disabled = this.currentIndex === 0;
            this.nextButton.disabled = this.currentIndex >= this.documents.length - 1;
        }
    }

    copyToClipboard() {
        if (this.currentIndex < 0) return;
        const contentToCopy = this.documents[this.currentIndex].content;

        navigator.clipboard.writeText(contentToCopy).then(() => {
            this.copyButton.textContent = 'Copied!';
            setTimeout(() => {
                this.copyButton.textContent = 'Copy';
            }, 2000);
        }).catch(err => {
            console.error('Failed to copy text: ', err);
            this.copyButton.textContent = 'Error';
            setTimeout(() => {
                this.copyButton.textContent = 'Copy';
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
        // state = { show: boolean, prev: boolean, next: boolean }
        const controls = this.shadowRoot.querySelector('.controls');
        controls.style.display = state.show ? 'flex' : '';
        this.prevButton.disabled = !state.prev;
        this.nextButton.disabled = !state.next;

        // Also hide the counter if we are showing history nav
        if (state.show) {
            this.counter.style.display = 'none';
            this.container.classList.remove('has-multiple-docs');
        } else {
            this.counter.style.display = ''; // reset to default
        }
    }

    clear() {
        this.documents = [];
        this.currentIndex = -1;
        this.updateNavControls({ show: false }); // Hide controls
        this.render();
    }
}

customElements.define('document-view', DocumentView);
