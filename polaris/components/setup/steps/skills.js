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

        const scheduleHtml = generateScheduleUI(capabilities, backendConfig);
        const userSkillsHtml = generateUserSkillsUI();
        const nexusHtml = generateNexusUI(properties, backendConfig);   // <-- now uses properties

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

function generateNexusUI(properties, backendConfig) {
    const apps = groupNexusApps(properties);
    if (apps.length === 0) return '';

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
        </style>
    `;

    const appsHtml = apps.map(app => {
        const parts = [];

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
        if (parts.length === 0) return '';

        return `
            <div class="nexus-app" data-vendor="${app.vendor}" data-bundle="${app.bundle}">
                <h4>${escapeHtml(capitalize(app.bundle))} <span style="font-weight:normal;color:#888;">(${escapeHtml(capitalize(app.vendor))})</span></h4>
                <div class="nexus-app-skills">${parts.join('')}</div>
                <button type="button" class="nexus-reset-all-btn" data-vendor="${app.vendor}" data-bundle="${app.bundle}">Reset all properties in this Nexus App</button>
            </div>
        `;
    }).join('');

    return `
        ${nexusStyles}
        <div class="nexus-search-container">
            <input
                type="search"
                id="nexus-search-input"
                placeholder="Search properties…"
                autocomplete="off"
            >
            <div id="nexus-search-status"></div>
        </div>
        <div class="nexus-apps-list">${appsHtml}</div>
    `;
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
        searchInput.addEventListener('input', () => {
            const rawQuery = searchInput.value.trim();
            const query = rawQuery.toLowerCase();
            const statusEl = document.getElementById('nexus-search-status');
            const allItems = Array.from(document.querySelectorAll('.nexus-param-item'));

            // Clear search: show everything again
            if (!query) {
                resetNexusSearchVisibility();
                if (statusEl) statusEl.textContent = '';
                return;
            }

            const tokens = query.split(/\s+/).filter(Boolean);
            let matchCount = 0;

            allItems.forEach(item => {
                const haystack = (item.dataset.search || '').toLowerCase();
                const matches = tokens.every(token => haystack.includes(token));
                item.style.display = matches ? '' : 'none';
                if (matches) matchCount++;
            });

            if (matchCount > NEXUS_SEARCH_MAX_RESULTS) {
                // Too many matches: hide everything and ask the user to narrow down
                allItems.forEach(item => { item.style.display = 'none'; });
                if (statusEl) {
                    statusEl.textContent = `Too many results (${matchCount}). Please add more keywords to narrow the search.`;
                    statusEl.classList.add('too-many');
                }
            } else {
                if (statusEl) {
                    if (matchCount === 0) {
                        statusEl.textContent = 'No matching properties.';
                    } else {
                        statusEl.textContent = `${matchCount} result${matchCount === 1 ? '' : 's'}`;
                    }
                    statusEl.classList.remove('too-many');
                }
            }

            updateNexusSkillSummaries();
            refreshNexusContainerVisibility();
        });
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
