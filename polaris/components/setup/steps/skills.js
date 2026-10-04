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

const utils = require('../core/utils');

module.exports = {
    id: 'skills',

    async init(ctx) {
        await generateSkillsUI(ctx);
    },

    async save(ctx) {
        await saveSkillsConfig(ctx);
    },

    validate(ctx) {
        return true; // Skills are optional
    },

    updateNextButtonState(ctx) {
        updateSkillsNextButtonState(ctx);
    }
};

async function generateSkillsUI(ctx) {
    try {
        const apiUrl = ctx.config.get('orakle.api_url');
        const [fullResp, propsResp] = await Promise.all([
            fetch(apiUrl + '/capabilities?view=full'),
            fetch(apiUrl + '/capabilities?view=properties')
        ]);
        if (!fullResp.ok) throw new Error(`Failed to load capabilities: ${fullResp.status}`);
        if (!propsResp.ok) throw new Error(`Failed to load capability properties: ${propsResp.status}`);

        const capabilities = await fullResp.json();
        const properties = await propsResp.json();
        const backendConfig = await ctx.api.loadBackendConfig();

        // Nexus subscription/install state from Pybridge (optional feature:
        // degrade gracefully if unavailable)
        let nexusApps = null;
        try {
            const pybridgeUrl = ctx.config.get('pybridge.api_url');
            const nexusResp = await fetch(pybridgeUrl + '/nexus/apps');
            if (nexusResp.ok) nexusApps = await nexusResp.json();
        } catch (e) {
            console.warn('Nexus apps state unavailable:', e);
        }

        const scheduleHtml = generateScheduleUI(capabilities, backendConfig);
        const userSkillsHtml = generateUserSkillsUI();
        const nexusHtml = generateNexusUI(properties, backendConfig, nexusApps);

        const tabStyles = `
            <style>
                .skills-tabs { display: flex; border-bottom: 2px solid #ddd; margin-bottom: 15px; gap: 0; }
                .skills-tab { padding: 10px 20px; background: none; border: none; border-bottom: 3px solid transparent; cursor: pointer; font-size: 14px; font-weight: 500; color: #666; }
                .skills-tab:hover { color: #333; }
                .skills-tab.active { color: #007bff; border-bottom-color: #007bff; }
                .skills-tab-content { display: none; padding: 15px 0; }
                .skills-tab-content.active { display: block; }
                .nexus-app { border: 1px solid #e0e0e0; border-radius: 8px; padding: 15px; margin-bottom: 20px; background: #fff; }
                .nexus-app h4 { margin: 0 0 5px 0; font-size: 16px; }
                .nexus-app-description { margin: 0 0 15px 0; font-size: 0.9em; color: #666; }
                .nexus-skill { border: 1px solid #eee; border-radius: 6px; margin-bottom: 10px; padding: 0; background: #fafafa; }
                .nexus-skill summary { padding: 12px 15px; cursor: pointer; font-size: 14px; }
                .nexus-skill-desc { display: block; font-size: 0.8em; color: #888; margin-top: 2px; }
                .nexus-skill-params { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 15px; padding: 15px; border-top: 1px solid #eee; }
                .nexus-param-item { display: flex; flex-direction: column; padding: 8px; }
                .nexus-param-item label { font-size: 0.85em; font-weight: bold; margin-bottom: 4px; }
                .nexus-param-item .param-desc { font-size: 0.8em; color: #666; margin-bottom: 6px; }
                .nexus-param-item input, .nexus-param-item select, .nexus-param-item textarea { padding: 6px; border: 1px solid #ddd; border-radius: 4px; font-size: 0.9em; width: 100%; box-sizing: border-box; }
                .nexus-param-item textarea { min-height: 80px; font-family: monospace; }
                .nexus-param-control { display: flex; align-items: center; gap: 6px; }
                .nexus-reset-btn { background: none; border: none; color: #007bff; cursor: pointer; font-size: 0.8em; padding: 2px 4px; white-space: nowrap; }
                .nexus-reset-btn:hover { text-decoration: underline; }
                .nexus-reset-all-btn {
                    margin-top: 10px;
                    font-size: 0.85em;
                    color: #721c24;
                    background: #f8d7da;
                    border: 1px solid #f5c6cb;
                    border-radius: 4px;
                    padding: 6px 12px;
                    cursor: pointer;
                }
                .nexus-reset-all-btn:hover {
                    background: #f8a7aa;
                    border-color: #f5a6ab;
                }
            </style>
        `;

        const tabsHtml = `
            ${tabStyles}
            <div class="skills-tabs">
                <button type="button" class="skills-tab active" data-tab="nexus">Nexus Apps Properties</button>
                <button type="button" class="skills-tab" data-tab="user">User Skills Directory</button>
                <button type="button" class="skills-tab" data-tab="scheduled">Scheduled Skills</button>
            </div>
            <div class="skills-tab-content active" data-tab-content="nexus">
                ${nexusHtml || '<p>No Nexus Apps available.</p>'}
            </div>
            <div class="skills-tab-content" data-tab-content="user">
                ${userSkillsHtml}
            </div>
            <div class="skills-tab-content" data-tab-content="scheduled">
                ${scheduleHtml || '<p>No scheduled skills available.</p>'}
            </div>
        `;

        const skillsListContainer = document.querySelector('.skills-list');
        if (skillsListContainer) {
            skillsListContainer.innerHTML = tabsHtml;
        }

        setupTabListeners();
        setupScheduleListeners(ctx);
        setupUserSkillsListeners(ctx, backendConfig);
        setupNexusListeners(ctx);

        updateSkillsNextButtonState(ctx);

    } catch (error) {
        console.error('Error generating skills UI:', error);
        const skillsListContainer = document.querySelector('.skills-list');
        if (skillsListContainer) {
            skillsListContainer.innerHTML = `
                <div class="error">Error loading skills: ${error.message}</div>
            `;
        }
    }
}

function updateSkillsNextButtonState(ctx) {
    const nextButton = document.getElementById('main-next-btn');
    if (nextButton) {
        nextButton.disabled = false;
    }
}

async function saveSkillsConfig(ctx) {
    if (ctx.modifiedFields.skills.size === 0) return;

    try {
        const backendConfig = await ctx.api.loadBackendConfig();

        // Save scheduler overrides
        if (ctx.modifiedFields.skills.has('scheduler')) {
            if (!backendConfig.scheduler) backendConfig.scheduler = {};
            if (!backendConfig.scheduler.overrides) backendConfig.scheduler.overrides = {};

            document.querySelectorAll('.schedule-row').forEach(row => {
                const skillName = row.dataset.skill;
                const isEnabled = row.querySelector('.schedule-enable').checked;
                const minutes = parseInt(row.querySelector('.schedule-interval').value);
                const isDefaultDefault = row.dataset.defaultDefault === "true";

                if (!isEnabled) {
                    if (isDefaultDefault) {
                        backendConfig.scheduler.overrides[skillName] = false;
                    } else {
                        delete backendConfig.scheduler.overrides[skillName];
                    }
                } else {
                    const uiKwargs = {};
                    document.querySelectorAll(`.param-input[data-skill="${skillName}"]`).forEach(input => {
                        const key = input.dataset.key;
                        const type = input.dataset.type;
                        let val = input.value;

                        if (type === 'boolean') val = (val === 'true');
                        else if (type === 'integer') { val = parseInt(val); if (isNaN(val)) val = null; }
                        else if (type === 'number') { val = parseFloat(val); if (isNaN(val)) val = null; }
                        else if (type === 'array') {
                            val = val ? val.split(',').map(s => s.trim()).filter(s => s !== '') : [];
                        }

                        if (!input.disabled) uiKwargs[key] = val;
                    });

                    const existingOverride = backendConfig.scheduler.overrides[skillName];
                    const existingKwargs = (existingOverride && existingOverride !== false && existingOverride.kwargs)
                                           ? existingOverride.kwargs : {};
                    const finalKwargs = { ...existingKwargs, ...uiKwargs };

                    backendConfig.scheduler.overrides[skillName] = {
                        trigger: 'interval',
                        minutes: minutes,
                        kwargs: finalKwargs
                    };
                }
            });
        }

        // Save user skills directory if modified
        if (ctx.modifiedFields.skills.has('user_skills')) {
            const userSkillsInput = document.getElementById('user-skills-directory');
            if (userSkillsInput && userSkillsInput.value.trim()) {
                if (!backendConfig.user_skills) backendConfig.user_skills = {};
                backendConfig.user_skills.directory = userSkillsInput.value.trim();
            }
        }
        // Save Nexus App overrides
        if (ctx.modifiedFields.skills.has('nexus')) {
            saveNexusConfig(ctx, backendConfig);
        }

        await ctx.api.saveBackendConfig(backendConfig, ctx.config.get('pybridge.api_url'));
        await ctx.api.saveBackendConfig(backendConfig, ctx.config.get('orakle.api_url'));

        ctx.modifiedFields.skills.clear();
    } catch (error) {
        console.error('Error saving skills config:', error);
        throw error;
    }
}

function generateScheduleUI(capabilities, backendConfig) {
    let rows = '';
    let hasSchedulable = false;

    const styles = `
        <style>
            .schedule-details-row { display: none; background-color: #f8f9fa; }
            .schedule-details-row.active { display: table-row; }
            .schedule-details-panel { padding: 15px; display: grid; grid-template-columns: repeat(auto-fill, minmax(250px, 1fr)); gap: 15px; border-bottom: 1px solid #eee; }
            .param-group { display: flex; flex-direction: column; }
            .param-group label { font-size: 0.85em; font-weight: bold; margin-bottom: 4px; color: #444; }
            .param-group .param-desc { font-size: 0.75em; color: #666; margin-top: 4px; line-height: 1.2; }
            .param-group input, .param-group select { padding: 6px; border: 1px solid #ddd; border-radius: 4px; font-size: 0.9em; }
            .settings-btn { background: none; border: none; cursor: pointer; font-size: 1.2em; padding: 0 10px; opacity: 0.6; transition: opacity 0.2s; }
            .settings-btn:hover, .settings-btn.active { opacity: 1; }
            .schedule-table td { vertical-align: middle; }
        </style>
    `;

    for (const [name, cap] of Object.entries(capabilities)) {
        if (cap.default_schedule) {
            hasSchedulable = true;
            const override = backendConfig.scheduler?.overrides?.[name];
            const defaultSched = cap.default_schedule;

            let isEnabled;
            if (defaultSched.default) {
                isEnabled = !(override === false);
            } else {
                isEnabled = typeof override !== "undefined" && override !== false;
            }

            const currentKwargs = (override && override !== false && override.kwargs)
                                  ? override.kwargs
                                  : (defaultSched.kwargs || {});

            const minutes = (override && override.minutes) ? override.minutes : (defaultSched.minutes || 10);
            const hasParams = cap.run_info?.parameters && Object.keys(cap.run_info.parameters).length > 0;

            rows += `
                <tr class="schedule-row" data-skill="${name}" data-default-default=${defaultSched.default || false} data-default-minutes="${defaultSched.minutes || 10}">
                    <td style="max-width: 100px">
                        <i>${name}</i>
                        <p style="font-size:0.8em; margin: 2px 0 0 0; color: #666;">${cap.description ? cap.description.trim().split('\n')[0] : ""}</p>
                    </td>
                    <td>
                        <label class="schedule-toggle">
                            <input type="checkbox" class="schedule-enable" ${isEnabled ? 'checked' : ''}>
                            Enable
                        </label>
                    </td>
                    <td>
                        Run every <input type="number" class="schedule-interval schedule-interval-input" value="${minutes}" min="1" ${isEnabled ? '' : 'disabled'} style="width: 60px;"> minutes
                    </td>
                    <td style="text-align: center;">
                        ${hasParams ? `<button class="settings-btn" style="display:none" data-skill="${name}" title="Configure Parameters">⚙️</button>` : ''}
                    </td>
                </tr>
                ${hasParams ? `
                <tr class="schedule-details-row" id="details-${name}">
                    <td colspan="4" style="padding: 0;">
                        <div class="schedule-details-panel">
                            ${utils.renderSkillParameters(name, cap, currentKwargs)}
                        </div>
                    </td>
                </tr>
                ` : ''}
            `;
        }
    }

    if (!hasSchedulable) return '';

    return `
        ${styles}
        <div class="schedule-config-section">
            <h3>Scheduled Skills</h3>
            <p>Configure automatic execution intervals and parameters for supported skills.</p>
            <table class="schedule-table">
                <thead>
                    <tr>
                        <th>Skill</th>
                        <th>Status</th>
                        <th>Frequency</th>
                        <th style="width: 50px;"></th>
                    </tr>
                </thead>
                <tbody>
                    ${rows}
                </tbody>
            </table>
        </div>
    `;
}

function setupScheduleListeners(ctx) {
    document.querySelectorAll('.schedule-row').forEach(row => {
        const checkbox = row.querySelector('.schedule-enable');
        const input = row.querySelector('.schedule-interval');
        const skillName = row.dataset.skill;

        checkbox.addEventListener('change', () => {
            input.disabled = !checkbox.checked;
            ctx.modifiedFields.skills.add('scheduler');
            updateSkillsNextButtonState(ctx);
        });

        input.addEventListener('input', () => {
            ctx.modifiedFields.skills.add('scheduler');
            updateSkillsNextButtonState(ctx);
        });

        const settingsBtn = row.querySelector('.settings-btn');
        if (settingsBtn) {
            settingsBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                const detailsRow = document.getElementById(`details-${skillName}`);
                const isActive = detailsRow.classList.contains('active');

                document.querySelectorAll('.schedule-details-row').forEach(el => el.classList.remove('active'));
                document.querySelectorAll('.settings-btn').forEach(el => el.classList.remove('active'));

                if (!isActive) {
                    detailsRow.classList.add('active');
                    settingsBtn.classList.add('active');
                }
            });
        }
    });

    document.querySelectorAll('.param-input').forEach(input => {
        input.addEventListener('change', () => {
            ctx.modifiedFields.skills.add('scheduler');
            updateSkillsNextButtonState(ctx);
        });
        if (input.tagName === 'INPUT' && input.type === 'text') {
             input.addEventListener('input', () => {
                ctx.modifiedFields.skills.add('scheduler');
             });
        }
    });
}

function escapeHtml(str) {
    return String(str ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function showNexusDescriptionModal(btn) {
    const existing = document.querySelector('.nexus-desc-modal-backdrop');
    if (existing) existing.remove();

    const rawTitle = btn.dataset.nexusTitle || '';
    const rawDescription = btn.dataset.nexusDescription || '';

    let title;
    let description;
    try { title = decodeURIComponent(rawTitle); } catch (e) { title = rawTitle; }
    try { description = decodeURIComponent(rawDescription); } catch (e) { description = rawDescription; }

    const backdrop = document.createElement('div');
    backdrop.className = 'nexus-desc-modal-backdrop';
    backdrop.innerHTML = `
        <div class="nexus-desc-modal" role="dialog" aria-modal="true" aria-labelledby="nexus-desc-modal-title">
            <button type="button" class="nexus-desc-modal-close" aria-label="Close">×</button>
            <h4 id="nexus-desc-modal-title">${escapeHtml(title)}</h4>
            <div class="nexus-desc-modal-body">${escapeHtml(description)}</div>
        </div>
    `;

    const closeBtn = backdrop.querySelector('.nexus-desc-modal-close');

    const close = () => {
        backdrop.remove();
        document.removeEventListener('keydown', onKey);
    };

    const onKey = (e) => {
        if (e.key === 'Escape') {
            e.preventDefault();
            close();
        }
    };

    document.body.appendChild(backdrop);

    if (closeBtn) {
        closeBtn.addEventListener('click', close);
        closeBtn.focus();
    }

    backdrop.addEventListener('click', (e) => {
        if (e.target === backdrop) close();
    });

    document.addEventListener('keydown', onKey);
}

function capitalize(str) {
    if (!str) return '';
    return str.charAt(0).toUpperCase() + str.slice(1);
}

function getNested(obj, path) {
    return path.split('.').reduce((acc, key) => (acc && acc[key] !== undefined ? acc[key] : undefined), obj);
}

function setNested(obj, path, value) {
    const keys = path.split('.');
    let cur = obj;
    for (let i = 0; i < keys.length - 1; i++) {
        const key = keys[i];
        if (!cur[key] || typeof cur[key] !== 'object') {
            cur[key] = {};
        }
        cur = cur[key];
    }
    cur[keys[keys.length - 1]] = value;
}

function deleteNested(obj, path) {
    const keys = path.split('.');
    let cur = obj;
    for (let i = 0; i < keys.length - 1; i++) {
        if (!cur || typeof cur !== 'object') return;
        cur = cur[keys[i]];
    }
    if (cur && typeof cur === 'object') {
        delete cur[keys[keys.length - 1]];
    }
}

function deepEqual(a, b) {
    if (a === b) return true;
    if (typeof a !== typeof b) return false;
    if (a === null || b === null) return a === b;
    if (Array.isArray(a) && Array.isArray(b)) {
        if (a.length !== b.length) return false;
        return a.every((v, i) => deepEqual(v, b[i]));
    }
    if (typeof a === 'object' && typeof b === 'object') {
        const keysA = Object.keys(a).sort();
        const keysB = Object.keys(b).sort();
        if (keysA.length !== keysB.length) return false;
        return keysA.every((k, i) => k === keysB[i] && deepEqual(a[k], b[k]));
    }
    return false;
}

function isNexusParamModified(prop, backendConfig) {
    const schema = (prop.schema && typeof prop.schema === 'object') ? prop.schema : {};
    const current = getNested(backendConfig, prop.fullKey);
    const hasDefault = schema.default !== undefined;
    const defaultVal = hasDefault ? schema.default : null;
    const currentValue = current !== undefined ? current : defaultVal;

    if (!hasDefault && current === undefined) return false;
    return !deepEqual(currentValue, defaultVal);
}

function countNexusModifiedParams(params, backendConfig) {
    return params.reduce((count, prop) => count + (isNexusParamModified(prop, backendConfig) ? 1 : 0), 0);
}

function cleanupNexusConfig(backendConfig) {
    const root = backendConfig && backendConfig.skills && backendConfig.skills.nexus;
    if (!root || typeof root !== 'object') return;

    removeEmptyObjects(root);

    if (Object.keys(root).length === 0) {
        delete backendConfig.skills.nexus;
    }

    if (backendConfig.skills && Object.keys(backendConfig.skills).length === 0) {
        delete backendConfig.skills;
    }
}

function removeEmptyObjects(obj) {
    for (const key of Object.keys(obj)) {
        const val = obj[key];
        if (val && typeof val === 'object' && !Array.isArray(val)) {
            removeEmptyObjects(val);
            if (Object.keys(val).length === 0) {
                delete obj[key];
            }
        }
    }
}

function parseNexusValue(raw, type) {
    switch (type) {
        case 'string':
            return raw;
        case 'number': {
            const trimmed = raw.trim();
            if (trimmed === '') return null;
            const val = Number(trimmed);
            if (isNaN(val)) throw new Error('Expected a number.');
            return val;
        }
        case 'integer': {
            const trimmed = raw.trim();
            if (trimmed === '') return null;
            const val = Number(trimmed);
            if (!Number.isInteger(val)) throw new Error('Expected an integer.');
            return val;
        }
        case 'boolean':
            return raw === 'true';
        case 'array':
        case 'object': {
            const val = JSON.parse(raw);
            if (type === 'array' && !Array.isArray(val)) throw new Error('Expected a JSON array.');
            if (type === 'object' && (val === null || typeof val !== 'object' || Array.isArray(val))) throw new Error('Expected a JSON object.');
            return val;
        }
        default:
            return raw;
    }
}

function setNexusInputValue(input, value, type) {
    if (type === 'boolean') {
        input.value = value ? 'true' : 'false';
    } else if (type === 'array' || type === 'object') {
        input.value = (value === undefined || value === null) ? '' : JSON.stringify(value, null, 2);
    } else if (input.tagName === 'SELECT') {
        let option = Array.from(input.options).find(o => o.value === String(value));
        if (!option && value !== undefined && value !== null) {
            option = document.createElement('option');
            option.value = String(value);
            option.textContent = String(value) + ' (custom)';
            input.add(option);
        }
        if (option) input.value = String(value);
        else input.value = '';
    } else {
        input.value = (value === undefined || value === null) ? '' : value;
    }
}

function updateNexusParamState(input) {
    input.disabled = false;
    const item = input.closest('.nexus-param-item');
    if (!item) return;

    const defaultRaw = decodeURIComponent(input.dataset.default || 'null');
    let defaultVal;
    try {
        defaultVal = JSON.parse(defaultRaw);
    } catch (e) {
        defaultVal = null;
    }

    const valueType = input.dataset.valueType || 'string';
    const rawValue = input.value.trim();

    let currentVal;
    if (valueType === 'string') {
        currentVal = rawValue;
    } else if (rawValue === '') {
        currentVal = null;
    } else {
        try {
            currentVal = parseNexusValue(rawValue, valueType);
        } catch (e) {
            currentVal = null;
        }
    }

    const isModified = !deepEqual(currentVal, defaultVal);

    const resetBtn = item.querySelector('.nexus-reset-btn');
    if (resetBtn) resetBtn.disabled = !isModified;

    item.classList.toggle('modified', isModified);
}

function groupNexusSharedParams(params) {
    const groups = {};
    for (const prop of params) {
        const moduleName = prop.module || 'General';
        if (!groups[moduleName]) groups[moduleName] = [];
        groups[moduleName].push(prop);
    }

    const sortedGroups = {};
    const sortedKeys = Object.keys(groups).sort((a, b) => a.localeCompare(b));
    for (const key of sortedKeys) {
        sortedGroups[key] = groups[key].sort((a, b) =>
            String(a.param || a.fullKey).localeCompare(String(b.param || b.fullKey))
        );
    }
    return sortedGroups;
}

function groupNexusApps(properties) {
    const appsMap = new Map();

    for (const [fullKey, prop] of Object.entries(properties || {})) {
        // Skip null-type properties entirely
        if (prop.value_type === 'null') continue;

        // Only support shared and skill scopes
        if (prop.scope !== 'shared' && prop.scope !== 'skill') continue;

        // Parse vendor/bundle from full key: skills.nexus.<vendor>.<bundle>.<rest...>
        const parts = fullKey.split('.');
        if (parts.length < 4) continue;
        const vendor = prop.vendor || parts[2];
        const bundle = prop.bundle || parts[3];
        if (!vendor || !bundle) continue;

        const appKey = `${vendor}.${bundle}`;
        if (!appsMap.has(appKey)) {
            appsMap.set(appKey, { vendor, bundle, shared: [], skills: new Map() });
        }
        const app = appsMap.get(appKey);

        // Normalize the property object with the full key
        const normalizedProp = { ...prop, fullKey };
        if (!normalizedProp.param) {
            normalizedProp.param = parts[parts.length - 1];
        }

        if (prop.scope === 'shared') {
            app.shared.push(normalizedProp);
        } else if (prop.scope === 'skill') {
            const skillName = prop.skill || (parts.length > 4 ? parts[parts.length - 2] : 'General');
            if (!app.skills.has(skillName)) {
                app.skills.set(skillName, []);
            }
            app.skills.get(skillName).push(normalizedProp);
        }
    }

    // Sort apps by vendor/bundle for stable display
    return Array.from(appsMap.values()).sort((a, b) => {
        if (a.vendor !== b.vendor) return a.vendor.localeCompare(b.vendor);
        return a.bundle.localeCompare(b.bundle);
    });
}

const NEXUS_SEARCH_MAX_RESULTS = 20;

function buildNexusSearchString(prop) {
    const schema = (prop.schema && typeof prop.schema === 'object') ? prop.schema : {};
    const fullKey = prop.fullKey || '';
    const parts = fullKey.split('.');
    const vendor = prop.vendor || parts[2] || '';
    const bundle = prop.bundle || parts[3] || '';
    const skill = prop.skill || (parts.length > 4 ? parts[parts.length - 2] : '') || '';
    const param = prop.param || parts[parts.length - 1] || '';
    const title = schema.title || prop.title || '';
    const description = schema.description || prop.description || '';

    return [fullKey, vendor, bundle, skill, param, title, description]
        .join(' ')
        .toLowerCase()
        .trim();
}

function renderNexusParam(prop, backendConfig) {
    const schema = (prop.schema && typeof prop.schema === 'object') ? prop.schema : {};
    const effectiveType = schema.type || prop.value_type || 'string';
    if (prop.value_type === 'null' || effectiveType === 'null') return '';

    const fullKey = prop.fullKey;
    const current = getNested(backendConfig, fullKey);
    const defaultVal = schema.default !== undefined ? schema.default : null;
    const currentValue = current !== undefined ? current : defaultVal;

    const inputId = 'nexus-' + fullKey.replace(/\./g, '-');
    const defJson = encodeURIComponent(JSON.stringify(defaultVal));
    const schemaJson = encodeURIComponent(JSON.stringify(schema || {}));
    const isModified = isNexusParamModified(prop, backendConfig);
    const resetBtn = `<button type="button" class="nexus-reset-btn" data-full-key="${fullKey}" data-default="${defJson}" data-value-type="${effectiveType}" data-schema="${schemaJson}" title="Reset to default" ${isModified ? '' : 'disabled'}>↺ Reset</button>`;

    // --- NEW: derive title and long description ---
    const title = String(schema.title || prop.title || prop.param || fullKey);
    const longDescription = String(schema.description || prop.description || '');
    const titleEncoded = encodeURIComponent(title);
    const descriptionEncoded = encodeURIComponent(longDescription);
    const infoButton = longDescription
        ? `<button type="button" class="nexus-info-btn" aria-label="More information about ${escapeHtml(title)}" data-nexus-title="${titleEncoded}" data-nexus-description="${descriptionEncoded}">ⓘ</button>`
        : '';
    // ------------------------------------------------

    let controlHtml = '';

    if (Array.isArray(schema.enum)) {
        const currentInEnum = schema.enum.some(opt => deepEqual(opt, currentValue));
        const customOption = (!currentInEnum && currentValue !== undefined && currentValue !== null)
            ? `<option value="${escapeHtml(currentValue)}" selected>${escapeHtml(currentValue)} (custom)</option>`
            : '';
        const options = schema.enum.map(opt => {
            const selected = deepEqual(opt, currentValue) ? 'selected' : '';
            return `<option value="${escapeHtml(opt)}" ${selected}>${escapeHtml(opt)}</option>`;
        }).join('');

        controlHtml = `<select id="${inputId}" class="nexus-param-input" data-full-key="${fullKey}" data-param="${prop.param}" data-value-type="${effectiveType}" data-default="${defJson}" data-schema="${schemaJson}">${customOption}${options}</select>`;
    } else if (effectiveType === 'boolean') {
        const isTrue = currentValue === true;
        controlHtml = `<select id="${inputId}" class="nexus-param-input" data-full-key="${fullKey}" data-param="${prop.param}" data-value-type="boolean" data-default="${defJson}" data-schema="${schemaJson}">
            <option value="true" ${isTrue ? 'selected' : ''}>True</option>
            <option value="false" ${!isTrue ? 'selected' : ''}>False</option>
        </select>`;
    } else if (effectiveType === 'integer' || effectiveType === 'number') {
        const isInteger = effectiveType === 'integer';
        const step = isInteger ? '1' : (schema.multipleOf !== undefined ? schema.multipleOf : 'any');
        const minAttr = schema.minimum !== undefined ? ` min="${schema.minimum}"` : '';
        const maxAttr = schema.maximum !== undefined ? ` max="${schema.maximum}"` : '';
        const val = (currentValue !== undefined && currentValue !== null) ? currentValue : '';
        controlHtml = `<input type="number" step="${step}" id="${inputId}" class="nexus-param-input" data-full-key="${fullKey}" data-param="${prop.param}" data-value-type="${effectiveType}" data-default="${defJson}" data-schema="${schemaJson}"${minAttr}${maxAttr} value="${escapeHtml(val)}">`;
    } else if (effectiveType === 'array' || effectiveType === 'object') {
        let textVal = '';
        if (currentValue !== undefined && currentValue !== null) {
            try { textVal = JSON.stringify(currentValue, null, 2); } catch (e) { textVal = ''; }
        }
        controlHtml = `<textarea id="${inputId}" class="nexus-param-input" data-full-key="${fullKey}" data-param="${prop.param}" data-value-type="${effectiveType}" data-default="${defJson}" data-schema="${schemaJson}">${escapeHtml(textVal)}</textarea>`;
    } else {
        const val = (typeof currentValue === 'string' || typeof currentValue === 'number') ? currentValue : '';
        const patternAttr = schema.pattern ? ` pattern="${escapeHtml(schema.pattern)}"` : '';
        controlHtml = `<input type="text" id="${inputId}" class="nexus-param-input" data-full-key="${fullKey}" data-param="${prop.param}" data-value-type="string" data-default="${defJson}" data-schema="${schemaJson}"${patternAttr} value="${escapeHtml(val)}">`;
    }

    controlHtml = controlHtml.replace(/\sdisabled(?=[\s>])/g, '');
    const searchString = buildNexusSearchString(prop);

    return `
        <div class="nexus-param-item${isModified ? ' modified' : ''}" data-full-key="${fullKey}" data-search="${escapeHtml(searchString)}">
            <label for="${inputId}">${escapeHtml(prop.param || fullKey)}</label>
            <div class="param-desc">
                ${escapeHtml(title)}
                ${infoButton}
            </div>
            <div class="nexus-param-control">
                ${controlHtml}
                ${resetBtn}
            </div>
        </div>
    `;
}

function getParamDomain(param) {
    if (!param) return 'General';
    const dotIndex = param.indexOf('.');
    if (dotIndex === -1) return 'General';
    const domain = param.slice(0, dotIndex).trim();
    return domain || 'General';
}

function groupNexusParamsByDomain(params) {
    const groups = {};
    for (const pd of params) {
        const domain = getParamDomain(pd.param);
        if (!groups[domain]) groups[domain] = [];
        groups[domain].push(pd);
    }

    const sortedGroups = {};
    const sortedKeys = Object.keys(groups).sort((a, b) => a.localeCompare(b));
    for (const key of sortedKeys) {
        sortedGroups[key] = groups[key].sort((a, b) =>
            String(a.param || a.fullKey).localeCompare(String(b.param || b.fullKey))
        );
    }
    return sortedGroups;
}

function formatNexusSkillLabel(skillName) {
    if (!skillName) return '';
    const fullLabel = escapeHtml(skillName);
    const parts = String(skillName).split('_');

    // Expecting: <vendor>_<app>_<domain>_<skill>
    if (parts.length < 4) return fullLabel;

    const domain = parts.slice(2, -1).join('_');
    const skill = parts[parts.length - 1];

    const pretty = (str) => str
        .split('_')
        .map(w => w.charAt(0).toUpperCase() + w.slice(1))
        .join(' ');

    const prettyDomain = domain ? pretty(domain) : '';
    const prettySkill = skill ? pretty(skill) : '';

    return `${prettyDomain}/${prettySkill} <span style="color:#888; font-weight:normal;">(${fullLabel})</span>`;
}

function formatNexusPropertySummary(count, modifiedCount) {
    const propText = `${count} propert${count === 1 ? 'y' : 'ies'}`;
    const modText = modifiedCount > 0
        ? ` / ${modifiedCount} modification${modifiedCount === 1 ? '' : 's'}`
        : '';
    return propText + modText;
}

function updateNexusSectionSummary(detailsEl) {
    if (!detailsEl) return;
    const desc = detailsEl.querySelector('.nexus-skill-desc');
    if (!desc) return;
    const total = detailsEl.querySelectorAll('.nexus-param-item').length;
    const modified = detailsEl.querySelectorAll('.nexus-param-item.modified').length;
    desc.textContent = formatNexusPropertySummary(total, modified);
}

function generateNexusUI(properties, backendConfig, nexusApps) {
    const apps = groupNexusApps(properties);
    const appState = new Map(
        (nexusApps || []).map(a => [`${a.vendor}/${a.app}`, a])
    );

    const nexusStyles = `
        <style>
            .nexus-domain-card {
                border: 1px solid #e0e0e0;
                border-radius: 6px;
                margin-bottom: 12px;
                background: #fff;
                overflow: hidden;
                grid-column: 1 / -1;
            }
            .nexus-domain-title {
                padding: 8px 12px;
                font-size: 0.9em;
                font-weight: bold;
                background: #f5f5f5;
                border-bottom: 1px solid #e0e0e0;
                text-transform: capitalize;
            }
            .nexus-domain-params {
                display: grid;
                grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
                gap: 15px;
                padding: 15px;
            }
            .nexus-app-skills {
                display: flex;
                flex-direction: column;
                gap: 10px;
            }
            .nexus-reset-btn:disabled {
                color: #999;
                cursor: default;
                text-decoration: none;
            }
            .nexus-param-item.modified {
                background-color: #fff9db;
                border-radius: 4px;
            }
            .nexus-info-btn {
                border: none;
                background: none;
                color: #007bff;
                cursor: help;
                font-size: 0.9em;
                padding: 0;
                margin-left: 4px;
                line-height: 1;
            }

            .nexus-desc-modal-backdrop {
                position: fixed;
                inset: 0;
                background: rgba(0, 0, 0, 0.35);
                display: flex;
                align-items: center;
                justify-content: center;
                z-index: 10000;
            }

            .nexus-desc-modal {
                position: relative;
                background: #fff;
                border-radius: 8px;
                padding: 16px;
                max-width: 560px;
                width: calc(100% - 32px);
                max-height: 80vh;
                overflow: auto;
                box-shadow: 0 10px 30px rgba(0, 0, 0, 0.3);
            }

            .nexus-desc-modal-close {
                position: absolute;
                top: 8px;
                right: 12px;
                border: none;
                background: none;
                font-size: 22px;
                cursor: pointer;
            }

            .nexus-desc-modal h4 {
                margin: 0 24px 8px 0;
            }

            .nexus-desc-modal-body {
                white-space: pre-wrap;
                line-height: 1.5;
                overflow-wrap: anywhere;
                color: #333;
            }

            /* Nexus properties search */
            .nexus-search-container {
                margin-bottom: 15px;
                padding: 12px;
                background-color: #f8f9fa;
                border-radius: 8px;
            }

            #nexus-search-input {
                width: 100%;
                padding: 10px 12px;
                border: 1px solid #ddd;
                border-radius: 6px;
                font-size: 14px;
                background-color: #fff;
                box-sizing: border-box;
                transition: border-color 0.2s, box-shadow 0.2s;
            }

            #nexus-search-input:focus {
                outline: none;
                border-color: #007bff;
                box-shadow: 0 0 0 3px rgba(0, 123, 255, 0.2);
            }

            #nexus-search-status {
                margin-top: 8px;
                font-size: 0.9em;
                color: #6c757d;
            }

            #nexus-search-status.too-many {
                color: #dc3545;
                font-weight: bold;
            }
            .nexus-search-options {
                margin-top: 8px;
                font-size: 0.88em;
            }
            .nexus-search-options label {
                display: inline-flex;
                align-items: center;
                gap: 6px;
                cursor: pointer;
                color: #555;
                user-select: none;
            }

            /* Nexus subscriptions & install (Stage C) */
            .nexus-add-box {
                border: 1px solid #d0e0ff;
                background: #f5f9ff;
                border-radius: 8px;
                padding: 12px 15px;
                margin-bottom: 20px;
            }
            .nexus-resolve-error {
                margin-top: 10px;
                color: #dc3545;
                font-size: 0.9em;
            }
            .nexus-remote-card {
                margin-top: 12px;
                border: 1px solid #e0e0e0;
                border-radius: 8px;
                padding: 12px;
                background: #fff;
            }
            .nexus-remote-desc {
                font-size: 0.9em;
                color: #555;
                margin: 8px 0;
            }
            .nexus-app-state { margin: 8px 0 12px 0; }
            .nexus-app-badges .nexus-badge {
                display: inline-block;
                padding: 2px 8px;
                border-radius: 10px;
                font-size: 0.78em;
                background: #eee;
                color: #555;
                margin-right: 6px;
            }
            .nexus-badge-ok { background: #e6f6e6 !important; color: #1a7a1a !important; }
            .nexus-badge-warn { background: #fff3e0 !important; color: #9a6200 !important; }
            .nexus-badge-code { font-family: monospace; letter-spacing: 1px; }
            .nexus-trust { font-size: 0.82em; color: #666; margin: 6px 0; }
            .nexus-trust-label { color: #999; }
            .nexus-addr { font-family: monospace; }
            .nexus-explorer-link { font-size: 0.95em; }
            .nexus-app-actions { margin-top: 8px; display: flex; gap: 8px; flex-wrap: wrap; }
            .nexus-app-actions button {
                padding: 6px 12px;
                border: 1px solid #ccc;
                border-radius: 6px;
                background: #fff;
                cursor: pointer;
                font-size: 0.85em;
            }
            .nexus-app-actions button:hover:not(:disabled) { background: #f2f6ff; border-color: #99b8e8; }
            .nexus-app-actions button:disabled { opacity: 0.5; cursor: default; }
            .nexus-app-status { margin-top: 6px; font-size: 0.85em; }
            .nexus-app-status .success-message { color: #1a7a1a; }
            .nexus-app-status .error-message { color: #dc3545; }
            .nexus-app-status .info-message { color: #555; }
        </style>
    `;

    const appsHtml = apps.map(app => {
        const parts = [];
        const state = appState.get(`${app.vendor}/${app.bundle}`);

        // Shared properties section
        if (app.shared.length > 0) {
            const sharedGroups = groupNexusSharedParams(app.shared);
            const sharedHtml = Object.entries(sharedGroups).map(([moduleName, params]) => `
                <div class="nexus-domain-card">
                    <div class="nexus-domain-title">${escapeHtml(moduleName)}</div>
                    <div class="nexus-domain-params">
                        ${params.map(prop => renderNexusParam(prop, backendConfig)).join('')}
                    </div>
                </div>
            `).join('');

            const sharedModifiedCount = countNexusModifiedParams(app.shared, backendConfig);
            parts.push(`
                <details class="nexus-skill">
                    <summary>
                        <strong>Shared Properties</strong>
                        <span class="nexus-skill-desc">${formatNexusPropertySummary(app.shared.length, sharedModifiedCount)}</span>
                    </summary>
                    <div class="nexus-skill-params">${sharedHtml}</div>
                </details>
            `);
        }

        // Skill-specific sections
        const skillsHtml = Array.from(app.skills.entries())
            .sort((a, b) => a[0].localeCompare(b[0]))
            .map(([skillName, params]) => {
            const validParams = params.filter(prop => prop.value_type !== 'null');
            if (validParams.length === 0) return '';

            const skillModifiedCount = countNexusModifiedParams(validParams, backendConfig);
            const domains = groupNexusParamsByDomain(validParams);
            const paramsHtml = Object.entries(domains).map(([domain, domainParams]) => `
                <div class="nexus-domain-card">
                    <div class="nexus-domain-title">${escapeHtml(domain)}</div>
                    <div class="nexus-domain-params">
                        ${domainParams.map(prop => renderNexusParam(prop, backendConfig)).join('')}
                    </div>
                </div>
            `).join('');

            return `
                <details class="nexus-skill">
                    <summary>
                        <strong>${formatNexusSkillLabel(skillName)}</strong>
                        <span class="nexus-skill-desc">${formatNexusPropertySummary(validParams.length, skillModifiedCount)}</span>
                    </summary>
                    <div class="nexus-skill-params">${paramsHtml}</div>
                </details>
            `;
        }).join('');

        if (skillsHtml) parts.push(skillsHtml);
        if (parts.length === 0) parts.push('<p style="color:#888;font-size:0.9em;">No configurable properties.</p>');

        return `
            <div class="nexus-app" data-vendor="${app.vendor}" data-bundle="${app.bundle}">
                <h4>${escapeHtml(capitalize(app.bundle))} <span style="font-weight:normal;color:#888;">(${escapeHtml(capitalize(app.vendor))})</span></h4>
                ${renderNexusAppHeader(state)}
                <div class="nexus-app-skills">${parts.join('')}</div>
                <button type="button" class="nexus-reset-all-btn" data-vendor="${app.vendor}" data-bundle="${app.bundle}">Reset all properties in this Nexus App</button>
            </div>
        `;
    }).join('');

    return `
        ${nexusStyles}
        ${renderNexusAddBox()}
        <div class="nexus-search-container">
            <input
                type="search"
                id="nexus-search-input"
                placeholder="Search properties…"
                autocomplete="off"
            >
            <div id="nexus-search-status"></div>
            <div class="nexus-search-options">
                <label><input type="checkbox" id="nexus-modified-toggle"> Show only modified properties</label>
            </div>
        </div>
        <div class="nexus-apps-list">${appsHtml || ''}</div>
    `;
}

// ---------------------------------------------------------------------
// Nexus subscriptions & install (Stage C)
// ---------------------------------------------------------------------

function nexusExplorerLinks(state) {
    if (!state) return '';
    const links = [];
    if (state.creatorId) {
        links.push(
            `<span class="nexus-trust-label">creator</span> ` +
            `<span class="nexus-addr" title="${escapeHtml(state.creatorId)}">${escapeHtml(shortAddr(state.creatorId))}</span>` +
            ` <a href="#" class="nexus-explorer-link" data-kind="account" data-addr="${escapeHtml(state.creatorId)}">view on explorer</a>`
        );
    }
    if (state.collection) {
        links.push(
            `<span class="nexus-trust-label">NFT collection</span> ` +
            `<span class="nexus-addr" title="${escapeHtml(state.collection)}">${escapeHtml(shortAddr(state.collection))}</span>` +
            ` <a href="#" class="nexus-explorer-link" data-kind="token" data-addr="${escapeHtml(state.collection)}">view on explorer</a>`
        );
    }
    return links.length ? `<div class="nexus-trust">${links.join('<br>')}</div>` : '';
}

function shortAddr(addr) {
    return addr.length > 14 ? `${addr.slice(0, 6)}…${addr.slice(-4)}` : addr;
}

function renderNexusAppHeader(state) {
    if (!state) return '';
    const bits = [];
    bits.push(`<span class="nexus-meta">v${escapeHtml(state.version || '?')} · ${escapeHtml(state.source || 'installed')}</span>`);

    if (state.gated) {
        const sub = state.subscription || {};
        if (sub.subscribed) {
            bits.push(`<span class="nexus-badge nexus-badge-ok" title="Continuous access while your NFT is held — verified on-chain periodically, no action needed">NFT validated</span>`);
            if (sub.code) bits.push(`<span class="nexus-badge nexus-badge-code" title="Subscription receipt">${escapeHtml(sub.code)}</span>`);
        } else {
            const reasons = {
                no_subscription: 'NFT ownership required — verify your wallet',
                tampered_or_invalid: 'Verification invalid — verify your wallet again',
                licensing_unavailable: 'Licensing backend unavailable',
                invalid_identity: 'Invalid bundle identity',
            };
            bits.push(`<span class="nexus-badge nexus-badge-warn">${escapeHtml(reasons[sub.reason] || 'NFT ownership required')}</span>`);
        }
    } else {
        bits.push('<span class="nexus-badge">Open app</span>');
    }

    if (state.identity_verified) {
        bits.push('<span class="nexus-badge nexus-badge-ok" title="Manifest signed by the creator\'s Solana key">Verified author</span>');
    } else {
        bits.push(`<span class="nexus-badge nexus-badge-warn" title="${escapeHtml(state.identity_reason || '')}">Unverified author</span>`);
    }

    const actions = [];
    if (state.gated && !(state.subscription && state.subscription.subscribed)) {
        actions.push(`<button type="button" class="nexus-subscribe-btn" data-vendor="${escapeHtml(state.vendor)}" data-app="${escapeHtml(state.app)}">Verify wallet</button>`);
    }
    actions.push(`<button type="button" class="nexus-uninstall-btn" data-vendor="${escapeHtml(state.vendor)}" data-app="${escapeHtml(state.app)}">Uninstall</button>`);

    return `
        <div class="nexus-app-state">
            <div class="nexus-app-badges">${bits.join(' ')}</div>
            ${nexusExplorerLinks(state)}
            <div class="nexus-app-actions">${actions.join(' ')}</div>
            <div class="nexus-app-status"></div>
        </div>
    `;
}

function renderNexusAddBox() {
    return `
        <div class="nexus-add-box">
            <h4 style="margin:0 0 6px 0;">Add a Nexus App</h4>
            <p style="margin:0 0 10px 0;font-size:0.9em;color:#666;">
                Enter the app name or address (e.g. <code>myapp</code> or <code>myapp.nexus</code>).
            </p>
            <div style="display:flex;gap:8px;">
                <input type="text" id="nexus-add-input" placeholder="myapp" autocomplete="off" style="flex:1;padding:8px 10px;border:1px solid #ddd;border-radius:6px;">
                <button type="button" id="nexus-add-btn" class="btn">Find app</button>
            </div>
            <div id="nexus-resolve-result"></div>
        </div>
    `;
}

function renderNexusRemoteCard(s) {
    if (!s || s.ok === false) {
        return `<div class="nexus-resolve-error">${escapeHtml((s && s.message) || 'Lookup failed.')}</div>`;
    }
    const bits = [];
    bits.push(`<strong>${escapeHtml(capitalize(s.app))}</strong> <span style="color:#888;">(${escapeHtml(capitalize(s.vendor))})</span>`);
    bits.push(`<span class="nexus-badge">v${escapeHtml(s.latest)}</span>`);
    if (s.gated) {
        bits.push('<span class="nexus-badge nexus-badge-warn">Requires NFT ownership</span>');
        const sub = s.subscription || {};
        if (sub.subscribed) bits.push('<span class="nexus-badge nexus-badge-ok">NFT validated</span>');
    } else {
        bits.push('<span class="nexus-badge">Open app</span>');
    }
    if (s.installed_version) {
        const upToDate = compareVersions(s.latest, s.installed_version) <= 0;
        bits.push(`<span class="nexus-badge ${upToDate ? 'nexus-badge-ok' : 'nexus-badge-warn'}">installed v${escapeHtml(s.installed_version)}${upToDate ? ' (up to date)' : ''}</span>`);
    }

    const actions = [];
    const actionLabel = !s.installed_version ? 'Install' : (compareVersions(s.latest, s.installed_version) > 0 ? `Update to v${escapeHtml(s.latest)}` : 'Reinstall');
    actions.push(`<button type="button" class="nexus-install-btn" data-source="${escapeHtml(s.source_host || '')}">${actionLabel}</button>`);

    return `
        <div class="nexus-remote-card" data-source="${escapeHtml(s.source_host || '')}">
            <div class="nexus-app-badges">${bits.join(' ')}</div>
            ${s.gated ? '<div class="nexus-remote-desc">NFT ownership (verified on-chain) is required to install this app and to keep it running. Verify with your wallet below if needed.</div>' : ''}
            ${s.description ? `<div class="nexus-remote-desc">${escapeHtml(s.description)}</div>` : ''}
            ${nexusExplorerLinks({ creatorId: s.creatorId, collection: s.collection })}
            <div class="nexus-app-actions">${actions.join(' ')}</div>
            <div class="nexus-app-status"></div>
        </div>
    `;
}

function compareVersions(a, b) {
    const pa = String(a || '').split(/[.\-+]/).map(x => parseInt(x, 10) || 0);
    const pb = String(b || '').split(/[.\-+]/).map(x => parseInt(x, 10) || 0);
    for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
        const d = (pa[i] || 0) - (pb[i] || 0);
        if (d !== 0) return d;
    }
    return 0;
}

function setupTabListeners() {
    document.querySelectorAll('.skills-tab').forEach(tab => {
        tab.addEventListener('click', () => {
            document.querySelectorAll('.skills-tab').forEach(t => t.classList.remove('active'));
            document.querySelectorAll('.skills-tab-content').forEach(c => c.classList.remove('active'));
            tab.classList.add('active');
            const content = document.querySelector(`.skills-tab-content[data-tab-content="${tab.dataset.tab}"]`);
            if (content) content.classList.add('active');
        });
    });
}

function resetNexusSearchVisibility() {
    document.querySelectorAll('.nexus-param-item').forEach(item => { item.style.display = ''; });
    document.querySelectorAll('.nexus-domain-card, details.nexus-skill, .nexus-app').forEach(el => { el.style.display = ''; });
    updateNexusSkillSummaries();
}

function refreshNexusContainerVisibility() {
    document.querySelectorAll('.nexus-domain-card').forEach(card => {
        const hasVisibleItem = Array.from(card.querySelectorAll('.nexus-param-item'))
            .some(item => item.style.display !== 'none');
        card.style.display = hasVisibleItem ? '' : 'none';
    });

    document.querySelectorAll('details.nexus-skill').forEach(details => {
        const hasVisibleCard = details.querySelector('.nexus-domain-card') &&
            Array.from(details.querySelectorAll('.nexus-domain-card'))
                .some(card => card.style.display !== 'none');
        details.style.display = hasVisibleCard ? '' : 'none';
    });

    document.querySelectorAll('.nexus-app').forEach(app => {
        const hasVisibleDetails = Array.from(app.querySelectorAll('details.nexus-skill'))
            .some(details => details.style.display !== 'none');
        app.style.display = hasVisibleDetails ? '' : 'none';
    });
}

function updateNexusSkillSummaries() {
    document.querySelectorAll('details.nexus-skill').forEach(details => {
        const visibleItems = Array.from(details.querySelectorAll('.nexus-param-item'))
            .filter(item => item.style.display !== 'none');
        const visibleModified = visibleItems.filter(item => item.classList.contains('modified')).length;
        const desc = details.querySelector('.nexus-skill-desc');
        if (desc) {
            desc.textContent = formatNexusPropertySummary(visibleItems.length, visibleModified);
        }
    });
}

function setupNexusListeners(ctx) {
    document.querySelectorAll('.nexus-param-input').forEach(input => {
        const markDirty = () => {
            updateNexusParamState(input);
            const detailsEl = input.closest('details.nexus-skill');
            if (detailsEl) updateNexusSectionSummary(detailsEl);
            ctx.modifiedFields.skills.add('nexus');
            updateSkillsNextButtonState(ctx);
        };
        input.addEventListener('change', markDirty);
        if (input.tagName === 'INPUT' && ['text', 'number'].includes(input.type)) {
            input.addEventListener('input', markDirty);
        }
        if (input.tagName === 'TEXTAREA') {
            input.addEventListener('input', markDirty);
        }
    });

    document.querySelectorAll('.nexus-reset-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const fullKey = btn.dataset.fullKey;
            const input = document.querySelector(`.nexus-param-input[data-full-key="${fullKey}"]`);
            if (!input) return;
            const defaultVal = JSON.parse(decodeURIComponent(btn.dataset.default || 'null'));
            setNexusInputValue(input, defaultVal, btn.dataset.valueType);
            updateNexusParamState(input);
            const detailsEl = input.closest('details.nexus-skill');
            if (detailsEl) updateNexusSectionSummary(detailsEl);
            ctx.modifiedFields.skills.add('nexus');
            updateSkillsNextButtonState(ctx);
        });
    });

    document.querySelectorAll('.nexus-reset-all-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const appEl = btn.closest('.nexus-app');
            if (!appEl) return;
            const appName = `${appEl.dataset.bundle} (${appEl.dataset.vendor})`;
            if (!confirm(`Reset all settings in ${appName} to their default values? This cannot be undone.`)) return;

            appEl.querySelectorAll('.nexus-param-input').forEach(input => {
                const defaultVal = JSON.parse(decodeURIComponent(input.dataset.default || 'null'));
                setNexusInputValue(input, defaultVal, input.dataset.valueType);
                updateNexusParamState(input);
            });

            appEl.querySelectorAll('details.nexus-skill').forEach(detailsEl => {
                updateNexusSectionSummary(detailsEl);
            });

            ctx.modifiedFields.skills.add('nexus');
            updateSkillsNextButtonState(ctx);
            alert(`All settings in ${appName} have been reset to defaults.`);
        });
    });

    document.querySelectorAll('.nexus-info-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            showNexusDescriptionModal(btn);
        });
    });

    const searchInput = document.getElementById('nexus-search-input');
    if (searchInput) {
        const modifiedToggle = document.getElementById('nexus-modified-toggle');

        const applyNexusFilters = () => {
            const rawQuery = searchInput.value.trim();
            const query = rawQuery.toLowerCase();
            const statusEl = document.getElementById('nexus-search-status');
            const allItems = Array.from(document.querySelectorAll('.nexus-param-item'));
            const onlyModified = !!(modifiedToggle && modifiedToggle.checked);

            // Nothing active: show everything again
            if (!query && !onlyModified) {
                resetNexusSearchVisibility();
                if (statusEl) { statusEl.textContent = ''; statusEl.classList.remove('too-many'); }
                return;
            }

            const tokens = query.split(/\s+/).filter(Boolean);
            let matchCount = 0;

            allItems.forEach(item => {
                const haystack = (item.dataset.search || '').toLowerCase();
                const matchesSearch = tokens.every(token => haystack.includes(token));
                const visible = matchesSearch && (!onlyModified || item.classList.contains('modified'));
                item.style.display = visible ? '' : 'none';
                if (visible) matchCount++;
            });

            if (query && matchCount > NEXUS_SEARCH_MAX_RESULTS) {
                // Too many matches: hide everything and ask the user to narrow down
                allItems.forEach(item => { item.style.display = 'none'; });
                if (statusEl) {
                    statusEl.textContent = `Too many results (${matchCount}). Please add more keywords to narrow the search.`;
                    statusEl.classList.add('too-many');
                }
            } else {
                if (statusEl) {
                    statusEl.textContent = matchCount === 0
                        ? 'No matching properties.'
                        : `${matchCount} result${matchCount === 1 ? '' : 's'}`;
                    statusEl.classList.remove('too-many');
                }
            }

            updateNexusSkillSummaries();
            refreshNexusContainerVisibility();
        };

        searchInput.addEventListener('input', applyNexusFilters);
        if (modifiedToggle) modifiedToggle.addEventListener('change', applyNexusFilters);
    }

    setupNexusLifecycleListeners(ctx);
}

// ---------------------------------------------------------------------
// Nexus subscriptions & install — lifecycle listeners (Stage C)
// ---------------------------------------------------------------------

let nexusLifecycleDelegationInstalled = false;

function setupNexusLifecycleListeners(ctx) {
    const pybridgeUrl = ctx.config.get('pybridge.api_url');
    const openExternal = (url) => ctx.ipcRenderer.send('open-external', url);

    const resolveSource = async (source) => {
        const resp = await fetch(pybridgeUrl + '/nexus/install/resolve', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ source })
        });
        const data = await resp.json();
        if (!resp.ok) data.ok = false;
        return data;
    };

    const portalUrl = (s, installed) => {
        const params = new URLSearchParams({ app: `${s.vendor}/${s.app}` });
        if (!installed) {
            if (s.collection) params.set('collection', s.collection);
            if (s.creatorId) params.set('creator', s.creatorId);
            if (s.latest) params.set('version', s.latest);
        }
        return `${pybridgeUrl}/nexus/subscription/portal?${params.toString()}`;
    };

    const setStatus = (container, text, cls) => {
        const el = container && container.querySelector('.nexus-app-status');
        if (el) { el.textContent = text || ''; el.className = `nexus-app-status ${cls || ''}`; }
    };

    const refreshUI = () => generateSkillsUI(ctx);

    // Event delegation (survives re-renders); registered once per window
    if (!nexusLifecycleDelegationInstalled) {
        nexusLifecycleDelegationInstalled = true;

        document.addEventListener('click', async (e) => {
            // Explorer links (creator / collection)
            const explorer = e.target.closest('.nexus-explorer-link');
            if (explorer) {
                e.preventDefault();
                const kind = explorer.dataset.kind === 'token' ? 'token' : 'account';
                openExternal(`https://solscan.io/${kind}/${explorer.dataset.addr}`);
                return;
            }

            // Verify wallet (installed app, lapsed): portal reads the
            // local manifest; on success the card flips back to active
            const subBtn = e.target.closest('.nexus-subscribe-btn');
            if (subBtn) {
                const vendor = subBtn.dataset.vendor, app = subBtn.dataset.app;
                const container = subBtn.closest('.nexus-app-state');
                openExternal(portalUrl({ vendor, app }, true));
                setStatus(container, 'Waiting for wallet verification (complete the sign in your browser)…', 'info-message');
                const started = Date.now();
                const timer = setInterval(async () => {
                    if (Date.now() - started > 180000) {
                        clearInterval(timer);
                        setStatus(container, 'Verification timed out — try again.', 'error-message');
                        return;
                    }
                    try {
                        const resp = await fetch(pybridgeUrl + '/nexus/apps');
                        const apps = await resp.json();
                        const st = (apps || []).find(
                            a => a.vendor === vendor && a.app === app
                        );
                        if (st && st.subscription && st.subscription.subscribed) {
                            clearInterval(timer);
                            setStatus(container, 'Subscription active!', 'success-message');
                            setTimeout(refreshUI, 800);
                        }
                    } catch (err) { /* keep polling */ }
                }, 2000);
                return;
            }

            // Uninstall: remove the app; the NFT and subscription state
            // remain (a reinstall does not need to re-subscribe)
            const unsubBtn = e.target.closest('.nexus-uninstall-btn');
            if (unsubBtn) {
                const vendor = unsubBtn.dataset.vendor, app = unsubBtn.dataset.app;
                if (!confirm(`Uninstall ${vendor}/${app}? Your NFT and subscription remain valid — reinstalling later won't require verifying again.`)) return;
                try {
                    const resp = await fetch(`${pybridgeUrl}/nexus/app/${vendor}/${app}`, { method: 'DELETE' });
                    const data = await resp.json();
                    if (!data.ok) {
                        alert('Uninstall failed: ' + (data.message || 'unknown error'));
                        return;
                    }
                    // Mirror the install flow: reload Orakle so the app's
                    // skills/properties disappear, then refresh the step
                    const orakleUrl = ctx.config.get('orakle.api_url');
                    setStatus(unsubBtn.closest('.nexus-app').querySelector('.nexus-app-state') || unsubBtn.parentElement,
                        'Uninstalled. Reloading…', 'info-message');
                    ctx.ipcRenderer.send('nexus:reload-orakle');
                    const started = Date.now();
                    const timer = setInterval(async () => {
                        if (Date.now() - started > 180000) { clearInterval(timer); refreshUI(); return; }
                        try {
                            const props = await fetch(orakleUrl + '/capabilities?view=properties').then(r => r.json());
                            if (!Object.keys(props || {}).some(k => k.includes(`.nexus.${vendor}.${app}`))) {
                                clearInterval(timer);
                                refreshUI();
                            }
                        } catch (err) { /* keep polling */ }
                    }, 2000);
                } catch (err) {
                    alert('Uninstall failed: ' + err.message);
                }
                return;
            }

            // Install / Update / Reinstall — subscribes first (portal +
            // poll) when the app is gated and the wallet isn't verified
            const installBtn = e.target.closest('.nexus-install-btn');
            if (installBtn && !installBtn.disabled) {
                const source = installBtn.dataset.source;
                const card = installBtn.closest('.nexus-remote-card');
                if (!source) return;
                installBtn.disabled = true;

                const waitForSubscription = (s) => new Promise((resolve) => {
                    setStatus(card, 'NFT ownership required — complete the wallet sign, the app will install automatically…', 'info-message');
                    const started = Date.now();
                    const timer = setInterval(async () => {
                        if (Date.now() - started > 300000) {
                            clearInterval(timer);
                            resolve(false);
                            return;
                        }
                        try {
                            const st = await resolveSource(source);
                            if (st.subscription && st.subscription.subscribed) {
                                clearInterval(timer);
                                resolve(true);
                            }
                        } catch (err) { /* keep polling */ }
                    }, 2000);
                });

                const waitForCapabilities = (vendor, app) => new Promise((resolve) => {
                    const orakleUrl = ctx.config.get('orakle.api_url');
                    const started = Date.now();
                    const timer = setInterval(async () => {
                        if (Date.now() - started > 180000) { clearInterval(timer); resolve(); return; }
                        try {
                            const props = await fetch(orakleUrl + '/capabilities?view=properties').then(r => r.json());
                            if (Object.keys(props || {}).some(k => k.includes(`.nexus.${vendor}.${app}`))) {
                                clearInterval(timer);
                                resolve();
                            }
                        } catch (err) { /* keep polling */ }
                    }, 2000);
                });

                (async () => {
                    try {
                        setStatus(card, 'Checking requirements…', 'info-message');
                        const s = await resolveSource(source);
                        if (s.ok === false) {
                            setStatus(card, s.message || 'Lookup failed.', 'error-message');
                            installBtn.disabled = false;
                            return;
                        }
                        const needsSubscribe = s.gated && !(s.subscription && s.subscription.subscribed);
                        if (needsSubscribe) {
                            openExternal(portalUrl(s, false));
                            const okSub = await waitForSubscription(s);
                            if (!okSub) {
                                setStatus(card, 'Subscription timed out — try again.', 'error-message');
                                installBtn.disabled = false;
                                return;
                            }
                        }
                        setStatus(card, 'Downloading and verifying…', 'info-message');
                        const resp = await fetch(pybridgeUrl + '/nexus/install', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ source })
                        });
                        const data = await resp.json();
                        if (data.ok) {
                            setStatus(card, `Installed ${data.vendor}/${data.app} v${data.version}. Reloading skills…`, 'success-message');
                            ctx.ipcRenderer.send('nexus:reload-orakle');
                            await waitForCapabilities(data.vendor, data.app);
                            refreshUI();
                        } else {
                            setStatus(card, data.message || 'Install failed.', 'error-message');
                            installBtn.disabled = false;
                        }
                    } catch (err) {
                        setStatus(card, 'Install failed: ' + err.message, 'error-message');
                        installBtn.disabled = false;
                    }
                })();
                return;
            }
        });
    }

    // Add box (per render)
    const addBtn = document.getElementById('nexus-add-btn');
    const addInput = document.getElementById('nexus-add-input');
    if (addBtn && addInput) {
        const doResolve = async () => {
            const source = addInput.value.trim();
            if (!source) return;
            const resultEl = document.getElementById('nexus-resolve-result');
            addBtn.disabled = true;
            resultEl.innerHTML = '<div class="info-message">Looking up…</div>';
            try {
                const s = await resolveSource(source);
                resultEl.innerHTML = renderNexusRemoteCard(s);
            } catch (err) {
                resultEl.innerHTML = `<div class="nexus-resolve-error">${escapeHtml(err.message)}</div>`;
            } finally {
                addBtn.disabled = false;
            }
        };
        addBtn.addEventListener('click', doResolve);
        addInput.addEventListener('keydown', (e) => { if (e.key === 'Enter') doResolve(); });
    }
}

function generateUserSkillsUI() {
    return `
        <div class="skill-category UserSkills">
            <h3>User Skills</h3>
            <p>Select a directory containing your own Python skills.</p>
            <div class="form-group">
                <label for="user-skills-directory">User Skills Directory:</label>
                <div style="display:flex; align-items:center; gap:10px;">
                    <input type="text" id="user-skills-directory" placeholder="e.g., ~/my_skills" style="flex:1;">
                    <button id="browse-user-skills-btn" class="btn btn-secondary">Browse…</button>
                </div>
                <p class="field-description">Leave empty to disable user skills.</p>
            </div>
        </div>
    `;
}

function setupUserSkillsListeners(ctx, backendConfig) {
    const userSkillsInput = document.getElementById('user-skills-directory');
    const browseUserSkillsBtn = document.getElementById('browse-user-skills-btn');

    if (userSkillsInput) {
        if (backendConfig?.user_skills?.directory) {
            userSkillsInput.value = backendConfig.user_skills.directory;
        }

        userSkillsInput.addEventListener('input', () => {
            ctx.modifiedFields.skills.add('user_skills');
            updateSkillsNextButtonState(ctx);
        });

        if (browseUserSkillsBtn) {
            browseUserSkillsBtn.addEventListener('click', async () => {
                try {
                    const result = await ctx.ipcRenderer.invoke('select-user-skills-directory');
                    if (result && !result.canceled && result.filePaths && result.filePaths[0]) {
                        userSkillsInput.value = result.filePaths[0];
                        ctx.modifiedFields.skills.add('user_skills');
                        updateSkillsNextButtonState(ctx);
                    }
                } catch (error) {
                    console.error('Error selecting user skills directory:', error);
                }
            });
        }
    }
}

function validateNexusValue(value, schema, label) {
    if (!schema || typeof schema !== 'object' || Object.keys(schema).length === 0) return null;

    if (Array.isArray(schema.anyOf)) {
        const anyValid = schema.anyOf.some(subSchema => !validateNexusValue(value, subSchema, label));
        if (!anyValid) return `Invalid value for ${label}: does not match any allowed schema.`;
    }

    const type = schema.type;
    if (type) {
        if (type === 'integer' && !Number.isInteger(value)) {
            return `Invalid value for ${label}: expected an integer.`;
        }
        if (type === 'number' && (typeof value !== 'number' || isNaN(value))) {
            return `Invalid value for ${label}: expected a number.`;
        }
        if (type === 'string' && typeof value !== 'string') {
            return `Invalid value for ${label}: expected a string.`;
        }
        if (type === 'boolean' && typeof value !== 'boolean') {
            return `Invalid value for ${label}: expected a boolean.`;
        }
        if (type === 'array' && !Array.isArray(value)) {
            return `Invalid value for ${label}: expected an array.`;
        }
        if (type === 'object' && (value === null || typeof value !== 'object' || Array.isArray(value))) {
            return `Invalid value for ${label}: expected an object.`;
        }
        if (type === 'null' && value !== null) {
            return `Invalid value for ${label}: expected null.`;
        }
    }

    if (value === null || value === undefined) return null;

    if (Array.isArray(schema.enum)) {
        const matches = schema.enum.some(opt => deepEqual(opt, value));
        if (!matches) {
            return `Invalid value for ${label}: must be one of ${schema.enum.map(v => JSON.stringify(v)).join(', ')}.`;
        }
    }

    if (typeof value === 'number') {
        if (schema.minimum !== undefined && value < schema.minimum) {
            return `Invalid value for ${label}: must be >= ${schema.minimum}.`;
        }
        if (schema.maximum !== undefined && value > schema.maximum) {
            return `Invalid value for ${label}: must be <= ${schema.maximum}.`;
        }
    }

    if (typeof value === 'string' && schema.pattern) {
        const re = new RegExp(schema.pattern);
        if (!re.test(value)) {
            return `Invalid value for ${label}: does not match pattern ${schema.pattern}.`;
        }
    }

    if (Array.isArray(value) && schema.items) {
        if (schema.minItems !== undefined && value.length < schema.minItems) {
            return `Invalid value for ${label}: must have at least ${schema.minItems} items.`;
        }
        if (schema.maxItems !== undefined && value.length > schema.maxItems) {
            return `Invalid value for ${label}: must have at most ${schema.maxItems} items.`;
        }
        for (let i = 0; i < value.length; i++) {
            const err = validateNexusValue(value[i], schema.items, `${label}[${i}]`);
            if (err) return err;
        }
    }

    if (value && typeof value === 'object' && !Array.isArray(value) && schema.properties) {
        if (Array.isArray(schema.required)) {
            for (const req of schema.required) {
                if (value[req] === undefined) {
                    return `Invalid value for ${label}: missing required property "${req}".`;
                }
            }
        }

        for (const [key, propSchema] of Object.entries(schema.properties)) {
            if (value[key] !== undefined) {
                const err = validateNexusValue(value[key], propSchema, `${label}.${key}`);
                if (err) return err;
            }
        }

        if (schema.additionalProperties === false) {
            const allowed = new Set(Object.keys(schema.properties || {}));
            for (const key of Object.keys(value)) {
                if (!allowed.has(key)) {
                    return `Invalid value for ${label}: unexpected property "${key}".`;
                }
            }
        }
    }

    return null;
}

function saveNexusConfig(ctx, backendConfig) {
    document.querySelectorAll('.nexus-param-input').forEach(input => {
        const fullKey = input.dataset.fullKey;
        const valueType = input.dataset.valueType;
        const rawValue = input.value.trim();
        const defaultRaw = decodeURIComponent(input.dataset.default || 'null');
        let defaultVal;
        try {
            defaultVal = JSON.parse(defaultRaw);
        } catch (e) {
            defaultVal = undefined;
        }

        if (rawValue === '') {
            deleteNested(backendConfig, fullKey);
            return;
        }

        let parsedValue;
        try {
            parsedValue = parseNexusValue(rawValue, valueType);
        } catch (e) {
            throw new Error(`Invalid value for ${input.dataset.param || fullKey}: ${e.message}`);
        }

        const schemaRaw = decodeURIComponent(input.dataset.schema || '{}');
        let schema = {};
        try {
            schema = JSON.parse(schemaRaw);
        } catch (e) {
            schema = {};
        }

        const validationError = validateNexusValue(parsedValue, schema, input.dataset.param || fullKey);
        if (validationError) {
            throw new Error(validationError);
        }

        if (deepEqual(parsedValue, defaultVal)) {
            deleteNested(backendConfig, fullKey);
        } else {
            setNested(backendConfig, fullKey, parsedValue);
        }
    });

    cleanupNexusConfig(backendConfig);
}
