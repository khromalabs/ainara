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

function extractApiKeysFromConfig(config) {
    const apiKeys = {};

    function findApiKeys(obj, path = []) {
        if (!obj || typeof obj !== 'object') return;

        for (const [key, value] of Object.entries(obj)) {
            const currentPath = [...path, key];

            if (!String(currentPath).startsWith("apis"))
                continue;

            if (String(currentPath).startsWith("apis.messaging.email"))
                continue;

            if (typeof value !== 'object' && value !== null) {
                const parentPath = currentPath.slice(0, -1).join('.');

                if (!apiKeys[parentPath]) {
                    apiKeys[parentPath] = {
                        displayName: formatKeyName(currentPath.slice(0, -1)),
                        keys: []
                    };
                }

                apiKeys[parentPath].keys.push({
                    path: currentPath.join('.'),
                    keyName: key,
                    displayName: formatKeyName([key]),
                    value: value === "<key>" ? "" : value,
                    description: getKeyDescription(currentPath)
                });
            }
            else if (typeof value === 'object' && value !== null) {
                findApiKeys(value, currentPath);
            }
        }
    }

    findApiKeys(config);

    return apiKeys;
}

function formatKeyName(pathArray) {
    return pathArray.map(part => {
        return part
            .replace(/_/g, ' ')
            .replace(/([A-Z])/g, ' $1')
            .replace(/^./, str => str.toUpperCase());
    }).join(' › ');
}

function getKeyDescription(pathArray) {
    const parentPart = pathArray.length > 1 ? pathArray[pathArray.length - 2] : '';

    const descriptions = {
        'coinmarketcap': {
            url: 'https://coinmarketcap.com/api/',
            description: 'Used for extended quotes in cryptocurrency market data, not present in main markets'
        },
        'weather': {
            url: 'https://openweathermap.org/api',
            description: 'Used for weather forecasts and current conditions'
        },
        'finance': {
            url: 'https://www.alphavantage.co/support/#api-key',
            description: 'Used for stock market data and financial information'
        },
        'newsapi': {
            url: 'https://newsapi.org/register',
            description: 'Used for retrieving news articles and headlines'
        },
        'google': {
            url: 'https://developers.google.com/custom-search/v1/overview',
            description: 'Used for web search capabilities'
        },
        'tavily': {
            url: 'https://tavily.com/',
            description: 'Used for AI-powered search capabilities'
        },
        'perplexity': {
            url: 'https://www.perplexity.ai/',
            description: 'Used for AI-powered search and answers'
        },
        'metaphor': {
            url: 'https://metaphor.systems/',
            description: 'Used for neural search capabilities'
        },
        'brave': {
            url: 'https://brave.com/search/api/',
            description: 'Used for web search capabilities (free tier available)'
        },
        'searxng': {
            url: null,
            description: "Paste your instance URL (e.g. http://127.0.0.1:8888) to enable it; leave empty to disable. The instance must allow JSON output ('json' in settings.yml > search > formats).",  // , `api_key` is optional."
        },
        'twitter': {
            url: 'https://developer.twitter.com/en/portal/dashboard',
            description: 'Used for Twitter/X integration'
        },
        'reddit': {
            url: 'https://www.reddit.com/prefs/apps',
            description: 'Used for Reddit integration'
        },
        'coinmarketcap': {
            url: 'https://coinmarketcap.com/api/',
            description: 'Used for cryptocurrency market data'
        },
        'helius': {
            url: 'https://helius.xyz/',
            description: 'Used for Solana blockchain data'
        },
        'discord': {
            url: 'https://discord.com/developers/applications',
            description: 'Used for Discord bot integration'
        },
        'email': {
            url: null,
            description: 'Configure IMAP accounts for email integration'
        },
        // TODO This only applies to Polaris "Supporters Edition" it should only appear if Ataria is installed
        // same in ainara.yaml.defaults
        'hyperliquid': {
            url: 'https://app.hyperliquid.xyz/join/AINARA',
            description: 'Hyperliquid DEX: Trade crypto, commodities, indices, and more (AINARA referral). All three fields are required: api_key (agent address), secret (agent private key) and wallet_address (master account).'
        }
    };
    if (descriptions[parentPart]) {
        return {
            text: descriptions[parentPart].description,
            url: descriptions[parentPart].url
        };
    }

    return {
        text: `API key for ${formatKeyName(pathArray)}`,
        url: null
    };
}

function normalizeModelName(model, provider) {
    if (!model) return model;

    const providerPrefix = provider.toLowerCase() + '/';

    if (provider === 'custom' || provider === 'custom_api') {
        return model;
    }

    if (model.toLowerCase().startsWith(providerPrefix)) {
        return model;
    }

    return `${provider}/${model}`;
}

function parsePythonDefault(val) {
    if (val === undefined || val === null) return null;
    const sVal = String(val).trim();
    if (sVal === "None") return null;
    if (sVal === "True") return true;
    if (sVal === "False") return false;
    if (!isNaN(Number(sVal))) return Number(sVal);
    if ((sVal.startsWith("'") && sVal.endsWith("'")) || (sVal.startsWith('"') && sVal.endsWith('"'))) {
        return sVal.slice(1, -1);
    }
    return sVal;
}

function renderInputBySchema(skillName, paramName, paramDef, currentValue) {
    const schema = paramDef.schema || {};
    const type = schema.type || 'string';
    const inputId = `param-${skillName}-${paramName}`;

    let value = currentValue;
    if (value === undefined || value === null) {
        value = parsePythonDefault(paramDef.default);
    }

    let defaultValue = paramDef.required ? ` value="${value}" ` : '';

    let inputHtml = '';

    if (type === 'boolean') {
        const isTrue = value === true;
        inputHtml = `
            <select class="param-input" data-skill="${skillName}" data-key="${paramName}" data-type="boolean">
                <option value="true" ${isTrue ? 'selected' : ''}>True</option>
                <option value="false" ${!isTrue ? 'selected' : ''}>False</option>
            </select>
        `;
    } else if (type === 'integer' || type === 'number') {
        inputHtml = `<input type="number" class="param-input" id="${inputId}" data-skill="${skillName}" data-key="${paramName}" data-type="${type}" ${defaultValue}  placeholder="${value !== null ? value : ''}" step="${type === 'integer' ? '1' : 'any'}">`;
    } else if (type === 'array') {
        let displayVal = value;
        if (Array.isArray(value)) displayVal = value.join(', ');
        inputHtml = `<input type="text" class="param-input" id="${inputId}" data-skill="${skillName}" data-key="${paramName}" data-type="array" placeholder="${displayVal || ''}" >`;
    } else if (type === 'object') {
        inputHtml = `<input type="text" disabled value="COMPLEX CONFIGURATION (OBJECT) - NOT EDITABLE IN THIS VERSION" style="font-style: italic; color: #888; background-color: #eee;">`;
    } else {
        inputHtml = `<input type="text" class="param-input" id="${inputId}" data-skill="${skillName}" data-key="${paramName}" data-type="string" placeholder="${value || ''}">`;
    }

    return `
        <div class="param-group">
            <label for="${inputId}" title="${paramName}">${paramName}</label>
            ${inputHtml}
            <div class="param-desc">${paramDef.description || ''}</div>
        </div>
    `;
}

function renderSkillParameters(skillName, cap, currentKwargs) {
    const parameters = cap.run_info?.parameters;
    if (!parameters || Object.keys(parameters).length === 0) {
        return '<p style="color: #666; font-style: italic;">No configurable parameters.</p>';
    }

    let html = '';
    for (const [paramName, paramDef] of Object.entries(parameters)) {
        const val = currentKwargs ? currentKwargs[paramName] : undefined;
        html += renderInputBySchema(skillName, paramName, paramDef, val);
    }
    return html;
}

module.exports = {
    extractApiKeysFromConfig,
    formatKeyName,
    getKeyDescription,
    normalizeModelName,
    parsePythonDefault,
    renderInputBySchema,
    renderSkillParameters
};
