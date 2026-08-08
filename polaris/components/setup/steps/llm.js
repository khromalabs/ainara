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

const api = require('../core/api');
const utils = require('../core/utils');
const Logger = require('../../../framework/logger');
const ollamaModule = require('./ollama');

function hasValidConfiguredProvider(backendConfig) {
    return !!(
        backendConfig?.llm &&
        Array.isArray(backendConfig.llm.providers) &&
        backendConfig.llm.providers.length > 0 &&
        backendConfig.llm.selected_provider &&
        backendConfig.llm.providers.some(p => p.model === backendConfig.llm.selected_provider)
    );
}

async function loadProvidersWithFilter(ctx, filter = '') {
    try {
        const providerContainer = document.getElementById('provider-options');
        providerContainer.innerHTML = '<p>Loading providers...</p>';

        try {
            fetch(ctx.config.get('pybridge.api_url') + '/health');
        } catch (e) {
            console.log(e);
        }

        let url = ctx.config.get('pybridge.api_url') + '/providers';
        if (filter) {
            url += `?filter=${encodeURIComponent(filter)}`;
        }

        fetch(url)
            .then(response => {
                if (!response.ok) {
                    throw new Error('Failed to load providers');
                }
                return response.json();
            })
            .then(data => {
                ctx.providersData = data.providers;

                if (!ctx.providersData || Object.keys(ctx.providersData).length === 0) {
                    throw new Error('No providers available');
                }

                for (const providerId in ctx.providersData) {
                    if (api.providerWebsites[providerId]) {
                        ctx.providersData[providerId].website = api.providerWebsites[providerId];
                    }
                }

                const apiKeyInfoContainer = document.getElementById('api-key-info-container');
                if (apiKeyInfoContainer) {
                    // API key info generation is intentionally left empty for now
                }

                let html = '';
                const sortedProviders = Object.entries(ctx.providersData).sort((a, b) => {
                    if (a[0] === 'custom_api' || a[0] === 'custom') return -1;
                    if (b[0] === 'custom_api' || b[0] === 'custom') return 1;
                    return 0;
                });

                html += '<div class="provider-options-grid">';

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

                html += '</div>';
                providerContainer.innerHTML = html;

                document.querySelectorAll('input[name="llm-provider"]').forEach(radio => {
                    radio.addEventListener('change', () => {
                        const testResult = document.getElementById('test-result');
                        testResult.classList.add('hidden');
                        updateProviderDetailsUI(ctx);
                    });
                });

                document.getElementById('clear-filter-btn')?.addEventListener('click', () => {
                    document.getElementById('model-filter').value = '';
                    loadProviders(ctx);
                });
            })
            .catch(error => {
                providerContainer.innerHTML = `
                    <p class="error">Error loading providers: ${error.message}</p>
                    <p>Please check that the application is properly installed and that PyBridge is running.</p>
                    <button id="retry-providers-btn">Retry</button>
                `;

                document.getElementById('retry-providers-btn')?.addEventListener('click', () => loadProviders(ctx));
            });
    } catch (error) {
        console.error('Error in loadProvidersWithFilter:', error);
    }
}

async function displayFeaturedModels(ctx, existingProviders = []) {
    const container = document.getElementById('featured-providers-container');
    if (!container) return;

    let tags = {
        "high_speed": { text: 'HIGH SPEED', color: '#ffc107' },
        "low_price": { text: 'LOW PRICE', color: '#9ACD32' },
        "high_intelligence": { text: 'HIGH INTELLIGENCE', color: '#007bff' },
        "free_access": { text: 'FREE ACCESS', color: '#287725' },
        "open_model": { text: 'OPEN MODEL', color: '#CD32A8' },
    };

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

    document.querySelectorAll('.provider-banner.not-configured').forEach(banner => {
        banner.addEventListener('click', async () => {
            const defaultFilterCheckbox = document.getElementById('default-filter');
            if (defaultFilterCheckbox && !defaultFilterCheckbox.checked) {
                defaultFilterCheckbox.click();
                await new Promise(resolve => setTimeout(resolve, 100));
            }

            const providerId = banner.dataset.providerId;
            const modelId = banner.dataset.modelId;
            const radio = document.getElementById(providerId);

            if (radio) {
                radio.click();

                const modelSelect = document.getElementById(`${providerId}-model`);
                if (modelSelect) {
                    modelSelect.value = modelId;
                }
                const modelWindow = document.getElementById(`${providerId}-context_window`);
                if (banner.dataset.contextWindow && modelWindow) {
                    modelWindow.value = banner.dataset.contextWindow;
                }
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

async function loadProviders(ctx) {
    const nextButton = document.getElementById('main-next-btn');
    const testResult = document.getElementById('test-result');

    testResult.classList.add('hidden');
    nextButton.disabled = true;

    await loadExistingProviders(ctx);

    const filter = document.getElementById('model-filter')?.value || '';
    loadProvidersWithFilter(ctx, filter);
}

async function loadExistingProviders(ctx) {
    try {
        await ollamaModule.updateOllamaProviders(ctx);

        const backendConfig = await ctx.api.loadBackendConfig();
        let existingProviders = backendConfig?.llm?.providers || [];
        const selectedProvider = backendConfig?.llm?.selected_provider;

        await displayFeaturedModels(ctx, existingProviders);

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

        existingContainer.innerHTML = '';

        if (existingProviders.length === 0) {
            existingContainer.innerHTML = '<p>No providers configured yet.</p>';
            return;
        }

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

        if (existingProviders.length > 0) {
            const hasSelectedProvider = document.querySelector('input[name="existing-provider"]:checked');
            if (hasSelectedProvider) {
                document.getElementById('main-next-btn').disabled = false;
            }
        }

        const style = document.createElement('style');
        style.textContent = `
            .ollama-provider {
                background-color: #d0e8ff;
            }
        `;
        if (!document.getElementById('ollama-provider-style')) {
            style.id = 'ollama-provider-style';
            document.head.appendChild(style);
        }

        document.querySelectorAll('input[name="existing-provider"]').forEach(radio => {
            radio.addEventListener('change', async () => {
                if (radio.checked) {
                    document.querySelectorAll('input[name="llm-provider"]').forEach(newRadio => {
                        newRadio.checked = false;
                    });

                    document.querySelectorAll('.existing-provider').forEach(el => {
                        el.classList.remove('selected');
                    });
                    radio.closest('.existing-provider').classList.add('selected');

                    document.getElementById('provider-details').innerHTML = '';

                    document.getElementById('main-next-btn').disabled = false;

                    document.getElementById('test-result').classList.add('hidden');

                    let errorMsg = await updateSelectedLLMProvider(ctx, radio.value);
                    if (errorMsg) {
                        console.error("Error saving provider selection:", errorMsg);
                    }
                }
            });
        });

        document.querySelectorAll('.delete-provider-btn').forEach(button => {
            button.addEventListener('click', async (event) => {
                event.preventDefault();
                event.stopPropagation();

                const index = parseInt(button.dataset.index);
                const provider = existingProviders[index];
                const providerName = provider.name || `Provider ${index + 1}`;

                if (confirm(`Are you sure you want to delete the provider "${providerName}"?`)) {
                    await deleteProvider(ctx, index);
                }
            });
        });
    } catch (error) {
        console.error('Error loading existing providers:', error);
    }
}

async function updateSelectedLLMProvider(ctx, providerIndex) {
    try {
        const backendConfig = await ctx.api.loadBackendConfig();

        if (!backendConfig.llm || !Array.isArray(backendConfig.llm.providers)) {
            console.error("LLM providers configuration is missing or invalid.");
            return "Error: LLM configuration is invalid.";
        }

        const selectedProvider = backendConfig.llm.providers[providerIndex];

        if (!selectedProvider) {
            console.error(`Selected existing provider at index ${providerIndex} not found in config.`);
            return `Error: Selected provider not found in configuration.`;
        }

        backendConfig.llm.selected_provider = selectedProvider.model;

        console.log("Selecting existing provider:", backendConfig.llm.selected_provider);

        await ctx.api.saveBackendConfig(backendConfig, ctx.config.get('pybridge.api_url'));
        await ctx.api.saveBackendConfig(backendConfig, ctx.config.get('orakle.api_url'));

    } catch (error) {
        console.error('Error selecting existing LLM provider:', error);
        return `Error saving provider selection: ${error.message}`;
    }
    return null;
}

function updateProviderDetailsUI(ctx) {
    const selectedProviderId = document.querySelector('input[name="llm-provider"]:checked')?.value;
    const detailsContainer = document.getElementById('provider-details');
    const testButton = document.getElementById('test-connection-btn');
    const testResult = document.getElementById('test-result');

    testResult.classList.add('hidden');

    if (!selectedProviderId || !ctx.providersData || !ctx.providersData[selectedProviderId]) {
        detailsContainer.innerHTML = '';
        testButton.disabled = true;
        return;
    }

    const provider = ctx.providersData[selectedProviderId];

    let html = `
        <h3>${provider.name} Configuration</h3>
    `;

    provider.fields.forEach(field => {
        const isApiBaseField = field.id === 'api_base' || field.id === 'base_url';
        const isCustomProvider = selectedProviderId === 'custom' || selectedProviderId === 'custom_api';

        if (isCustomProvider && field.id == "model") {
            field.required = true;
        }

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

    testButton.disabled = false;

    detailsContainer.querySelectorAll('input, select').forEach(input => {
        input.addEventListener('input', (event) => ctx.handleInputChange(event, false));
    });

    validateProviderForm(ctx);
}

function validateProviderForm(ctx) {
    const selectedProviderId = document.querySelector('input[name="llm-provider"]:checked')?.value;
    const testButton = document.getElementById('test-connection-btn');

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

async function testLLMConnection(ctx, event) {
    if (event) event.stopPropagation();

    const selectedProviderId = document.querySelector('input[name="llm-provider"]:checked')?.value;

    if (!selectedProviderId || !ctx.providersData || !ctx.providersData[selectedProviderId]) {
        return;
    }

    const testButton = document.getElementById('test-connection-btn');
    const originalText = testButton.textContent;
    testButton.textContent = 'Testing...';
    testButton.disabled = true;

    const testResult = document.getElementById('test-result');
    testResult.textContent = "";
    testResult.classList.add('hidden');

    await testLLMConnectionFetch(ctx, getLLMConfig(ctx));

    testButton.textContent = originalText;
    validateProviderForm(ctx);
}

async function testLLMConnectionFetch(ctx, llmConfig) {
    var result;
    try {
        const testResult = document.getElementById('test-result');
        testResult.classList.remove('hidden', 'success', 'error');

        Logger.log('Setup: Testing LLM connection via IPC with config:', JSON.stringify({
            provider: llmConfig.provider,
            model: llmConfig.model,
            api_base: llmConfig.api_base
        }));

        const response = await fetch(
            ctx.config.get('pybridge.api_url') + "/test-llm", {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(llmConfig)
            }
        );

        testResult.classList.remove('hidden', 'success', 'error');
        result = await response.json();
        Logger.log('Setup: Received test result from pybridge:', result);

        if (response.ok && result.success) {
            testResult.textContent = 'Connection successful! LLM is working properly.';
            testResult.classList.add('success');

            const selectedProviderId = document.querySelector('input[name="llm-provider"]:checked')?.value;
            if (selectedProviderId) {
                ctx.modifiedFields.llm.add(selectedProviderId);
            }

            let error_msg = await saveLLMConfig(ctx);
            if (error_msg) {
                testResult.textContent = error_msg;
                testResult.classList.remove('hidden', 'success');
                testResult.classList.add('error');
            } else {
                testResult.textContent += ' Provider registered.';
                document.getElementById('main-next-btn').disabled = false;
            }
        } else {
            testResult.classList.add('error');
            testResult.textContent = `Connection failed: ${result.message}`;
        }

    } catch (error) {
        Logger.error('Setup: LLM connection test failed:', error);
        const testResult = document.getElementById('test-result');
        testResult.classList.add('error');
        testResult.textContent = `Failed to test LLM provider: ${error.message || JSON.stringify(result || 'Unknown error')}`;
    }
}

function getLLMConfig(ctx) {
    const selectedProviderId = document.querySelector('input[name="llm-provider"]:checked')?.value;

    if (!ctx.providersData || !ctx.providersData[selectedProviderId]) {
        return null;
    }

    const provider = ctx.providersData[selectedProviderId];

    const config = {
        provider: selectedProviderId
    };

    provider.fields.forEach(field => {
        const input = document.getElementById(`${selectedProviderId}-${field.id}`);
        if (input && input.value.trim()) {
            config[field.id] = input.value.trim();
        }
    });

    const modelSelect = document.getElementById(`${selectedProviderId}-model`);
    if (modelSelect) {
        config.model = ctx.utils.normalizeModelName(modelSelect.value, selectedProviderId);
    }

    const contextWindowInput = document.getElementById(`${selectedProviderId}-context_window`);
    if (contextWindowInput && contextWindowInput.value.trim()) {
        const contextWindowValue = parseInt(contextWindowInput.value.trim(), 10);
        if (!isNaN(contextWindowValue) && contextWindowValue > 0) {
            config.context_window = contextWindowValue;
        }
    }
    return config;
}

async function saveLLMConfig(ctx) {
    const selectedExistingProvider = document.querySelector('input[name="existing-provider"]:checked');
    const llmConfig = getLLMConfig(ctx);
    let changedSelectedProvider = false;

    if (!llmConfig) {
        return "No LLM provider is configured yet. Please add a provider above or select an existing one.";
    }

    try {
        const backendConfig = await ctx.api.loadBackendConfig();

        if (!backendConfig.llm) {
            backendConfig.llm = { backend: "litellm", providers: [] };
        }

        function modelExists(providers, modelName) {
            return providers.some(provider => provider.model == modelName);
        }

        const modelName = llmConfig.model;
        if (backendConfig.llm.providers && modelExists(backendConfig.llm.providers, modelName)) {
            return 'This model is already registered';
        }

        if (selectedExistingProvider) {
            const providerIndex = parseInt(selectedExistingProvider.value);
            if (backendConfig.llm.providers && backendConfig.llm.providers[providerIndex]) {
                const provider = backendConfig.llm.providers[providerIndex];
                backendConfig.llm.selected_provider = provider.model;
                changedSelectedProvider = true;
            }
        }

        const provider = {
            model: llmConfig.model
        };

        if (llmConfig.api_key) {
            provider.api_key = llmConfig.api_key;
        }

        if (llmConfig.api_base) {
            provider.api_base = llmConfig.api_base;
        }

        if (llmConfig.context_window) {
            provider.context_window = llmConfig.context_window;
        }

        if (Array.isArray(backendConfig.llm.providers)) {
            backendConfig.llm.providers.push(provider);
        } else {
            backendConfig.llm.providers = [provider];
        }

        if (!backendConfig.llm.selected_provider || backendConfig.llm.providers.length === 1) {
            backendConfig.llm.selected_provider = provider.model;
            changedSelectedProvider = true;
        }

        await ctx.api.saveBackendConfig(backendConfig, ctx.config.get('pybridge.api_url'));
        if (changedSelectedProvider) {
            await ctx.api.saveBackendConfig(backendConfig, ctx.config.get('orakle.api_url'));
        }

        ctx.modifiedFields.llm.clear();

        await updateUIAfterSave(ctx, provider);
    } catch (error) {
        console.error('Error updating LLM config:', error);
    }
}

async function updateUIAfterSave(ctx, newProvider) {
    await ctx.loadExistingProviders();

    const providerRadios = document.querySelectorAll('input[name="existing-provider"]');
    const newProviderRadio = Array.from(providerRadios).find(radio => {
        const label = radio.nextElementSibling;
        return label?.textContent.includes(newProvider.name);
    });

    if (newProviderRadio) {
        newProviderRadio.checked = true;
        newProviderRadio.dispatchEvent(new Event('change'));
    }

    document.getElementById('main-next-btn').disabled = false;
}

async function deleteProvider(ctx, index) {
    try {
        const backendConfig = await ctx.api.loadBackendConfig();
        let changedSelectedProvider = false;

        if (!backendConfig.llm || !backendConfig.llm.providers || !backendConfig.llm.providers[index]) {
            throw new Error('Provider not found');
        }

        const deletedProvider = backendConfig.llm.providers[index];

        backendConfig.llm.providers.splice(index, 1);

        if (backendConfig.llm.selected_provider === deletedProvider.model) {
            if (backendConfig.llm.providers.length > 0) {
                backendConfig.llm.selected_provider = backendConfig.llm.providers[0].model;
            } else {
                delete backendConfig.llm.selected_provider;
                const nextButton = document.getElementById('main-next-btn');
                nextButton.disabled = true;
            }
            changedSelectedProvider = true;
        }

        await ctx.api.saveBackendConfig(backendConfig, ctx.config.get('pybridge.api_url'));
        if (changedSelectedProvider) {
            await ctx.api.saveBackendConfig(backendConfig, ctx.config.get('orakle.api_url'));
        }

        const existingContainer = document.getElementById('existing-providers');
        if (existingContainer) {
            existingContainer.innerHTML = '';
        }

        ctx.loadExistingProviders();

        const testResult = document.getElementById('test-result');
        testResult.textContent = 'Provider deleted successfully';
        testResult.classList.remove('hidden', 'error');
        testResult.classList.add('success');

        setTimeout(() => {
            testResult.classList.add('hidden');
        }, 3000);
    } catch (error) {
        console.error('Error deleting provider:', error);

        const testResult = document.getElementById('test-result');
        testResult.textContent = `Error deleting provider: ${error.message}`;
        testResult.classList.remove('hidden', 'success');
        testResult.classList.add('error');
    }
}

module.exports = {
    id: 'llm',
    hasValidConfiguredProvider,

    async init(ctx) {
        ctx.loadExistingProviders = loadExistingProviders;
        ctx.validateProviderForm = validateProviderForm;
        await loadProviders(ctx);
    },

    async save(ctx) {
        const backendConfig = await ctx.api.loadBackendConfig();
        if (hasValidConfiguredProvider(backendConfig)) {
            ctx.modifiedFields.llm.clear();
            return;
        }
        const errorMsg = await saveLLMConfig(ctx);
        if (errorMsg) {
            throw new Error(errorMsg);
        }
    },

    async loadProviders(ctx) {
        return loadProviders(ctx);
    },

    async testLLMConnection(ctx, event) {
        return testLLMConnection(ctx, event);
    }
};
