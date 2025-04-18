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

const { dialog } = require('electron');
const Logger = require('./logger');
const fetch = require('node-fetch');
const ConfigManager = require('./config');


class ConfigHelper {
    /**
     * Resolves paths to binary files that might be in app.asar.unpacked when packaged with Electron
     * @param {string} originalPath - The original path to the binary file
     * @returns {string} - The corrected path that works in both development and production
     */
    static resolveBinaryPath(originalPath) {
        // Only perform the replacement if we're in an Electron packaged environment
        // and the path contains app.asar
        if (process.resourcesPath && originalPath && originalPath.includes('app.asar')) {
            const correctedPath = originalPath.replace('app.asar', 'app.asar.unpacked');
            Logger.log(`Binary path corrected: ${originalPath} → ${correctedPath}`);
            return correctedPath;
        }
        return originalPath;
    }
    
    static async fetchBackendConfig() {
        const config1 = new ConfigManager();
        try {
            const response1 = await fetch(
                config1.get('pybridge.api_url') +
                '/config?show_sensitive=true'
            );
            const response2 = await fetch(
                config1.get('pybridge.api_url') +
                '/config/models_contexts'
            );
            if (!response1.ok || !response2.ok) {
                throw new Error('Failed to load configuration');
            }
            let response1_json = await response1.json();
            let response2_json = await response2.json();
            // Add context_window to models
            if (response1_json && response2_json) {
                for (let model1 of response1_json.llm.providers) {
                    for (const model2 of response2_json.models) {
                        if (model1.model == model2.model) {
                            model1.context_window = model2.context_window;
                            break;
                        }
                    }
                }
            }
            return response1_json;

        } catch (error) {
            Logger.error('Error loading backend config:', error);
            throw error;
        }
    }

    static async updateBackendConfig(config, server) {
        try {
            const response = await fetch(
                server + '/config',
                {
                    method: 'PUT',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify(config)
                }
            );

            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(`Failed to save configuration: ${errorData.error || 'Unknown error'}`);
            }

            return await response.json();
        } catch (error) {
            Logger.error('Error saving backend config:', error);
            throw error;
        }
    }

    static async getLLMProviders() {
        try {
            const config = await this.fetchBackendConfig();
            return {
                providers: config?.llm?.providers || [],
                selected_provider: config?.llm?.selected_provider
            };
        } catch (error) {
            Logger.error('Error getting LLM providers:', error);
            return { providers: [], selected_provider: null };
        }
    }

    static async selectLLMProvider(providerName) {
        try {
            const config1 = new ConfigManager();
            const configBackend = await this.fetchBackendConfig();
            if (!configBackend.llm) {
                configBackend.llm = { providers: [] };
            }
            configBackend.llm.selected_provider = providerName;
            // Update selected provider in backends
            await this.updateBackendConfig(configBackend, config1.get("pybridge.api_url"));
            await this.updateBackendConfig(configBackend, config1.get("orakle.api_url"));
            return true;
        } catch (error) {
            Logger.error('Error selecting LLM provider:', error);
            dialog.showErrorBox(
                'Provider Selection Error',
                `Failed to select provider: ${error.message}`
            );
            return false;
        }
    }
}

module.exports = ConfigHelper;