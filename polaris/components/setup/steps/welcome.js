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

const fs = require('fs');
const { marked } = require('marked');

let initialized = false;

function setupTosListeners(config, updateButtonVisibility, tosVersion) {
    const tosCheckbox = document.getElementById('terms-accept-btn');
    const openModalLink = document.getElementById('open-tos-modal');
    const closeModalBtn = document.getElementById('close-tos-modal');
    const acceptModalBtn = document.getElementById('accept-tos-modal-btn');
    const tosModal = document.getElementById('tos-modal');

    // Returning user who completed setup against older terms: show notice
    if (config.get('setup.completed') && config.get('setup.tosAcceptedVersion') !== tosVersion) {
        const notice = document.getElementById('tos-update-notice');
        if (notice) notice.classList.remove('hidden');
    }

    // Load saved state: only pre-check the box when the stored acceptance
    // matches the current ToS version, forcing active re-acceptance otherwise
    if (config.get('setup.tosAccepted') && config.get('setup.tosAcceptedVersion') === tosVersion) {
        tosCheckbox.checked = true;
    }

    // Checkbox change listener
    tosCheckbox.addEventListener('change', () => {
        config.set('setup.tosAccepted', tosCheckbox.checked);
        config.set('setup.tosAcceptedVersion', tosCheckbox.checked ? tosVersion : '');
        config.saveConfig();
        updateButtonVisibility();
    });

    // Open modal
    openModalLink.addEventListener('click', (e) => {
        e.preventDefault();
        tosModal.classList.remove('hidden');
    });

    // Close modal
    closeModalBtn.addEventListener('click', () => {
        tosModal.classList.add('hidden');
    });

    // Accept from modal
    acceptModalBtn.addEventListener('click', () => {
        tosCheckbox.checked = true;
        config.set('setup.tosAccepted', true);
        config.set('setup.tosAcceptedVersion', tosVersion);
        config.saveConfig();
        tosModal.classList.add('hidden');
        updateButtonVisibility();
    });
}

// Render the bundled CHANGES.md release notes into the welcome panel.
// Newest release first (file is newest-first), full history scrollable.
// Contributor-facing preamble before the first release heading is skipped.
// Fail-open: a missing or malformed file renders nothing.
function setupChangelog(ctx) {
    const container = document.getElementById('welcome-changelog');
    const body = document.getElementById('welcome-changelog-body');
    if (!container || !body) return;

    try {
        const docPath = ctx.config.getBundledChangesDocPath();
        if (!docPath) return;
        const raw = fs.readFileSync(docPath, 'utf8');
        const firstRelease = raw.indexOf('\n## ');
        if (firstRelease === -1) return;
        const releases = raw.slice(firstRelease + 1);

        body.appendChild(
            ctx.utils.sanitizeMarkdownHtml(marked.parse(releases))
        );
        container.classList.remove('hidden');

        // Markdown links must never navigate the wizard window; open
        // them in the user's browser instead (main rejects non-http(s)).
        body.addEventListener('click', (e) => {
            const link = e.target.closest('a[href]');
            if (link) {
                e.preventDefault();
                ctx.ipcRenderer.send('open-external', link.href);
            }
        });
    } catch (error) {
        console.error('Error loading changelog:', error);
    }
}

module.exports = {
    id: 'welcome',

    async init(ctx) {
        if (initialized) return;
        initialized = true;

        setupTosListeners(ctx.config, ctx.updateButtonVisibility, ctx.TOS_VERSION);
        setupChangelog(ctx);
    },

    validate() {
        const tosCheckbox = document.getElementById('terms-accept-btn');
        return !!tosCheckbox?.checked;
    }
};
