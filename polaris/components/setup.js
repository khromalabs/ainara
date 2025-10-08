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
const ConfigHelper = require('../framework/ConfigHelper');
// const fs = require('fs');
// const path = require('path');
// const yaml = require('js-yaml');


const ollama = require('ollama');


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
document.addEventListener('DOMContentLoaded', () => {
    setupEventListeners();
    loadProviders();
    updateLLMStepTitle(); // Update the LLM step title
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
            description: 'Used for cryptocurrency market data'
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

        // Extract API keys
        const apiKeys = extractApiKeysFromConfig(sampleConfig);

        // Generate HTML for each API key
        let html = '';

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

        // Generate HTML for each category
        for (const [category, keyGroups] of categories.entries()) {
            if (keyGroups.length === 0) continue;

            html += `
                <div class="skill-category">
                    <h3>${category.charAt(0).toUpperCase() + category.slice(1)}</h3>
                    <div class="skill-items">
            `;

            keyGroups.forEach(group => {
                // const pathParts = group.parentPath.split('.');
                // const serviceName = pathParts[pathParts.length - 1];

                html += `
                    <div class="skill-item" data-group-path="${group.parentPath}">
                        <h4>${group.displayName} <span class="skill-validation-status" id="status-${group.parentPath.replace(/\./g, '-')}"></span></h4>
                        <div class="skill-validation-message" id="message-${group.parentPath.replace(/\./g, '-')}"></div>
                `;

                // Use the description from the first key in the group
                if (group.keys.length > 0 && group.keys[0].description) {
                    if (group.keys[0].description.text) {
                        html += `<p>${group.keys[0].description.text}</p>`;
                    }

                    if (group.keys[0].description.url) {
                        html += `<p>Get API key(s) from: <a href="#" class="external-link" data-url="${group.keys[0].description.url}">${new URL(group.keys[0].description.url).hostname}</a></p>`;
                    }
                }

                // Add all keys for this group
                group.keys.forEach(key => {
                    html += `
                        <div class="form-group">
                            <label for="api-key-${key.path.replace(/\./g, '-')}">${key.displayName}:</label>
                            <input type="text" placeholder="${key.keyName}" id="api-key-${key.path.replace(/\./g, '-')}" data-path="${key.path}">
                        </div>
                    `;
                });

                html += `</div>`;
            });

            html += `
                    </div>
                </div>
            `;
        }

        // Update the skills list container
        const skillsListContainer = document.querySelector('.skills-list');
        if (skillsListContainer) {
            skillsListContainer.innerHTML = html;
            skillsListContainer.insertAdjacentHTML('beforeend', `
                <div class="validate-all-container" style="text-align: center; margin-top: 20px; margin-bottom: 10px; display: flex; justify-content: center; gap: 10px;">
                    <button id="reset-skills-btn" class="btn btn-secondary">Reset Changes</button>
                    <button id="validate-all-keys-btn" class="btn">Validate API Keys</button>
                </div>
            `);
        }

        // Add event listeners to all input fields
        document.querySelectorAll('.skills-list input[data-path]').forEach(input => {
            input.addEventListener('input', (event) => handleInputChange(event));
        });

        // Add event listener for the main validation button
        document.getElementById('validate-all-keys-btn').addEventListener('click', validateAllApiKeys);

        // Add event listener for the reset button
        document.getElementById('reset-skills-btn').addEventListener('click', resetApiKeys);

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

    if (currentStep === 'llm') {
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

    // Add CSS for hardware acceleration info and shortcuts
    const style = document.createElement('style');
    style.textContent = `
        .hardware-info {
            margin-bottom: 20px;
            padding: 15px;
            background-color: #f8f9fa;
            border-radius: 8px;
            /* border-left: 4px solid #6c757d; */
         }

        .success-message {
            color: #28a745;
            font-weight: bold;
            margin-bottom: 10px;
            display: flex;
            align-items: center;
        }

        .warning-message {
            color: #ffc107;
            font-weight: bold;
            margin-bottom: 10px;
            display: flex;
            align-items: center;
        }

        .info-message {
            color: #17a2b8;
            font-weight: bold;
            margin-bottom: 10px;
            display: flex;
            align-items: center;
        }

        .success-message .icon,
        .warning-message .icon,
        .info-message .icon {
            margin-right: 8px;
            font-size: 1.2em;
        }

        .hardware-info p {
            margin: 8px 0;
        }

        .hardware-info a {
            color: #007bff;
            text-decoration: underline;
        }

        .gpu-details {
            background-color: #f0f0f0;
            padding: 10px;
            border-radius: 4px;
            margin-top: 10px;
        }

        .gpu-details ul {
            margin: 5px 0 0 20px;
            padding: 0;
        }

        .gpu-details li {
            margin-bottom: 5px;
        }

        .hardware-info ul {
            margin: 5px 0 0 20px;
            padding: 0;
        }

        .hardware-info li {
            margin-bottom: 5px;
        }

        #ollama-models-container {
            margin-top: 20px;
        }

        #ollama-models-container ul {
            list-style-type: none;
            padding: 0;
        }

        #ollama-models-container li {
            background-color: #f9f9f9;
            padding: 10px;
            margin-bottom: 5px;
            border-radius: 4px;
            border: 1px solid #ddd;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        #ollama-models-container select {
            padding: 8px;
            margin-right: 10px;
            border: 1px solid #ddd;
            border-radius: 4px;
            width: 300px;
        }

        #download-model-btn {
            background-color: #28a745;
            color: white;
            padding: 10px 20px;
            border: none;
            border-radius: 4px;
            cursor: pointer;
            transition: background-color 0.3s;
        }

        #download-model-btn:hover {
            background-color: #218838;
        }

        #download-model-btn:disabled {
            background-color: #ccc;
            cursor: not-allowed;
        }

        #download-progress {
            margin-top: 10px;
            padding: 10px;
            border-radius: 4px;
        }

        #download-progress p {
            margin: 0;
        }

        .delete-model-btn {
            background-color: #dc3545;
            color: white;
            border: none;
            padding: 5px 10px;
            border-radius: 4px;
            cursor: pointer;
            transition: background-color 0.3s;
        }

        .delete-model-btn:hover {
            background-color: #c82333;
        }

        .field-description {
            font-size: 0.8em;
            color: #6c757d;
            margin-top: 4px;
        }

        .skill-test-container {
            margin-top: 10px;
            display: flex;
            align-items: center;
            gap: 10px;
        }
        .skill-test-status.success {
            color: #28a745;
            font-weight: bold;
        }
        .skill-test-status.error {
            color: #dc3545;
            font-weight: bold;
            background-color: #00000000 !important;
        }
        .skill-validation-status {
            display: inline-block;
            width: 16px;
            height: 16px;
            margin-left: 8px;
            vertical-align: middle;
            font-size: 16px;
            line-height: 1;
            background-color: transparent;
        }
        .skill-validation-status.success::after {
            content: '✔';
            color: #28a745;
        }
        .skill-validation-status.error::after {
            content: '✖';
            color: #dc3545;
        }
        .skill-validation-status.pending::after {
            content: '...';
            color: #6c757d;
        }

        .skill-validation-message {
            margin-top: 5px;
            font-size: 0.9em;
        }

        .skill-validation-message.success {
            color: #28a745;
        }

        .skill-validation-message.error {
            color: #dc3545;
            font-weight: bold;
        }

        /* Shortcuts panel styles */
        .shortcuts-container {
            display: flex;
            flex-direction: column;
            gap: 20px;
        }

        .shortcut-group {
            background-color: #f8f9fa;
            padding: 15px;
            border-radius: 8px;
            /* border-left: 4px solid #007bff; */
        }

        .shortcut-group h3 {
            margin-top: 0;
            color: #007bff;
        }

        .shortcut-description {
            font-size: 0.9em;
            color: #6c757d;
            margin-top: 5px;
        }

        .usage-instructions {
            background-color: #f8f9fa;
            padding: 15px;
            border-radius: 8px;
            /* border-left: 4px solid #28a745; */
        }

        .usage-instructions h3 {
            margin-top: 0;
            color: #28a745;
        }

        .usage-instructions ol {
            padding-left: 20px;
        }

        .usage-instructions li {
            margin-bottom: 10px;
        }

        #show-key-display,
        #hide-key-display,
        #trigger-key-display {
            background-color: #e9ecef;
            padding: 2px 6px;
            border-radius: 4px;
            font-family: monospace;
            font-weight: bold;
        }

        input.capturing {
            background-color: #ffe8e8;
            border-color: #dc3545;
        }
    `;
    document.head.appendChild(style);

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

            // Add event listener for the review stt checkbox
            const reviewSttCheckbox = document.getElementById('review-stt-checkbox');
            if (reviewSttCheckbox) {
                reviewSttCheckbox.addEventListener('change', (event) => handleInputChange(event));
                reviewSttCheckbox.checked = config.get('stt.review');
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

            // Add event listener for the backup directory input and browse button
            const backupDirectoryInput = document.getElementById('backup-directory-input');
            const browseBackupDirectoryBtn = document.getElementById('browse-backup-directory-btn');

            if (backupDirectoryInput) {
                backupDirectoryInput.addEventListener('input', (event) => handleInputChange(event));
                backupDirectoryInput.value = config.get('startup.backupDirectory', '');

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
                filterInput.value = 'xai,qwen3,deepseek';
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
                    filterInput.value = 'qwen3,deepseek,-8b,-3b';
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
                        const nextButton = document.getElementById('main-next-btn');

                        testResult.classList.add('hidden');
                        nextButton.disabled = true;

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

// Replace the existing loadProviders function
function loadProviders() {
    // First load existing providers from backend config
    const nextButton = document.getElementById('main-next-btn');
    const testResult = document.getElementById('test-result');

    // Reset UI state related to new provider testing and assume button is disabled initially.
    // It will be enabled by loadExistingProviders if a valid selection exists,
    // or by testLLMConnectionFetch if a new provider is successfully tested.
    testResult.classList.add('hidden');
    nextButton.disabled = true;

    loadExistingProviders(); // This might enable nextButton if an existing provider is selected.

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
                        ${provider.context_window ? `Context: ${provider.context_window / 1024}K` : ''}
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
            if (hasSelectedProvider) {
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

                    // Enable the next button
                    document.getElementById('main-next-btn').disabled = false;

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
    const nextButton = document.getElementById('main-next-btn');

    // Hide test result and disable next button when provider changes
    testResult.classList.add('hidden');
    nextButton.disabled = true;

    if (!selectedProviderId || !providersData || !providersData[selectedProviderId]) {
        detailsContainer.innerHTML = '';
        testButton.disabled = true;
        return;
    }

    const provider = providersData[selectedProviderId];

    let html = `
        <h3>${provider.name} Configuration</h3>
    `;

    if (provider.website) {
        html += `<p>Get your API key from <a href="${provider.website}" target="_blank">${provider.website}</a></p>`;
    }

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

        html += `
            <div class="form-group">
                <label for="${selectedProviderId}-${field.id}">${field.name}:</label>
                <input
                    type="${field.type}"
                    id="${selectedProviderId}-${field.id}"
                    ${field.placeholder ? `placeholder="${field.placeholder}"` : ''}
                    ${field.required ? 'required' : ''}
                    ${isCustomProvider && isApiBaseField ? `value="http://192.168.1.200:7080"` : ``}
                    ${isCustomProvider && field.id === 'model' ? `value="openai/gamingpc"` : ``}
                >
            </div>
        `;
    });

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
            <label for="${selectedProviderId}-context_window">Context Window (Optional):</label>
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
        input.addEventListener('input', (event) => handleInputChange(event));
    });

    validateProviderForm();
}

// New function to handle input changes
function handleInputChange(event) {
    // Hide test result and disable next button when any input changes
    const testResult = document.getElementById('test-result');
    const nextButton = document.getElementById('main-next-btn');

    testResult.classList.add('hidden');
    nextButton.disabled = true;

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
        } else if (fieldId === 'start-minimized-checkbox' || fieldId === 'review-stt-checkbox' || fieldId === 'background-notifications-checkbox' || fieldId === 'backup-directory-input' || fieldId === 'auto-start-checkbox') {
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

    listElement.innerHTML = '<li class="loading">Loading capabilities...</li>'; // Show loading state

    try {
        // Use pybridge URL as the base for capabilities endpoint
        const response = await fetch(config.get('orakle.api_url') + '/capabilities');
        if (!response.ok) {
            throw new Error(`Failed to fetch capabilities: ${response.status} ${response.statusText}`);
        }
        const data = await response.json();
        if (data && data instanceof Object && Object.keys(data).length > 0) {
            listElement.innerHTML = ''; // Clear loading state
            Object.keys(data).forEach(skillId => {
                let skill = data[skillId];
                const li = document.createElement('li');
                li.textContent = skill.description;
                if (skill.type == "mcp") {
                    li.textContent += " (" + skill.type + ":" + skill.server + ")"
                } else {
                    li.textContent += " (native skill)"
                }
                listElement.appendChild(li);
            });
        } else {
            listElement.innerHTML = '<li class="info">No specific capabilities listed by the backend.</li>';
        }
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
    nextButton.disabled = !allValid;
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
function setupSTTEventListeners() {
    const sttNextButton = document.getElementById('main-next-btn');
    const sttPanel = document.getElementById('stt-panel');

    // Add hardware acceleration info section if it doesn't exist
    if (!document.getElementById('hardware-acceleration-info')) {
        const infoHtml = `
            <div id="hardware-acceleration-info" class="hardware-info">
                <h3>Hardware Acceleration</h3>
                <div id="hardware-status">Checking hardware acceleration status...</div>
            </div>
        `;

        // Insert before the STT options
        const sttOptions = sttPanel.querySelector('.stt-options');
        if (sttOptions) {
            sttOptions.insertAdjacentHTML('beforebegin', infoHtml);
        }

        // Check hardware acceleration status
        ConfigHelper.getHardwareAcceleration().then(result => {
            const statusElement = document.getElementById('hardware-status');
            if (statusElement) {
                if (result.cuda_available) {
                    statusElement.innerHTML = `
                        <div class="success-message">
                            <span class="icon">✓</span>
                            <span>CUDA ${result.cuda_version || ''} is available</span>
                        </div>
                        <p>Your system will use GPU acceleration for faster speech recognition.</p>
                    `;

                    // Show GPU details if available
                    if (result.gpu_list && result.gpu_list.length > 0) {
                        let gpuHtml = `<div class="gpu-details"><p>Using GPU(s):</p><ul>`;
                        result.gpu_list.forEach(gpu => {
                            gpuHtml += `<li>${gpu.name} ${gpu.memory ? '(' + gpu.memory + ')' : ''}</li>`;
                        });
                        gpuHtml += `</ul></div>`;
                        statusElement.innerHTML += gpuHtml;
                    }
                } else if (result.has_nvidia_hardware) {
                    // NVIDIA hardware detected but CUDA not available
                    let helpText = '';
                    if (result.platform === 'win32') {
                        helpText = `
                            <p>An NVIDIA GPU was detected, but CUDA drivers are not installed or not working properly.</p>
                            <p>For faster speech recognition, we recommend installing NVIDIA CUDA drivers:</p>
                            <p><a href="#" class="external-link" data-url="https://www.nvidia.com/Download/index.aspx">Download NVIDIA Drivers</a></p>
                            <p><a href="#" class="external-link" data-url="https://developer.nvidia.com/cuda-downloads">Download CUDA Toolkit</a></p>
                            <p>You can continue without GPU acceleration, but speech recognition will be slower.</p>
                        `;
                    } else if (result.platform === 'linux') {
                        helpText = `
                            <p>An NVIDIA GPU was detected, but CUDA drivers are not installed or not working properly.</p>
                            <p>For faster speech recognition, install NVIDIA drivers using your distribution's package manager.</p>
                            <p>You can continue without GPU acceleration, but speech recognition will be slower.</p>
                        `;
                    }

                    // Show GPU details if available
                    if (result.gpu_list && result.gpu_list.length > 0) {
                        helpText += `<div class="gpu-details"><p>Detected GPU(s):</p><ul>`;
                        result.gpu_list.forEach(gpu => {
                            helpText += `<li>${gpu.name} ${gpu.driver_version ? '(Driver: ' + gpu.driver_version + ')' : ''}</li>`;
                        });
                        helpText += `</ul></div>`;
                    }

                    statusElement.innerHTML = `
                        <div class="warning-message">
                            <span class="icon">⚠</span>
                            <span>Hardware acceleration not available</span>
                        </div>
                        ${helpText}
                    `;
                } else if (result.platform === 'darwin') {
                    // macOS - no NVIDIA hardware
                    let helpText = `
                        <p>On macOS, Metal is used for acceleration on Apple Silicon.</p>
                        <p>CPU will be used on Intel Macs, which may be slower for speech recognition.</p>
                    `;

                    statusElement.innerHTML = `
                        <div class="info-message">
                            <span class="icon">ℹ</span>
                            <span>Using macOS native acceleration</span>
                        </div>
                        ${helpText}
                    `;
                } else {
                    // No NVIDIA hardware detected
                    let helpText = `
                        <p>Your system will use CPU for speech recognition, which may be slower.</p>
                        <p>If you have an NVIDIA GPU, installing CUDA drivers can improve performance.</p>
                    `;

                    statusElement.innerHTML = `
                        <div class="info-message">
                            <span class="icon">ℹ</span>
                            <span>No NVIDIA GPU detected</span>
                        </div>
                        ${helpText}
                    `;
                }
            }
        }).catch(error => {
            console.error('Failed to check hardware acceleration:', error);
            const statusElement = document.getElementById('hardware-status');
            if (statusElement) {
                statusElement.innerHTML = `
                    <div class="warning-message">
                        <span class="icon">⚠</span>
                        <span>Unable to check hardware acceleration status</span>
                    </div>
                    <p>Speech recognition will work, but may be slower without GPU acceleration.</p>
                `;
            }
        });
    }

    // Show/hide details based on selection
    document.querySelectorAll('input[name="stt-backend"]').forEach(radio => {
        radio.addEventListener('change', () => {
            // Hide all details first
            document.querySelectorAll('.stt-details').forEach(el => {
                el.style.display = 'none';
            });

            // Show details for selected option
            const selectedValue = radio.value;
            if (selectedValue === 'custom') {
                document.getElementById('custom-stt-details').style.display = 'block';
                // Disable next button until validation passes
                sttNextButton.disabled = true;
            } else {
                // Enable next button for built-in option
                sttNextButton.disabled = false;
            }

            // Hide any previous validation messages
            document.getElementById('stt-test-result').classList.add('hidden');

            // Track this change
            modifiedFields.stt.add('stt-backend');
        });
    });

    // Add input validation for custom API fields
    const apiUrlInput = document.getElementById('custom-api-url');
    const apiKeyInput = document.getElementById('custom-api-key');

    [apiUrlInput, apiKeyInput].forEach(input => {
        if (input) {
            input.addEventListener('input', validateSTTForm);
        }
    });

    // Initial validation
    validateSTTForm();
}

// Validate STT form inputs
function validateSTTForm() {
    const selectedBackend = document.querySelector('input[name="stt-backend"]:checked')?.value;
    const sttNextButton = document.getElementById('main-next-btn');
    const testResult = document.getElementById('stt-test-result');

    // Reset validation state
    testResult.classList.add('hidden');

    // If using built-in whisper, always valid
    if (selectedBackend === 'faster_whisper') {
        sttNextButton.disabled = false;
        return true;
    }

    // For custom API, validate URL and key
    if (selectedBackend === 'custom') {
        const apiUrl = document.getElementById('custom-api-url').value.trim();

        // URL is required
        if (!apiUrl) {
            sttNextButton.disabled = true;
            testResult.textContent = 'API URL is required';
            testResult.classList.remove('hidden');
            testResult.classList.add('error');
            return false;
        }

        // Validate URL format
        try {
            new URL(apiUrl);
            sttNextButton.disabled = false;
            return true;
        } catch (e) {
            console.log(e);
            sttNextButton.disabled = true;
            testResult.textContent = 'Please enter a valid URL';
            testResult.classList.remove('hidden');
            testResult.classList.add('error');
            return false;
        }
    }

    return false;
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

// Function to save STT config
async function saveSTTConfig() {
    const selectedBackend = document.querySelector('input[name="stt-backend"]:checked')?.value || 'faster_whisper';

    // If no STT fields were modified and we're using the default, skip saving
    const usingDefault = selectedBackend === 'faster_whisper';
    if (modifiedFields.stt.size === 0 && usingDefault) {
        return;
    }

    // Save to Polaris config
    const sttConfig = {
        backend: selectedBackend
    };

    if (selectedBackend === 'custom') {
        const apiUrl = document.getElementById('custom-api-url').value;
        const apiKey = document.getElementById('custom-api-key').value;

        if (apiUrl) {
            sttConfig.custom = {
                apiUrl,
                apiKey: apiKey || 'local' // Use 'local' as default if no key provided
            };
        }
    }

    config.set('stt', sttConfig);
    config.saveConfig();

    try {
        // Load current backend config
        const backendConfig = await loadBackendConfig();

        // Ensure STT section exists
        if (!backendConfig.stt) {
            backendConfig.stt = { default_module: "custom" };
        }

        // Update backend based on selection
        backendConfig.stt.backend = selectedBackend;

        if (selectedBackend === 'custom') {
            const apiUrl = document.getElementById('custom-api-url').value;
            const apiKey = document.getElementById('custom-api-key').value;

            if (!backendConfig.stt.modules) {
                backendConfig.stt.modules = {};
            }
            if (!backendConfig.stt.modules.whisper) {
                backendConfig.stt.modules.whisper = {};
            }

            backendConfig.stt.modules.whisper.service = 'custom';
            if (!backendConfig.stt.modules.whisper.custom) {
                backendConfig.stt.modules.whisper.custom = {};
            }

            if (apiUrl) {
                backendConfig.stt.modules.whisper.custom.api_url = apiUrl;
            }
            if (apiKey) {
                backendConfig.stt.modules.whisper.custom.api_key = apiKey;
            } else {
                backendConfig.stt.modules.whisper.custom.api_key = 'local';
            }
        }

        // Save the updated backend config
        await saveBackendConfig(backendConfig, config.get('pybridge.api_url'));
        // await saveBackendConfig(backendConfig, config.get('orakle.api_url'));

        // After successful save, clear the modified fields tracking
        modifiedFields.stt.clear();
    } catch (error) {
        console.error('Error updating STT config:', error);
    }
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

        // console.log("======================");
        // console.log("backendConfig");
        // console.log(JSON.stringify(backendConfig));
        // console.log("======================");

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

        if (modifiedFields.finish.has('review-stt-checkbox')) {
            const isChecked = document.getElementById('review-stt-checkbox').checked;
            config.set('stt.review', isChecked);
        }

        if (modifiedFields.finish.has('background-notifications-checkbox')) {
            const isChecked = document.getElementById('background-notifications-checkbox').checked;
            config.set('ui.backgroundNotifications', isChecked);
        }

        if (modifiedFields.finish.has('backup-directory-input')) {
            const backupDirectory = document.getElementById('backup-directory-input').value.trim();
            config.set('startup.backupDirectory', backupDirectory);

            // Save to backend config
            const backendConfig = await loadBackendConfig();
            if (!backendConfig.backup) {
                backendConfig.backup = {};
            }
            backendConfig.backup.directory = backupDirectory;
            backendConfig.backup.enabled = !!backupDirectory; // Enable if directory is not empty

            await saveBackendConfig(backendConfig, config.get('pybridge.api_url'));
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
            titleElement.textContent = 'LLM Provider Selection';
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
            const performanceWarning = `<p>PLEASE NOTE: Ainara requires at very least a 4B model, but 7B at least is strongly recommended. Carefully select the size of the model accordingly to your available VRAM, your RAM performance for specific systems, or system RAM for Apple Silicon systems.<br>
                        Ollama can run models fully on CPU and normal RAM on all supported systems, but that will give very bad performance in most scenarios.
                        As a rule of thumb, unless owning very specific fast hardware, you should only choose models with an amount of parameters closely matching your available VRAM (eg. Qwen 14B is good for a RTX3060 with 12GB of VRAM available).</p>`
            if (totalVram < 12 || (isAppleSilicon && totalRam < 16)) {
                hardwareInfoElement.innerHTML += `
                    <div class="warning-block">
                        Your system hardware requirements are quite tight to run LLMs with Ollama effectively.
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
                        <p>The Ollama setup has been disabled. You can proceed to the next step to configure other providers.</p>
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
            recommendationText += "<li>Suitable for tiny models (e.g., 7B Q4, 3B).</li>";
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
    // Save any pending changes from the last configurable steps
    saveShortcutsConfig(); // Save shortcuts if modified
    await saveFinishStepConfig(); // Save finish step settings (like start minimized)

    // Mark setup as completed
    config.set('setup.completed', true);
    config.set('setup.version', '0.9.1');
    config.set('setup.timestamp', new Date().toISOString());

    // Save the final config state including setup completion flags
    config.saveConfig();

    // Notify main process that setup is complete
    ipcRenderer.send('setup-complete');
}
