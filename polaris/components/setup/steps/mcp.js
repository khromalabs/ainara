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

module.exports = {
    id: 'mcp',

    async init(ctx) {
        await generateMcpUI(ctx);
    },

    async save(ctx) {
        await saveMcpConfig(ctx);
    },

    validate(ctx) {
        return validateMcpStep(ctx);
    },

    addServerForm(ctx, serverName, container) {
        addMcpServerForm(ctx, serverName, container);
    }
};

// Copy the following functions from setup.js into this module,
// adapting them to use ctx.api, ctx.config, ctx.modifiedFields, etc.

async function generateMcpUI(ctx) {
    const mcpPanel = document.getElementById('mcp-panel');
    if (!mcpPanel) return;

    let container = mcpPanel.querySelector('.mcp-configurations');
    if (!container) {
        mcpPanel.innerHTML = `<h2>MCP Server Configuration</h2>
                              <p>Configure connections to Model-Context-Protocol (MCP) compatible servers.</p>
                              <div class="mcp-configurations"></div>
                              <button id="add-mcp-server-btn" class="btn">Add MCP Server</button>`;
        container = mcpPanel.querySelector('.mcp-configurations');
    }
    container.innerHTML = '<p>Loading MCP configurations...</p>';

    try {
        const backendConfig = await ctx.api.loadBackendConfig();
        const mcpClients = backendConfig.mcp_clients || {};
        container.innerHTML = '';

        if (Object.keys(mcpClients).length === 0) {
            container.innerHTML = '<p>No MCP servers configured yet. Click "Add MCP Server" to begin.</p>';
        } else {
            for (const serverName in mcpClients) {
                addMcpServerForm(ctx, serverName, container, mcpClients[serverName]);
            }
        }
    } catch (error) {
        console.error('Error loading MCP configurations:', error);
        container.innerHTML = `<p class="error">Error loading MCP configurations: ${error.message}</p>`;
    }
}

function addMcpServerForm(ctx, serverName, container, serverConfig = {}) {
    const serverId = serverName || `new-mcp-${Date.now()}`;
    const formHtml = `
        <div class="mcp-server-form" data-server-id="${serverId}">
            <h4>${serverName ? `Edit Server: ${serverName}` : 'New MCP Server'}</h4>
            <div class="form-group">
                <label for="mcp-${serverId}-name">Server Name:</label>
                <input type="text" id="mcp-${serverId}-name" class="mcp-name" value="${serverName || ''}" placeholder="e.g., my-server">
            </div>
            <div class="form-group">
                <label for="mcp-${serverId}-command">Command:</label>
                <textarea id="mcp-${serverId}-command" class="mcp-command" placeholder="e.g., npx -y @modelcontextprotocol/server-everything">${serverConfig.command || ''}</textarea>
            </div>
            <h5>Environment Variables</h5>
            <div class="mcp-env-vars">
                ${Object.entries(serverConfig.env || {}).map(([key, value]) => `
                    <div class="mcp-env-var-item">
                        <input type="text" class="mcp-env-key" placeholder="Key" value="${key}">
                        <span>=</span>
                        <input type="text" class="mcp-env-value" placeholder="Value" value="${value}">
                        <button type="button" class="btn btn-xs btn-danger remove-mcp-env-btn">&times;</button>
                    </div>
                `).join('')}
            </div>
            <button type="button" class="btn btn-sm add-mcp-env-btn">Add Environment Variable</button>
            <button type="button" class="btn btn-sm btn-danger remove-mcp-server-btn">Remove Server</button>
        </div>
    `;
    container.insertAdjacentHTML('beforeend', formHtml);

    const form = container.lastElementChild;

    // Add env var listener
    form.querySelector('.add-mcp-env-btn').addEventListener('click', () => {
        addMcpEnvVarForm(ctx, form.querySelector('.mcp-env-vars'));
        ctx.modifiedFields.mcp.add(serverId);
    });

    // Remove env var listener
    form.querySelectorAll('.remove-mcp-env-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            btn.closest('.mcp-env-var-item').remove();
            ctx.modifiedFields.mcp.add(serverId);
        });
    });

    // Remove server listener
    form.querySelector('.remove-mcp-server-btn').addEventListener('click', () => {
        if (confirm('Remove this MCP server?')) {
            form.remove();
            ctx.modifiedFields.mcp.add(serverId);
        }
    });

    // Input listeners
    form.querySelectorAll('input, textarea').forEach(input => {
        input.addEventListener('input', (event) => ctx.handleInputChange(event));
    });
}

function addMcpEnvVarForm(ctx, container) {
    const envVarHtml = `
        <div class="mcp-env-var-item">
            <input type="text" class="mcp-env-key" placeholder="Key">
            <span>=</span>
            <input type="text" class="mcp-env-value" placeholder="Value">
            <button type="button" class="btn btn-xs btn-danger remove-mcp-env-btn">&times;</button>
        </div>
    `;
    container.insertAdjacentHTML('beforeend', envVarHtml);

    const envVarItem = container.lastElementChild;

    envVarItem.querySelector('.remove-mcp-env-btn').addEventListener('click', () => {
        envVarItem.remove();
        const serverId = envVarItem.closest('.mcp-server-form').dataset.serverId;
        ctx.modifiedFields.mcp.add(serverId);
    });

    envVarItem.querySelectorAll('input').forEach(input => {
        input.addEventListener('input', (event) => ctx.handleInputChange(event));
    });
}

async function saveMcpConfig(ctx) {
    // If no MCP fields were modified, skip saving
    if (ctx.modifiedFields.mcp.size === 0) {
        return;
    }

    try {
        const backendConfig = await ctx.api.loadBackendConfig();

        if (!backendConfig.mcp_clients) {
            backendConfig.mcp_clients = {};
        }

        const newMcpClients = {};

        document.querySelectorAll('.mcp-server-form').forEach(form => {
            const serverId = form.dataset.serverId;
            const nameInput = form.querySelector('.mcp-name');
            const commandInput = form.querySelector('.mcp-command');

            const name = nameInput ? nameInput.value.trim() : '';
            const command = commandInput ? commandInput.value.trim() : '';

            if (!name || !command) return;

            const env = {};
            form.querySelectorAll('.mcp-env-var-item').forEach(item => {
                const key = item.querySelector('.mcp-env-key').value.trim();
                const value = item.querySelector('.mcp-env-value').value.trim();
                if (key) {
                    env[key] = value;
                }
            });

            newMcpClients[name] = {
                command: command,
                env: env
            };
        });

        backendConfig.mcp_clients = newMcpClients;

        await ctx.api.saveBackendConfig(backendConfig, ctx.config.get('pybridge.api_url'));

        ctx.modifiedFields.mcp.clear();
    } catch (error) {
        console.error('Error updating MCP config:', error);
    }
}

function validateMcpStep(ctx) {
    // MCP servers are optional, so the step is always valid
    return true;
}
