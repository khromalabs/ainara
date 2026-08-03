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

const { ipcRenderer } = require('electron');
const ConfigManager = require('../framework/config');
const Logger = require('../framework/logger');
// const ConfigHelper = require('../framework/ConfigHelper');
// const fs = require('fs');
// const path = require('path');
// const yaml = require('js-yaml');


const ollama = require('ollama');

const providerWebsites = {
    'openai': 'https://platform.openai.com/api-keys',
    'anthropic': 'https://console.anthropic.com/settings/keys',
    'cohere': 'https://dashboard.cohere.com/api-keys',
    'groq': 'https://console.groq.com/keys',
    'xai': 'https://console.x.ai/',
    'google': 'https://aistudio.google.com/app/apikey',
    'mistral': 'https://console.mistral.ai/api-keys/',
    'deepmind': 'https://aistudio.google.com/app/apikey',
    'deepseek': 'https://platform.deepseek.com/api_keys',
    'perplexity': 'https://www.perplexity.ai/settings/api',
    'fireworks': 'https://fireworks.ai/api-keys',
    'helius': 'https://dashboard.helius.dev/api-keys',
    'together_ai': 'https://api.together.xyz/settings/api-keys',
    'openrouter': 'https://openrouter.ai/keys',
    'anyscale': 'https://console.anyscale.com/credentials',
    'voyage': 'https://dash.voyageai.com/api-keys',
    'bedrock': 'https://console.aws.amazon.com/bedrock/',
    'azure': 'https://portal.azure.com/',
    'sagemaker': 'https://console.aws.amazon.com/sagemaker/',
    'vertex_ai': 'https://console.cloud.google.com/vertex-ai',
};

// Create a ConfigManager instance
const config = new ConfigManager();

// Step navigation
const steps = ['welcome', 'ollama', 'llm', 'stt', 'skills', 'mcp', 'shortcuts', 'finish'];
let currentStepIndex = 0;
let providersData = null;
let skillValidationStatus = {};
let initialSkillValues = {};
// Track modified fields
const modifiedFields = {
    llm: new Set(),
    stt: new Set(),
    mcp: new Set(),
    skills: new Set(),
    shortcuts: new Set(),
    finish: new Set()
};

// Initialize the UI
document.addEventListener('DOMContentLoaded', async () => {
    setupEventListeners();
    setupTosListeners();
    loadProviders();
    updateLLMStepTitle(); // Update the LLM step title
    await setupAuthListeners();
    updateButtonVisibility();
});

// Function to load the backend config via API
async function loadBackendConfig() {
    try {
        const response = await fetch(
            config.get('pybridge.api_url') +
            '/config?show_sensitive=true'
        );
        if (!response.ok) {
            throw new Error('Failed to load configuration');
        }
        return await response.json();
    } catch (error) {
        console.error('Error loading backend config:', error);
    }
}

// Function to save the backend config via API
async function saveBackendConfig(config, server) {
    try {
        const stringConfig = JSON.stringify(config);
        console.log(`Saving config to server: ${server}`);
        const response = await fetch(
            server + '/config',
            {
                method: 'PUT',
                headers: {
                    'Content-Type': 'application/json'
            },
            body: stringConfig
        });

        if (!response.ok) {
            const errorData = await response.json();
            throw new Error(`Failed to save configuration: ${errorData.error || 'Unknown error'}`);
        }

        const result = await response.json();
        console.log('Backend config saved successfully:', result);
        return result;
    } catch (error) {
        console.error(`Error saving backend config to ${server}:`, error);
        // Show error to user
        const errorMessage = `Failed to save configuration: ${error.message}`;
        alert(errorMessage);
        throw error;
    }
}

// Function to extract API keys from the backend config
function extractApiKeysFromConfig(config) {
    const apiKeys = {};

    // Helper function to recursively search for API keys
    function findApiKeys(obj, path = []) {
        if (!obj || typeof obj !== 'object') return;

        // Check each property
        for (const [key, value] of Object.entries(obj)) {
            const currentPath = [...path, key];

            if (!String(currentPath).startsWith("apis"))
                continue;

            // EXCLUDE EMAIL: Handled manually via table
            if (String(currentPath).startsWith("apis.messaging.email"))
                continue;

            // If the value is "<key>" or contains "api_key" in the key name, it's likely an API key
            // if (value === "<key>" || key.includes('api_key') || key.includes('apiKey')) {
            if (typeof value !== 'object' && value !== null) {
                // Create a parent path (everything except the last segment)
                const parentPath = currentPath.slice(0, -1).join('.');

                // If this parent path doesn't exist in our apiKeys object, create it
                if (!apiKeys[parentPath]) {
                    apiKeys[parentPath] = {
                        displayName: formatKeyName(currentPath.slice(0, -1)),
                        keys: []
                    };
                }

                // Add this key to the parent's keys array
                apiKeys[parentPath].keys.push({
                    path: currentPath.join('.'),
                    keyName: key,
                    displayName: formatKeyName([key]),
                    value: value === "<key>" ? "" : value,
                    description: getKeyDescription(currentPath)
                });
            }
            // If it's an object, recursively search it
            // else if (typeof value === 'object' && value !== null) {
            else if (typeof value === 'object' && value !== null) {
                findApiKeys(value, currentPath);
            }
        }
    }

    // Start the recursive search
    findApiKeys(config);

    return apiKeys;
}

// Format the key name for display
function formatKeyName(pathArray) {
    // Default formatting
    return pathArray.map(part => {
        // Convert snake_case or camelCase to Title Case
        return part
            .replace(/_/g, ' ')
            .replace(/([A-Z])/g, ' $1')
            .replace(/^./, str => str.toUpperCase());
    }).join(' › ');
}

// Get description for known API keys
function getKeyDescription(pathArray) {
    // const lastPart = pathArray[pathArray.length - 1];
    const parentPart = pathArray.length > 1 ? pathArray[pathArray.length - 2] : '';

    const descriptions = {
        'coinmarketcap': {
            url: 'https://coinmarketcap.com/api/',
            description: 'Used for extended quotes in cryptocurrency market data, not present in main markets'
        },
        'weather': {
            url: 'https://openweathermap.org/api',
            description: 'Used for weather forecasts and current conditions'
        },
        'finance': {
            url: 'https://www.alphavantage.co/support/#api-key',
            description: 'Used for stock market data and financial information'
        },
        'newsapi': {
            url: 'https://newsapi.org/register',
            description: 'Used for retrieving news articles and headlines'
        },
        'google': {
            url: 'https://developers.google.com/custom-search/v1/overview',
            description: 'Used for web search capabilities'
        },
        'tavily': {
            url: 'https://tavily.com/',
            description: 'Used for AI-powered search capabilities'
        },
        'perplexity': {
            url: 'https://www.perplexity.ai/',
            description: 'Used for AI-powered search and answers'
        },
        'metaphor': {
            url: 'https://metaphor.systems/',
            description: 'Used for neural search capabilities'
        },
        'twitter': {
            url: 'https://developer.twitter.com/en/portal/dashboard',
            description: 'Used for Twitter/X integration'
        },
        'reddit': {
            url: 'https://www.reddit.com/prefs/apps',
            description: 'Used for Reddit integration'
        },
        'crypto': {
            url: 'https://coinmarketcap.com/api/',
            description: 'Used for cryptocurrency market data'
        },
        'helius': {
            url: 'https://helius.xyz/',
            description: 'Used for Solana blockchain data'
        },
        'discord': {
            url: 'https://discord.com/developers/applications',
            description: 'Used for Discord bot integration'
        },
        'email': {
            url: null,
            description: 'Configure IMAP accounts for email integration'
        }
    };

    // Check if we have a description for this service
    if (descriptions[parentPart]) {
        return {
            text: descriptions[parentPart].description,
            url: descriptions[parentPart].url
        };
    }

    // Default description
    return {
        text: `API key for ${formatKeyName(pathArray)}`,
        url: null
    };
}

// Function to generate the skills UI
async function generateSkillsUI() {
    // Reset validation status when UI is generated
    initialSkillValues = {};
    skillValidationStatus = {};

    try {
        // Load the sample config from the API instead of the file
        const response = await fetch(
            config.get('pybridge.api_url') + '/config/defaults'
        );

        if (!response.ok) {
            throw new Error('Failed to load default configuration');
        }

        const sampleConfig = await response.json();

        // Load ACTUAL config to populate email table
        const backendConfig = await loadBackendConfig();

        // Fetch capabilities to find schedulable ones
        const capsResponse = await fetch(config.get('orakle.api_url') + '/capabilities?view=full');
        const capabilities = await capsResponse.json();

        // Extract API keys
        const apiKeys = extractApiKeysFromConfig(sampleConfig);

        // Generate HTML for each API key
        // let html = '';

        // Add event to load capabilities when navigating to finish step
        const observer = new MutationObserver((mutations) => {
            mutations.forEach((mutation) => {
                if (mutation.type === 'attributes' && mutation.attributeName === 'class') {
                    const finishPanel = document.getElementById('finish-panel');
                    if (finishPanel && finishPanel.classList.contains('active')) {
                        loadAndDisplayCapabilities().catch(err => {
                            console.error('Error loading capabilities:', err);
                        });
                    }
                }
            });
        });

        const finishPanel = document.getElementById('finish-panel');
        if (finishPanel) {
            observer.observe(finishPanel, { attributes: true });
        }

        // Group keys by category
        const categories = new Map();

        // console.log("-------");
        // console.log("apiKeys:");
        // console.log(JSON.stringify(apiKeys));
        // console.log("-------");

        // Ensure Messaging category exists for Email table, even if no other messaging keys exist
        if (!categories.has('messaging')) {
            categories.set('messaging', []);
        }

        // Group by top-level category first
        for (const [parentPath, keyGroup] of Object.entries(apiKeys)) {
            const pathParts = parentPath.split('.');
            const category = pathParts[0];

            // Skip stt and llm categories as they've been processed in previous slides
            if (category === 'stt' || category === 'llm') {
                continue;
            }

            if (!categories.has(category)) {
                categories.set(category, []);
            }

            categories.get(category).push({
                parentPath,
                displayName: keyGroup.displayName,
                keys: keyGroup.keys
            });
        }

        const orderedCategoriesEntries = new Map([...categories.entries()].sort());

        // Prepare content buffers
        let generalApiHtml = '';
        let messagingHtml = '';

        // Generate HTML for each category
        for (const [category, keyGroups] of orderedCategoriesEntries) {
            // Only skip if empty AND not messaging (messaging might need to show email table)
            if (keyGroups.length === 0 && category !== 'messaging') continue;

            let categoryTitle = category.charAt(0).toUpperCase() + category.slice(1);
            let sectionHtml = `
                <div class="skill-category ${categoryTitle}">
                    <h3>${category.charAt(0).toUpperCase() + category.slice(1)}</h3>
                    <div class="skill-items">
            `;

            keyGroups.forEach(group => {
                sectionHtml += `
                    <div class="skill-item" data-group-path="${group.parentPath}">
                        <h4>${group.displayName} <span class="skill-validation-status" id="status-${group.parentPath.replace(/\./g, '-')}"></span></h4>
                        <div class="skill-validation-message" id="message-${group.parentPath.replace(/\./g, '-')}"></div>
                `;

                // Use the description from the first key in the group
                if (group.keys.length > 0 && group.keys[0].description) {
                    if (group.keys[0].description.text) {
                        sectionHtml += `<p>${group.keys[0].description.text}</p>`;
                    }

                    if (group.keys[0].description.url) {
                        sectionHtml += `<p>Get API key(s) from: <a href="#" class="external-link" data-url="${group.keys[0].description.url}">${new URL(group.keys[0].description.url).hostname}</a></p>`;
                    }
                }

                // Add all keys for this group
                group.keys.forEach(key => {
                    sectionHtml += `
                        <div class="form-group">
                            <label for="api-key-${key.path.replace(/\./g, '-')}">${key.displayName}:</label>
                            <input type="text" placeholder="${key.keyName}" id="api-key-${key.path.replace(/\./g, '-')}" data-path="${key.path}">
                        </div>
                    `;
                });

                sectionHtml += `</div>`;
            });

            // INJECT EMAIL TABLE FOR MESSAGING CATEGORY
            if (category === 'messaging') {
               sectionHtml += generateEmailTableHtml(backendConfig);
               sectionHtml += `</div></div>`;
               messagingHtml += sectionHtml;
            } else {
               sectionHtml += `</div></div>`;
               generalApiHtml += sectionHtml;
            }
        }

        // Generate Schedule UI
        const scheduleHtml = generateScheduleUI(capabilities, backendConfig);

        // Construct the Layout with Top Menu
        const layoutHtml = `
            <div class="skills-layout">
                <div class="skills-nav-bar">
                    <div class="skills-nav-item active" data-target="section-api-keys">API Keys</div>
                    <div class="skills-nav-item" data-target="section-messaging">Messaging</div>
                    <div class="skills-nav-item" data-target="section-scheduler">Scheduled Skills</div>
                </div>
                <div class="skills-content-area">
                    <div id="section-api-keys" class="skills-section-anchor">
                        ${generalApiHtml}
                    </div>
                    <div id="section-messaging" class="skills-section-anchor">
                        ${messagingHtml}
                    </div>
                    <div id="section-scheduler" class="skills-section-anchor">
                        ${scheduleHtml}
                    </div>

                    <div class="validate-all-container" style="text-align: center; margin-top: 40px; margin-bottom: 10px; display: flex; justify-content: center; gap: 10px;">
                        <button id="reset-skills-btn" class="btn btn-secondary">Reset Changes</button>
                        <button id="validate-all-keys-btn" class="btn">Validate API Keys</button>
                    </div>
                </div>
            </div>
        `;

        // Update the skills list container
        const skillsListContainer = document.querySelector('.skills-list');
        if (skillsListContainer) {
            skillsListContainer.innerHTML = layoutHtml;
        }

        // Setup Navigation Logic
        setupSkillsNavigation();

        // Add event listeners to all input fields
        document.querySelectorAll('.skills-list input[data-path]').forEach(input => {
            input.addEventListener('input', (event) => handleInputChange(event));
        });

        // Add event listener for the main validation button
        document.getElementById('validate-all-keys-btn').addEventListener('click', validateAllApiKeys);

        // Add event listener for the reset button
        document.getElementById('reset-skills-btn').addEventListener('click', resetApiKeys);

        // SETUP EMAIL TABLE LISTENERS
        setupEmailTableListeners();

        // SETUP SCHEDULE LISTENERS
        setupScheduleListeners();

        // Load existing values from config
        await loadExistingApiKeys();

        // Store initial values and set initial validation status
        document.querySelectorAll('.skills-list input[data-path]').forEach(input => {
            initialSkillValues[input.dataset.path] = input.value;
        });
        document.querySelectorAll('.skill-item').forEach(item => {
            const groupPath = item.dataset.groupPath;
            // Initially, all skills are considered valid for navigation until changed.
            skillValidationStatus[groupPath] = 'success';
        });

        updateSkillsNextButtonState();

    } catch (error) {
        console.error('Error generating skills UI:', error);
        const skillsListContainer = document.querySelector('.skills-list');
        if (skillsListContainer) {
            skillsListContainer.innerHTML = `
                <div class="error">
                    Error loading API keys: ${error.message}
                </div>
            `;
        }
    }
}

function resetApiKeys() {
    // Restore input values from stored initial state
    document.querySelectorAll('.skills-list input[data-path]').forEach(input => {
        const path = input.dataset.path;
        input.value = initialSkillValues[path] || '';
    });

    // Reset all validation statuses and UI indicators
    document.querySelectorAll('.skill-item').forEach(item => {
        const groupPath = item.dataset.groupPath;
        skillValidationStatus[groupPath] = 'success';

        const statusElement = document.getElementById(`status-${groupPath.replace(/\./g, '-')}`);
        if (statusElement) {
            statusElement.className = 'skill-validation-status';
        }
        const messageElement = document.getElementById(`message-${groupPath.replace(/\./g, '-')}`);
        if (messageElement) {
            messageElement.textContent = '';
            messageElement.className = 'skill-validation-message';
        }
    });

    // Clear the set of modified fields for skills
    modifiedFields.skills.clear();

    // Re-enable the next button
    updateSkillsNextButtonState();
}

async function updateOllamaProviders() {
    try {
        // Load current backend config
        const backendConfig = await loadBackendConfig();
        if (!backendConfig.llm) {
            backendConfig.llm = { backend: "litellm", providers: [] };
        }

        // Get current Ollama models
        const serverIp = config.get('ollama.serverIp', '127.0.0.1');
        const port = config.get('ollama.port', 11434);
        const client = new ollama.Ollama({ host: `http://${serverIp}:${port}` });
        const modelsResponse = await client.list();
        const ollamaModels = modelsResponse.models || [];

        // Track if changes were made
        let providersModified = false;
        let selectedProviderChanged = false;

        // Get existing Ollama providers
        const existingProviders = backendConfig.llm.providers || [];
        // const existingOllamaProviders = existingProviders.filter(p => p.model.startsWith('ollama/'));
        const currentOllamaModelNames = ollamaModels.map(model => `ollama/${model.name}`);

        // Remove Ollama providers that no longer exist
        const initialProviderCount = existingProviders.length;
        backendConfig.llm.providers = existingProviders.filter(provider => {
            if (provider.model.startsWith('ollama/')) {
                return currentOllamaModelNames.includes(provider.model);
            }
            return true;
        });
        if (backendConfig.llm.providers.length !== initialProviderCount) {
            providersModified = true;
            // Check if the selected provider was removed
            const selectedProvider = backendConfig.llm.selected_provider;
            if (selectedProvider && selectedProvider.startsWith('ollama/') &&
                !backendConfig.llm.providers.some(p => p.model === selectedProvider)) {
                backendConfig.llm.selected_provider = backendConfig.llm.providers.length > 0 ?
                    backendConfig.llm.providers[0].model : null;
                selectedProviderChanged = true;
            }
        }

        // Add new Ollama models to providers if not already present
        ollamaModels.forEach(model => {
            const modelName = `ollama/${model.name}`;
            if (!existingProviders.some(provider => provider.model === modelName)) {
                backendConfig.llm.providers.push({
                    model: modelName,
                    api_base: `http://${serverIp}:${port}`,
                    context_window: 4096 // Default context window
                });
                providersModified = true;
            } else {
                // Update the api_base in case the server IP or port has changed
                const existingProvider = backendConfig.llm.providers.find(provider => provider.model === modelName);
                if (existingProvider.api_base !== `http://${serverIp}:${port}`) {
                    existingProvider.api_base = `http://${serverIp}:${port}`;
                    providersModified = true;
                }
            }
        });

        // Save changes to backend if modified
        if (providersModified) {
            await saveBackendConfig(backendConfig, config.get('pybridge.api_url'));
            if (selectedProviderChanged) {
                await saveBackendConfig(backendConfig, config.get('orakle.api_url'));
            }
            // Refresh the provider list in the LLM step UI
            await loadExistingProviders();
        }

        return { success: true, config: backendConfig };
    } catch (error) {
        console.error('Error updating Ollama providers:', error);
        return { success: false, error: error.message };
    }
}

// Function to load existing API keys from config
async function loadExistingApiKeys() {
    try {
        // Load backend config
        const backendConfig = await loadBackendConfig();

        // Helper function to get value at path
        function getValueAtPath(obj, path) {
            const parts = path.split('.');
            let current = obj;

            for (const part of parts) {
                if (current === undefined || current === null || typeof current !== 'object') {
                    return undefined;
                }
                current = current[part];
            }

            return current;
        }

        // Find all API key inputs
        document.querySelectorAll('input[data-path]').forEach(input => {
            const path = input.dataset.path;
            const value = getValueAtPath(backendConfig, path);

            if (value && value !== '<key>') {
                input.value = value;
            }
        });

    } catch (error) {
        console.error('Error loading existing API keys:', error);
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
        const testResult = document.getElementById('test-result');
        const hasExistingSelection = document.querySelector('input[name="existing-provider"]:checked');
        const isTestSuccessful = testResult.classList.contains('success') && !testResult.classList.contains('hidden');
        // console.log("hasExistingSelection: " + hasExistingSelection);
        // console.log("isTestSuccessful:" + isTestSuccessful);
        nextBtn.disabled = !(hasExistingSelection || isTestSuccessful);
        // console.log("nextBtn.disabled:" + nextBtn.disabled);
    } else if (currentStep === 'stt') {
        validateSTTForm();
    } else if (currentStep === 'skills') {
        updateSkillsNextButtonState();
    } else {
        nextBtn.disabled = false;
    }
}

function setupEventListeners() {
    // Close button
    document.querySelector('.close-btn').addEventListener('click', () => {
        event.preventDefault(); // Prevent any default behavior
        if (confirm('Do you really want to close the setup wizard?')) {
            ipcRenderer.send('close-setup-window');
        }
    });

    // Setup shortcut key capture
    setupShortcutCapture();

    // Generate Ollama UI when navigating to the Ollama step
    const ollamaObserver = new MutationObserver((mutations) => {
        mutations.forEach((mutation) => {
            if (mutation.type === 'attributes' && mutation.attributeName === 'class') {
                const ollamaPanel = document.getElementById('ollama-panel');
                if (ollamaPanel && ollamaPanel.classList.contains('active')) {
                    initializeOllamaStep().catch(err => console.error('Error initializing Ollama step:', err));
                }
            }
        });
    });
    const ollamaPanel = document.getElementById('ollama-panel');
    if (ollamaPanel) {
        ollamaObserver.observe(ollamaPanel, { attributes: true });
    }

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
    document.getElementById('test-connection-btn').addEventListener('click', testLLMConnection);

    // Setup STT event listeners
    setupSTTEventListeners();

    // Generate skills UI when navigating to the skills step
    const observer = new MutationObserver((mutations) => {
        mutations.forEach((mutation) => {
            if (mutation.type === 'attributes' && mutation.attributeName === 'class') {
                const skillsPanel = document.getElementById('skills-panel');
                if (skillsPanel && skillsPanel.classList.contains('active')) {
                    generateSkillsUI().catch(err => {
                        console.error('Error generating skills UI:', err);
                    });
                }
            }
        });
    });

    const skillsPanel = document.getElementById('skills-panel');
    if (skillsPanel) {
        observer.observe(skillsPanel, { attributes: true });
    }

    // Generate MCP UI when navigating to the MCP step
    const mcpObserver = new MutationObserver((mutations) => {
        mutations.forEach((mutation) => {
            if (mutation.type === 'attributes' && mutation.attributeName === 'class') {
                const mcpPanel = document.getElementById('mcp-panel');
                if (mcpPanel && mcpPanel.classList.contains('active')) {
                    generateMcpUI().catch(err => console.error('Error generating MCP UI:', err));
                }
            }
        });
    });
    const mcpPanel = document.getElementById('mcp-panel');
    if (mcpPanel) {
        mcpObserver.observe(mcpPanel, { attributes: true });
    }

    // Add MCP Server button listener
    const addMcpServerButton = document.getElementById('add-mcp-server-btn');
    if (addMcpServerButton) {
        addMcpServerButton.addEventListener('click', () => {
            const mcpPanel = document.getElementById('mcp-panel');
            if (mcpPanel) {
                const container = mcpPanel.querySelector('.mcp-configurations');
                if (container) {
                    addMcpServerForm(null, container); // Pass the container to add the new form into
                }
            }
        });
    }
    // Add filter input and button
    const llmPanel = document.getElementById('llm-panel');
    if (llmPanel) {
        // Add filter UI before the provider options
        const filterHtml = `
            <div class="filter-container">
                <div class="default-filter-option">
                    <input type="checkbox" id="default-filter" name="default-filter" checked>
                    <label for="default-filter">Show only recommended models</label>
                </div>
                <label for="model-filter">Filter models:</label>
                <input type="text" id="model-filter" placeholder="e.g., gpt4,haiku,claude">
                <button id="apply-filter-btn">Apply</button>
            </div>
        `;

        const providerOptions = document.getElementById('provider-options');
        if (providerOptions) {
            const addProviderHtml = `
                <div class="add-provider-section">
                    <h3>Add a New Provider</h3>
                    ${filterHtml}
                </div>
            `;
            providerOptions.insertAdjacentHTML('beforebegin', addProviderHtml);

            // Add event listeners for filter
            document.getElementById('apply-filter-btn').addEventListener('click', () => {
                loadProviders();
            });

            // Add event listener for the start minimized checkbox
            const startMinimizedCheckbox = document.getElementById('start-minimized-checkbox');
            if (startMinimizedCheckbox) {
                startMinimizedCheckbox.addEventListener('change', (event) => handleInputChange(event));
                startMinimizedCheckbox.checked = config.get('startup.startMinimized');
            }

            // Add event listener for the review stt select
            const reviewSttSelect = document.getElementById('review-stt-select');
            if (reviewSttSelect) {
                reviewSttSelect.addEventListener('change', (event) => handleInputChange(event));
                reviewSttSelect.value = config.get('stt.review');
            }

            // // Add event listener for the auto start checkbox
            // TODO delayed for v0.10
            // const autoStartCheckbox = document.getElementById('auto-start-checkbox');
            // if (autoStartCheckbox) {
            //     autoStartCheckbox.addEventListener('change', (event) => handleInputChange(event));
            //     autoStartCheckbox.checked = config.get('startup.autoStart', false);
            // }

            // Add event listener for the background notifications checkbox
            const backgroundNotificationsCheckbox = document.getElementById('background-notifications-checkbox');
            if (backgroundNotificationsCheckbox) {
                backgroundNotificationsCheckbox.addEventListener('change', (event) => handleInputChange(event));
                backgroundNotificationsCheckbox.checked = config.get('ui.backgroundNotifications');
            }

            const lowerVolumeCheckbox = document.getElementById('lower-volume-checkbox');
            if (lowerVolumeCheckbox) {
                lowerVolumeCheckbox.addEventListener('change', (event) => handleInputChange(event));
                lowerVolumeCheckbox.checked = config.get('stt.lowerVolume');
            }

            const wakeWordCheckbox = document.getElementById('wakeword-checkbox');
            if (wakeWordCheckbox) {
                wakeWordCheckbox.addEventListener('change', (event) => handleInputChange(event));
                wakeWordCheckbox.checked = config.get('wakeword.enabled');
            }

            const comringNotificationsCheckbox = document.getElementById('comring-notifications-checkbox');
            if (comringNotificationsCheckbox) {
                comringNotificationsCheckbox.addEventListener('change', (event) => handleInputChange(event));
                comringNotificationsCheckbox.checked = config.get('ui.comringNotifications');
            }

            // Add event listener for the backup directory input and browse button
            const backupDirectoryInput = document.getElementById('backup-directory-input');
            const browseBackupDirectoryBtn = document.getElementById('browse-backup-directory-btn');

            if (backupDirectoryInput) {
                backupDirectoryInput.addEventListener('input', (event) => handleInputChange(event));

                // Load from backend config, not frontend config
                (async () => {
                    try {
                        const backendConfig = await loadBackendConfig();
                        backupDirectoryInput.value = backendConfig?.backup?.directory || '';
                    } catch (error) {
                        console.error('Error loading backup directory from backend:', error);
                    }
                })();

                // Make the input clickable to trigger browse
                backupDirectoryInput.addEventListener('click', () => {
                    if (browseBackupDirectoryBtn) {
                        browseBackupDirectoryBtn.click();
                    }
                });
            }

            if (browseBackupDirectoryBtn) {
                browseBackupDirectoryBtn.addEventListener('click', () => {
                    ipcRenderer.send('select-backup-directory');
                });
            }

            // Listen for backup directory selection response
            ipcRenderer.on('backup-directory-selected', (event, directoryPath) => {
                if (backupDirectoryInput) {
                    backupDirectoryInput.value = directoryPath;
                    // Trigger change event to mark as modified
                    backupDirectoryInput.dispatchEvent(new Event('input'));
                }
            });

            // Add enter key support for filter input
            document.getElementById('model-filter').addEventListener('keypress', (e) => {
                if (e.key === 'Enter') {
                    loadProviders();
                }
            });

            // Initialize filter state based on default checkbox
            const defaultFilterCheckbox = document.getElementById('default-filter');
            if (defaultFilterCheckbox.checked) {
                const filterInput = document.getElementById('model-filter');
                const applyButton = document.getElementById('apply-filter-btn');
                const filterInputContainer = document.querySelector('.filter-container label[for="model-filter"]');

                // Apply default filter - include recommended models but exclude smaller ones
                filterInput.value = 'qwen-3,qwen3,moonshot,deepseek,-3b,xai,zai,minimax';
                // Hide filter input, label and apply button
                filterInput.style.display = 'none';
                filterInputContainer.style.display = 'none';
                applyButton.style.display = 'none';

                // Load providers with default filter
                loadProviders();
            }

            // Add event listener for default filter checkbox
            defaultFilterCheckbox.addEventListener('change', (e) => {
                const filterInput = document.getElementById('model-filter');
                const applyButton = document.getElementById('apply-filter-btn');
                const filterInputContainer = document.querySelector('.filter-container label[for="model-filter"]');
                const clearFilterBtn = document.getElementById('clear-filter-btn');

                if (e.target.checked) {
                    // Save current filter value before disabling
                    filterInput.dataset.previousValue = filterInput.value;

                    // Apply default filter - include recommended models but exclude smaller ones
                    filterInput.value = 'xai,moonshot,qwen-3,qwen3,deepseek,-3b';
                    // Hide filter input, label and apply button
                    filterInput.style.display = 'none';
                    filterInputContainer.style.display = 'none';
                    applyButton.style.display = 'none';

                    // Hide clear filter button if it exists
                    if (clearFilterBtn) {
                        clearFilterBtn.style.display = 'none';
                    }

                    // Load providers with default filter
                    loadProviders();
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
                    loadProviders();
                }
            });
        }
    }
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
        // Save data from current step (now async)
        await saveCurrentStepData();

        // Hide current step
        document.querySelector(`.step-panel.active`).classList.remove('active');
        document.querySelector(`.step.active`).classList.remove('active');

        // Show next step
        currentStepIndex++;
        document.getElementById(`${steps[currentStepIndex]}-panel`).classList.add('active');
        document.querySelector(`.step[data-step="${steps[currentStepIndex]}"]`).classList.add('active');
        console.log(currentStepIndex)
        updateButtonVisibility();

    } catch (error) {
        console.error('Error saving step data:', error);
        alert(`Error saving configuration: ${error.message}`);
    } finally {
        // Reset button
        nextButton.textContent = originalText;
        // TODO Unsure why this is here
        // nextButton.disabled = false;
    }
}

function goToPreviousStep() {
    // Hide current step
    document.querySelector(`.step-panel.active`).classList.remove('active');
    document.querySelector(`.step.active`).classList.remove('active');

    // Show previous step
    currentStepIndex--;
    document.getElementById(`${steps[currentStepIndex]}-panel`).classList.add('active');
    document.querySelector(`.step[data-step="${steps[currentStepIndex]}"]`).classList.add('active');
    updateButtonVisibility();
}

function loadProvidersWithFilter(filter = '') {
    try {
        // Show loading state
        const providerContainer = document.getElementById('provider-options');
        providerContainer.innerHTML = '<p>Loading providers...</p>';

        // Try to start pybridge if it's not running
        try {
            fetch(config.get('pybridge.api_url') + '/health');
        } catch (e) {
            console.log(e)
            // Pybridge might not be running yet, that's okay
            // The main process will handle starting it when needed
        }

        // Build the URL with filter if provided
        let url = config.get('pybridge.api_url') + '/providers';
        if (filter) {
            url += `?filter=${encodeURIComponent(filter)}`;
        }

        // Fetch providers from pybridge
        fetch(url)
            .then(response => {
                if (!response.ok) {
                    throw new Error('Failed to load providers');
                }
                return response.json();
            })
            .then(data => {
                providersData = data.providers;

                if (!providersData || Object.keys(providersData).length === 0) {
                    throw new Error('No providers available');
                }

                // Manually add website URLs
                for (const providerId in providersData) {
                    if (providerWebsites[providerId]) {
                        providersData[providerId].website = providerWebsites[providerId];
                    }
                }

                // Generate API key info
                const apiKeyInfoContainer = document.getElementById('api-key-info-container');
                if (apiKeyInfoContainer) {
                    // let linksHtml = `
                    //     <div class="api-key-info">
                    //         <p>You can get API keys from the following providers:</p>
                    //         <ul>`;
                    // const sortedProvidersForLinks = Object.values(data.providers)
                    //     .filter(p => p.website)
                    //     .sort((a, b) => a.name.localeCompare(b.name));
                    //
                    // for (const provider of sortedProvidersForLinks) {
                    //     linksHtml += `<li><a href="#" class="external-link" data-url="${provider.website}">${provider.name}</a></li>`;
                    // }
                    // linksHtml += `</ul></div>`;
                    // apiKeyInfoContainer.innerHTML = linksHtml;
                }

                // Generate provider options
                let html = '';

                // Create a sorted array of providers with custom_api first
                const sortedProviders = Object.entries(providersData).sort((a, b) => {
                    // Always put custom_api first
                    if (a[0] === 'custom_api' || a[0] === 'custom') return -1;
                    if (b[0] === 'custom_api' || b[0] === 'custom') return 1;
                    return 0;
                });

                // Start the grid container
                html += '<div class="provider-options-grid">';

                // Add each provider
                for (const [id, provider] of sortedProviders) {
                    if (id == "ollama") {
                        continue;
                    }
                    html += `
                        <div class="provider-option">
                            <input type="radio" name="llm-provider" id="${id}" value="${id}">
                            <label for="${id}">${provider.name}</label>
                        </div>
                    `;
                }

                // Close the grid container
                html += '</div>';

                providerContainer.innerHTML = html;

                // Add change event listeners
                document.querySelectorAll('input[name="llm-provider"]').forEach(radio => {
                    radio.addEventListener('change', () => {
                        // Hide test result and disable next button when provider changes
                        const testResult = document.getElementById('test-result');
                        testResult.classList.add('hidden');
                        // const nextButton = document.getElementById('main-next-btn');
                        // nextButton.disabled = true;

                        updateProviderDetailsUI();
                    });
                });

                // Add clear filter button handler
                document.getElementById('clear-filter-btn')?.addEventListener('click', () => {
                    document.getElementById('model-filter').value = '';
                    loadProviders();
                });
            })
            .catch(error => {
                // Show error state
                providerContainer.innerHTML = `
                    <p class="error">Error loading providers: ${error.message}</p>
                    <p>Please check that the application is properly installed and that PyBridge is running.</p>
                    <button id="retry-providers-btn">Retry</button>
                `;

                // Add retry button handler
                document.getElementById('retry-providers-btn')?.addEventListener('click', loadProviders);
            });
    } catch (error) {
        console.error('Error in loadProvidersWithFilter:', error);
    }
}

async function displayFeaturedModels(existingProviders = []) {
    const container = document.getElementById('featured-providers-container');
    if (!container) return;

    let tags = {
        "high_speed": { text: 'HIGH SPEED', color: '#ffc107' },
        "low_price": { text: 'LOW PRICE', color: '#9ACD32' },
        "high_intelligence": { text: 'HIGH INTELLIGENCE', color: '#007bff' },
        "free_access": { text: 'FREE ACCESS', color: '#287725' },
        "open_model": { text: 'OPEN MODEL', color: '#CD32A8' },
    }

    const featured = [
        { id: 'kimi-k2-turbo', name: 'Kimi K2 Turbo', providerId: 'moonshot', modelId: 'moonshot/kimi-k2-turbo-preview', description: 'A fast, highly smart, open model from Moonshot.', imageUrl: '../assets/providers/kimi-k2-turbo.png', tags: [ "open_model", "high_intelligence", "high_speed" ] },
        { id: 'deepseek-deepseek-chat', name: 'DeepSeek v3 (Chat)', providerId: 'deepseek', modelId: 'deepseek/deepseek-chat', description: 'DeepSeek\'s open, highly smart, very affordable model.', imageUrl: '../assets/providers/deepseek-deepseek-chat.png', contextWindow: 130072, tags: [ 'open_model', 'high_intelligence', 'low_price'  ] },
        { id: 'xai-grok-4-1-fast-non-reasoning', name: 'xAI Grok 4.1 Fast (Non Reasoning)', providerId: 'xai', modelId: 'xai/grok-4-1-fast-non-reasoning', description: 'A very fast, smart, affordable model from xAI.', imageUrl: '../assets/providers/grok-4-fast.png', tags: [ "high_speed", "high_intelligence", "low_price"  ] },
    ];

    const existingModelIds = new Set(existingProviders.map(p => p.model));

    let html = '<h3>Featured Models</h3><p style="font-size:0.9em;position:relative;margin-top:-10px;margin-bottom:10px;">Quick and easy setup, great user experience.</p><br><div class="featured-providers-grid">';
    featured.forEach(model => {
        const isConfigured = existingModelIds.has(model.modelId);
        const bannerClass = isConfigured ? 'provider-banner configured' : 'provider-banner not-configured';
        const dataAttributes = isConfigured ? '' : `data-provider-id="${model.providerId}" data-model-id="${model.modelId}"`;
        const contextWindowData = isConfigured || !model.contextWindow ? '' : `data-context-window="${model.contextWindow}"`;
        const tagsHtml = model.tags.map(tag => `<span class="provider-tag" style="background-color: ${tags[tag].color};">${tags[tag].text}</span>`).join('');

        html += `
            <div class="provider-banner-wrapper">
                <div class="${bannerClass}" ${dataAttributes} ${contextWindowData}  style="background-image: url('${model.imageUrl}');">
                    <div class="provider-banner-overlay">
                        <div class="provider-banner-content">
                            <h4>${model.name}</h4>
                            <p>${model.description}</p>
                        </div>
                        <div class="provider-tags">
                            ${tagsHtml}
                        </div>
                    </div>
                </div>
                ${isConfigured ? `
                    <div class="configured-status">
                        <span class="checkmark">✔</span> <p>Model Configured</p>
                    </div>
                ` : ''}
            </div>
        `;
    });
    html += '</div>';

    container.innerHTML = html;
    container.style.display = 'block';

    // Add event listeners only to non-configured banners
    document.querySelectorAll('.provider-banner.not-configured').forEach(banner => {
        // banner.addEventListener('click', async (event) => {
        banner.addEventListener('click', async () => {
            const defaultFilterCheckbox = document.getElementById('default-filter');
            // ensure filter configuration is default, this assumes featured models
            // always will be present in the default configuration
            if (defaultFilterCheckbox && !defaultFilterCheckbox.checked) {
                defaultFilterCheckbox.click();
                // Wait for the DOM to update
                await new Promise(resolve => setTimeout(resolve, 100));
            }

            const providerId = banner.dataset.providerId;
            const modelId = banner.dataset.modelId;
            const radio = document.getElementById(providerId);

            if (radio) {
                radio.click();

                // Now, select the model in the dropdown
                const modelSelect = document.getElementById(`${providerId}-model`);
                if (modelSelect) {
                    modelSelect.value = modelId;
                }
                const modelWindow = document.getElementById(`${providerId}-context_window`);
                if (banner.dataset.contextWindow && modelWindow) {
                    modelWindow.value = banner.dataset.contextWindow;
                }
                // Scroll to the details section
                const details = document.getElementById('provider-details');
                if (details) {
                    details.scrollIntoView({ behavior: 'smooth', block: 'center' });
                }
                const apiKeyInput = document.getElementById(`${providerId}-api_key`);
                apiKeyInput?.focus();
                if (apiKeyInput) {
                    apiKeyInput.disabled = false;
                }
                if (apiKeyInput) apiKeyInput.value = "";
            }
        });
    });
}

// Replace the existing loadProviders function
async function loadProviders() {
    // First load existing providers from backend config
    const nextButton = document.getElementById('main-next-btn');
    const testResult = document.getElementById('test-result');

    // Reset UI state related to new provider testing and assume button is disabled initially.
    // It will be enabled by loadExistingProviders if a valid selection exists,
    // or by testLLMConnectionFetch if a new provider is successfully tested.
    testResult.classList.add('hidden');
    nextButton.disabled = true;

    await loadExistingProviders(); // This might enable nextButton if an existing provider is selected.

    const filter = document.getElementById('model-filter')?.value || '';
    loadProvidersWithFilter(filter);
}

// // Function to get local Ollama models
// async function getLocalOllamaModels() {
//     try {
//         const serverIp = config.get('ollama.serverIp', '127.0.0.1');
//         const port = config.get('ollama.port', 11434);
//         const client = new ollama.Ollama({ host: `http://${serverIp}:${port}` });
//         const models = await client.list();
//         console.log("Local Ollama Models for Providers:", models.models);
//         return models.models ? models.models.map(model => ({
//             name: model.name,
//             contextWindow: 4096 // Default context window; adjust if Ollama provides this info
//         })) : [];
//     } catch (error) {
//         console.error('Error fetching local Ollama models for providers:', error);
//         return [];
//     }
// }

// Add new function to load existing providers
async function loadExistingProviders() {
    try {
        // First, update Ollama providers to ensure the list is current
        await updateOllamaProviders();

        const backendConfig = await loadBackendConfig();
        let existingProviders = backendConfig?.llm?.providers || [];
        const selectedProvider = backendConfig?.llm?.selected_provider;

        // Display recommended models if they are not configured
        await displayFeaturedModels(existingProviders);

        // Create a container for existing providers if it doesn't exist
        let existingContainer = document.getElementById('existing-providers');
        if (!existingContainer) {
            const addProviderSection = document.querySelector('.add-provider-section');
            if (addProviderSection) {
                addProviderSection.insertAdjacentHTML('beforebegin', `
         <div class="existing-providers-section">
                        <h3>Your Configured Providers</h3>
                        <p>Select one of your existing providers or configure a new one below.</p>
                        <div id="existing-providers"></div>
                    </div>
                `);
                existingContainer = document.getElementById('existing-providers');
            }
        }

        if (!existingContainer) return;

        // Clear existing content
        existingContainer.innerHTML = '';

        if (existingProviders.length === 0) {
            existingContainer.innerHTML = '<p>No providers configured yet.</p>';
            return;
        }

        // Add each existing provider
        existingProviders.forEach((provider, index) => {
            const providerId = `existing-${index}`;
            const isOllamaModel = provider.model.startsWith('ollama/');
            const providerModel = isOllamaModel ?
                `Ollama: ${provider.model.split('/')[1]}` :
                provider.model;
            const isSelected = selectedProvider === provider.model;

            existingContainer.innerHTML += `
                <div class="existing-provider ${isSelected ? 'selected' : ''} ${isOllamaModel ? 'ollama-provider' : ''}">
                    <input type="radio" name="existing-provider" id="${providerId}"
                        value="${index}" ${isSelected ? 'checked' : ''}>
                    <label for="${providerId}">
                        <strong>${providerModel}</strong><br>
                        ${provider.api_base ? `API: ${provider.api_base}` : ''}
                        ${provider.context_window ? `Context: ${(provider.context_window / 1024).toFixed(2)}K` : ''}
                    </label>
                    <button class="delete-provider-btn" data-index="${index}" title="Delete this provider">
                        &times;
                    </button>
                </div>
            `;
        });

        // If there are existing providers, enable the next button
        // This allows users to proceed without configuring a new provider
        if (existingProviders.length > 0) {
            // Check if any existing provider is selected
            const hasSelectedProvider = document.querySelector('input[name="existing-provider"]:checked');

            // If a provider is already selected enable the next button
            if (hasSelectedProvider && steps[currentStepIndex] === 'llm') {
                document.getElementById('main-next-btn').disabled = false;
            }
        }

        // Add some styling for Ollama providers
        const style = document.createElement('style');
        style.textContent = `
            .ollama-provider {
                background-color: #d0e8ff;
                /*border-left: 3px solid #1e90ff;*/
            }
        `;
        if (!document.getElementById('ollama-provider-style')) {
            style.id = 'ollama-provider-style';
            document.head.appendChild(style);
        }

        // Add event listeners for existing provider selection
        document.querySelectorAll('input[name="existing-provider"]').forEach(radio => {
            radio.addEventListener('change', async () => {
                // When an existing provider is selected, update the UI
                if (radio.checked) {
                    // Uncheck any new provider selection
                    document.querySelectorAll('input[name="llm-provider"]').forEach(newRadio => {
                        newRadio.checked = false;
                    });

                    // Update selected styling
                    document.querySelectorAll('.existing-provider').forEach(el => {
                        el.classList.remove('selected');
                    });
                    radio.closest('.existing-provider').classList.add('selected');

                    // Hide provider details
                    document.getElementById('provider-details').innerHTML = '';

                    // Enable the next button if we are in llm panel
                    if (steps[currentStepIndex] === 'llm') {
                        document.getElementById('main-next-btn').disabled = false;
                    }

                    // Hide test result
                    document.getElementById('test-result').classList.add('hidden');

                    // Save new LLM config after changing selected provider
                    let errorMsg = await updateSelectedLLMProvider(radio.value)
                    if (errorMsg) {
                        console.error("Error saving provider selection:", errorMsg);
                    }
                }
            });
        });

        // Add event listeners for delete buttons
        document.querySelectorAll('.delete-provider-btn').forEach(button => {
            button.addEventListener('click', async (event) => {
                event.preventDefault();
                event.stopPropagation();

                const index = parseInt(button.dataset.index);
                const provider = existingProviders[index];
                const providerName = provider.name || `Provider ${index + 1}`;

                // Ask for confirmation
                if (confirm(`Are you sure you want to delete the provider "${providerName}"?`)) {
                    await deleteProvider(index);
                }
            });
        });
    } catch (error) {
        console.error('Error loading existing providers:', error);
    }
}

// Function specifically for selecting an existing provider
async function updateSelectedLLMProvider(providerIndex) {
    try {
        // Load current backend config
        const backendConfig = await loadBackendConfig();

        if (!backendConfig.llm || !Array.isArray(backendConfig.llm.providers)) {
            console.error("LLM providers configuration is missing or invalid.");
            return "Error: LLM configuration is invalid.";
        }

        // Find the selected provider object
        const selectedProvider = backendConfig.llm.providers[providerIndex];

        if (!selectedProvider) {
            console.error(`Selected existing provider at index ${providerIndex} not found in config.`);
            return `Error: Selected provider not found in configuration.`;
        }

        // Update the selected provider key
        backendConfig.llm.selected_provider = selectedProvider.model;

        console.log("Selecting existing provider:", backendConfig.llm.selected_provider);

        // Save the updated backend config to both servers
        await saveBackendConfig(backendConfig, config.get('pybridge.api_url'));
        await saveBackendConfig(backendConfig, config.get('orakle.api_url'));

    } catch (error) {
        console.error('Error selecting existing LLM provider:', error);
        return `Error saving provider selection: ${error.message}`;
    }
    return null; // Indicate success
}

function updateProviderDetailsUI() {
    const selectedProviderId = document.querySelector('input[name="llm-provider"]:checked')?.value;
    const detailsContainer = document.getElementById('provider-details');
    const testButton = document.getElementById('test-connection-btn');
    const testResult = document.getElementById('test-result');

    // Hide test result and disable next button when provider changes
    testResult.classList.add('hidden');
    // const nextButton = document.getElementById('main-next-btn');
    // nextButton.disabled = true;

    if (!selectedProviderId || !providersData || !providersData[selectedProviderId]) {
        detailsContainer.innerHTML = '';
        testButton.disabled = true;
        return;
    }

    const provider = providersData[selectedProviderId];

    let html = `
        <h3>${provider.name} Configuration</h3>
    `;

    // Add fields
    provider.fields.forEach(field => {
        // Check if this is an API Base URL field and if we should show it
        const isApiBaseField = field.id === 'api_base' || field.id === 'base_url';
        const isCustomProvider = selectedProviderId === 'custom' || selectedProviderId === 'custom_api';

        if (isCustomProvider && field.id == "model") {
            field.required = true;
        }

        // Skip API Base URL field if not using custom provider
        if (selectedProviderId != "ollama" && isApiBaseField && !isCustomProvider) {
            return;
        }

        const isApiKeyField = field.id.toLowerCase().includes('api_key');
        let apiKeyLink = '';
        if (isApiKeyField && provider.website) {
            apiKeyLink = ` <a href="#" class="external-link get-api-key-link" data-url="${provider.website}">Get a new API key</a>`;
        }

        html += `
            <div class="form-group">
                <label for="${selectedProviderId}-${field.id}">${field.name}:${apiKeyLink}</label>
                <input
                    type="${field.type}"
                    id="${selectedProviderId}-${field.id}"
                    ${field.placeholder ? `placeholder="<custom server url:port>"` : ''}
                    ${field.required ? 'required' : ''}
                >
            </div>
        `;
    });
                    // ${isCustomProvider && isApiBaseField ? `value="http://192.168.1.200:7080"` : ``}
                    // ${isCustomProvider && field.id === 'model' ? `value="openai/gamingpc"` : ``}

    // Add model selection if available
    if (provider.models && provider.models.length > 0) {
        html += `
            <div class="form-group">
                <label for="${selectedProviderId}-model">Model:</label>
                <select id="${selectedProviderId}-model">
        `;

        provider.models.forEach(model => {
            let context_window = model.context_window ?
                "(C" + Math.round(model.context_window / 1024) + "K)" :
                "";
            html += `<option value="${model.id}" ${model.default ? 'selected' : ''}>${model.name} ${context_window}</option>`;
        });

        html += `
                </select>
            </div>
        `;
    }

    // Add optional context window override field
    html += `
        <div class="form-group">
            <label for="${selectedProviderId}-context_window">Context Window (Optional, don't change unless confident about it):</label>
            <input
                type="number"
                step="2048"
                min="0"
                id="${selectedProviderId}-context_window"
                placeholder="e.g., 4096"
            >
            <p class="field-description">Override the default context window size for this model. Leave blank to use the model's default or LiteLLM's detected value.</p>
        </div>
    `;
    detailsContainer.innerHTML = html;

    // Enable test button
    testButton.disabled = false;

    // Add input event listeners for validation
    detailsContainer.querySelectorAll('input, select').forEach(input => {
        input.addEventListener('input', (event) => handleInputChange(event,false));
    });

    validateProviderForm();
}

// New function to handle input changes
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
            modifiedFields.skills.add(field.dataset.path);

            const groupItem = field.closest('.skill-item');
            const groupPath = groupItem.dataset.groupPath;

            let isGroupModified = false;
            groupItem.querySelectorAll('input[data-path]').forEach(input => {
                const path = input.dataset.path;
                if (input.value && input.value !== initialSkillValues[path]) {
                    isGroupModified = true;
                }
            });

            const statusElement = document.getElementById(`status-${groupPath.replace(/\./g, '-')}`);
            const messageElement = document.getElementById(`message-${groupPath.replace(/\./g, '-')}`);

            if (isGroupModified) {
                skillValidationStatus[groupPath] = 'unvalidated';
            } else {
                // All fields in the group are back to their initial state
                skillValidationStatus[groupPath] = 'success';
            }

            // Always clear validation UI on change, forcing a re-validation for modified groups
            if (statusElement) statusElement.className = 'skill-validation-status';
            if (messageElement) {
                messageElement.textContent = '';
                messageElement.className = 'skill-validation-message';
            }
            updateSkillsNextButtonState();
        } else if (fieldId.includes('custom-api')) {
            modifiedFields.stt.add(fieldId);
        } else if (fieldId.startsWith('mcp-')) {
            modifiedFields.mcp.add(field.closest('.mcp-server-form')?.dataset.serverId || 'mcp_general');
        } else if (fieldId === 'start-minimized-checkbox' || fieldId === 'review-stt-select' || fieldId === 'background-notifications-checkbox' || fieldId === 'backup-directory-input' || fieldId === 'auto-start-checkbox' || fieldId == 'lower-volume-checkbox' || fieldId === 'wakeword-checkbox' || fieldId == 'comring-notifications-checkbox') {
            modifiedFields.finish.add(fieldId);
        } else {
            // LLM fields
            modifiedFields.llm.add(fieldId);
        }
    }

    // Also validate the form
    validateProviderForm();
}

// Function to load and display capabilities
async function loadAndDisplayCapabilities() {
    const listElement = document.getElementById('capabilities-list');
    if (!listElement) return;

    listElement.innerHTML = '<li class="loading">Loading capabilities...</li>';

    try {
        const response = await fetch(config.get('orakle.api_url') + '/capabilities');
        if (!response.ok) {
            throw new Error(`Failed to fetch capabilities: ${response.status} ${response.statusText}`);
        }

        const data = await response.json();
        if (!data || typeof data !== 'object' || Object.keys(data).length === 0) {
            listElement.innerHTML = '<li class="info">No specific capabilities listed by the backend.</li>';
            return;
        }

        const groups = {
            native: [],
            nexus: [],
            mcp: [],
            user: [],
            other: []
        };

        Object.entries(data).forEach(([skillId, skill]) => {
            const entry = {
                id: skillId,
                description: (skill.description || '').trim().split('\n')[0],
                bundle: skill.bundle || '',
                server: skill.server || ''
            };

            switch (skill.type) {
                case 'skill':
                    groups.native.push(entry);
                    break;
                case 'nexus':
                    groups.nexus.push(entry);
                    break;
                case 'mcp':
                    groups.mcp.push(entry);
                    break;
                case 'user_skill':
                    groups.user.push(entry);
                    break;
                default:
                    groups.other.push(entry);
            }
        });

        const renderEntries = (entries) => entries
            .sort((a, b) => a.id.localeCompare(b.id))
            .map(entry => {
                const suffix = entry.server ? ` <em>(server: ${entry.server})</em>` : '';
                return `<li><code>${entry.id}</code> — ${entry.description}${suffix}</li>`;
            })
            .join('');

        const renderGroup = (title, entries) => {
            if (entries.length === 0) return '';
            return `
                <div class="capability-group">
                    <h3>${title}</h3>
                    <ul>${renderEntries(entries)}</ul>
                </div>
            `;
        };

        const sections = [];

        sections.push(renderGroup('Native Skills', groups.native));

        const nexusByBundle = {};
        groups.nexus.forEach(entry => {
            const bundle = entry.bundle || 'General';
            if (!nexusByBundle[bundle]) nexusByBundle[bundle] = [];
            nexusByBundle[bundle].push(entry);
        });

        Object.keys(nexusByBundle)
            .sort((a, b) => a.localeCompare(b))
            .forEach(bundle => {
                const title = `Nexus Skills — ${bundle.charAt(0).toUpperCase() + bundle.slice(1)}`;
                sections.push(renderGroup(title, nexusByBundle[bundle]));
            });

        sections.push(renderGroup('MCP Servers', groups.mcp));
        sections.push(renderGroup('User Skills', groups.user));
        sections.push(renderGroup('Other Capabilities', groups.other));

        listElement.innerHTML = sections.filter(Boolean).join('') || '<li class="info">No capabilities available.</li>';
    } catch (error) {
        console.error('Error loading capabilities:', error);
        listElement.innerHTML = `<li class="error">Failed to load capabilities: ${error.message}</li>`;
    }
}

async function validateAllApiKeys() {
    const validateButton = document.getElementById('validate-all-keys-btn');
    validateButton.disabled = true;
    validateButton.textContent = 'Validating...';

    const validationPromises = [];
    const groupsToValidate = [];

    document.querySelectorAll('.skill-item').forEach(item => {
        const groupPath = item.dataset.groupPath;
        const serviceName = groupPath.split('.').pop();
        const statusElement = document.getElementById(`status-${groupPath.replace(/\./g, '-')}`);
        const messageElement = document.getElementById(`message-${groupPath.replace(/\./g, '-')}`);
        if (messageElement) {
            messageElement.textContent = '';
            messageElement.className = 'skill-validation-message';
        }

        let hasValue = false;
        const keys = {};
        item.querySelectorAll('input[data-path]').forEach(input => {
            const value = input.value.trim();
            if (value) {
                hasValue = true;
            }
            const keyName = input.dataset.path.split('.').pop();
            keys[keyName] = value;
        });

        if (hasValue) {
            groupsToValidate.push({ groupPath, serviceName, keys, statusElement, messageElement });
        } else {
            // If no value, it's considered valid for progression, clear status
            if (statusElement) statusElement.className = 'skill-validation-status';
            if (messageElement) messageElement.textContent = '';
            skillValidationStatus[groupPath] = 'success';
        }
    });

    groupsToValidate.forEach(group => {
        if (group.statusElement) {
            group.statusElement.className = 'skill-validation-status pending';
        }
        skillValidationStatus[group.groupPath] = 'validating';

        const promise = fetch(
            config.get('pybridge.api_url') + '/test-skill-key',
            {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ service: group.serviceName, keys: group.keys })
            }
        )
        .then(response => response.json())
        .then(result => ({ ...group, result }))
        .catch(error => ({ ...group, result: { success: false, message: error.message } }));

        validationPromises.push(promise);
    });

    const results = await Promise.all(validationPromises);

    results.forEach(res => {
        if (res.result.success) {
            if (res.statusElement) res.statusElement.className = 'skill-validation-status success';
            skillValidationStatus[res.groupPath] = 'success';
            if (res.messageElement) {
                res.messageElement.textContent = 'Success!';
                res.messageElement.className = 'skill-validation-message success';
            }
        } else {
            if (res.statusElement) res.statusElement.className = 'skill-validation-status error';
            skillValidationStatus[res.groupPath] = 'error';
            if (res.messageElement) {
                res.messageElement.textContent = `Failed: ${res.result.message || 'Unknown error'}`;
                res.messageElement.className = 'skill-validation-message error';
            }
        }
    });

    updateSkillsNextButtonState();

    validateButton.disabled = false;
    validateButton.textContent = 'Validate API Keys';
}

function updateSkillsNextButtonState() {
    const nextButton = document.getElementById('main-next-btn');
    if (!nextButton) return;

    const allValid = Object.values(skillValidationStatus).every(status => status === 'success');
    if (steps[currentStepIndex] === 'skills') {
        nextButton.disabled = !allValid;
    }
}

function validateProviderForm() {
    const selectedProviderId = document.querySelector('input[name="llm-provider"]:checked')?.value;
    const testButton = document.getElementById('test-connection-btn');

    if (!selectedProviderId || !providersData || !providersData[selectedProviderId]) {
        testButton.disabled = true;
        return;
    }

    const provider = providersData[selectedProviderId];

    // Check if all required fields are filled
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

// Function to generate MCP UI
async function generateMcpUI() {
    const mcpPanel = document.getElementById('mcp-panel');
    if (!mcpPanel) return;

    let container = mcpPanel.querySelector('.mcp-configurations');
    if (!container) {
        mcpPanel.innerHTML = `<h2>MCP Server Configuration</h2>
                              <p>Configure connections to Model-Context-Protocol (MCP) compatible servers.</p>
                              <div class="mcp-configurations"></div>
                              <button id="add-mcp-server-btn" class="btn">Add MCP Server</button>`;
        container = mcpPanel.querySelector('.mcp-configurations');
        // The button listener is now handled in setupEventListeners
    }
    container.innerHTML = '<p>Loading MCP configurations...</p>'; // Clear previous content, show loading

    try {
        const backendConfig = await loadBackendConfig();
        const mcpClients = backendConfig.mcp_clients || {};
        container.innerHTML = ''; // Clear loading message

        if (Object.keys(mcpClients).length === 0) {
            container.innerHTML = '<p>No MCP servers configured yet. Click "Add MCP Server" to begin.</p>';
        } else {
            for (const serverName in mcpClients) {
                addMcpServerForm(serverName, container, mcpClients[serverName]);
            }
        }
    } catch (error) {
        console.error('Error loading MCP configurations:', error);
        container.innerHTML = `<p class="error">Error loading MCP configurations: ${error.message}</p>`;
    }
}

function addMcpServerForm(serverName, container, serverConfig = {}) {
    const serverId = serverName || `new-mcp-${Date.now()}`;
    const formHtml = `
        <div class="mcp-server-form" data-server-id="${serverId}">
            <h4>${serverName ? `Edit Server: ${serverName}` : 'New MCP Server'}</h4>
            <div class="form-group">
                <label for="mcp-name-${serverId}">Server Name:</label>
                <input type="text" id="mcp-name-${serverId}" class="mcp-server-name" value="${serverName || ''}" ${serverName ? 'disabled' : ''} placeholder="e.g., my_home_server" required>
                ${serverName ? '' : '<p class="field-description">Unique identifier for this server. Cannot be changed after creation.</p>'}
            </div>
            <div class="form-group">
                <label for="mcp-prefix-${serverId}">Prefix (Optional):</label>
                <input type="text" id="mcp-prefix-${serverId}" class="mcp-prefix" value="${serverConfig.prefix || ''}" placeholder="e.g., home.">
            </div>
            <div class="form-group">
                <label for="mcp-command-${serverId}">Command (and arguments, one per line):</label>
                <textarea id="mcp-command-${serverId}" class="mcp-command" rows="3" placeholder="my_command\n--arg1\nvalue1">${(serverConfig.stdio_params && serverConfig.stdio_params.command ? serverConfig.stdio_params.command.join('\n') : '')}</textarea>
            </div>
            <h5>Environment Variables:</h5>
            <div class="mcp-env-vars" id="mcp-env-vars-${serverId}">
                ${serverConfig.stdio_params && serverConfig.stdio_params.env ? Object.entries(serverConfig.stdio_params.env).map(([key, value]) => addMcpEnvVarForm(key, value, serverId, false)).join('') : ''}
            </div>
            <button class="btn btn-sm add-mcp-env-btn" data-server-id="${serverId}">Add Environment Variable</button>
            <button class="btn btn-sm btn-danger remove-mcp-server-btn" data-server-id="${serverId}" style="margin-left: 10px;">Remove Server</button>
            <hr>
        </div>
    `;
    container.insertAdjacentHTML('beforeend', formHtml);

    const serverForm = container.querySelector(`.mcp-server-form[data-server-id="${serverId}"]`);

    serverForm.querySelector('.add-mcp-env-btn').addEventListener('click', (e) => {
        const currentServerId = e.target.dataset.serverId;
        const envVarsContainer = serverForm.querySelector(`#mcp-env-vars-${currentServerId}`);
        addMcpEnvVarForm(null, null, currentServerId, true, envVarsContainer);
        modifiedFields.mcp.add(currentServerId); // Mark server as modified
    });

    serverForm.querySelector('.remove-mcp-server-btn').addEventListener('click', async (e) => { // Make async
        if (confirm('Are you sure you want to remove this MCP server configuration?')) {
            const currentServerId = e.target.dataset.serverId;
            const removeButton = e.target;
            const originalButtonText = removeButton.textContent;

            // Remove from UI first
            serverForm.remove();

            // Mark that a change occurred for MCP.
            // saveMcpConfig will use this and then clear it.
            modifiedFields.mcp.add(currentServerId);

            removeButton.textContent = 'Removing...';
            removeButton.disabled = true;

            try {
                // Immediately save the MCP configuration
                await saveMcpConfig();
            } catch (error) {
                console.error("Failed to save MCP config after removal:", error);
                alert("Error removing server. The server configuration might not have been saved correctly. The server might reappear if you refresh or navigate. Please check the console for details.");
                // If save fails, the UI is out of sync. Regenerating MCP UI from backend might be an option,
                // but could lose other unsaved changes. Alerting is the simplest first step.
            } finally {
                // Button is part of the removed form, so it won't be visible if successful.
                // This is more for if the removal/save failed and the button somehow remains.
                if (document.body.contains(removeButton)) {
                    removeButton.textContent = originalButtonText;
                    removeButton.disabled = false;
                }
            }
        }
    });

    serverForm.querySelectorAll('input, textarea').forEach(input => {
        input.addEventListener('input', () => modifiedFields.mcp.add(serverId));
    });
}

function addMcpEnvVarForm(key, value, serverId, appendToDom = true, container = null) {
    const envVarId = `env-${serverId}-${Date.now()}`;
    const envVarHtml = `
        <div class="mcp-env-var-item" data-env-id="${envVarId}">
            <input type="text" class="mcp-env-key" placeholder="KEY" value="${key || ''}">
            <span>=</span>
            <input type="text" class="mcp-env-value" placeholder="VALUE" value="${value || ''}">
            <button class="btn btn-xs btn-danger remove-mcp-env-btn" data-env-id="${envVarId}">&times;</button>
        </div>
    `;

    if (appendToDom && container) {
        container.insertAdjacentHTML('beforeend', envVarHtml);
        const newItem = container.querySelector(`.mcp-env-var-item[data-env-id="${envVarId}"]`);
        newItem.querySelector('.remove-mcp-env-btn').addEventListener('click', () => {
            newItem.remove();
            modifiedFields.mcp.add(serverId); // Mark server as modified
        });
        newItem.querySelectorAll('input').forEach(input => {
            input.addEventListener('input', () => modifiedFields.mcp.add(serverId));
        });
    }
    return envVarHtml;
}

async function testLLMConnection() {
    event.stopPropagation(); // Prevent event from bubbling up
    const selectedProviderId = document.querySelector('input[name="llm-provider"]:checked')?.value;

    if (!selectedProviderId || !providersData || !providersData[selectedProviderId]) {
        return;
    }

    // Show loading state
    const testButton = document.getElementById('test-connection-btn');
    const originalText = testButton.textContent;
    testButton.textContent = 'Testing...';
    testButton.disabled = true;

    // Reset test result
    const testResult = document.getElementById('test-result');
    testResult.textContent = "";
    testResult.classList.add('hidden');

    await testLLMConnectionFetch(getLLMConfig());

    // Reset button immediately after response is received
    testButton.textContent = originalText;
    validateProviderForm();
}

async function testLLMConnectionFetch(llmConfig) {
    var result;
    try {
        const testResult = document.getElementById('test-result');
        testResult.classList.remove('hidden', 'success', 'error');
        // testResult.classList.add('success');
        // testResult.textContent = JSON.stringify(llmConfig);
        // return;

        Logger.log('Setup: Testing LLM connection via IPC with config:', JSON.stringify({
            provider: llmConfig.provider,
            model: llmConfig.model,
            // Don't log API keys if they were included
            api_base: llmConfig.api_base
        }));

        // Make a request to the dedicated test-llm endpoint
        const response = await fetch(
            config.get('pybridge.api_url') + "/test-llm", {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(llmConfig)
            }
        );

        // Logger.log(JSON.stringify(response)) // This logs the Response object, not the body

        testResult.classList.remove('hidden', 'success', 'error');
        result = await response.json();
        Logger.log('Setup: Received test result from pybridge:', result);

        if (response.ok && result.success) {
            testResult.textContent = 'Connection successful! LLM is working properly.';
            testResult.classList.add('success');
            // Mark the provider as modified when test is successful
            const selectedProviderId = document.querySelector('input[name="llm-provider"]:checked')?.value;
            if (selectedProviderId) {
                modifiedFields.llm.add(selectedProviderId);
            }

            let error_msg = await saveLLMConfig();
            if (error_msg) { // saveLLMConfig returns error message string or null
                testResult.textContent = error_msg;
                testResult.classList.remove('hidden', 'success');
                testResult.classList.add('error');
            } else {
                testResult.textContent += ' Provider registered.'; // Append registration message
                document.getElementById('main-next-btn').disabled = false;
            }
        } else {
            testResult.classList.add('error');
            testResult.textContent = `Connection failed: ${result.message}`;
        }

    } catch (error) {
        Logger.error('Setup: LLM connection test failed:', error);
        // console.log('LLM connection test failed:', error.message);
        const testResult = document.getElementById('test-result');
        testResult.classList.add('error');
        testResult.textContent = `Failed to test LLM provider: ${error.message || JSON.stringify(result || 'Unknown error')}`;
    }
}

function getLLMConfig() {
    const selectedProviderId = document.querySelector('input[name="llm-provider"]:checked')?.value;

    if (!providersData || !providersData[selectedProviderId]) {
        return null;
    }

    const provider = providersData[selectedProviderId];

    // Build the configuration object
    const config = {
        provider: selectedProviderId
    };

    // Add fields
    provider.fields.forEach(field => {
        const input = document.getElementById(`${selectedProviderId}-${field.id}`);
        if (input && input.value.trim()) {
            config[field.id] = input.value.trim();
        }
    });

    // Add model if available
    const modelSelect = document.getElementById(`${selectedProviderId}-model`);
    if (modelSelect) {
        config.model = normalizeModelName(modelSelect.value, selectedProviderId);
    }

    // Add context window if provided
    const contextWindowInput = document.getElementById(`${selectedProviderId}-context_window`);
    if (contextWindowInput && contextWindowInput.value.trim()) {
        const contextWindowValue = parseInt(contextWindowInput.value.trim(), 10);
        if (!isNaN(contextWindowValue) && contextWindowValue > 0) {
            config.context_window = contextWindowValue;
        }
    }
    return config;
}

function validateCurrentStep() {
    const currentStep = steps[currentStepIndex];

    switch (currentStep) {
        case 'welcome':
            return true;
        case 'ollama':
            return true; // No strict validation needed; user can skip if no models are downloaded
        case 'llm':
            // LLM step is valid if the next button is enabled (after successful test)
            return !document.getElementById('main-next-btn').disabled;
        case 'mcp':
            // Basic validation: ensure server names are unique if multiple servers
            return validateMcpStep();
        case 'stt':
            // STT step is valid if the next button is enabled
            return !document.getElementById('main-next-btn').disabled;
        case 'skills':
            return true; // Skills are optional
        default:
            return true;
    }
}

function validateMcpStep() {
    const serverForms = document.querySelectorAll('#mcp-panel .mcp-server-form');
    const serverNames = new Set();
    for (const form of serverForms) {
        const nameInput = form.querySelector('.mcp-server-name');
        const serverName = nameInput.value.trim();
        if (!serverName && serverForms.length > 0) { // Allow empty if no servers defined
            // alert('MCP Server Name cannot be empty.'); nameInput.focus(); return false;
        }
        if (serverName && serverNames.has(serverName)) {
            alert(`Duplicate MCP Server Name: ${serverName}. Names must be unique.`); nameInput.focus(); return false;
        }
        if (serverName) serverNames.add(serverName);
    }
    return true;
}

// Add event listeners for STT options
async function setupSTTEventListeners() {
    const sttNextButton = document.getElementById('main-next-btn');
    const languageSelect = document.getElementById('stt-language-select');
    const voiceSelect = document.getElementById('tts-voice-select');
    const warningDiv = document.getElementById('stt-ram-warning');

    // Define supported languages (Intersection of Faster-Whisper and Kokoro)
    const sttLanguages = [
        { code: 'en', name: 'English', flag: '🇬🇧' },
        { code: 'es', name: 'Spanish (Español)', flag: '🇪🇸' },
        { code: 'fr', name: 'French (Français)', flag: '🇫🇷' },
        { code: 'it', name: 'Italian (Italiano)', flag: '🇮🇹' },
        { code: 'pt', name: 'Portuguese (Português)', flag: '🇵🇹' },
        // { code: 'ja', name: 'Japanese (日本語)', flag: '🇯🇵', highMem: true },
        // { code: 'zh', name: 'Chinese (中文)', flag: '🇨🇳', highMem: true },
        { code: 'hi', name: 'Hindi (हिन्दी)', flag: '🇮🇳', highMem: true },
    ];

    // Kokoro Voice Data
    const kokoroVoices = {
        'en': [ // English (US & UK)
            { id: 'af_heart',   name: 'Heart',   lang: 'en-us', flag: '🇺🇸', grade: 'A',  desc: 'High quality' },
            { id: 'af_bella',   name: 'Bella',   lang: 'en-us', flag: '🇺🇸', grade: 'A-', desc: 'High quality' },
            { id: 'af_nicole',  name: 'Nicole',  lang: 'en-us', flag: '🇺🇸', grade: 'B-', desc: 'Good quality' },
            { id: 'bf_emma',    name: 'Emma',    lang: 'en-gb', flag: '🇬🇧', grade: 'B-', desc: 'Good quality' },
            // { id: 'af_alloy',   name: 'Alloy',   lang: 'en-us', flag: '🇺🇸', grade: 'C',  desc: 'Average quality' },
            { id: 'bf_isabella',name: 'Isabella',lang: 'en-gb', flag: '🇬🇧', grade: 'C',  desc: 'Average quality' },
            // { id: 'bf_fable',   name: 'Fable',   lang: 'en-gb', flag: '🇬🇧', grade: 'C',  desc: 'Average quality' },
            // { id: 'bf_george',  name: 'George',  lang: 'en-gb', flag: '🇬🇧', grade: 'C',  desc: 'Average quality' }
        ],
        'es': [ // Spanish
            { id: 'ef_dora',  name: 'Dora',  lang: 'es', flag: '🇪🇸', grade: '', desc: 'Female' },
            { id: 'em_alex',  name: 'Alex',  lang: 'es', flag: '🇪🇸', grade: '', desc: 'Male' },
            { id: 'em_santa', name: 'Santa', lang: 'es', flag: '🇪🇸', grade: '', desc: 'Male' }
        ],
        'fr': [ // French
            { id: 'ff_siwis', name: 'Siwis', lang: 'fr-fr', flag: '🇫🇷', grade: 'B-', desc: 'Female' }
        ],
        'it': [ // Italian
            { id: 'if_sara',   name: 'Sara',   lang: 'it', flag: '🇮🇹', grade: 'C', desc: 'Female' },
            { id: 'im_nicola', name: 'Nicola', lang: 'it', flag: '🇮🇹', grade: 'C', desc: 'Male' }
        ],
        'pt': [ // Portuguese (Brazilian)
            { id: 'pf_dora',  name: 'Dora',  lang: 'pt-br', flag: '🇧🇷', grade: '', desc: 'Female' },
            { id: 'pm_alex',  name: 'Alex',  lang: 'pt-br', flag: '🇧🇷', grade: '', desc: 'Male' },
            { id: 'pm_santa', name: 'Santa', lang: 'pt-br', flag: '🇧🇷', grade: '', desc: 'Male' }
        ],
        'ja': [ // Japanese
            { id: 'jf_alpha',      name: 'Alpha',      lang: 'ja', flag: '🇯🇵', grade: 'C+', desc: 'Female' },
            { id: 'jf_gongitsune', name: 'Gongitsune', lang: 'ja', flag: '🇯🇵', grade: 'C',  desc: 'Female' },
            { id: 'jf_tebukuro',   name: 'Tebukuro',   lang: 'ja', flag: '🇯🇵', grade: 'C',  desc: 'Female' }
        ],
        'zh': [ // Chinese (Mandarin)
            { id: 'zf_xiaobei', name: 'Xiaobei', lang: 'zh', flag: '🇨🇳', grade: 'D', desc: 'Female' },
            { id: 'zf_xiaoni',  name: 'Xiaoni',  lang: 'zh', flag: '🇨🇳', grade: 'D', desc: 'Female' },
            { id: 'zm_yunjian', name: 'Yunjian', lang: 'zh', flag: '🇨🇳', grade: 'D', desc: 'Male' }
        ],
        'hi': [ // Hindi
            { id: 'hf_alpha', name: 'Alpha', lang: 'hi', flag: '🇮🇳', grade: 'C', desc: 'Female' },
            { id: 'hf_beta',  name: 'Beta',  lang: 'hi', flag: '🇮🇳', grade: 'C', desc: 'Female' },
            { id: 'hm_omega', name: 'Omega', lang: 'hi', flag: '🇮🇳', grade: 'C', desc: 'Male' },
            { id: 'hm_psi',   name: 'Psi',   lang: 'hi', flag: '🇮🇳', grade: 'C', desc: 'Male' }
        ]
    };

    // Function to update voice options based on selected language
    function updateVoiceOptions(langCode, backendConfig = null) {
        if (!voiceSelect) return;

        voiceSelect.innerHTML = '';
        const voices = kokoroVoices[langCode] || [];

        if (voices.length === 0) {
            const option = document.createElement('option');
            option.textContent = "No voices available";
            voiceSelect.appendChild(option);
            return;
        }

        voices.forEach(voice => {
            const option = document.createElement('option');
            option.value = voice.id;
            // Store specific lang code (e.g. en-us) in dataset for saving
            option.dataset.lang = voice.lang;

            let text = `${voice.flag} ${voice.name}`;
            if (voice.grade) text += ` (Grade: ${voice.grade})`;
            if (voice.desc) text += ` - ${voice.desc}`;

            option.textContent = text;
            voiceSelect.appendChild(option);
        });

        // Select previously configured voice if it matches current language
        // TODO Fixed in kokoro
        const configuredVoice = backendConfig?.tts?.modules?.kokoro?.default_voice
        if (configuredVoice && voices.some(v => v.id === configuredVoice)) {
            voiceSelect.value = configuredVoice;
        }
    }

    // Populate language dropdown
    if (languageSelect && languageSelect.options.length === 0) {
        sttLanguages.forEach(lang => {
            const option = document.createElement('option');
            option.value = lang.code;
            option.textContent = `${lang.flag} ${lang.name}`;
            if (lang.highMem) {
                option.dataset.highMem = "true";
            }
            languageSelect.appendChild(option);
        });

        // Auto-detect language
        const systemLang = navigator.language.split('-')[0];
        const supportedLang = sttLanguages.find(l => l.code === systemLang);

        // Set default: Configured > System > English
        const backendConfig = await loadBackendConfig();
        const configuredLang = backendConfig?.stt?.language;
        if (configuredLang) {
            languageSelect.value = configuredLang;
        } else if (supportedLang) {
            languageSelect.value = systemLang;
        } else {
            languageSelect.value = 'en';
        }

        // Initialize voices for the selected language
        updateVoiceOptions(languageSelect.value, backendConfig);
    }

    // Check RAM and handle warnings
    async function checkRamAndWarn() {
        try {
            const response = await fetch(config.get('pybridge.api_url') + '/hardware/acceleration');
            const hwInfo = await response.json();
            const totalRam = hwInfo.details?.total_ram_gb || 0;

            const selectedOption = languageSelect.options[languageSelect.selectedIndex];
            const isHighMemLang = selectedOption.dataset.highMem === "true";

            warningDiv.classList.add('hidden');
            warningDiv.innerHTML = '';

            if (totalRam < 8) {
                warningDiv.innerHTML = `Your system has less than 8GB of RAM (${totalRam.toFixed(1)} GB detected). Speech recognition might be slow or have lower quality.`;
                warningDiv.classList.remove('hidden');
            } else if (totalRam < 15 && isHighMemLang) {
                warningDiv.innerHTML = `The selected language requires significant memory. With less than 16GB of RAM (${totalRam.toFixed(1)} GB detected), performance may be impacted.`;
                warningDiv.classList.remove('hidden');
            }
        } catch (error) {
            console.error('Error checking RAM for STT:', error);
        }
    }

    // Event listener for language change
    if (languageSelect) {
        languageSelect.addEventListener('change', () => {
            modifiedFields.stt.add('stt.language');
            updateVoiceOptions(languageSelect.value);
            checkRamAndWarn();
        });
    }

    // Event listener for voice change
    if (voiceSelect) {
        voiceSelect.addEventListener('change', () => {
            modifiedFields.stt.add('tts.voice');
        });
    }

    // Initial check
    checkRamAndWarn();

    // Enable next button (always valid now that we removed custom config)
    if (sttNextButton) sttNextButton.disabled = false;

    /*
    // GPU Hardware Acceleration Info - Commented out for now as STT is CPU only
    // Add hardware acceleration info section if it doesn't exist
    if (!document.getElementById('hardware-acceleration-info')) {
        // ... (Previous GPU check logic preserved here in comments if needed later) ...
    }
    */
}

// Validate STT form inputs
function validateSTTForm() {
    // Simplified validation since we removed custom backend options
    const sttNextButton = document.getElementById('main-next-btn');
    if (sttNextButton) sttNextButton.disabled = false;
    return true;
}

async function saveCurrentStepData() {
    const currentStep = steps[currentStepIndex];
    let serverIp = null, port = null;

    switch (currentStep) {
        case 'ollama':
            serverIp = document.getElementById('ollama-server-ip')?.value || '127.0.0.1';
            port = parseInt(document.getElementById('ollama-port')?.value || '11434', 10);
            config.set('ollama.serverIp', serverIp);
            config.set('ollama.port', port);
            config.saveConfig();
            break;
        case 'llm':
            await saveLLMConfig();
            break;
        case 'mcp':
            await saveMcpConfig();
            break;
        case 'stt':
            await saveSTTConfig();
            break;
        case 'skills':
            await saveSkillsConfig();
            break;
        case 'shortcuts':
            saveShortcutsConfig();
            break;
        // Note: Finish step data is saved only when the 'Finish' button is clicked,
        // not during step navigation. See finishSetup().
        // case 'finish':
        //     await saveFinishStepConfig();
        //     break;
    }
}

// Add a new function to handle provider deletion
async function deleteProvider(index) {
    try {
        // Load current backend config
        const backendConfig = await loadBackendConfig();
        let changedSelectedProvider = false;

        if (!backendConfig.llm || !backendConfig.llm.providers || !backendConfig.llm.providers[index]) {
            throw new Error('Provider not found');
        }

        // Get the provider being deleted
        const deletedProvider = backendConfig.llm.providers[index];

        // Remove the provider from the array
        backendConfig.llm.providers.splice(index, 1);

        // If this was the selected provider, update the selection
        if (backendConfig.llm.selected_provider === deletedProvider.model) {
            // If there are other providers, select the first one
            if (backendConfig.llm.providers.length > 0) {
                backendConfig.llm.selected_provider = backendConfig.llm.providers[0].model;
            } else {
                // No providers left, remove the selected key
                delete backendConfig.llm.selected_provider;
                // Disable the next button as well
                const nextButton = document.getElementById('main-next-btn');
                nextButton.disabled = true;
            }
            changedSelectedProvider = true;
        }

        // Save the updated backend config to both servers
        await saveBackendConfig(backendConfig, config.get('pybridge.api_url'));
        if (changedSelectedProvider) {
            await saveBackendConfig(backendConfig, config.get('orakle.api_url'));
        }

        // Clear the existing providers container before reloading
        const existingContainer = document.getElementById('existing-providers');
        if (existingContainer) {
            existingContainer.innerHTML = '';
        }

        // Reload the providers list
        loadExistingProviders();

        // Show success message
        const testResult = document.getElementById('test-result');
        testResult.textContent = 'Provider deleted successfully';
        testResult.classList.remove('hidden', 'error');
        testResult.classList.add('success');

        // Hide the message after 3 seconds
        setTimeout(() => {
            testResult.classList.add('hidden');
        }, 3000);
    } catch (error) {
        console.error('Error deleting provider:', error);

        // Show error message
        const testResult = document.getElementById('test-result');
        testResult.textContent = `Error deleting provider: ${error.message}`;
        testResult.classList.remove('hidden', 'success');
        testResult.classList.add('error');
    }
}

async function updateUIAfterSave(newProvider) {
    // Reload the providers list
    await loadExistingProviders();

    // Select the newly added provider in the UI
    const providerRadios = document.querySelectorAll('input[name="existing-provider"]');
    const newProviderRadio = Array.from(providerRadios).find(radio => {
        const label = radio.nextElementSibling;
        return label?.textContent.includes(newProvider.name);
    });

    if (newProviderRadio) {
        newProviderRadio.checked = true;
        // Trigger the change event to update the UI state
        newProviderRadio.dispatchEvent(new Event('change'));
    }

    // Enable the Next button since we have a valid provider
    document.getElementById('main-next-btn').disabled = false;
}

function normalizeModelName(model, provider) {
    if (!model) return model;

    // Convert provider to lowercase for comparison
    const providerPrefix = provider.toLowerCase() + '/';

    // For custom providers, don't modify the name
    if (provider === 'custom' || provider === 'custom_api') {
        return model;
    }

    // If model already starts with provider prefix, return as-is
    if (model.toLowerCase().startsWith(providerPrefix)) {
        return model;
    }

    // Default case - prepend provider
    return `${provider}/${model}`;
}

async function saveLLMConfig() {
    // Check if an existing provider is selected
    const selectedExistingProvider = document.querySelector('input[name="existing-provider"]:checked');
    // llmConfig is the configuration of the selected new provider
    const llmConfig = getLLMConfig();
    let changedSelectedProvider = false;
    // we don't have a new provider selected, return
    if (!llmConfig) {
        return "No provider defined won't save";
    }

    // If no LLM fields were modified and we're not selecting an existing provider, skip saving
    if (modifiedFields.llm.size === 0 && !selectedExistingProvider) {
        return null; // No error, just nothing to save
    }
    // const notCustomProvider = document.querySelector('input[name="llm-provider"]:checked')?.value !== 'custom';

    try {
        // Load current backend config
        const backendConfig = await loadBackendConfig();

        // Update LLM config in backend
        if (!backendConfig.llm) {
            backendConfig.llm = { backend: "litellm", providers: [] };
        }

        function modelExists(providers, modelName) {
            return providers.some(provider => provider.model == modelName);
        }

        // Check for duplicate model name
        const modelName = llmConfig.model; // Already normalized by getLLMConfig()
        if (backendConfig.llm.providers && modelExists(backendConfig.llm.providers, modelName)) {
            return 'This model is already registered';
        }

        // If an existing provider is selected, update the selected key
        if (selectedExistingProvider) {
            const providerIndex = parseInt(selectedExistingProvider.value);
            if (backendConfig.llm.providers && backendConfig.llm.providers[providerIndex]) {
                const provider = backendConfig.llm.providers[providerIndex];
                backendConfig.llm.selected_provider = provider.model;
                changedSelectedProvider = true;
            }
        }

        // Convert the Polaris LLM config format to the backend format
        const provider = {
            model: llmConfig.model
        };

        // Add API key if present
        if (llmConfig.api_key) {
            provider.api_key = llmConfig.api_key;
        }

        // Add API base if present
        if (llmConfig.api_base) {
            provider.api_base = llmConfig.api_base;
        }

        // Add context window if present
        if (llmConfig.context_window) {
            provider.context_window = llmConfig.context_window;
        }

        // Add as a new provider instead of replacing
        if (Array.isArray(backendConfig.llm.providers)) {
            backendConfig.llm.providers.push(provider);
        } else {
            backendConfig.llm.providers = [provider];
        }

        // If this is the only provider or there's no selected provider yet, select it
        if (!backendConfig.llm.selected_provider || backendConfig.llm.providers.length === 1) {
            backendConfig.llm.selected_provider = provider.model;
            changedSelectedProvider = true;
        }

        // Save the updated backend config to both servers
        await saveBackendConfig(backendConfig, config.get('pybridge.api_url'));
        if (changedSelectedProvider) {
            await saveBackendConfig(backendConfig, config.get('orakle.api_url'));
        }

        // After successful save, clear the modified fields tracking
        modifiedFields.llm.clear();

        await updateUIAfterSave(provider);
    } catch (error) {
        console.error('Error updating LLM config:', error);
    }
}

async function saveMcpConfig() {
    if (modifiedFields.mcp.size === 0) {
        return; // Nothing to save
    }

    try {
        const backendConfig = await loadBackendConfig();
        const newMcpClients = {};
        const serverForms = document.querySelectorAll('#mcp-panel .mcp-server-form');

        for (const form of serverForms) {
            const serverNameInput = form.querySelector('.mcp-server-name');
            const serverName = serverNameInput.value.trim();

            if (!serverName) {
                // If a form was added but name is empty, skip it, unless it was a pre-existing one being cleared.
                // For simplicity, we'll rely on the user to remove unwanted empty forms.
                // Or, if it's an existing server whose name was cleared, it implies deletion.
                // The current logic rebuilds mcp_clients, so empty names are effectively ignored.
                continue;
            }

            const prefix = form.querySelector('.mcp-prefix').value.trim();
            const commandText = form.querySelector('.mcp-command').value.trim();
            const command = commandText ? commandText.split('\n').map(cmd => cmd.trim()).filter(cmd => cmd) : [];

            const env = {};
            form.querySelectorAll('.mcp-env-var-item').forEach(item => {
                const key = item.querySelector('.mcp-env-key').value.trim();
                const value = item.querySelector('.mcp-env-value').value.trim();
                if (key) {
                    env[key] = value;
                }
            });

            newMcpClients[serverName] = {
                ...(prefix && { prefix }), // Add prefix only if it exists
                stdio_params: {
                    command,
                    env,
                },
            };
        }
        backendConfig.mcp_clients = newMcpClients;
        await saveBackendConfig(backendConfig, config.get('pybridge.api_url'));
        // Orakle might also need mcp_clients if it acts as one or manages them.
        // await saveBackendConfig(backendConfig, config.get('orakle.api_url'));
        modifiedFields.mcp.clear();
    } catch (error) {
        console.error('Error saving MCP config:', error);
        alert(`Error saving MCP configuration: ${error.message}`);
    }
}

// Function to save Voice (STT & TTS) config
async function saveSTTConfig() {
    // If no fields were modified, skip saving
    if (modifiedFields.stt.size === 0) {
        return;
    }

    const languageSelect = document.getElementById('stt-language-select');
    const voiceSelect = document.getElementById('tts-voice-select');

    const selectedLanguage = languageSelect ? languageSelect.value : 'en';
    const selectedSttBackend = 'faster_whisper';

    const selectedVoiceId = voiceSelect ? voiceSelect.value : 'af_heart';
    // Get the specific lang code (e.g. en-us) from the selected option's dataset
    const selectedOption = voiceSelect ? voiceSelect.options[voiceSelect.selectedIndex] : null;
    const selectedVoiceLang = selectedOption ? selectedOption.dataset.lang : 'en-us';
    const selectedTtsBackend = 'kokoro';

    // Save to Polaris backend config
    try {
        // Load current backend config
        const backendConfig = await loadBackendConfig();

        // --- Update STT Config ---
        if (!backendConfig.stt) {
            backendConfig.stt = {
                language: selectedLanguage,
                modules: { faster_whisper: { model_size: "small" } },
                selected_module: selectedSttBackend
            };
        } else {
            backendConfig.stt.language = selectedLanguage;
            backendConfig.stt.selected_module = selectedSttBackend;
            if (!backendConfig.stt.modules) backendConfig.stt.modules = {};
            if (!backendConfig.stt.modules.faster_whisper) {
                backendConfig.stt.modules.faster_whisper = { model_size: "small" };
            }
        }

        // --- Update TTS Config ---
        if (!backendConfig.tts) {
            backendConfig.tts = {
                selected_module: selectedTtsBackend,
                modules: {}
            };
        }

        backendConfig.tts.selected_module = "kokoro";
        if (!backendConfig.tts.modules) backendConfig.tts.modules = {};

        // Set Kokoro specific settings
        backendConfig.tts.modules.kokoro = {
            default_lang: selectedVoiceLang,
            default_voice: selectedVoiceId
        };

        // Save the updated backend config
        await saveBackendConfig(backendConfig, config.get('pybridge.api_url'));

        // After successful save, clear the modified fields tracking
        modifiedFields.stt.clear();
    } catch (error) {
        console.error('Error updating Voice config:', error);
    }
}

function generateEmailTableHtml(config) {
    const accounts = config?.apis?.messaging?.email?.accounts || [];

    let rowsHtml = '';

    // Helper to generate a row
    const createRow = (acc, isGhost = false) => `
        <div class="email-row ${isGhost ? 'ghost' : ''}">
            <div class="email-cell"><input type="text" class="email-id" placeholder="ID (e.g. gmail)" value="${acc.id || ''}" ${isGhost ? '' : 'required'}></div>
            <div class="email-cell"><input type="text" class="email-host" placeholder="imap.email.com" value="${acc.imap_host || ''}" ${isGhost ? '' : 'required'}></div>
            <div class="email-cell"><input type="number" class="email-port" placeholder="993" value="${acc.imap_port || ''}"></div>
            <div class="email-cell"><input type="text" class="email-user" placeholder="user@email.com" value="${acc.username || ''}" ${isGhost ? '' : 'required'}></div>
            <div class="email-cell">
                <div class="password-wrapper">
                    <input type="password" class="email-pass" placeholder="Password" value="${acc.password || ''}" ${isGhost ? '' : 'required'}>
                    <button class="password-toggle" type="button" tabindex="-1">Show</button>
                </div>
            </div>
            <div class="email-cell">
                ${!isGhost ? '<button class="remove-email-btn" title="Remove account">&times;</button>' : ''}
            </div>
        </div>
    `;

    // Existing accounts
    accounts.forEach(acc => {
        rowsHtml += createRow(acc, false);
    });

    // Ghost row
    rowsHtml += createRow({}, true);

    return `
        <div class="skill-item email-config-section" data-group-path="apis.messaging.email">
            <div class="email-config-header">
                <h4>Email Accounts</h4>
                <p>Configure IMAP accounts for email integration.</p>
            </div>
            <div class="email-config-table" id="email-accounts-table">
                <div class="email-col-header">ID</div>
                <div class="email-col-header">IMAP Host</div>
                <div class="email-col-header">Port</div>
                <div class="email-col-header">Username</div>
                <div class="email-col-header">Password</div>
                <div class="email-col-header"></div>
                ${rowsHtml}
            </div>
        </div>
    `;
}

function setupEmailTableListeners() {
    const table = document.getElementById('email-accounts-table');
    if (!table) return;

    // Delegate events
    table.addEventListener('click', (e) => {
        // Remove button
        if (e.target.closest('.remove-email-btn')) {
            if (confirm('Remove this email account?')) {
                e.target.closest('.email-row').remove();
                modifiedFields.skills.add('apis.messaging.email');
                updateSkillsNextButtonState();
            }
        }

        // Password toggle
        if (e.target.classList.contains('password-toggle')) {
            const btn = e.target;
            const input = btn.previousElementSibling;
            if (input.type === 'password') {
                input.type = 'text';
                btn.textContent = 'Hide';
            } else {
                input.type = 'password';
                btn.textContent = 'Show';
            }
        }
    });

    table.addEventListener('input', (e) => {
        const row = e.target.closest('.email-row');
        if (!row) return;

        // Mark as modified
        modifiedFields.skills.add('apis.messaging.email');
        updateSkillsNextButtonState();

        // Handle Ghost Row interaction
        if (row.classList.contains('ghost')) {
            // Remove ghost class and required attributes
            row.classList.remove('ghost');
            row.querySelectorAll('input').forEach(input => input.required = true);
            // Port is optional
            row.querySelector('.email-port').required = false;

            // Add remove button
            const actionCell = row.lastElementChild;
            actionCell.innerHTML = '<button class="remove-email-btn" title="Remove account">&times;</button>';

            // Create new ghost row
            const newGhostHtml = `
                <div class="email-row ghost">
                    <div class="email-cell"><input type="text" class="email-id" placeholder="ID (e.g. gmail)"></div>
                    <div class="email-cell"><input type="text" class="email-host" placeholder="imap.email.com"></div>
                    <div class="email-cell"><input type="number" class="email-port" placeholder="993"></div>
                    <div class="email-cell"><input type="text" class="email-user" placeholder="user@email.com"></div>
                    <div class="email-cell">
                        <div class="password-wrapper">
                            <input type="password" class="email-pass" placeholder="Password">
                            <button class="password-toggle" type="button" tabindex="-1">Show</button>
                        </div>
                    </div>
                    <div class="email-cell"></div>
                </div>
            `;
            table.insertAdjacentHTML('beforeend', newGhostHtml);
        }
    });
}

async function saveSkillsConfig() {
    // If no skill fields were modified, skip saving
    if (modifiedFields.skills.size === 0) {
        return;
    }

    try {
        // Load current backend config
        const backendConfig = await loadBackendConfig();

        // Helper function to set value at path
        function setValueAtPath(obj, path, value) {
            const parts = path.split('.');
            let current = obj;

            for (let i = 0; i < parts.length - 1; i++) {
                const part = parts[i];
                if (!(part in current)) {
                    current[part] = {};
                }
                current = current[part];
            }

            current[parts[parts.length - 1]] = value;
        }

        // Only update modified API keys
        document.querySelectorAll('input[data-path]').forEach(input => {
            const path = input.dataset.path;
            if (modifiedFields.skills.has(path)) {
                const value = input.value.trim();
                // Save the value, even if it's empty, to allow clearing keys.
                setValueAtPath(backendConfig, path, value);
            }
        });

        // SAVE EMAIL ACCOUNTS
        if (modifiedFields.skills.has('apis.messaging.email')) {
            const emailAccounts = [];
            const rows = document.querySelectorAll('#email-accounts-table .email-row:not(.ghost)');

            rows.forEach(row => {
                const id = row.querySelector('.email-id').value.trim();
                const host = row.querySelector('.email-host').value.trim();
                const port = row.querySelector('.email-port').value.trim();
                const user = row.querySelector('.email-user').value.trim();
                const pass = row.querySelector('.email-pass').value.trim();

                if (id && host && user && pass) {
                    const accountObj = {
                        id: id,
                        imap_host: host,
                        username: user,
                        password: pass
                    };
                    if (port) accountObj.imap_port = parseInt(port);
                    emailAccounts.push(accountObj);
                }
            });

            // Ensure structure exists
            if (!backendConfig.apis) backendConfig.apis = {};
            if (!backendConfig.apis.messaging) backendConfig.apis.messaging = {};
            if (!backendConfig.apis.messaging.email) backendConfig.apis.messaging.email = {};

            backendConfig.apis.messaging.email.accounts = emailAccounts;
        }

        // SAVE SCHEDULE OVERRIDES (Updated Logic)
        if (modifiedFields.skills.has('scheduler')) {
            if (!backendConfig.scheduler) backendConfig.scheduler = {};
            if (!backendConfig.scheduler.overrides) backendConfig.scheduler.overrides = {};

            document.querySelectorAll('.schedule-row').forEach(row => {
                const skillName = row.dataset.skill;
                const isEnabled = row.querySelector('.schedule-enable').checked;
                const minutes = parseInt(row.querySelector('.schedule-interval').value);
                const isDefaultDefault = row.dataset.defaultDefault === "true";

                if (!isEnabled) {
                    // If disabled:
                    // - If default was enabled (true), we must explicitly set false.
                    // - If default was disabled (false), we can just remove the override key.
                    if (isDefaultDefault) {
                        backendConfig.scheduler.overrides[skillName] = false;
                    } else {
                        delete backendConfig.scheduler.overrides[skillName];
                    }
                } else {
                    // If enabled, we construct the full config object

                    // 1. Harvest Kwargs from UI
                    const uiKwargs = {};
                    const paramInputs = document.querySelectorAll(`.param-input[data-skill="${skillName}"]`);

                    paramInputs.forEach(input => {
                        const key = input.dataset.key;
                        const type = input.dataset.type;
                        let val = input.value;

                        if (type === 'boolean') {
                            val = (val === 'true');
                        } else if (type === 'integer') {
                            val = parseInt(val);
                            if (isNaN(val)) val = null; // Handle empty
                        } else if (type === 'number') {
                            val = parseFloat(val);
                            if (isNaN(val)) val = null;
                        } else if (type === 'array') {
                            // Split by comma and trim
                            val = val ? val.split(',').map(s => s.trim()).filter(s => s !== '') : [];
                        }

                        // Only add if not object placeholder (which is disabled)
                        if (!input.disabled) {
                            uiKwargs[key] = val;
                        }
                    });

                    // 2. Merge with existing kwargs to preserve hidden/complex objects
                    // We start with the existing override kwargs (if any), or default kwargs
                    const existingOverride = backendConfig.scheduler.overrides[skillName];
                    const existingKwargs = (existingOverride && existingOverride !== false && existingOverride.kwargs)
                                           ? existingOverride.kwargs
                                           : {};

                    // Merge: Existing takes precedence for keys NOT in UI, UI takes precedence for keys IN UI
                    const finalKwargs = { ...existingKwargs, ...uiKwargs };

                    backendConfig.scheduler.overrides[skillName] = {
                        trigger: 'interval',
                        minutes: minutes,
                        kwargs: finalKwargs
                    };
                }
            });
        }

        // Save the updated backend config
        await saveBackendConfig(backendConfig, config.get('pybridge.api_url'));
        await saveBackendConfig(backendConfig, config.get('orakle.api_url'));

        // Clear modified fields after successful save
        modifiedFields.skills.clear();
    } catch (error) {
        console.error('Error updating skills config:', error);
    }
}

// Function to save finish step configuration
async function saveFinishStepConfig() {
    // If no finish step fields were modified, skip saving
    if (modifiedFields.finish.size === 0) {
        return true;
    }

    try {
        if (modifiedFields.finish.has('start-minimized-checkbox')) {
            const isChecked = document.getElementById('start-minimized-checkbox').checked;
            config.set('startup.startMinimized', isChecked);
        }

        // TODO delayed for v0.10
        // if (modifiedFields.finish.has('auto-start-checkbox')) {
        //     const isChecked = document.getElementById('auto-start-checkbox').checked;
        //     config.set('startup.autoStart', isChecked);
        //     // Notify the main process to apply the setting immediately
        //     ipcRenderer.send('set-auto-start');
        // }

        if (modifiedFields.finish.has('review-stt-select')) {
            config.set('stt.review', document.getElementById('review-stt-select').value);
        }

        if (modifiedFields.finish.has('background-notifications-checkbox')) {
            const isChecked = document.getElementById('background-notifications-checkbox').checked;
            config.set('ui.backgroundNotifications', isChecked);
        }

        if (modifiedFields.finish.has('backup-directory-input')) {
            const backupDirectory = document.getElementById('backup-directory-input').value.trim();

            // Save only to backend config
            const backendConfig = await loadBackendConfig();
            if (!backendConfig.backup) {
                backendConfig.backup = {};
            }
            backendConfig.backup.directory = backupDirectory;
            backendConfig.backup.enabled = !!backupDirectory; // Enable if directory is not empty

            await saveBackendConfig(backendConfig, config.get('pybridge.api_url'));
        }

        if (modifiedFields.finish.has('wakeword-checkbox')) {
            const isChecked = document.getElementById('wakeword-checkbox').checked;
            config.set('wakeword.enabled', isChecked);
        }

        if (modifiedFields.finish.has('lower-volume-checkbox')) {
            const isChecked = document.getElementById('lower-volume-checkbox').checked;
            config.set('stt.lowerVolume', isChecked);
        }

        if (modifiedFields.finish.has('comring-notifications-checkbox')) {
            const isChecked = document.getElementById('comring-notifications-checkbox').checked;
            config.set('ui.comringNotifications', isChecked);
        }

        config.saveConfig();
        modifiedFields.finish.clear();
        return true;
    } catch (error) {
        console.error('Error saving finish step config:', error);
        return false;
    }
}

// Function to save shortcuts configuration
function saveShortcutsConfig() {
    // If no shortcut fields were modified, skip saving
    if (modifiedFields.shortcuts.size === 0) {
        return true;
    }

    try {
        // Get shortcut values
        const showShortcut = document.getElementById('show-shortcut').value.trim();
        const hideShortcut = document.getElementById('hide-shortcut').value.trim();
        const triggerShortcut = document.getElementById('trigger-shortcut').value.trim();

        // Update config
        if (showShortcut && modifiedFields.shortcuts.has('show-shortcut')) {
            config.set('shortcuts.show', showShortcut);
        }

        if (hideShortcut && modifiedFields.shortcuts.has('hide-shortcut')) {
            config.set('shortcuts.hide', hideShortcut);
        }

        if (triggerShortcut && modifiedFields.shortcuts.has('trigger-shortcut')) {
            config.set('shortcuts.trigger', triggerShortcut);
        }

        // Save to disk
        config.saveConfig();

        // Clear modified fields after successful save
        modifiedFields.shortcuts.clear();

        return true;
    } catch (error) {
        console.error('Error saving shortcuts config:', error);
        return false;
    }
}

// Function to handle shortcut key capture
function setupShortcutCapture() {
    const showInput = document.getElementById('show-shortcut');
    const hideInput = document.getElementById('hide-shortcut');
    const triggerInput = document.getElementById('trigger-shortcut');
    const showDisplay = document.getElementById('show-key-display');
    const hideDisplay = document.getElementById('hide-key-display');
    const triggerDisplay = document.getElementById('trigger-key-display');

    // Load current values from config
    const currentShow = config.get('shortcuts.show', 'F1');
    const currentHide = config.get('shortcuts.hide', 'Escape');
    const currentTrigger = config.get('shortcuts.trigger', 'Space');

    // Set initial values
    showInput.value = currentShow;
    hideInput.value = currentHide;
    triggerInput.value = currentTrigger;
    showDisplay.textContent = currentShow;
    hideDisplay.textContent = currentHide;
    triggerDisplay.textContent = currentTrigger;

    // Function to handle key capture
    function captureKey(input, displayElement) {
        input.addEventListener('focus', () => {
            input.value = 'Press a key...';
            input.classList.add('capturing');
        });

        input.addEventListener('blur', () => {
            if (input.value === 'Press a key...') {
                // Restore previous value if no key was pressed
                input.value = displayElement.textContent;
            }
            input.classList.remove('capturing');
        });

        input.addEventListener('keydown', (e) => {
            e.preventDefault();

            // Get the key name
            let keyName;
            if (e.key === ' ') {
                keyName = 'Space';
            } else if (e.key === 'Escape') {
                // Cancel and restore previous value
                keyName = displayElement.textContent;
            } else {
                keyName = e.key;
            }

            // Special handling for modifier keys
            if (e.ctrlKey && e.key !== 'Control') keyName = 'Ctrl+' + keyName;
            if (e.altKey && e.key !== 'Alt') keyName = 'Alt+' + keyName;
            if (e.shiftKey && e.key !== 'Shift') keyName = 'Shift+' + keyName;

            // Update input and display
            input.value = keyName;
            displayElement.textContent = keyName;

            // Remove focus to complete capture
            input.blur();
        });
    }

    // Set up key capture for both inputs
    captureKey(showInput, showDisplay);
    captureKey(hideInput, hideDisplay);
    captureKey(triggerInput, triggerDisplay);

    // Update display when input changes directly
    showInput.addEventListener('input', () => {
        showDisplay.textContent = showInput.value;
        modifiedFields.shortcuts.add('show-shortcut');
    });

    hideInput.addEventListener('input', () => {
        hideDisplay.textContent = hideInput.value;
        modifiedFields.shortcuts.add('hide-shortcut');
    });

    triggerInput.addEventListener('input', () => {
        triggerDisplay.textContent = triggerInput.value;
        modifiedFields.shortcuts.add('trigger-shortcut');
    });
}

// Helper to parse Python default string values from run_info
function parsePythonDefault(val) {
    if (val === undefined || val === null) return null;
    const sVal = String(val).trim();
    if (sVal === "None") return null;
    if (sVal === "True") return true;
    if (sVal === "False") return false;
    // Check if it's a number
    if (!isNaN(Number(sVal))) return Number(sVal);
    // Remove quotes if present
    if ((sVal.startsWith("'") && sVal.endsWith("'")) || (sVal.startsWith('"') && sVal.endsWith('"'))) {
        return sVal.slice(1, -1);
    }
    return sVal;
}

function renderInputBySchema(skillName, paramName, paramDef, currentValue) {
    const schema = paramDef.schema || {};
    const type = schema.type || 'string';
    const inputId = `param-${skillName}-${paramName}`;

    // Determine effective value
    let value = currentValue;
    if (value === undefined || value === null) {
        value = parsePythonDefault(paramDef.default);
    }

    let defaultValue = paramDef.required ? ` value="${value}" ` : '';

    // console.log("----------------------");
    // console.log(paramDef);
    // console.log("----------------------");
    // console.log(defaultValue);

    let inputHtml = '';

    if (type === 'boolean') {
        const isTrue = value === true;
        inputHtml = `
            <select class="param-input" data-skill="${skillName}" data-key="${paramName}" data-type="boolean">
                <option value="true" ${isTrue ? 'selected' : ''}>True</option>
                <option value="false" ${!isTrue ? 'selected' : ''}>False</option>
            </select>
        `;
    } else if (type === 'integer' || type === 'number') {
        inputHtml = `<input type="number" class="param-input" id="${inputId}" data-skill="${skillName}" data-key="${paramName}" data-type="${type}" ${defaultValue}  placeholder="${value !== null ? value : ''}" step="${type === 'integer' ? '1' : 'any'}">`;
    } else if (type === 'array') {
        // List handling - comma separated
        let displayVal = value;
        if (Array.isArray(value)) displayVal = value.join(', ');
        inputHtml = `<input type="text" class="param-input" id="${inputId}" data-skill="${skillName}" data-key="${paramName}" data-type="array" placeholder="${displayVal || ''}" >`;
    } else if (type === 'object') {
        // Placeholder for complex objects
        inputHtml = `<input type="text" disabled value="COMPLEX CONFIGURATION (OBJECT) - NOT EDITABLE IN THIS VERSION" style="font-style: italic; color: #888; background-color: #eee;">`;
    } else {
        // String and fallback
        inputHtml = `<input type="text" class="param-input" id="${inputId}" data-skill="${skillName}" data-key="${paramName}" data-type="string" placeholder="${value || ''}">`;
    }

    return `
        <div class="param-group">
            <label for="${inputId}" title="${paramName}">${paramName}</label>
            ${inputHtml}
            <div class="param-desc">${paramDef.description || ''}</div>
        </div>
    `;
}

function renderSkillParameters(skillName, cap, currentKwargs) {
    const parameters = cap.run_info?.parameters;
    if (!parameters || Object.keys(parameters).length === 0) {
        return '<p style="color: #666; font-style: italic;">No configurable parameters.</p>';
    }

    let html = '';
    for (const [paramName, paramDef] of Object.entries(parameters)) {
        // We ignore 'hidden' flag as discussed to allow advanced config
        const val = currentKwargs ? currentKwargs[paramName] : undefined;
        html += renderInputBySchema(skillName, paramName, paramDef, val);
    }
    return html;
}

function generateScheduleUI(capabilities, backendConfig) {
    let rows = '';
    let hasSchedulable = false;

    // Inject CSS for the accordion and form
    const styles = `
        <style>
            .schedule-details-row { display: none; background-color: #f8f9fa; }
            .schedule-details-row.active { display: table-row; }
            .schedule-details-panel { padding: 15px; display: grid; grid-template-columns: repeat(auto-fill, minmax(250px, 1fr)); gap: 15px; border-bottom: 1px solid #eee; }
            .param-group { display: flex; flex-direction: column; }
            .param-group label { font-size: 0.85em; font-weight: bold; margin-bottom: 4px; color: #444; }
            .param-group .param-desc { font-size: 0.75em; color: #666; margin-top: 4px; line-height: 1.2; }
            .param-group input, .param-group select { padding: 6px; border: 1px solid #ddd; border-radius: 4px; font-size: 0.9em; }
            .settings-btn { background: none; border: none; cursor: pointer; font-size: 1.2em; padding: 0 10px; opacity: 0.6; transition: opacity 0.2s; }
            .settings-btn:hover, .settings-btn.active { opacity: 1; }
            .schedule-table td { vertical-align: middle; }
        </style>
    `;

    for (const [name, cap] of Object.entries(capabilities)) {
        if (cap.default_schedule) {
            hasSchedulable = true;
            // Determine current state
            const override = backendConfig.scheduler?.overrides?.[name];
            const defaultSched = cap.default_schedule;

            let isEnabled;
            if (defaultSched.default) {
                isEnabled = !(override === false);
            } else {
                isEnabled = typeof override !== "undefined" && override !== false;
            }

            // Resolve current kwargs: Override > Default Schedule > Empty
            // Note: If override is false (disabled), we fall back to default kwargs for display
            const currentKwargs = (override && override !== false && override.kwargs)
                                  ? override.kwargs
                                  : (defaultSched.kwargs || {});

            const minutes = (override && override.minutes) ? override.minutes : (defaultSched.minutes || 10);
            const hasParams = cap.run_info?.parameters && Object.keys(cap.run_info.parameters).length > 0;

            // TODO Hidden settings configuration by now
            rows += `
                <tr class="schedule-row" data-skill="${name}" data-default-default=${defaultSched.default || false} data-default-minutes="${defaultSched.minutes || 10}">
                    <td style="max-width: 100px">
                        <i>${name}</i>
                        <p style="font-size:0.8em; margin: 2px 0 0 0; color: #666;">${cap.description ? cap.description.trim().split('\n')[0] : ""}</p>
                    </td>
                    <td>
                        <label class="schedule-toggle">
                            <input type="checkbox" class="schedule-enable" ${isEnabled ? 'checked' : ''}>
                            Enable
                        </label>
                    </td>
                    <td>
                        Run every <input type="number" class="schedule-interval schedule-interval-input" value="${minutes}" min="1" ${isEnabled ? '' : 'disabled'} style="width: 60px;"> minutes
                    </td>
                    <td style="text-align: center;">
                        ${hasParams ? `<button class="settings-btn" style="display:none" data-skill="${name}" title="Configure Parameters">⚙️</button>` : ''}
                    </td>
                </tr>
                ${hasParams ? `
                <tr class="schedule-details-row" id="details-${name}">
                    <td colspan="4" style="padding: 0;">
                        <div class="schedule-details-panel">
                            ${renderSkillParameters(name, cap, currentKwargs)}
                        </div>
                    </td>
                </tr>
                ` : ''}
            `;
        }
    }

    if (!hasSchedulable) return '';

    return `
        ${styles}
        <div class="schedule-config-section">
            <h3>Scheduled Skills</h3>
            <p>Configure automatic execution intervals and parameters for supported skills.</p>
            <table class="schedule-table">
                <thead>
                    <tr>
                        <th>Skill</th>
                        <th>Status</th>
                        <th>Frequency</th>
                        <th style="width: 50px;"></th>
                    </tr>
                </thead>
                <tbody>
                    ${rows}
                </tbody>
            </table>
        </div>
    `;
}

function setupScheduleListeners() {
    // Handle Enable/Disable and Interval changes
    document.querySelectorAll('.schedule-row').forEach(row => {
        const checkbox = row.querySelector('.schedule-enable');
        const input = row.querySelector('.schedule-interval');
        const skillName = row.dataset.skill;

        checkbox.addEventListener('change', () => {
            input.disabled = !checkbox.checked;
            modifiedFields.skills.add('scheduler');
            updateSkillsNextButtonState();
        });

        input.addEventListener('input', () => {
            modifiedFields.skills.add('scheduler');
            updateSkillsNextButtonState();
        });

        // Handle Settings Button (Accordion)
        const settingsBtn = row.querySelector('.settings-btn');
        if (settingsBtn) {
            settingsBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                const detailsRow = document.getElementById(`details-${skillName}`);
                const isActive = detailsRow.classList.contains('active');

                // Close all other details
                document.querySelectorAll('.schedule-details-row').forEach(el => el.classList.remove('active'));
                document.querySelectorAll('.settings-btn').forEach(el => el.classList.remove('active'));

                // Toggle current
                if (!isActive) {
                    detailsRow.classList.add('active');
                    settingsBtn.classList.add('active');
                }
            });
        }
    });

    // Handle Parameter Input changes
    document.querySelectorAll('.param-input').forEach(input => {
        input.addEventListener('change', () => { // Use change for selects/inputs to avoid spamming on keystrokes
            modifiedFields.skills.add('scheduler');
            updateSkillsNextButtonState();
        });
        // Also capture text input for immediate feedback if needed, though 'change' is safer for complex forms
        if (input.tagName === 'INPUT' && input.type === 'text') {
             input.addEventListener('input', () => {
                modifiedFields.skills.add('scheduler');
             });
        }
    });
}

function setupSkillsNavigation() {
    const navItems = document.querySelectorAll('.skills-nav-item');
    const sections = document.querySelectorAll('.skills-section-anchor');
    const scrollContainer = document.querySelector('.step-content'); // The main scrollable area

    // Click handling
    navItems.forEach(item => {
        item.addEventListener('click', () => {
            const targetId = item.dataset.target;
            const targetElement = document.getElementById(targetId);
            if (targetElement) {
                targetElement.scrollIntoView({ behavior: 'smooth', block: 'start' });
            }
        });
    });

    // Scroll Spy Logic
    // We use the scroll event on the container because IntersectionObserver can be tricky with nested scrolling
    if (scrollContainer) {
        scrollContainer.addEventListener('scroll', () => {
            let currentSectionId = '';

            // Find which section is currently closest to the top of the viewport
            sections.forEach(section => {
                const rect = section.getBoundingClientRect();
                // 150px offset to trigger slightly before the section hits the very top
                if (rect.top < 200 && rect.bottom > 0) {
                    currentSectionId = section.id;
                }
            });

            if (currentSectionId) {
                navItems.forEach(item => {
                    if (item.dataset.target === currentSectionId) {
                        item.classList.add('active');
                    } else {
                        item.classList.remove('active');
                    }
                });
            }
        });
    }
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

// New function to initialize the Ollama step
async function initializeOllamaStep() {
    const hardwareInfoElement = document.getElementById('ollama-hardware-info');

    // Clear previous content and show loading message
    if (hardwareInfoElement) hardwareInfoElement.innerHTML = '';
    const existingServerConfig = document.getElementById('ollama-server-config');
    if (existingServerConfig) existingServerConfig.remove();

    try {
        const response = await fetch(config.get('pybridge.api_url') + '/hardware/acceleration');
        if (!response.ok) {
            throw new Error(`Failed to fetch hardware info: ${response.statusText}`);
        }
        const hwInfo = await response.json();

        const totalVram = hwInfo.details?.total_vram_gb || 0;
        const isAppleSilicon = hwInfo.details?.is_apple_silicon || false;
        const totalRam = hwInfo.details?.total_ram_gb || 0;

        const meetsGpuRequirement = totalVram >= 4;
        const meetsAppleRequirement = isAppleSilicon && totalRam >= 6;

        if (meetsGpuRequirement || meetsAppleRequirement) {
            // Hardware requirements met, proceed with normal setup
            hardwareInfoElement.style.display = "block";
            await displayHardwareInfo();
            await displayOllamaModels();
            const serverConfigElement = document.getElementById('ollama-server-config');
            if (serverConfigElement) {
                serverConfigElement.style.display = "none";
            }
            const performanceWarning = `<p>PLEASE NOTE: Ainara has proved to work even with the very small Qwen 3 1.7B model, but at least a 8B model is strongly recommended. Carefully select the size of the model accordingly to your available GPU VRAM, or your RAM in specific systems, eg Apple Silicon systems.<br>
                        Ollama can always run models fully on CPU and normal RAM, but that will give very bad performance in most scenarios.
                        As a rule of thumb, unless owning very specific fast hardware, you should only choose models with an amount of parameters closely matching your available GPU VRAM (eg. Qwen 14B is good for an Nvidia RTX3060 with 12GB of VRAM available).</p>`
            if (totalVram < 8 || (isAppleSilicon && totalRam < 16)) {
                hardwareInfoElement.innerHTML += `
                    <div class="warning-block">
                        Your system hardware requirements look quite tight to run LLMs with Ollama effectively.
                        <p>Running local models on this system for Ainara may result in poor performance. It is recommended to use cloud-based LLM providers instead.</p>
                        ${performanceWarning}
                    </div>
                `;
            } else {
                hardwareInfoElement.innerHTML = `
                    <div class="warning-block">
                        ${performanceWarning}
                    </div>
                `;
            }
            // displayOllamaServerConfig();  // TODO: Disabled by now to not make things even more confusing to users
        } else {
            // Hardware requirements not met, disable Ollama setup
            hardwareInfoElement.style.display = "none";
            if (hardwareInfoElement) {
                hardwareInfoElement.innerHTML = `
                    <div class="warning-block">
                        Your system does not meet the recommended hardware requirements for running local LLMs with Ollama effectively.
                        <ul>
                            <li>Requirement 1: A dedicated GPU with at least 4 GB of VRAM. (Your system: ${totalVram.toFixed(1)} GB VRAM)</li>
                            <li>Requirement 2: An Apple Silicon Mac with at least 8 GB of RAM. (Your system: ${isAppleSilicon ? `${totalRam.toFixed(1)} GB RAM on Apple Silicon` : 'Not an Apple Silicon Mac'})</li>
                        </ul>
                        <p>Running local models on this system for Ainara may result in very poor performance. It is recommended to use cloud-based LLM providers instead.</p>
                        <p>The Ollama wizard setup has been disabled. You can proceed to the next step to configure other providers, or set up manually with the Custom API option.</p>
                    </div>
                `;
            }
        }
    } catch (error) {
        console.error('Error initializing Ollama step:', error);
        if (hardwareInfoElement) {
            hardwareInfoElement.innerHTML = `<div class="error">Could not check hardware requirements: ${error.message}</div>`;
        }
    }
}

// Function to display Ollama server configuration
// TODO Keeping this function even if unused now for possible future use
// eslint-disable-next-line no-unused-vars
function _displayOllamaServerConfig() {
    const ollamaPanel = document.getElementById('ollama-panel');
    let existingConfig = document.getElementById('ollama-server-config');
    if (existingConfig) {
        existingConfig.remove(); // Remove existing config to avoid duplicates
    }
    if (ollamaPanel) {
        const serverConfigHtml = `
            <div id="ollama-server-config" style="margin-top: 20px; width: 100%">
                <h3>Ollama Server Configuration</h3>
                <div style="display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; flex-wrap: wrap; max-width: 800px; margin-bottom: 15px;">
                    <!-- Server IP Field -->
                    <div class="form-group" style="flex: 1; min-width: 200px;">
                        <label for="ollama-server-ip" style="display: block; margin-bottom: 5px;">Server IP:</label>
                        <input type="text" id="ollama-server-ip" value="${config.get('ollama.serverIp', '127.0.0.1')}" placeholder="e.g., 127.0.0.1 or 192.168.1.100" style="width: 100%; padding: 8px; border: 1px solid #ccc; border-radius: 4px;">
                        <p class="field-description">Optional alternate Ollama host address, 127.0.0.1 by default.</p>
                    </div>
                    <!-- Port Field -->
                    <div class="form-group" style="flex: 0.5; min-width: 100px;">
                        <label for="ollama-port" style="display: block; margin-bottom: 5px;">Port:</label>
                        <input type="number" id="ollama-port" value="${config.get('ollama.port', 11434)}" placeholder="e.g., 11434" style="width: 100%; padding: 8px; border: 1px solid #ccc; border-radius: 4px;">
                        <p class="field-description">Optional alternate Ollama port, 11434 by default.</p>
                    </div>
                    <!-- Reload Button -->
                    <div class="form-group" style="flex: 0; min-width: auto; margin-left: auto; margin-top: 25px;">
                        <button id="reload-ollama-config-btn" style="background-color: #007bff; color: white; padding: 8px 16px; border: none; border-radius: 4px; cursor: pointer; transition: background-color 0.3s;">Reload</button>
                        <p class="field-description"></p>
                    </div>
                </div>
            </div>
        `;
        // Insert after hardware info or at the end of the panel
        const hardwareInfo = document.getElementById('ollama-hardware-info');
        if (hardwareInfo) {
            hardwareInfo.insertAdjacentHTML('afterend', serverConfigHtml);
        } else {
            ollamaPanel.insertAdjacentHTML('beforeend', serverConfigHtml);
        }

        // Add event listener for the reload button
        const reloadBtn = document.getElementById('reload-ollama-config-btn');
        if (reloadBtn) {
            reloadBtn.addEventListener('click', async () => {
                // Save the current configuraticonfiguration on
                const serverIp = document.getElementById('ollama-server-ip').value;
                const port = parseInt(document.getElementById('ollama-port').value, 10);
                config.set('ollama.serverIp', serverIp);
                config.set('ollama.port', port);
                config.saveConfig();
                // Refresh the Ollama step information
                reloadBtn.disabled = true;
                reloadBtn.textContent = 'Reloading...';
                try {
                    await initializeOllamaStep(); // Reinitialize to update hardware info visibility based on new IP
                    // alert('Ollama configuration reloaded successfully.');
                } catch (error) {
                    console.error('Error reloading Ollama configuration:', error);
                    alert(`Error reloading Ollama configuration: ${error.message}`);
                } finally {
                    reloadBtn.disabled = false;
                    reloadBtn.textContent = 'Reload';
                }
            });
        }
    }
}

// New function to display hardware information using PyBridge endpoint
async function displayHardwareInfo() {
    const hardwareInfoElement = document.getElementById('ollama-hardware-info');
    let hwInfo = null;

    if (!hardwareInfoElement) return;

    hardwareInfoElement.innerHTML = '<p>Checking system hardware...</p>';

    try {
        const response = await fetch(config.get('pybridge.api_url') + '/hardware/acceleration');
        if (!response.ok) {
            throw new Error(`Failed to fetch hardware info: ${response.statusText}`);
        }
        hwInfo = await response.json();

        console.log("Hardware Info Received:", hwInfo);

        let vramText = "VRAM information not available.";
        let gpuListText = "";
        let recommendationText = "<p>Recommendations based on VRAM:</p><ul>";
        const totalVram = hwInfo.details?.total_vram_gb || 0;

        if (hwInfo.details && hwInfo.details.total_vram_gb) {
            vramText = `Total Detected GPU VRAM: <strong>${hwInfo.details.total_vram_gb} GB</strong> (from reliable sources)`;
        } else if (hwInfo.gpu_list && hwInfo.gpu_list.length > 0) {
            let calculatedVram = 0;
            let reliableSourceFound = false;
            hwInfo.gpu_list.forEach(gpu => {
                if (gpu.memory_total_gb && ['nvidia-smi', 'wmic'].includes(gpu.source)) {
                    calculatedVram += gpu.memory_total_gb;
                    reliableSourceFound = true;
                }
            });
            if (reliableSourceFound) {
                vramText = `Total Detected GPU VRAM: <strong>${calculatedVram.toFixed(1)} GB</strong> (from reliable sources)`;
            }
        }

        if (hwInfo.gpu_list && hwInfo.gpu_list.length > 0) {
            gpuListText = "Detected GPUs:<ul>";
            hwInfo.gpu_list.forEach(gpu => {
                const vramInfo = gpu.memory_total_gb ? `${gpu.memory_total_gb} GB` : 'VRAM N/A';
                const sourceInfo = gpu.source ? `(Source: ${gpu.source})` : '';
                gpuListText += `<li>${gpu.name || 'Unknown GPU'} - ${vramInfo} ${sourceInfo}</li>`;
            });
            gpuListText += "</ul>";
        } else {
            gpuListText = "<p>No specific GPUs detected by the backend checker.</p>";
        }

        if (totalVram >= 22) {
            recommendationText += "<li>Suitable for large models (e.g., 70B Q4, 34B).</li>";
        } else if (totalVram >= 14) {
            recommendationText += "<li>Suitable for medium models (e.g., 34B Q4, 13B).</li>";
        } else if (totalVram >= 7) {
            recommendationText += "<li>Suitable for smaller models (e.g., 13B Q4, 7B).</li>";
        } else if (totalVram >= 3.5) {
            recommendationText += "<li>Suitable for tiny models (e.g. 4B or less).</li>";
        } else {
            recommendationText += "<li>Limited VRAM. May only run very small models or rely heavily on CPU/RAM.</li>";
        }
        recommendationText += "<li>Note: RAM is also important for running models.</li></ul>";
        if (hwInfo.platform === 'darwin') {
            recommendationText += "<p>On macOS, Ollama uses Metal acceleration on Apple Silicon.</p>";
        }

        hardwareInfoElement.innerHTML = `
            <p>${vramText}</p>
            ${gpuListText}
            ${recommendationText}
        `;

        // Store VRAM for model recommendation logic
        config.set('ollama.totalVram', totalVram);
        config.saveConfig();
    } catch (error) {
        console.error('Error fetching or displaying hardware info:', error);
        hardwareInfoElement.innerHTML = `<p class="error">Could not retrieve hardware information: ${error.message}</p>`;
    }
}

// New function to display Ollama models and management UI
async function displayOllamaModels() {
    const modelsContainer = document.getElementById('ollama-models-container');
    if (!modelsContainer) return;

    modelsContainer.innerHTML = '<p>Loading Ollama models...</p>';
    let modelsInfo = ""
    // const ollamaip = config.get('ollama.serverIp', '127.0.0.1');
    // const totalVram = config.get('ollama.totalVram', 0);

    // if (totalVram > 0 && totalVram < 12 && (ollamaip == "127.0.0.1" || ollamaip == "127.0.0.1") ) {
    //     modelsInfo += '<div class="warning-block">';
    //     modelsInfo += 'Ollama is configured to run locally and your system has less than 12GB of VRAM (' + totalVram.toFixed(1) + 'GB detected). ';
    //     modelsInfo += 'This may not be sufficient to run local LLMs effectively for the skills/tools system in this application. ';
    //     modelsInfo += 'Consider using cloud-based providers for better performance.';
    //     modelsInfo += '</div>';
    // }

    try {
        const serverIp = config.get('ollama.serverIp', '127.0.0.1');
        const port = config.get('ollama.port', 11434);
        const client = new ollama.Ollama({ host: `http://${serverIp}:${port}` });
        const modelsResponse = await client.list();
        console.log("Ollama Models:", modelsResponse);

        let modelsHtml = '<h3>Local Ollama Models</h3>';
        if (modelsResponse.models && modelsResponse.models.length > 0) {
            modelsHtml += '<ul>';
            modelsResponse.models.forEach(model => {
                modelsHtml += `<li>${model.name} <button class="delete-model-btn" data-model="${model.name}">Delete</button></li>`;
            });
            modelsHtml += '</ul>';
        } else {
            modelsHtml += '<p>No local models found. Download models to use Ollama locally.</p>';
        }

        // Extract names of local models for easy lookup
        const localModelNames = modelsResponse.models ? modelsResponse.models.map(model => model.name) : [];
        const recommendedModels = getRecommendedModels();
        const featuredModelsForDropdown = recommendedModels.filter(model => !localModelNames.some(name => name.includes(model.id.split(':')[0])));

        modelsHtml += '<h3>Recommended Models</h3>';

        if (featuredModelsForDropdown.length === 0) {
            modelsHtml += '<p>No featured models left to be added</p>';
        } else {
            modelsHtml += '<select id="ollama-model-select">';
            featuredModelsForDropdown.forEach(model => {
                modelsHtml += `<option value="${model.id}">${model.name} (${model.size} GB)</option>`;
            });
            modelsHtml += '</select>';
            modelsHtml += '<button id="download-model-btn">Download Model</button>';
        }

        // Add "Other models" section
        modelsHtml += '<h3>Other models</h3>';
        modelsHtml += '<p>You can download other models from <a href="#" class="external-link" data-url="https://ollama.com/library">Ollama Hub</a>. Please pay attention to the recommendations in the "Warning" section. Enter the model name (e.g., mistral:latest).</p>';
        modelsHtml += '<input type="text" id="ollama-other-model-input" placeholder="e.g., mistral:latest" style="width: 280px; margin-right: 10px;">';
        modelsHtml += '<button id="download-other-model-btn">Download Model</button>';

        modelsHtml += '<div id="download-progress"></div>';

        modelsContainer.innerHTML = modelsInfo+modelsHtml;

        // Add event listeners for delete buttons
        document.querySelectorAll('.delete-model-btn').forEach(btn => {
            btn.addEventListener('click', async () => {
                const modelName = btn.dataset.model;
                if (confirm(`Are you sure you want to delete ${modelName}?`)) {
                    btn.disabled = true; // Disable delete button during operation
                    await deleteOllamaModel(client, modelName);
                }
            });
        });

        // Add event listener for download button
        const downloadBtn = document.getElementById('download-model-btn');
        if (downloadBtn) {
            downloadBtn.addEventListener('click', async () => {
                downloadBtn.disabled = true; // Disable download button during operation
                const modelSelect = document.getElementById('ollama-model-select');
                const modelId = modelSelect.value;
                await downloadOllamaModel(client, modelId, downloadBtn); // Pass the button element
            });
        }

        // Add event listener for the "Other model" download button
        const downloadOtherModelBtn = document.getElementById('download-other-model-btn');
        if (downloadOtherModelBtn) {
            downloadOtherModelBtn.addEventListener('click', async () => {
                downloadOtherModelBtn.disabled = true; // Disable download button during operation
                const modelInput = document.getElementById('ollama-other-model-input');
                const modelId = modelInput.value.trim();
                if (modelId) {
                    await downloadOllamaModel(client, modelId, downloadOtherModelBtn); // Pass the button element
                    modelInput.value = ''; // Clear input after attempting download
                } else {
                    alert('Please enter a model name to download.');
                }
            });
        }
    } catch (error) {
        console.error('Error fetching Ollama models:', error);
        modelsContainer.innerHTML = modelsInfo+`<div class="warning-block">Ollama is not available. To use Ollama models in Ainara ensure is installed and running in the specified address, then reboot Ainara.<br><a class="external-link" href="#" data-url="https://ollama.com/download">Ollama download link</a></div>`;
    }
}

// New function to get recommended models based on VRAM
function getRecommendedModels() {
    const totalVram = config.get('ollama.totalVram', 0);
    console.log("Total VRAM for model recommendation:", totalVram);
    const models = [
        { id: 'qwen3:1.7b', name: 'Qwen 3 (1.7B)', size: 1.4, minVram: 4},
        { id: 'qwen3:4b', name: 'Qwen 3 (4B)', size: 2.5, minVram: 8},
        { id: 'qwen3:8b', name: 'Qwen 3 (8B)', size: 5.2, minVram: 8},
        { id: 'qwen3:14b', name: 'Qwen 3 (14B)', size: 9, minVram: 12 },
        { id: 'qwen3:30b', name: 'Qwen 3 (30B)', size: 19, minVram: 24 },
        { id: 'qwen3:32b', name: 'Qwen 3 (32B)', size: 20, minVram: 24 },
        { id: 'gpt-oss:20b', name: 'gpt-oss (20B)', size: 14, minVram: 24 },
        /*
         * TODO test DeepSeek r1 models
        { id: 'deepseeek-r1:7b', name: 'DeepSeek-R1 (7B)', size: 4.7, minVram: 8 },
        { id: 'deepseeek-r1:8b', name: 'DeepSeek-R1 (8B)', size: 5.2, minVram: 8 },
        { id: 'deepseeek-r1:14b', name: 'DeepSeek-R1 (14B)', size: 9, minVram: 8 },
        { id: 'deepseeek-r1:32b', name: 'DeepSeek-R1 (32B)', size: 20, minVram: 24 },
        */
    ];

    const filteredModels = models.filter(model => totalVram >= model.minVram);
    console.log("Filtered Models based on VRAM:", filteredModels);
    return filteredModels.length > 0 ? filteredModels : models; // Return all models if none meet VRAM criteria
}

// New function to download Ollama model
async function downloadOllamaModel(client, modelId, buttonElement) {
    const progressDiv = document.getElementById('download-progress');
    if (buttonElement) buttonElement.disabled = true;
    progressDiv.innerHTML = `<p>Initiating download for ${modelId}...</p>`;
    let downloadCompletedSuccessfully = false;

    try {
        const stream = await client.pull({
            model: modelId,
            stream: true
        });
        for await (const part of stream) {
            if (part.digest) {
                let percent = 0;
                if (part.completed && part.total) {
                    percent = Math.round((part.completed / part.total) * 100);
                }
                progressDiv.innerHTML = `<p>${part.status}: ${percent}%</p>`;
            } else if (part.status) {
                progressDiv.innerHTML = `<p>${part.status}</p>`;
                if (part.status.includes('success') || part.status.includes('completed')) {
                    downloadCompletedSuccessfully = true;
                    progressDiv.innerHTML = `<p>${modelId} downloaded successfully!</p>`;
                }
            }
        }
        if (downloadCompletedSuccessfully) {
            progressDiv.innerHTML += `<p>Refreshing model list...</p>`;
            // Load the model into memory after download
            progressDiv.innerHTML += `<p>Loading model into memory...</p>`;
            await loadOllamaModel(client, modelId);
            // Update providers list with new model
            progressDiv.innerHTML += `<p>Updating providers list...</p>`;
            await updateOllamaProviders();
            // Refresh model list after a short delay to ensure Ollama has processed the new model
            setTimeout(() => {
                displayOllamaModels(); // This will re-enable buttons as part of the refresh
            }, 1000);
        }
        buttonElement.disabled = false; // Re-enable button if download fails or completes
        progressDiv.scrollIntoView({ behavior: 'smooth', block: 'end' }); // Ensure progress is visible
    } catch (error) {
        console.error('Error downloading model:', error);
        progressDiv.innerHTML = `<p class="error">Error downloading ${modelId}: ${error.message}</p>`;
        buttonElement.disabled = false; // Re-enable button on error
    }
}

// New function to delete Ollama model
async function deleteOllamaModel(client, modelName) {
    try {
        await client.delete({ model: modelName });
        alert(`${modelName} deleted successfully.`);

        // Update providers list after deletion
        await updateOllamaProviders();

        await displayOllamaModels();
        loadExistingProviders(); // Refresh the providers list in the LLM step
    } catch (error) {
        console.error('Error deleting model:', error);
        alert(`Error deleting ${modelName}: ${error.message}`);
    }
}

// Add new function to load Ollama model into memory
async function loadOllamaModel(client, modelId) {
    try {
        // Ollama client does not have a direct "load" method, but we can send a request to ensure it's ready
        // For example, send a simple chat request or check model status
        await client.chat({
            model: modelId,
            messages: [{ role: 'user', content: 'Hello, are you ready?' }],
            stream: false
        });
        console.log(`Model ${modelId} loaded and ready.`);
        const progressDiv = document.getElementById('download-progress');
        progressDiv.innerHTML += `<p>Model ${modelId} loaded and ready.</p>`;
    } catch (error) {
        console.error(`Error loading model ${modelId}:`, error);
        const progressDiv = document.getElementById('download-progress');
        progressDiv.innerHTML += `<p class="error">Error loading model ${modelId}: ${error.message}</p>`;
    }
}

async function finishSetup() {
    // console.info("Saving pending changes..");
    // Save any pending changes from the last configurable steps
    saveShortcutsConfig(); // Save shortcuts if modified
    await saveFinishStepConfig(); // Save finish step settings (like start minimized)

    // console.info("Marking setup as completed..");
    // Mark setup as completed
    config.set('setup.completed', true);
    config.set('setup.version', '0.10.2');
    config.set('setup.timestamp', new Date().toISOString());

    // console.info("Saving config...");
    // Save the final config state including setup completion flags
    config.saveConfig();

    // Notify main process that setup is complete
    // console.info("Sending setup-complete signal");
    ipcRenderer.send('setup-complete');
    // console.info("finishSetup done");
}

async function setupAuthListeners() {
    const verifyBtn = document.getElementById('verify-wallet-btn');
    const walletInput = document.getElementById('wallet-address-input'); // We will hide/ignore this
    const statusMsg = document.getElementById('auth-status-message');
    const authContainer = document.getElementById('auth-container');

    // Hide the manual input if it exists, we don't need it anymore
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

    async function checkSolanaLogin()  {
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

function setupTosListeners() {
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
