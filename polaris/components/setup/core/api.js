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

const ConfigManager = require('../../../framework/config');

const config = new ConfigManager();

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


module.exports = {
    providerWebsites,
    loadBackendConfig,
    saveBackendConfig
};
