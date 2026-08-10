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

const ollama = require('ollama');

function buildOllamaStatusCards(ctx, hwInfo, ollamaAvailable) {
    let html = '';

    // Availability card - only shown when Ollama is unreachable
    if (ollamaAvailable === false) {
        html += `
            <div class="status-card ollama-availability unavailable">
                <h4>Ollama is not running</h4>
                <p>Start Ollama or install it, then restart Ainara to manage local models here.</p>
                <a class="external-link" href="#" data-url="https://ollama.com/download">Download Ollama</a>
            </div>
        `;
    }

    if (hwInfo) {
        const totalVram = hwInfo.details?.total_vram_gb || 0;
        const isAppleSilicon = hwInfo.details?.is_apple_silicon || false;
        const totalRam = hwInfo.details?.total_ram_gb || 0;
        const platform = hwInfo.platform || 'Unknown';

        const gpuList = (hwInfo.gpu_list && hwInfo.gpu_list.length > 0) ? hwInfo.gpu_list : [];
        let gpuHtml = '<p>No GPUs detected.</p>';
        if (gpuList.length > 0) {
            gpuHtml = '<ul>';
            gpuList.forEach(gpu => {
                const vram = gpu.memory_total_gb ? `${gpu.memory_total_gb} GB` : 'VRAM N/A';
                gpuHtml += `<li>${gpu.name || 'Unknown GPU'} — ${vram} ${gpu.source ? `(source: ${gpu.source})` : ''}</li>`;
            });
            gpuHtml += '</ul>';
        }

        html += `
            <div class="status-card hardware-details">
                <span class="card-icon hardware-icon" aria-hidden="true"></span>
                <h4>Detected Hardware</h4>
                <p><strong>Platform:</strong> ${platform}</p>
                <p><strong>Total VRAM:</strong> ${totalVram ? `${totalVram} GB` : 'Not detected'}</p>
                <p><strong>Total RAM:</strong> ${totalRam ? `${totalRam} GB` : 'Not detected'} ${isAppleSilicon ? '(Apple Silicon)' : ''}</p>
                <details>
                    <summary>Show GPU details</summary>
                    ${gpuHtml}
                </details>
            </div>
        `;

        const meetsGpu = totalVram >= 4;
        const meetsApple = isAppleSilicon && totalRam >= 8;
        const meetsRequirement = meetsGpu || meetsApple;
        const isTight = (totalVram >= 4 && totalVram < 8) || (isAppleSilicon && totalRam >= 8 && totalRam < 16);

        html += `
            <div class="status-card requirement-card">
                <h4>Can this system run Ollama well?</h4>
                <ul class="requirement-list">
                    <li class="requirement-option ${meetsGpu ? 'met' : 'unmet'}">
                        <strong>Option A</strong> — Dedicated GPU with ≥ 4 GB VRAM
                        <span class="requirement-result">${meetsGpu ? '✔ Yes' : (totalVram ? `✖ Detected ${totalVram} GB` : '✖ Not detected')}</span>
                    </li>
                    <li class="or-divider">OR</li>
                    <li class="requirement-option ${meetsApple ? 'met' : 'unmet'}">
                        <strong>Option B</strong> — Apple Silicon with ≥ 8 GB RAM
                        <span class="requirement-result">${meetsApple ? '✔ Yes' : (isAppleSilicon ? `✖ Detected ${totalRam} GB` : '✖ Not Apple Silicon')}</span>
                    </li>
                </ul>
                <div class="status-badge ${meetsRequirement ? (isTight ? 'warning' : 'good') : 'error'}">
                    ${meetsRequirement ? (isTight ? 'Local system meets minimum, but tight' : 'Local system meets requirements!') : 'Local system not recommended for Ainara local LLM backend'}
                </div>
            </div>
        `;

        let sizeHint = 'small (1–4B)';
        if (totalVram >= 22) sizeHint = 'large (30B+)';
        else if (totalVram >= 14) sizeHint = 'medium-large (20–32B)';
        else if (totalVram >= 7) sizeHint = 'medium (7–14B)';
        else if (totalVram >= 3.5) sizeHint = 'small (1–4B)';

        html += `
            <div class="status-card model-guidance">
                <h4><span class="tip-signal">&nbsp;</span> Picking the right model size</h4>
                ${meetsRequirement ? `
                    <p>Pick a model close to your available VRAM. For <strong>${totalVram ? totalVram + ' GB VRAM' : 'your hardware'}</strong>, try <strong>${sizeHint}</strong> models.</p>
                ` : `
                    <p>Running local models on this system is likely to be very slow. Prefer a cloud LLM provider in the next step, or use the <strong>Custom API</strong> option.</p>
                `}
            </div>
        `;
    } else {
        html += `
            <div class="status-card hardware-details error">
                <h4>Hardware check failed</h4>
                <p>Could not retrieve hardware information. You can still continue, but local model recommendations may not be accurate.</p>
            </div>
        `;
    }

    return html;
}

module.exports = {
    id: 'ollama',

    async init(ctx) {
        await initializeOllamaStep(ctx);
    },

    async updateOllamaProviders(ctx) {
        return updateOllamaProviders(ctx);
    }
};

async function updateOllamaProviders(ctx) {
    const { config, api } = ctx;

    try {
        // Load current backend config
        const backendConfig = await api.loadBackendConfig();
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
            await api.saveBackendConfig(backendConfig, config.get('pybridge.api_url'));
            if (selectedProviderChanged) {
                await api.saveBackendConfig(backendConfig, config.get('orakle.api_url'));
            }
            // The caller is responsible for refreshing the providers list,
            // so we no longer call loadExistingProviders() here.
        }

        return { success: true, config: backendConfig };
    } catch (error) {
        console.debug('Ollama server not reachable; skipping provider sync:', error.message);
        return { success: false, error: error.message };
    }
}

async function initializeOllamaStep(ctx) {
    const hardwareInfoElement = document.getElementById('ollama-hardware-info');
    if (!hardwareInfoElement) return;

    hardwareInfoElement.style.display = "block";
    const existingServerConfig = document.getElementById('ollama-server-config');
    if (existingServerConfig) existingServerConfig.remove();

    const hwInfo = await displayHardwareInfo(ctx);
    const ollamaAvailable = await displayOllamaModels(ctx);

    hardwareInfoElement.innerHTML = buildOllamaStatusCards(ctx, hwInfo, ollamaAvailable);
}

async function displayHardwareInfo(ctx) {
    const { config } = ctx;
    const hardwareInfoElement = document.getElementById('ollama-hardware-info');
    if (!hardwareInfoElement) return null;

    hardwareInfoElement.innerHTML = '<p>Checking system hardware...</p>';

    try {
        const response = await fetch(config.get('pybridge.api_url') + '/hardware/acceleration');
        if (!response.ok) {
            throw new Error(`Failed to fetch hardware info: ${response.statusText}`);
        }
        const hwInfo = await response.json();
        console.log("Hardware Info Received:", hwInfo);

        const totalVram = hwInfo.details?.total_vram_gb || 0;
        config.set('ollama.totalVram', totalVram);
        config.saveConfig();

        return hwInfo;
    } catch (error) {
        console.error('Error fetching hardware info:', error);
        return null;
    }
}

async function displayOllamaModels(ctx) {
    const { config } = ctx;
    const modelsContainer = document.getElementById('ollama-models-container');
    if (!modelsContainer) return false;

    modelsContainer.innerHTML = '<p>Loading Ollama models...</p>';
    let modelsInfo = ""

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
        const recommendedModels = getRecommendedModels(ctx);
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

        modelsContainer.innerHTML = modelsInfo + modelsHtml;

        // Add event listeners for delete buttons
        document.querySelectorAll('.delete-model-btn').forEach(btn => {
            btn.addEventListener('click', async () => {
                const modelName = btn.dataset.model;
                if (confirm(`Are you sure you want to delete ${modelName}?`)) {
                    btn.disabled = true;
                    await deleteOllamaModel(ctx, client, modelName);
                }
            });
        });

        // Add event listener for download button
        const downloadBtn = document.getElementById('download-model-btn');
        if (downloadBtn) {
            downloadBtn.addEventListener('click', async () => {
                downloadBtn.disabled = true;
                const modelSelect = document.getElementById('ollama-model-select');
                const modelId = modelSelect.value;
                await downloadOllamaModel(ctx, client, modelId, downloadBtn);
            });
        }

        // Add event listener for the "Other model" download button
        const downloadOtherModelBtn = document.getElementById('download-other-model-btn');
        if (downloadOtherModelBtn) {
            downloadOtherModelBtn.addEventListener('click', async () => {
                downloadOtherModelBtn.disabled = true;
                const modelInput = document.getElementById('ollama-other-model-input');
                const modelId = modelInput.value.trim();
                if (modelId) {
                    await downloadOllamaModel(ctx, client, modelId, downloadOtherModelBtn);
                    modelInput.value = '';
                } else {
                    alert('Please enter a model name to download.');
                }
            });
        }

        return true;
    } catch (error) {
        console.error('Error fetching Ollama models:', error);
        modelsContainer.innerHTML = '<p class="info-message">Ollama is not available. See the message above for next steps.</p>';
        return false;
    }
}

function getRecommendedModels(ctx) {
    const { config } = ctx;
    const totalVram = config.get('ollama.totalVram', 0);
    console.log("Total VRAM for model recommendation:", totalVram);
    const models = [
        { id: 'qwen3:1.7b', name: 'Qwen 3 (1.7B)', size: 1.4, minVram: 4 },
        { id: 'qwen3:4b', name: 'Qwen 3 (4B)', size: 2.5, minVram: 8 },
        { id: 'qwen3:8b', name: 'Qwen 3 (8B)', size: 5.2, minVram: 8 },
        { id: 'qwen3:14b', name: 'Qwen 3 (14B)', size: 9, minVram: 12 },
        { id: 'qwen3:30b', name: 'Qwen 3 (30B)', size: 19, minVram: 24 },
        { id: 'qwen3:32b', name: 'Qwen 3 (32B)', size: 20, minVram: 24 },
        { id: 'gpt-oss:20b', name: 'gpt-oss (20B)', size: 14, minVram: 24 },
    ];

    const filteredModels = models.filter(model => totalVram >= model.minVram);
    console.log("Filtered Models based on VRAM:", filteredModels);
    return filteredModels.length > 0 ? filteredModels : models;
}

async function downloadOllamaModel(ctx, client, modelId, buttonElement) {
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
            await loadOllamaModel(ctx, client, modelId);
            progressDiv.innerHTML += `<p>Updating providers list...</p>`;
            await updateOllamaProviders(ctx);
            if (typeof ctx.loadExistingProviders === 'function') {
                await ctx.loadExistingProviders(ctx);
            }
            setTimeout(() => {
                displayOllamaModels(ctx);
            }, 1000);
        }
        buttonElement.disabled = false;
        progressDiv.scrollIntoView({ behavior: 'smooth', block: 'end' });
    } catch (error) {
        console.error('Error downloading model:', error);
        progressDiv.innerHTML = `<p class="error">Error downloading ${modelId}: ${error.message}</p>`;
        buttonElement.disabled = false;
    }
}

async function deleteOllamaModel(ctx, client, modelName) {
    try {
        await client.delete({ model: modelName });
        alert(`${modelName} deleted successfully.`);

        await updateOllamaProviders(ctx);
        if (typeof ctx.loadExistingProviders === 'function') {
            await ctx.loadExistingProviders(ctx);
        }
        await displayOllamaModels(ctx);
    } catch (error) {
        console.error('Error deleting model:', error);
        alert(`Error deleting ${modelName}: ${error.message}`);
    }
}

async function loadOllamaModel(ctx, client, modelId) {
    try {
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
