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
        const capsResponse = await fetch(ctx.config.get('orakle.api_url') + '/capabilities?view=full');
        const capabilities = await capsResponse.json();
        const backendConfig = await ctx.api.loadBackendConfig();

        const scheduleHtml = generateScheduleUI(capabilities, backendConfig);

        const userSkillsHtml = `
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

        const layoutHtml = `<div class="skills-layout">${scheduleHtml}${userSkillsHtml}</div>`;

        const skillsListContainer = document.querySelector('.skills-list');
        if (skillsListContainer) {
            skillsListContainer.innerHTML = layoutHtml;
        }

        // Schedule listeners
        setupScheduleListeners(ctx);

        // User skills directory listeners
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

        await ctx.api.saveBackendConfig(backendConfig, ctx.config.get('pybridge.api_url'));
        await ctx.api.saveBackendConfig(backendConfig, ctx.config.get('orakle.api_url'));

        ctx.modifiedFields.skills.clear();
    } catch (error) {
        console.error('Error saving skills config:', error);
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
