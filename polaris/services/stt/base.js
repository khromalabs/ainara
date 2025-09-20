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

const { Logger } = require('../../framework/logger');

class STTBackend {
    /**
     * Initialize STT backend with configuration
     * @param {Object} config Dictionary containing STT configuration parameters
     */
    constructor(config = {}) {
        this.config = config;
    }

    /**
     * Record audio and convert to text
     * @returns {Promise<string>} Transcribed text
     */
    async listen() {
        throw new Error('Not implemented');
    }

    /**
     * Transcribe an existing audio file to text
     * @param {Blob} audioBlob Audio file blob to transcribe
     * @returns {Promise<string>} Transcribed text
     */
    async transcribeFile(audioBlob) {
        throw new Error('Not implemented');
    }
}

module.exports = STTBackend;