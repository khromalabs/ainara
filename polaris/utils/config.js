const path = require('path');
const fs = require('fs');
const electron = require('electron');
class ConfigManager {
    constructor() {
        // Singleton pattern
        if (ConfigManager.instance) {
            return ConfigManager.instance;
        }
        ConfigManager.instance = this;

        this.config = {};

        // Get app from either main or renderer process
        const app = electron.app || (electron.remote && electron.remote.app);

        if (!app) {
            console.warn('Running in renderer process without remote module, using fallback path');
            // Fallback to a reasonable default path
            const homeDir = require('os').homedir();
            this.configDir = path.join(homeDir, '.config', 'polaris');
        } else {
            this.configDir = path.join(app.getPath('userData'), 'config');
        }

        this.configFile = path.join(this.configDir, 'polaris.json');
        this.loadConfig();
    }

    loadConfig() {
        try {
            console.log('Loading configuration from:', this.configDir);
            if (!fs.existsSync(this.configDir)) {
                fs.mkdirSync(this.configDir, { recursive: true });
            }

            if (!fs.existsSync(this.configFile)) {
                // Create default config
                const defaultConfig = {
                    stt: {
                        modules: {
                            whisper: {
                                service: 'custom',
                                custom: {
                                    apiKey: 'local',
                                    apiUrl: 'http://127.0.0.1:5001/framework/stt',
                                    // apiUrl: 'http://127.0.0.1:8080/inference',
                                    headers: {}
                                }
                            }
                        }
                    },
                    orakle: {
                        api_url: 'http://localhost:5000'
                    },
                    window: {
                        width: 300,
                        height: 200,
                        frame: false,
                        transparent: true,
                        alwaysOnTop: true,
                        skipTaskbar: true,
                        focusable: true,
                        type: 'toolbar',
                        backgroundColor: '#00000000',
                        hasShadow: false,
                        vibrancy: 'blur',
                        visualEffectState: 'active',
                        opacity: 0.95
                    },
                    shortcuts: {
                        toggle: 'F1'
                    },
                    ring: {
                        volume: 0,
                        visible: false,
                        fftSize: 256,
                        fadeTimeout: 500,
                        opacity: {
                            min: 0.4,
                            max: 1,
                            scale: 1.2
                        }
                    }
                };
                fs.writeFileSync(this.configFile, JSON.stringify(defaultConfig, null, 2));
                this.config = defaultConfig;
            } else {
                const fileContents = fs.readFileSync(this.configFile, 'utf8');
                this.config = JSON.parse(fileContents);
            }
            console.log('Configuration loaded successfully');
        } catch (error) {
            console.error('Error loading configuration:', error);
            throw error;
        }
    }

    get(keyPath, defaultValue = null) {
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
            fs.writeFileSync(this.configFile, JSON.stringify(this.config, null, 2));
            Logger.log('Configuration saved successfully');
        } catch (error) {
            Logger.error('Error saving configuration:', error);
            throw error;
        }
    }
}

module.exports = ConfigManager;
