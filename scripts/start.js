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
 * Start Polaris (Electron) with a clean process chain.
 *
 * Spawns the Electron binary DIRECTLY (no npm/cmd.exe wrapper layer), which
 * keeps signal delivery (Ctrl+C, SIGTERM) reliable across platforms and
 * avoids the orphaned-backend-services races seen when booting through the
 * npm wrapper.
 *
 * Modes:
 *   default / --source : dev-source mode (AINARA_USE_SOURCE=1) — backend
 *                        services boot from the Python virtualenv.
 *   --bundle           : boot against the packaged server executables.
 *
 * The UI owns the service lifecycle (health monitoring, restarts, shutdown);
 * this script only forwards signals and mirrors the child exit code.
 */

const { spawn } = require('child_process');
const path = require('path');

const repoRoot = path.resolve(__dirname, '..');
const args = process.argv.slice(2);
const bundleMode = args.includes('--bundle');
const extraArgs = args.filter((a) => a !== '--bundle');

// In plain Node, `require('electron')` resolves to the binary path.
const electronPath = require('electron');
if (typeof electronPath !== 'string') {
    console.error(
        'start: could not resolve the Electron binary path. ' +
            'Did you run `npm run setup` (or `npm ci`) first?'
    );
    process.exit(1);
}

const env = { ...process.env };
if (bundleMode) {
    delete env.AINARA_USE_SOURCE;
} else {
    env.AINARA_USE_SOURCE = '1';
}

const child = spawn(electronPath, ['.', ...extraArgs], {
    cwd: repoRoot,
    env,
    stdio: 'inherit',
});

// Forward termination signals to Electron. On POSIX the child shares this
// process group, so Ctrl+C reaches it natively as well; forwarding keeps the
// contract explicit and covers remote/programmatic kills.
for (const signal of ['SIGINT', 'SIGTERM', 'SIGHUP']) {
    process.on(signal, () => child.kill(signal));
}

child.on('error', (err) => {
    console.error(`start: failed to launch Electron: ${err.message}`);
    process.exit(1);
});

child.on('exit', (code, signal) => process.exit(code ?? (signal ? 1 : 0)));
