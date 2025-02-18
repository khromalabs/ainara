const { Logger } = require('../../utils/logger');

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
