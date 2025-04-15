const { ipcRenderer } = require('electron');
const ConfigManager = require('../../utils/config');
const Logger = require('../../utils/logger');
// const fs = require('fs');
// const path = require('path');
// const yaml = require('js-yaml');

// Create a ConfigManager instance
const config = new ConfigManager();

// Step navigation
const steps = ['welcome', 'llm', 'stt', 'skills', 'shortcuts', 'finish'];
let currentStepIndex = 0;
let providersData = null;

// Initialize the UI
document.addEventListener('DOMContentLoaded', () => {
    setupEventListeners();
    loadProviders();
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
    // Special cases for known services
    // const lastPart = pathArray[pathArray.length - 1];
    // const parentPart = pathArray.length > 1 ? pathArray[pathArray.length - 2] : '';

    /*
    if (lastPart === 'api_key' || lastPart === 'apiKey') {
        if (parentPart === 'openweathermap') {
            return 'OpenWeatherMap API Key';
        } else if (parentPart === 'alphavantage') {
            return 'Alpha Vantage API Key';
        } else if (parentPart === 'newsapi') {
            return 'News API Key';
        } else if (parentPart === 'google') {
            return 'Google Search API Key';
        } else if (parentPart === 'tavily') {
            return 'Tavily Search API Key';
        } else if (parentPart === 'perplexity') {
            return 'Perplexity API Key';
        } else if (parentPart === 'metaphor') {
            return 'Metaphor Search API Key';
        } else if (parentPart === 'coinmarketcap') {
            return 'CoinMarketCap API Key';
        } else if (parentPart === 'helius') {
            return 'Helius API Key';
        }
    }
    */

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
                html += `
                    <div class="skill-item">
                        <h4>${group.displayName}</h4>
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
        }

        // Load existing values from config
        loadExistingApiKeys();

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

    // Add CSS for hardware acceleration info and shortcuts
    const style = document.createElement('style');
    style.textContent = `
        .hardware-info {
            margin-bottom: 20px;
            padding: 15px;
            background-color: #f8f9fa;
            border-radius: 8px;
            border-left: 4px solid #6c757d;
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
            border-left: 4px solid #007bff;
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
            border-left: 4px solid #28a745;
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

    // Next buttons
    document.querySelectorAll('.next-btn').forEach(btn => {
        btn.addEventListener('click', goToNextStep);
    });

    // Back buttons
    document.querySelectorAll('.back-btn').forEach(btn => {
        btn.addEventListener('click', goToPreviousStep);
    });

    // Finish button
    document.querySelector('.finish-btn').addEventListener('click', finishSetup);

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
            providerOptions.insertAdjacentHTML('beforebegin', filterHtml);

            // Add event listeners for filter
            document.getElementById('apply-filter-btn').addEventListener('click', () => {
                loadProviders();
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
                filterInput.value = 'qwen,deepseek-v3,deepseek-chat,deepseek-coder,llama,-8b,-3b,-1b';
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
                    filterInput.value = 'qwen,deepseek-v3,deepseek-chat,llama,-8b,-3b';
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
    const nextButton = document.querySelector('.next-btn');
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

        // Hide logo when leaving first slide
        if (currentStepIndex === 1) {
            const logo = document.querySelector('.setup-header .logo');
            if (logo) logo.style.display = 'none';
        }
    } catch (error) {
        console.error('Error saving step data:', error);
        alert(`Error saving configuration: ${error.message}`);
    } finally {
        // Reset button
        nextButton.textContent = originalText;
        nextButton.disabled = false;
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

    // Show logo when returning to first slide
    if (currentStepIndex === 0) {
        const logo = document.querySelector('.setup-header .logo');
        if (logo) logo.style.display = 'block';
    }
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
                        const nextButton = document.getElementById('llm-next');

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
    loadExistingProviders();

    const filter = document.getElementById('model-filter')?.value || '';
    loadProvidersWithFilter(filter);

    // Hide test result and disable next button when providers are reloaded
    const testResult = document.getElementById('test-result');
    const nextButton = document.getElementById('llm-next');

    testResult.classList.add('hidden');
    nextButton.disabled = true;
}

// Add new function to load existing providers
async function loadExistingProviders() {
    try {
        const backendConfig = await loadBackendConfig();
        const existingProviders = backendConfig?.llm?.providers || [];
        const selectedProvider = backendConfig?.llm?.selected_provider;

        if (existingProviders.length === 0) {
            return; // No existing providers
        }

        // Create a container for existing providers if it doesn't exist
        let existingContainer = document.getElementById('existing-providers');
        if (!existingContainer) {
            const providerOptions = document.getElementById('provider-options');
            if (providerOptions) {
                providerOptions.insertAdjacentHTML('beforebegin', `
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

        // Add each existing provider
        existingProviders.forEach((provider, index) => {
            const providerId = `existing-${index}`;
            const providerModel = provider.model;
            const isSelected = selectedProvider === providerModel;

            existingContainer.innerHTML += `
                <div class="existing-provider ${isSelected ? 'selected' : ''}">
                    <input type="radio" name="existing-provider" id="${providerId}"
                        value="${index}" ${isSelected ? 'checked' : ''}>
                    <label for="${providerId}">
                        <strong>${providerModel}</strong><br>
                        ${provider.api_base ? `API: ${provider.api_base}` : ''}
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

            // If a provider is already selected (or we have providers but none selected), enable the next button
            if (hasSelectedProvider || selectedProvider) {
                document.getElementById('llm-next').disabled = false;
            }
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
                    document.getElementById('llm-next').disabled = false;

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
    const nextButton = document.getElementById('llm-next');

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

    detailsContainer.innerHTML = html;

    // Enable test button
    testButton.disabled = false;

    // Add input event listeners for validation
    detailsContainer.querySelectorAll('input, select').forEach(input => {
        input.addEventListener('input', handleInputChange);
    });

    validateProviderForm();
}

// New function to handle input changes
function handleInputChange() {   // event
    // Hide test result and disable next button when any input changes
    const testResult = document.getElementById('test-result');
    const nextButton = document.getElementById('llm-next');

    testResult.classList.add('hidden');
    nextButton.disabled = true;

    // Also validate the form
    validateProviderForm();
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

        Logger.log('Testing LLM connection with config:', JSON.stringify({
            provider: llmConfig.provider,
            model: llmConfig.model,
            // Don't log API keys
            api_base: llmConfig.api_base
        }));

        // Make a request to the dedicated test-llm endpoint
        const response = await fetch(
            config.get('pybridge.api_url') + "/test-llm", {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(llmConfig)
            }
        );

        Logger.log(JSON.stringify(response))

        testResult.classList.remove('hidden', 'success', 'error');
        result = await response.json();

        if (response.ok && result.success) {
            let error_msg = await saveLLMConfig();
            if (error_msg) {
                testResult.textContent = error_msg;
                testResult.classList.remove('hidden', 'success');
                testResult.classList.add('error');
            } else {
                testResult.textContent = 'Connection successful! LLM is working properly. Provider registered.';
                testResult.classList.add('success');
                document.getElementById('llm-next').disabled = false;
            }
        } else {
            testResult.classList.add('error');
            testResult.textContent = `Connection failed: ${result.message}`;
        }

    } catch (error) {
        Logger.error('LLM connection test failed:' + error.message);
        console.log('LLM connection test failed:', error.message);
        const testResult = document.getElementById('test-result');
        testResult.classList.add('error');
        testResult.textContent = "Failed to connect to LLM provider: " + JSON.stringify(result);
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

    return config;
}

function validateCurrentStep() {
    const currentStep = steps[currentStepIndex];

    switch (currentStep) {
        case 'welcome':
            return true;
        case 'llm':
            // LLM step is valid if the next button is enabled (after successful test)
            return !document.getElementById('llm-next').disabled;
        case 'stt':
            // STT step is valid if the next button is enabled
            return !document.getElementById('stt-next').disabled;
        case 'skills':
            return true; // Skills are optional
        default:
            return true;
    }
}

// Add a function to check hardware acceleration status
async function checkHardwareAcceleration() {
    try {
        const response = await fetch(config.get('pybridge.api_url') + '/hardware/acceleration');
        if (!response.ok) {
            throw new Error('Failed to check hardware acceleration');
        }
        return await response.json();
    } catch (error) {
        console.error('Error checking hardware acceleration:', error);
        return {
            cuda_available: false,
            message: 'Unable to check hardware acceleration status'
        };
    }
}

// Add event listeners for STT options
function setupSTTEventListeners() {
    const sttNextButton = document.getElementById('stt-next');
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
        checkHardwareAcceleration().then(result => {
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
    const sttNextButton = document.getElementById('stt-next');
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

    switch (currentStep) {
        case 'llm':
            await saveLLMConfig();
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
    }
}

// Add a new function to handle provider deletion
async function deleteProvider(index) {
    try {
        // Load current backend config
        const backendConfig = await loadBackendConfig();

        if (!backendConfig.llm || !backendConfig.llm.providers || !backendConfig.llm.providers[index]) {
            throw new Error('Provider not found');
        }

        // Get the provider being deleted
        const deletedProvider = backendConfig.llm.providers[index];

        // Remove the provider from the array
        backendConfig.llm.providers.splice(index, 1);

        // If this was the selected provider, update the selection
        if (backendConfig.llm.selected_provider === deletedProvider.name) {
            // If there are other providers, select the first one
            if (backendConfig.llm.providers.length > 0) {
                backendConfig.llm.selected_provider = backendConfig.llm.providers[0].model;
            } else {
                // No providers left, remove the selected key
                delete backendConfig.llm.selected_provider;
            }
        }

        // Save the updated backend config to both servers
        await saveBackendConfig(backendConfig, config.get('pybridge.api_url'));
        await saveBackendConfig(backendConfig, config.get('orakle.api_url'));

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
    document.getElementById('llm-next').disabled = false;
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
    // we don't have a new provider selected, return
    if (!llmConfig) {
        return "No provider defined won't save";
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

        // Add as a new provider instead of replacing
        if (Array.isArray(backendConfig.llm.providers)) {
            backendConfig.llm.providers.push(provider);
        } else {
            backendConfig.llm.providers = [provider];
        }

        // Set this as the selected provider
        backendConfig.llm.selected_provider = provider.model;

        console.log(backendConfig);

        // Save the updated backend config to both servers
        await saveBackendConfig(backendConfig, config.get('pybridge.api_url'));
        await saveBackendConfig(backendConfig, config.get('orakle.api_url'));
        await updateUIAfterSave(provider);
    } catch (error) {
        console.error('Error updating LLM config:', error);
    }
}

// Function to save STT config
async function saveSTTConfig() {
    const selectedBackend = document.querySelector('input[name="stt-backend"]:checked')?.value || 'faster_whisper';

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
        await saveBackendConfig(backendConfig, config.get('orakle.api_url'));
    } catch (error) {
        console.error('Error updating STT config:', error);
    }
}

async function saveSkillsConfig() {
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

        // Update each API key in the backend config
        document.querySelectorAll('input[data-path]').forEach(input => {
            const path = input.dataset.path;
            const value = input.value.trim();

            if (value) {
                setValueAtPath(backendConfig, path, value);
            }
        });

        console.log("======================");
        console.log("backendConfig");
        console.log(JSON.stringify(backendConfig));
        console.log("======================");

        // Save the updated backend config
        await saveBackendConfig(backendConfig, config.get('pybridge.api_url'));
        await saveBackendConfig(backendConfig, config.get('orakle.api_url'));
    } catch (error) {
        console.error('Error updating skills config:', error);
    }
}

// Function to save shortcuts configuration
function saveShortcutsConfig() {
    try {
        // Get shortcut values
        const showShortcut = document.getElementById('show-shortcut').value.trim();
        const hideShortcut = document.getElementById('hide-shortcut').value.trim();
        const triggerShortcut = document.getElementById('trigger-shortcut').value.trim();

        // Update config
        if (showShortcut) {
            config.set('shortcuts.show', showShortcut);
        }
        
        if (hideShortcut) {
            config.set('shortcuts.hide', hideShortcut);
        }

        if (triggerShortcut) {
            config.set('shortcuts.trigger', triggerShortcut);
        }

        // Save to disk
        config.saveConfig();

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
    });
    
    hideInput.addEventListener('input', () => {
        hideDisplay.textContent = hideInput.value;
    });

    triggerInput.addEventListener('input', () => {
        triggerDisplay.textContent = triggerInput.value;
    });
}

async function finishSetup() {
    // Mark setup as completed
    config.set('setup.completed', true);
    config.set('setup.version', '0.1.0');
    config.set('setup.timestamp', new Date().toISOString());
    config.saveConfig();

    // Notify main process that setup is complete
    ipcRenderer.send('setup-complete');
}

