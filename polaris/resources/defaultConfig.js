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
    stt: {
        modules: {
            whisper: {
                service: 'custom',
                custom: {
                    apiKey: 'local',
                    apiUrl: 'http://127.0.0.1:5001/framework/stt',
                    headers: {}
                }
            }
        }
    },
    orakle: {
        api_url: 'http://localhost:5000'
    },
    pybridge: {
        api_url: 'http://localhost:5001'
    },
    window: {
        width: 300,
        height: 200,
        frame: false,
        transparent: true,
        alwaysOnTop: true,
        skipTaskbar: true,
        focusable: true,
        type: 'toolbar',
        backgroundColor: '#00000000',
        hasShadow: false,
        vibrancy: 'blur',
        visualEffectState: 'active',
        opacity: 0.95
    },
    shortcuts: {
        show: 'F1',
        hide: 'Escape',
        trigger: 'Space'
    },
    ring: {
        volume: 0,
        visible: false,
        fftSize: 256,
        fadeTimeout: 500,
        opacity: {
            min: 0.4,
            max: 1,
            scale: 1.2
        }
    },
    updates: {
        ignoredVersion: null
    },
    setup: {
        completed: false,
        version: 0,
        timestamp: 0
    },
    startup: {
        startMinimized: false
    }
};
