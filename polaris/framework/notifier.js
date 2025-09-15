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

const notifier = require('node-notifier');
const path = require('path');

class Notifier {
    static show(message) {
        notifier.notify(
            {
                title: 'Ainara AI',
                message,
                icon: path.join(__dirname, '..', 'windows', 'assets', 'icon.png'),
                sound: false, // Do not play a sound
            },
            function (err, response) {
                // Response is response from notification
                if (err) {
                    console.error('Notification error:', err);
                }
            }
        );
    }
}

module.exports = Notifier;
