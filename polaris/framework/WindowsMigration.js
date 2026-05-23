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

const fs = require('fs');
const path = require('path');
const os = require('os');
const { execSync } = require('child_process');
const Logger = require('./logger');

/**
 * Gets the real Documents path on Windows using PowerShell.
 * This handles OneDrive redirection correctly.
 * @returns {string} The path to the user's Documents folder
 */
function getWindowsDocumentsPath() {
    try {
        // Use PowerShell to get the actual Documents folder path
        const result = execSync(
            'powershell -Command "[Environment]::GetFolderPath(\'MyDocuments\')"',
            { encoding: 'utf8' }
        ).trim();
        return result;
    } catch (error) {
        Logger.warn('Failed to get Documents path via PowerShell, falling back to default: ' + error);
        return path.join(os.homedir(), 'Documents');
    }
}

/**
 * Recursively copies a directory's contents to a destination.
 * @param {string} src Source directory
 * @param {string} dest Destination directory
 * @param {string[]} excludeDirs Directory names to exclude from copying
 */
function copyDirectorySync(src, dest, excludeDirs = []) {
    if (!fs.existsSync(src)) {
        return;
    }

    if (!fs.existsSync(dest)) {
        fs.mkdirSync(dest, { recursive: true });
    }

    const entries = fs.readdirSync(src, { withFileTypes: true });

    for (const entry of entries) {
        const srcPath = path.join(src, entry.name);
        const destPath = path.join(dest, entry.name);

        if (entry.isDirectory()) {
            if (!excludeDirs.includes(entry.name)) {
                copyDirectorySync(srcPath, destPath, excludeDirs);
            }
        } else {
            // Avoid copy if dest already exists
            if(!fs.existsSync(destPath)) {
                fs.copyFileSync(srcPath, destPath);
            }
        }
    }
}

/**
 * Sets the hidden attribute on a folder (Windows only).
 * @param {string} folderPath Path to the folder
 */
function setHiddenAttribute(folderPath) {
    try {
        execSync(`attrib +h "${folderPath}"`, { encoding: 'utf8' });
        Logger.info(`Set hidden attribute on: ${folderPath}`);
    } catch (error) {
        Logger.warn(`Failed to set hidden attribute on ${folderPath}: ${error.message}`);
    }
}

/**
 * Ensures the Windows data location exists and migrates legacy data if needed.
 * This should be called before starting Python services.
 * 
 * @returns {Promise<{success: boolean, skipped: boolean, error?: string}>}
 */
async function ensureWindowsDataLocation() {
    // Skip on non-Windows platforms
    if (process.platform !== 'win32') {
        return { success: true, skipped: true };
    }

    try {
        const documentsPath = getWindowsDocumentsPath();
        const newBaseDir = path.join(documentsPath, 'Ainara');
        const configDir = path.join(newBaseDir, 'Config');
        const dataDir = path.join(newBaseDir, 'Data');
        const logsDir = path.join(newBaseDir, 'Logs');
        const cacheDir = path.join(newBaseDir, 'Cache');

        const configFile = path.join(configDir, 'ainara.yaml');

        // Check if migration already done (config file exists in new location)
        if (fs.existsSync(configFile)) {
            Logger.info('Windows data location already set up, skipping migration');
            return { success: true, skipped: true };
        }

        Logger.info('Setting up Windows data location and migrating legacy data...');

        // Create folder structure
        const folders = [configDir, dataDir, logsDir, cacheDir];
        for (const folder of folders) {
            if (!fs.existsSync(folder)) {
                fs.mkdirSync(folder, { recursive: true });
                Logger.info(`Created folder: ${folder}`);
            }
        }

        // Define legacy paths
        const userHome = os.homedir();
        const legacyRoaming = path.join(userHome, 'AppData', 'Roaming', 'Ainara');
        const legacyLocal = path.join(userHome, 'AppData', 'Local', 'Ainara');
        const legacyLogs = path.join(legacyLocal, 'logs');
        const legacyCache = path.join(legacyLocal, 'Cache');

        // Migrate Config (Roaming -> Config)
        if (fs.existsSync(legacyRoaming)) {
            Logger.info(`Migrating configuration from ${legacyRoaming}...`);
            copyDirectorySync(legacyRoaming, configDir);
            Logger.info('Configuration migration complete');
        }

        // Migrate Data (Local -> Data, excluding logs and Cache)
        if (fs.existsSync(legacyLocal)) {
            Logger.info(`Migrating data from ${legacyLocal}...`);
            copyDirectorySync(legacyLocal, dataDir, ['logs', 'Cache']);
            Logger.info('Data migration complete');
        }

        // Migrate Logs (Local/logs -> Logs)
        if (fs.existsSync(legacyLogs)) {
            Logger.info(`Migrating logs from ${legacyLogs}...`);
            copyDirectorySync(legacyLogs, logsDir);
            Logger.info('Logs migration complete');
        }

        // Migrate Cache (Local/Cache -> Cache)
        if (fs.existsSync(legacyCache)) {
            Logger.info(`Migrating cache from ${legacyCache}...`);
            copyDirectorySync(legacyCache, cacheDir);
            Logger.info('Cache migration complete');
        }

        // Set hidden attribute on the Ainara folder
        setHiddenAttribute(newBaseDir);

        Logger.info('Windows data location setup and migration complete');
        return { success: true, skipped: false };

    } catch (error) {
        Logger.error('Failed to set up Windows data location:', error);
        return { success: false, skipped: false, error: error.message };
    }
}

module.exports = { ensureWindowsDataLocation };
