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

let initialized = false;

function setupTosListeners(config, updateButtonVisibility) {
    const tosCheckbox = document.getElementById('terms-accept-btn');
    const openModalLink = document.getElementById('open-tos-modal');
    const closeModalBtn = document.getElementById('close-tos-modal');
    const acceptModalBtn = document.getElementById('accept-tos-modal-btn');
    const tosModal = document.getElementById('tos-modal');

    // Load saved state
    if (config.get('setup.tosAccepted')) {
        tosCheckbox.checked = true;
    }

    // Checkbox change listener
    tosCheckbox.addEventListener('change', () => {
        config.set('setup.tosAccepted', tosCheckbox.checked);
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
        config.saveConfig();
        tosModal.classList.add('hidden');
        updateButtonVisibility();
    });
}

async function setupAuthListeners(config, ipcRenderer, updateButtonVisibility) {
    const verifyBtn = document.getElementById('verify-wallet-btn');
    const walletInput = document.getElementById('wallet-address-input');
    const statusMsg = document.getElementById('auth-status-message');
    const authContainer = document.getElementById('auth-container');

    // Hide the manual input if it exists
    if (walletInput) walletInput.style.display = 'none';

    let pollingInterval = null;
    let verified = await checkSolanaLogin();

    if (!verified) {
        verifyBtn.textContent = "Login with Solana Wallet";
        verifyBtn.addEventListener('click', async () => {
            // 1. Open the portal
            ipcRenderer.send('open-auth-portal');
            verifyBtn.disabled = true;
            verifyBtn.textContent = "Waiting for browser login...";
            statusMsg.textContent = "Please complete login in your browser...";
            statusMsg.className = "info-message";
            // 2. Start polling for success
            if (pollingInterval) clearInterval(pollingInterval);
            pollingInterval = setInterval(checkSolanaLogin, 2000);
        });
    }

    async function checkSolanaLogin() {
        try {
            const response = await fetch(config.get('pybridge.api_url') + '/auth/status');
            const status = await response.json();

            if (status.authorized) {
                if (pollingInterval) {
                    clearInterval(pollingInterval);
                }
                statusMsg.textContent = `Success! Wallet verified: ${status.wallet}`;
                statusMsg.className = "success-message";
                authContainer.classList.add('verified');
                verifyBtn.textContent = "Verified";
                updateButtonVisibility();
            }
            return status.authorized;
        } catch (e) {
            console.error("Auth polling error", e);
        }
    }
}

module.exports = {
    id: 'welcome',

    async init(ctx) {
        if (initialized) return;
        initialized = true;

        setupTosListeners(ctx.config, ctx.updateButtonVisibility);
        await setupAuthListeners(ctx.config, ctx.ipcRenderer, ctx.updateButtonVisibility);
    },

    validate(ctx) {
        const authContainer = document.getElementById('auth-container');
        const tosCheckbox = document.getElementById('terms-accept-btn');
        return authContainer?.classList.contains('verified') && tosCheckbox?.checked;
    }
};
