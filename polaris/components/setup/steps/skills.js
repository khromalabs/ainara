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
                .nexus-param-item { display: flex; flex-direction: column; }
                .nexus-param-item label { font-size: 0.85em; font-weight: bold; margin-bottom: 4px; }
                .nexus-param-item .param-desc { font-size: 0.8em; color: #666; margin-bottom: 6px; }
                .nexus-param-item input, .nexus-param-item select, .nexus-param-item textarea { padding: 6px; border: 1px solid #ddd; border-radius: 4px; font-size: 0.9em; width: 100%; box-sizing: border-box; }
                .nexus-param-item textarea { min-height: 80px; font-family: monospace; }
                .nexus-param-control { display: flex; align-items: center; gap: 6px; }
                .nexus-reset-btn { background: none; border: none; color: #007bff; cursor: pointer; font-size: 0.8em; padding: 2px 4px; white-space: nowrap; }
                .nexus-reset-btn:hover { text-decoration: underline; }
                .nexus-reset-all-btn { margin-top: 10px; font-size: 0.85em; color: #666; background: none; border: 1px solid #ccc; border-radius: 4px; padding: 5px 10px; cursor: pointer; }
                .nexus-reset-all-btn:hover { background: #f0f0f0; }
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

function groupNexusSharedParams(params) {
    const groups = {};
    for (const prop of params) {
        const moduleName = prop.module || 'General';
        if (!groups[moduleName]) groups[moduleName] = [];
        groups[moduleName].push(prop);
    }
    return groups;
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

function renderNexusParam(prop, backendConfig) {
    const schema = (prop.schema && typeof prop.schema === 'object') ? prop.schema : {};
    const effectiveType = schema.type || prop.value_type || 'string';
    if (prop.value_type === 'null' || effectiveType === 'null') return '';

    const fullKey = prop.fullKey;
    const current = getNested(backendConfig, fullKey);
    const currentValue = current !== undefined ? current : prop.default;

    const inputId = 'nexus-' + fullKey.replace(/\./g, '-');
    const defJson = encodeURIComponent(JSON.stringify(prop.default !== undefined ? prop.default : null));
    const schemaJson = encodeURIComponent(JSON.stringify(schema || {}));
    const resetBtn = `<button type="button" class="nexus-reset-btn" data-full-key="${fullKey}" data-default="${defJson}" data-value-type="${effectiveType}" data-schema="${schemaJson}" title="Reset to default">↺ Reset</button>`;

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

    return `
        <div class="nexus-param-item" data-full-key="${fullKey}">
            <label for="${inputId}">${escapeHtml(prop.param || fullKey)}</label>
            <div class="param-desc">${escapeHtml(prop.description || '')}</div>
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
    return groups;
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

            parts.push(`
                <details class="nexus-skill">
                    <summary>
                        <strong>Shared Properties</strong>
                        <span class="nexus-skill-desc">${app.shared.length} propert${app.shared.length === 1 ? 'y' : 'ies'}</span>
                    </summary>
                    <div class="nexus-skill-params">${sharedHtml}</div>
                </details>
            `);
        }

        // Skill-specific sections
        const skillsHtml = Array.from(app.skills.entries()).map(([skillName, params]) => {
            const validParams = params.filter(prop => prop.value_type !== 'null');
            if (validParams.length === 0) return '';

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
                        <span class="nexus-skill-desc">${validParams.length} propert${validParams.length === 1 ? 'y' : 'ies'}</span>
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
                <button type="button" class="nexus-reset-all-btn" data-vendor="${app.vendor}" data-bundle="${app.bundle}">Reset all settings in this app</button>
            </div>
        `;
    }).join('');

    return `${nexusStyles}<div class="nexus-apps-list">${appsHtml}</div>`;
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

function setupNexusListeners(ctx) {
    document.querySelectorAll('.nexus-param-input').forEach(input => {
        const markDirty = () => {
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
            ctx.modifiedFields.skills.add('nexus');
            updateSkillsNextButtonState(ctx);
        });
    });

    document.querySelectorAll('.nexus-reset-all-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const appEl = btn.closest('.nexus-app');
            if (!appEl) return;
            appEl.querySelectorAll('.nexus-param-input').forEach(input => {
                const defaultVal = JSON.parse(decodeURIComponent(input.dataset.default || 'null'));
                setNexusInputValue(input, defaultVal, input.dataset.valueType);
            });
            ctx.modifiedFields.skills.add('nexus');
            updateSkillsNextButtonState(ctx);
        });
    });
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
