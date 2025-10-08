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

const path = require('path');
const fs = require('fs');
// const Logger = require('./logger');
const defaultConfig = require('../resources/defaultConfig');
const os = require('os');
class ConfigManager {
    constructor() {
        // Singleton pattern
        if (ConfigManager.instance) {
            return ConfigManager.instance;
        }
        ConfigManager.instance = this;
        this.config = {};
        this.lastLoadTimestamp = 0; // Track when we last loaded the config

        this.configDir = this._getConfigDirectory();
        this.configFile = path.join(this.configDir, 'polaris.json');
        this.loadConfig();
    }

    _getConfigDirectory() {
        const platform = process.platform;
        const homeDir = os.homedir();

        // Follow platform-specific standards for config locations
        if (platform === 'win32') {
            // Windows: %APPDATA%\ainara\polaris
            return path.join(homeDir, 'AppData', 'Roaming', 'ainara', 'polaris');
        } else if (platform === 'darwin') {
            // macOS: ~/Library/Application Support/ainara/polaris
            return path.join(homeDir, 'Library', 'Application Support', 'ainara', 'polaris');
        } else {
            // Linux/Unix: ~/.config/ainara/polaris
            return path.join(homeDir, '.config', 'ainara', 'polaris');
        }
    }

    loadConfig() {
        try {
            console.log('Loading configuration from:', this.configDir);
            if (!fs.existsSync(this.configDir)) {
                fs.mkdirSync(this.configDir, { recursive: true });
            }

            if (!fs.existsSync(this.configFile)) {
                // Create default config
                fs.writeFileSync(this.configFile, JSON.stringify(defaultConfig, null, 2));
                this.config = defaultConfig;
            } else {
                let loadedConfig;
                try {
                    const fileContents = fs.readFileSync(this.configFile, 'utf8');
                    loadedConfig = JSON.parse(fileContents);
                    // TODO disabled frontend config verification until v0.10
                    this.config = loadedConfig;
                } catch (e) {
                    console.warn('Configuration file contains invalid JSON. Resetting to default: ' + e.message);
                    // loadedConfig will be undefined, triggering the reset below
                }

                // if (loadedConfig && this._isConfigValid(loadedConfig, defaultConfig)) {
                //     this.config = loadedConfig;
                // } else {
                //     if (loadedConfig) { // It was valid JSON but invalid structure/types
                //         console.warn('Configuration file has invalid structure or types. Resetting to default.');
                //     }
                //     this.config = JSON.parse(JSON.stringify(defaultConfig)); // Deep copy
                //     // Overwrite the invalid file with a valid one
                //     fs.writeFileSync(this.configFile, JSON.stringify(this.config, null, 2));
                // }
            }

            // Ensure Ollama settings are present in config
            if (!this.config.ollama) {
                this.config.ollama = {
                    serverIp: '127.0.0.1',
                    port: 11434
                };
            }

            // Force correct Python server URLs (temporary enforcement)
            if (this.config.orakle) {
                this.config.orakle.api_url = 'http://127.0.0.1:8100';
            }
            if (this.config.pybridge) {
                this.config.pybridge.api_url = 'http://127.0.0.1:8101';
            }

            this.config.stt = this.config.stt ?? {};
            this.config.stt.review = this.config.stt.review ?? true;

            // Update the timestamp after successful load
            this.lastLoadTimestamp = this._getFileModificationTime();
            console.log('Configuration loaded successfully');
        } catch (error) {
            console.error('Error loading configuration:', error);
            throw error;
        }
    }

    _getFileModificationTime() {
        try {
            const stats = fs.statSync(this.configFile);
            return stats.mtimeMs; // Return the modification time in milliseconds
        } catch (error) {
            console.error('Error getting file modification time:', error);
            return 0; // Return 0 if there's an error, which will force a reload
        }
    }

    _checkAndReloadIfNeeded() {
        try {
            const currentFileTimestamp = this._getFileModificationTime();
            if (currentFileTimestamp > this.lastLoadTimestamp) {
                console.log('Config file has been modified, reloading...');
                this.loadConfig();
            }
        } catch (error) {
            console.error('Error checking file modification time:', error);
            // Continue with the current config if there's an error
        }
    }

    get(keyPath, defaultValue = null) {
        // Check if config file has been modified and reload if necessary
        this._checkAndReloadIfNeeded();

        const parts = keyPath.split('.');
        let current = this.config;

        for (const part of parts) {
            if (current === undefined || current === null) {
                return defaultValue;
            }
            current = current[part];
        }

        return current !== undefined ? current : defaultValue;
    }

    set(keyPath, value) {
        // Check if config file has been modified and reload if necessary
        this._checkAndReloadIfNeeded();

        const parts = keyPath.split('.');
        let current = this.config;

        for (let i = 0; i < parts.length - 1; i++) {
            const part = parts[i];
            if (!(part in current)) {
                current[part] = {};
            }
            current = current[part];
        }

        current[parts[parts.length - 1]] = value;
        this.saveConfig();
    }

    saveConfig() {
        try {
            // Validate the current config against the default structure
            const validatedConfig = this.validateConfig(this.config, defaultConfig);

            fs.writeFileSync(this.configFile, JSON.stringify(validatedConfig, null, 2));
            // Update the in-memory config with the validated version
            this.config = validatedConfig;
            // Update the timestamp after successful save
            this.lastLoadTimestamp = this._getFileModificationTime();
            console.log('Configuration saved successfully');
        } catch (error) {
            console.error('Error saving configuration:', error);
            throw error;
        }
    }

    _isConfigValid(config, defaultConfig, path = '') {
        for (const key in defaultConfig) {
            const currentPath = path ? `${path}.${key}` : key;
            const defaultValue = defaultConfig[key];
            const userValue = config[key];

            // The sanitizer will add missing keys, so we only care about existing keys with wrong types.
            if (userValue === undefined) {
                continue;
            }

            const defaultType = typeof defaultValue;
            const userType = typeof userValue;

            // Special handling for null, since typeof null is 'object'
            if (defaultValue === null) {
                if (userValue !== null) {
                    console.warn(`Invalid configuration at '${currentPath}'. Expected null, got ${userType}.`);
                    return false;
                }
                continue; // Both are null, which is fine.
            }

            if (defaultType !== userType) {
                console.warn(`Invalid configuration at '${currentPath}'. Type mismatch: expected ${defaultType}, got ${userType}.`);
                return false;
            }

            // Recurse for nested objects
            if (defaultType === 'object' && !Array.isArray(defaultValue) && !this._isConfigValid(userValue, defaultValue, currentPath)) {
                return false;
            }
        }
        return true;
    }

    validateConfig(config, defaultConfig, path = '') {
        const validatedConfig = {};

        // Process all keys in the current config
        for (const key in config) {
            const currentPath = path ? `${path}.${key}` : key;

            // Check if this key exists in the default config
            if (defaultConfig && key in defaultConfig) {
                if (typeof config[key] === 'object' && config[key] !== null &&
                    typeof defaultConfig[key] === 'object' && defaultConfig[key] !== null) {
                    // Recursively validate nested objects
                    validatedConfig[key] = this.validateConfig(config[key], defaultConfig[key], currentPath);
                } else {
                    // For primitive values, just copy them
                    validatedConfig[key] = config[key];
                }
            } else {
                console.warn(`Ignoring invalid configuration key: ${currentPath}`);
            }
        }

        // Add missing keys from default config with their default values
        for (const key in defaultConfig) {
            if (!(key in validatedConfig)) {
                validatedConfig[key] = JSON.parse(JSON.stringify(defaultConfig[key]));
            }
        }

        return validatedConfig;
    }
}

module.exports = ConfigManager;
