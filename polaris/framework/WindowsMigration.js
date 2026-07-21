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
 * Gets the Saved Games folder path on Windows using PowerShell.
 * @returns {string}
 */
function getWindowsSavedGamesPath() {
    try {
        const result = execSync(
            'powershell -Command "[Environment]::GetFolderPath(\'SavedGames\')"',
            { encoding: 'utf8' }
        ).trim();
        return result;
    } catch (error) {
        Logger.warn('Failed to get Saved Games path via PowerShell, falling back to default: ' + error);
        return path.join(os.homedir(), 'Saved Games');
    }
}

/**
 * Gets the real Documents path on Windows using PowerShell.
 * This handles OneDrive redirection correctly.
 * @returns {string} The path to the user's Documents folder
 */
function getWindowsDocumentsPath() {
    try {
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
            if (!fs.existsSync(destPath)) {
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
 * Replaces old paths in ainara.yaml content to point to the new Saved Games location.
 * @param {string} yamlPath Path to the ainara.yaml file
 * @param {string} oldDocumentsDir Old Documents directory
 * @param {string} newSavedGamesDir New Saved Games directory
 */
function updateAinaraYamlPaths(yamlPath, oldDocumentsDir, newSavedGamesDir) {
    try {
        let content = fs.readFileSync(yamlPath, 'utf8');
        const oldBase = path.join(oldDocumentsDir, 'Ainara');
        const newBase = path.join(newSavedGamesDir, 'Ainara');
        // Normalize to forward slashes for YAML
        const oldNorm = oldBase.replace(/\\/g, '/');
        const newNorm = newBase.replace(/\\/g, '/');
        // Replace directory keys that may contain the old path
        const dirKeys = ['data.directory', 'logging.directory', 'cache.directory'];
        dirKeys.forEach(key => {
            // Replace forward-slashed paths
            content = content.split(`${key}: ${oldNorm}/Data`).join(`${key}: ${newNorm}/Data`);
            content = content.split(`${key}: ${oldNorm}/Logs`).join(`${key}: ${newNorm}/Logs`);
            content = content.split(`${key}: ${oldNorm}/Cache`).join(`${key}: ${newNorm}/Cache`);
            // Also handle backslashes if present
            const oldBack = oldBase.replace(/\//g, '\\\\');
            const newBack = newBase.replace(/\//g, '\\\\');
            content = content.split(`${key}: ${oldBack}\\\\Data`).join(`${key}: ${newBack}\\\\Data`);
            content = content.split(`${key}: ${oldBack}\\\\Logs`).join(`${key}: ${newBack}\\\\Logs`);
            content = content.split(`${key}: ${oldBack}\\\\Cache`).join(`${key}: ${newBack}\\\\Cache`);
        });
        fs.writeFileSync(yamlPath, content, 'utf8');
        Logger.info('Updated paths in ainara.yaml');
    } catch (err) {
        Logger.warn('Failed to update paths in ainara.yaml: ' + err.message);
    }
}

/**
 * Main migration function: moves all data from old locations to Saved Games\Ainara.
 * Returns { success: bool, migrated: bool, error?: string }
 */
async function migrateToSavedGamesIfNeeded() {
    // Skip on non-Windows platforms
    if (process.platform !== 'win32') {
        return { success: true, migrated: false };
    }

    try {
        const savedGamesPath = getWindowsSavedGamesPath();
        const targetBase = path.join(savedGamesPath, 'Ainara');
        const targetConfigDir = path.join(targetBase, 'Config');
        const targetDataDir = path.join(targetBase, 'Data');
        const targetLogsDir = path.join(targetBase, 'Logs');
        const targetCacheDir = path.join(targetBase, 'Cache');
        const targetPolarisConfigDir = path.join(targetConfigDir, 'polaris');
        const targetPolarisJson = path.join(targetPolarisConfigDir, 'polaris.json');
        const targetAinaraYaml = path.join(targetConfigDir, 'ainara.yaml');

        // If polaris.json already exists in target, migration is done
        if (fs.existsSync(targetPolarisJson)) {
            Logger.info('Migration already completed, target polaris.json exists.');
            return { success: true, migrated: false };
        }

        Logger.info('Starting migration to Saved Games...');

        const documentsPath = getWindowsDocumentsPath();
        const oldDocumentsAinara = path.join(documentsPath, 'Ainara');

        const legacyRoaming = path.join(os.homedir(), 'AppData', 'Roaming', 'ainara');
        const legacyLocal = path.join(os.homedir(), 'AppData', 'Local', 'ainara');
        const oldPolarisJson = path.join(legacyRoaming, 'polaris', 'polaris.json');

        let backendSource = null; // 'documents' or 'appdata'

        // Determine which backend data source to use
        if (fs.existsSync(oldDocumentsAinara)) {
            backendSource = 'documents';
        } else if (fs.existsSync(legacyRoaming) || fs.existsSync(legacyLocal)) {
            backendSource = 'appdata';
        }

        // Create target folders
        for (const dir of [targetConfigDir, targetDataDir, targetLogsDir, targetCacheDir, targetPolarisConfigDir]) {
            fs.mkdirSync(dir, { recursive: true });
        }

        // Migrate backend files
        if (backendSource === 'documents') {
            // Copy entire Documents/Ainara subfolders
            Logger.info('Migrating backend data from Documents/Ainara...');
            const subfolders = ['Config', 'Data', 'Logs', 'Cache'];
            for (const sub of subfolders) {
                const src = path.join(oldDocumentsAinara, sub);
                if (fs.existsSync(src)) {
                    copyDirectorySync(src, path.join(targetBase, sub));
                }
            }
            // Rename old Documents folder
            const oldRenamed = path.join(documentsPath, 'Ainara.old.migrated_to_savedgames');
            fs.renameSync(oldDocumentsAinara, oldRenamed);
            Logger.info(`Renamed ${oldDocumentsAinara} to ${oldRenamed}`);
        } else if (backendSource === 'appdata') {
            // Migrate from legacy AppData to target
            Logger.info('Migrating backend data from AppData...');
            if (fs.existsSync(legacyRoaming)) {
                copyDirectorySync(legacyRoaming, targetConfigDir);
            }
            if (fs.existsSync(legacyLocal)) {
                copyDirectorySync(path.join(legacyLocal, 'logs'), targetLogsDir);
                copyDirectorySync(path.join(legacyLocal, 'Cache'), targetCacheDir);
                copyDirectorySync(legacyLocal, targetDataDir, ['logs', 'Cache']);
            }
            // Rename AppData folders
            if (fs.existsSync(legacyRoaming)) {
                fs.renameSync(legacyRoaming, path.join(os.homedir(), 'AppData', 'Roaming', 'ainara.old.migrated_to_savedgames'));
            }
            if (fs.existsSync(legacyLocal)) {
                fs.renameSync(legacyLocal, path.join(os.homedir(), 'AppData', 'Local', 'ainara.old.migrated_to_savedgames'));
            }
        }

        // Migrate Electron polaris.json
        if (fs.existsSync(oldPolarisJson)) {
            Logger.info('Moving polaris.json...');
            fs.copyFileSync(oldPolarisJson, targetPolarisJson);
        }

        // Update paths inside ainara.yaml if it exists
        if (fs.existsSync(targetAinaraYaml)) {
            updateAinaraYamlPaths(targetAinaraYaml, documentsPath, savedGamesPath);
        }

        // Set hidden attribute on target
        setHiddenAttribute(targetBase);

        Logger.info('Migration to Saved Games completed successfully.');
        return { success: true, migrated: true };

    } catch (error) {
        Logger.error('Migration failed: ' + error.message);
        return { success: false, migrated: false, error: error.message };
    }
}

module.exports = { migrateToSavedGamesIfNeeded };
