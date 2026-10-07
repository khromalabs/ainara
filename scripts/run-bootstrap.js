#!/usr/bin/env node
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

/**
 * Cross-platform launcher for `npm run setup`.
 * Locates a suitable Python interpreter and delegates all logic to
 * scripts/bootstrap.py, so this file stays a thin shim on purpose.
 */

const { spawn, spawnSync } = require('child_process');
const path = require('path');

const bootstrapScript = path.join(__dirname, 'bootstrap.py');

function findPython() {
    const candidates = process.platform === 'win32'
        ? [['py', ['-3']], ['python', []]]
        : [['python3.12', []], ['python3', []], ['python', []]];

    for (const [cmd, prefix] of candidates) {
        const probe = spawnSync(cmd, [...prefix, '--version'], {
            encoding: 'utf8',
        });
        if (!probe.error && probe.status === 0) {
            return { cmd, prefix };
        }
    }
    return null;
}

const python = findPython();
if (!python) {
    console.error(
        'setup: no Python interpreter found (Python 3.12 required; ' +
            'on Windows install python.org Python or the py launcher).'
    );
    process.exit(1);
}

const child = spawn(python.cmd, [...python.prefix, bootstrapScript, ...process.argv.slice(2)], {
    cwd: path.resolve(__dirname, '..'),
    stdio: 'inherit',
});

for (const signal of ['SIGINT', 'SIGTERM']) {
    process.on(signal, () => child.kill(signal));
}

child.on('error', (err) => {
    console.error(`setup: failed to launch Python: ${err.message}`);
    process.exit(1);
});

child.on('exit', (code, signal) => process.exit(code ?? (signal ? 1 : 0)));
