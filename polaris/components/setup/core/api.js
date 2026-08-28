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
    // Must FAIL LOUD. The backend PUT /config deep-merges the payload, but this
    // is still the base every save step reads-modifies-writes, so a save must
    // never proceed on a config we could not actually read. Returning undefined
    // here (the previous behaviour) let callers build a payload from defaults
    // and PUT it — which, under the old delete-on-absence merge, wiped the
    // user's trading + LLM config. Re-throw so save steps abort instead.
    try {
        const response = await fetch(
            config.get('pybridge.api_url') +
            '/config?show_sensitive=true'
        );
        if (!response.ok) {
            throw new Error('Failed to load configuration');
        }
        const loaded = await response.json();
        if (!loaded || typeof loaded !== 'object' || Array.isArray(loaded)) {
            throw new Error('Backend returned an invalid configuration object');
        }
        return loaded;
    } catch (error) {
        console.error('Error loading backend config:', error);
        throw error;
    }
}

async function saveBackendConfig(config, server) {
    try {
        // Backstop: never PUT an empty or non-object payload. Even with the
        // backend now deep-merging (so a partial PUT no longer deletes keys),
        // pushing {} or undefined is never intended and only signals that the
        // caller built its payload without a real config to modify.
        if (!config || typeof config !== 'object' || Array.isArray(config)
            || Object.keys(config).length === 0) {
            throw new Error(
                'Refusing to save: configuration payload is empty or invalid'
                + ' (the current config could not be read).'
            );
        }
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
