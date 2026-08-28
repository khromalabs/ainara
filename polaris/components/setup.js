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
// but WITHOUT ANY WARRANTY, without even the implied warranty of
// MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
// Lesser General Public License for more details.

const { ipcRenderer } = require('electron');
const ConfigManager = require('../framework/config');
const Logger = require('../framework/logger');

const api = require('./setup/core/api');
const utils = require('./setup/core/utils');
const { SetupState } = require('./setup/core/state');

const stepModules = {
    welcome: require('./setup/steps/welcome'),
    ollama: require('./setup/steps/ollama'),
    llm: require('./setup/steps/llm'),
    stt: require('./setup/steps/stt'),
    api: require('./setup/steps/api'),
    skills: require('./setup/steps/skills'),
    mcp: require('./setup/steps/mcp'),
    shortcuts: require('./setup/steps/shortcuts'),
    finish: require('./setup/steps/finish')
};

// Create a ConfigManager instance
const config = new ConfigManager();

// Step navigation
const steps = ['welcome', 'ollama', 'llm', 'stt', 'api', 'skills', 'mcp', 'shortcuts', 'finish'];
let currentStepIndex = 0;

// Track modified fields
const modifiedFields = {
    llm: new Set(),
    stt: new Set(),
    api: new Set(),
    mcp: new Set(),
    skills: new Set(),
    shortcuts: new Set(),
    finish: new Set()
};

const { TOS_VERSION } = require('../framework/constants');

async function refreshLLMStepButtonState() {
    const nextBtn = document.getElementById('main-next-btn');
    try {
        const backendConfig = await ctx.api.loadBackendConfig();
        if (stepModules.llm.hasValidConfiguredProvider(backendConfig)) {
            nextBtn.disabled = false;
        } else {
            nextBtn.disabled = true;
        }
    } catch (error) {
        console.error('Error checking LLM provider config:', error);
        nextBtn.disabled = true;
    }
}

function updateButtonVisibility() {
    const backBtn = document.getElementById('main-back-btn');
    const nextBtn = document.getElementById('main-next-btn');
    const finishBtn = document.getElementById('main-finish-btn');

    // Visibility
    backBtn.style.display = (currentStepIndex === 0) ? 'none' : 'inline-block';
    nextBtn.style.display = (currentStepIndex === steps.length - 1) ? 'none' : 'inline-block';
    finishBtn.style.display = (currentStepIndex === steps.length - 1) ? 'inline-block' : 'none';

    // Disabled state
    const currentStep = steps[currentStepIndex];

    if (currentStep === 'welcome') {
        const isWalletVerified = document.getElementById('auth-container').classList.contains('verified');
        const isTosAccepted = document.getElementById('terms-accept-btn').checked;
        nextBtn.disabled = !(isWalletVerified && isTosAccepted);
    } else if (currentStep === 'llm') {
        // Defer to backend config: only enable Next if a provider is actually
        // configured and selected. Start disabled and let the async check refine
        // this to avoid a brief enabled state before the config loads.
        nextBtn.disabled = true;
        refreshLLMStepButtonState();
    } else if (currentStep === 'stt') {
        nextBtn.disabled = false;
    } else if (currentStep === 'api') {
        nextBtn.disabled = true;
        stepModules.api.updateNextButtonState(ctx);
    } else if (currentStep === 'skills') {
        nextBtn.disabled = false;
    } else {
        nextBtn.disabled = false;
    }
}

function handleInputChange(event, disableNext = true) {
    // Hide test result and disable next button when any input changes
    const testResult = document.getElementById('test-result');
    const nextButton = document.getElementById('main-next-btn');

    testResult.classList.add('hidden');
    if (disableNext) {
        nextButton.disabled = true;
    }

    // Track the modified field
    if (event && event.target) {
        const field = event.target;
        const fieldId = field.id;

        // Determine which section this field belongs to
        if (fieldId.includes('shortcut')) {
            modifiedFields.shortcuts.add(fieldId);
        } else if (fieldId.includes('api-key-')) {
            modifiedFields.api.add(field.dataset.path);

            const groupItem = field.closest('.api-group');
            if (!groupItem) return;

            const groupPath = groupItem.dataset.groupPath;

            let isGroupModified = false;
            groupItem.querySelectorAll('input[data-path]').forEach(input => {
                const path = input.dataset.path;
                if (input.value && input.value !== ctx.state.initialApiValues[path]) {
                    isGroupModified = true;
                }
            });

            const statusElement = document.getElementById(`api-status-${groupPath.replace(/\./g, '-')}`);
            const messageElement = document.getElementById(`api-message-${groupPath.replace(/\./g, '-')}`);

            if (isGroupModified) {
                ctx.state.apiValidationStatus[groupPath] = 'unvalidated';
            } else {
                // All fields in the group are back to their initial state
                ctx.state.apiValidationStatus[groupPath] = 'success';
            }

            // Always clear validation UI on change, forcing a re-validation for modified groups
            if (statusElement) statusElement.className = 'api-validation-status';
            if (messageElement) {
                messageElement.textContent = '';
                messageElement.className = 'api-validation-message';
            }
            stepModules.api.updateNextButtonState(ctx);
        } else if (fieldId.includes('custom-api')) {
            modifiedFields.stt.add(fieldId);
        } else if (fieldId.startsWith('mcp-')) {
            modifiedFields.mcp.add(field.closest('.mcp-server-form')?.dataset.serverId || 'mcp_general');
        } else if (['start-minimized-checkbox', 'review-stt-select', 'background-notifications-checkbox', 'backup-directory-input', 'auto-start-checkbox', 'lower-volume-checkbox', 'wakeword-checkbox', 'comring-notifications-checkbox'].includes(fieldId)) {
            modifiedFields.finish.add(fieldId);
        } else {
            // LLM fields
            modifiedFields.llm.add(fieldId);
        }
    }

    // Also validate the form
    if (typeof ctx.validateProviderForm === 'function') {
        ctx.validateProviderForm(ctx);
    }
}

function validateProviderForm(ctx) {
    const selectedProviderId = document.querySelector('input[name="llm-provider"]:checked')?.value;
    const testButton = document.getElementById('test-connection-btn');
    if (!testButton) return;

    if (!selectedProviderId || !ctx.providersData || !ctx.providersData[selectedProviderId]) {
        testButton.disabled = true;
        return;
    }

    const provider = ctx.providersData[selectedProviderId];

    let isValid = true;
    provider.fields.forEach(field => {
        if (field.required) {
            const input = document.getElementById(`${selectedProviderId}-${field.id}`);
            if (!input || !input.value.trim()) {
                isValid = false;
            }
        }
    });
    testButton.disabled = !isValid;
}

async function loadAndDisplayCapabilities() {
    if (stepModules.finish && typeof stepModules.finish.loadAndDisplayCapabilities === 'function') {
        await stepModules.finish.loadAndDisplayCapabilities(ctx);
    }
}

const ctx = {
    config,
    ipcRenderer,
    api,
    utils,
    state: new SetupState(),
    providersData: null,
    modifiedFields,
    updateButtonVisibility,
    handleInputChange,
    validateProviderForm,
    loadAndDisplayCapabilities,
    TOS_VERSION
};

function setupLLMFilterUI() {
    const llmPanel = document.getElementById('llm-panel');
    if (!llmPanel) return;

    const providerOptions = document.getElementById('provider-options');
    if (!providerOptions) return;

    const filterHtml = `
        <div class="filter-container">
            <div class="default-filter-option">
                <input type="checkbox" id="default-filter" name="default-filter">
                <label for="default-filter">Show only recommended models</label>
            </div>
            <label for="model-filter">Filter models:</label>
            <input type="text" id="model-filter" placeholder="e.g., gpt4,haiku,claude">
            <button id="apply-filter-btn">Apply</button>
        </div>
    `;

    const addProviderHtml = `
        <div class="add-provider-section">
            <h3>Add a New Provider</h3>
            ${filterHtml}
        </div>
    `;

    providerOptions.insertAdjacentHTML('beforebegin', addProviderHtml);

    document.getElementById('apply-filter-btn').addEventListener('click', () => {
        stepModules.llm.loadProviders(ctx);
    });

    document.getElementById('model-filter').addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
            stepModules.llm.loadProviders(ctx);
        }
    });

    const defaultFilterCheckbox = document.getElementById('default-filter');

    if (defaultFilterCheckbox.checked) {
        const filterInput = document.getElementById('model-filter');
        const applyButton = document.getElementById('apply-filter-btn');
        const filterInputContainer = document.querySelector('.filter-container label[for="model-filter"]');

        filterInput.value = 'qwen,moonshot,deepseek,-3b,xai,zai,minimax';
        filterInput.style.display = 'none';
        filterInputContainer.style.display = 'none';
        applyButton.style.display = 'none';

        stepModules.llm.loadProviders(ctx);
    }

    defaultFilterCheckbox.addEventListener('change', (e) => {
        const filterInput = document.getElementById('model-filter');
        const applyButton = document.getElementById('apply-filter-btn');
        const filterInputContainer = document.querySelector('.filter-container label[for="model-filter"]');

        if (e.target.checked) {
            // Save current filter value before disabling
            filterInput.dataset.previousValue = filterInput.value;

            // Apply default filter - include recommended models but exclude smaller ones
            filterInput.value = 'xai,moonshot,qwen-3,qwen3,deepseek,-3b';

            // Hide filter input, label and apply button
            filterInput.style.display = 'none';
            filterInputContainer.style.display = 'none';
            applyButton.style.display = 'none';

            // Load providers with default filter
            stepModules.llm.loadProviders(ctx);
        } else {
            // Restore previous value if it exists
            if (filterInput.dataset.previousValue) {
                filterInput.value = filterInput.dataset.previousValue;
            } else {
                filterInput.value = '';
            }

            // Show filter input, label and apply button
            filterInput.style.display = '';
            filterInputContainer.style.display = '';
            applyButton.style.display = '';

            // Load providers with restored filter
            stepModules.llm.loadProviders(ctx);
        }
    });
}

function setupEventListeners() {
    // Close button
    document.querySelector('.close-btn').addEventListener('click', () => {
        event.preventDefault(); // Prevent any default behavior
        if (confirm('Do you really want to close the setup wizard?')) {
            ipcRenderer.send('close-setup-window');
        }
    });

    // Handle external links to open in system browser
    document.addEventListener('click', (event) => {
        const link = event.target.closest('.external-link');
        if (link) {
            event.preventDefault();
            const url = link.getAttribute('data-url');
            if (url) {
                ipcRenderer.send('open-external-url', url);
            }
        }
    });

    // Navigation buttons
    document.getElementById('main-next-btn').addEventListener('click', goToNextStep);
    document.getElementById('main-back-btn').addEventListener('click', goToPreviousStep);
    document.getElementById('main-finish-btn').addEventListener('click', finishSetup);

    // Test connection button
    document.getElementById('test-connection-btn').addEventListener('click', (event) => {
        stepModules.llm.testLLMConnection(ctx, event);
    });

    // Delegated click for dynamically created "Add MCP Server" button
    document.addEventListener('click', (event) => {
        if (event.target.closest('#add-mcp-server-btn')) {
            const mcpPanel = document.getElementById('mcp-panel');
            const container = mcpPanel && mcpPanel.querySelector('.mcp-configurations');
            if (container) {
                stepModules.mcp.addServerForm(ctx, null, container);
            }
        }
    });

    // LLM filter UI (added once on startup)
    setupLLMFilterUI();
}

async function goToNextStep() {
    // Validate current step
    if (!validateCurrentStep()) return;

    // Show loading indicator
    const nextButton = document.getElementById('main-next-btn');
    const originalText = nextButton.textContent;
    nextButton.textContent = 'Saving...';
    nextButton.disabled = true;

    try {
        // Save data from current step (module-aware)
        const currentModule = stepModules[steps[currentStepIndex]];
        if (currentModule && typeof currentModule.save === 'function') {
            await currentModule.save(ctx);
        } else if ( steps[currentStepIndex] != 'welcome' ) {
            // throw new Error(`No save method for step ${steps[currentStepIndex]}`);
        }

        // Hide current step
        document.querySelector('.step-panel.active')?.classList.remove('active');
        document.querySelector('.step.active')?.classList.remove('active');

        // Show next step
        currentStepIndex++;
        document.getElementById(`${steps[currentStepIndex]}-panel`).classList.add('active');
        document.querySelector(`.step[data-step="${steps[currentStepIndex]}"]`).classList.add('active');

        // Initialize the newly entered step if it has a module
        const nextModule = stepModules[steps[currentStepIndex]];
        if (nextModule && typeof nextModule.init === 'function') {
            await nextModule.init(ctx);
        }

        updateButtonVisibility();
    } catch (error) {
        console.error('Error saving step data:', error);
        alert(`Error saving configuration: ${error.message}`);
    } finally {
        // Reset button
        nextButton.textContent = originalText;
        // We intentionally do not re-enable the button here; updateButtonVisibility will set the correct state.
    }
}

function goToPreviousStep() {
    // Hide current step
    document.querySelector('.step-panel.active')?.classList.remove('active');
    document.querySelector('.step.active')?.classList.remove('active');

    // Show previous step
    currentStepIndex--;
    document.getElementById(`${steps[currentStepIndex]}-panel`).classList.add('active');
    document.querySelector(`.step[data-step="${steps[currentStepIndex]}"]`).classList.add('active');

    // Initialize the previous step if it has a module
    const prevModule = stepModules[steps[currentStepIndex]];
    if (prevModule && typeof prevModule.init === 'function') {
        prevModule.init(ctx).catch(err => console.error('Error initializing previous step:', err));
    }

    updateButtonVisibility();
}

function validateCurrentStep() {
    const currentModule = stepModules[steps[currentStepIndex]];
    if (currentModule && typeof currentModule.validate === 'function') {
        return currentModule.validate(ctx);
    }
    return true;
}

async function finishSetup() {
    await stepModules.finish.finishSetup(ctx);
}

// Function to update the LLM step title
function updateLLMStepTitle() {
    const llmStepElement = document.querySelector('.step[data-step="llm"]');
    if (llmStepElement) {
        llmStepElement.textContent = 'LLM Providers';
    }
    const llmPanelElement = document.getElementById('llm-panel');
    if (llmPanelElement) {
        const titleElement = llmPanelElement.querySelector('h2');
        if (titleElement) {
            titleElement.textContent = 'LLM Providers';
        }
    }
}

// Initialize the UI
document.addEventListener('DOMContentLoaded', async () => {
    setupEventListeners();
    updateLLMStepTitle();
    await stepModules.welcome.init(ctx);
    updateButtonVisibility();

    const finishPanel = document.getElementById('finish-panel');
    if (finishPanel) {
        const observer = new MutationObserver(() => {
            if (finishPanel.classList.contains('active')) {
                ctx.loadAndDisplayCapabilities().catch(err => {
                    console.error('Error loading capabilities:', err);
                });
            }
        });
        observer.observe(finishPanel, { attributes: true, attributeFilter: ['class'] });
    }
});
