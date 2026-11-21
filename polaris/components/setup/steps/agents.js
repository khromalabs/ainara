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
// but WITHOUT ANY WARRANTY, without even the implied warranty of
// MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
// Lesser General Public License for more details.

// Standing-consent step for agentic analysis of oversized skill results
// (issue #26 P2, ratified with #18). This wizard step is the ONLY path
// to a persistent 'allow' spend posture — the consent card's "Always"
// button is session-scoped by design (low-deliberation vs
// high-deliberation split). It also owns the `orakle.enable_agent_spawn`
// standing gate: choosing any policy other than "Never" grants it.

const RADIO_IDS = {
    allow: 'agents-policy-allow',
    ask: 'agents-policy-ask',
    deny: 'agents-policy-deny',
};

// Mirror of OrakleMiddleware._is_digestion_model_metered (#26 P2): the
// Ollama backend runs local models — no spend axis; anything else is
// metered. Fail-closed: an unresolvable selection counts as metered, so
// the cost warning shows rather than being silently skipped.
function isDigestionModelMetered(backendConfig) {
    const llm = (backendConfig && backendConfig.llm) || {};
    const selected = llm.selected_provider || '';
    let provider = null;
    for (const p of llm.providers || []) {
        if (p.model === selected || p.name === selected) {
            provider = p;
            break;
        }
    }
    const backend =
        (provider && provider.provider) || llm.selected_backend || 'litellm';
    return !(selected.startsWith('ollama/') || backend === 'ollama');
}

function selectedPolicy() {
    for (const [policy, id] of Object.entries(RADIO_IDS)) {
        const el = document.getElementById(id);
        if (el && el.checked) return policy;
    }
    return 'ask';
}

async function init(ctx) {
    if (!ctx.modifiedFields.agents) ctx.modifiedFields.agents = new Set();

    const warning = document.getElementById('agents-metered-warning');

    try {
        const backendConfig = await ctx.api.loadBackendConfig();

        // Cost warning is only meaningful on a metered analysis model.
        if (warning) {
            warning.classList.toggle(
                'hidden', !isDigestionModelMetered(backendConfig)
            );
        }

        // Preselect the stored posture; schema default is 'ask'.
        const current = (((backendConfig || {}).orakle || {}).offload || {})
            .spend_policy;
        const radio = document.getElementById(RADIO_IDS[current]);
        if (radio) radio.checked = true;
    } catch (error) {
        // Fail soft on the *display*: the step stays usable with the
        // default 'ask' preselection and the warning hidden. The save
        // path fails loud on its own (loadBackendConfig re-throws).
        console.error(
            'Error loading backend config for agent-consent step:', error
        );
        if (warning) warning.classList.add('hidden');
    }

    for (const id of Object.values(RADIO_IDS)) {
        const el = document.getElementById(id);
        if (el) {
            el.addEventListener('change', () => {
                ctx.modifiedFields.agents.add('policy');
            });
        }
    }
}

async function save(ctx) {
    if (!ctx.modifiedFields.agents || ctx.modifiedFields.agents.size === 0) {
        return true;
    }

    // Read-modify-write the real backend config (never build a payload
    // from defaults — see loadBackendConfig's contract).
    const backendConfig = await ctx.api.loadBackendConfig();
    if (!backendConfig.orakle) backendConfig.orakle = {};
    if (!backendConfig.orakle.offload) backendConfig.orakle.offload = {};

    const policy = selectedPolicy();
    backendConfig.orakle.offload.spend_policy = policy;
    // The standing spawn gate rides the same deliberate decision: any
    // posture other than "Never" enables ephemeral agent spawning
    // (#26 offload routing; #35 skill-powered agents later). "Never"
    // revokes it.
    backendConfig.orakle.enable_agent_spawn = policy !== 'deny';

    await ctx.api.saveBackendConfig(
        backendConfig, ctx.config.get('pybridge.api_url')
    );
    await ctx.api.saveBackendConfig(
        backendConfig, ctx.config.get('orakle.api_url')
    );

    ctx.modifiedFields.agents.clear();
    return true;
}

module.exports = { id: 'agents', init, save };
