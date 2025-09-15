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

const path = require('path');
const os = require('os');

const isWindows = os.platform() === "win32";
var notifier = null

if ( isWindows ) {
    const WindowsBalloon = require('node-notifier').WindowsBalloon;
    notifier = new WindowsBalloon({
        withFallback: false,
        customPath: undefined
    });
} else {
    notifier = require('node-notifier');
}

class Notifier {
    static show(message) {
        var msg_clean = isWindows ? message.replace(/[\r|\n]*$/, "") : message;
        notifier.notify(
            {
                title: 'Ainara AI',
                message: msg_clean,
                icon: path.join(__dirname, '..', 'windows', 'assets', 'icon.png'),
                sound: false, // Do not play a sound
                time: 5000,
                wait: false
            },
            // function (err, response) {
            function (err, ) {
                // Response is response from notification
                if (err) {
                    console.error('Notification error:', err);
                }
            }
        );
    }
}

module.exports = Notifier;
