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

const STTBackend = require('./base');
const ConfigManager = require('../../framework/config');
const ConfigHelper = require('../../framework/ConfigHelper');
const { ipcRenderer } = require('electron');
const { promisify } = require('util');
const fs = require('fs');
const os = require('os');
const path = require('path');

const ffmpeg = require('fluent-ffmpeg');
const ffmpegPath = require('ffmpeg-static');
ffmpeg.setFfmpegPath(ConfigHelper.resolveBinaryPath(ffmpegPath));



class WhisperSTT extends STTBackend {
    /**
     * OpenAI Whisper API implementation of STT backend
     */
    constructor() {
        super();

        const config = new ConfigManager();
        this.service = config.get('stt.modules.whisper.service', 'openai');
        const serviceConfig = config.get(`stt.modules.whisper.${this.service}`, {});

        if (!['openai', 'pybridge', 'custom'].includes(this.service)) {
            throw new Error(`Unknown Whisper service: ${this.service}`);
        }

        this.apiKey = serviceConfig.apiKey;
        this.apiUrl = serviceConfig.apiUrl;
        this.model = serviceConfig.model || 'whisper-1';
        this.headers = serviceConfig.headers || {};

        if (!this.apiKey || !this.apiUrl) {
            throw new Error(`Whisper ${this.service} service not properly configured`);
        }
    }

    async initialize() {
        try {
            console.log("WhisperSTT initialize starting");
            console.log("apiUrl is:", this.apiUrl);
            console.log("ffmpegPath is:", ConfigHelper.resolveBinaryPath(ffmpegPath));
            // const url = new URL(this.apiUrl);
            // // Check if server is available by requesting the root URL
            // const baseUrl = `${url.protocol}//${url.host}`;
            const baseUrl = this.apiUrl;
            console.log("Checking Whisper server at: " + baseUrl);
            const response = await fetch(baseUrl);
            if (!response.ok) {
                throw new Error(`Whisper service not available at ${baseUrl}`);
            }
            console.log('Whisper service connection established');
        } catch (error) {
            const msg = 'Speech-to-Text service is not available.\n\n' +
                'Please ensure the Whisper server is running and try again.\n\n' +
                'Error details: ' + error.message
            ipcRenderer.send('critical-error', msg);
            throw new Error('Whisper STT service is not available. Please ensure the Whisper server is running at ' + this.apiUrl);
        }
    }

    // In WhisperSTT class:
    async webmToWav(webmBlob) {
        try {
            console.log('Converting WebM to WAV...');

            // Create temp files
            const tempDir = os.tmpdir();
            const inputPath = path.join(tempDir, `input-${Date.now()}.webm`);
            const outputPath = path.join(tempDir, `output-${Date.now()}.wav`);

            // Write WebM blob to temp file
            const buffer = Buffer.from(await webmBlob.arrayBuffer());
            await promisify(fs.writeFile)(inputPath, buffer);

            // Convert using FFmpeg
            await new Promise((resolve, reject) => {
                ffmpeg(inputPath)
                    .toFormat('wav')
                    .audioFrequency(16000)  // Force 16 kHz sample rate
                    .audioChannels(1)       // Mono audio
                    .audioBitrate('16k')    // 16-bit depth
                    .on('error', reject)
                    .on('end', resolve)
                    .save(outputPath);
            });

            // Read result
            const wavData = await promisify(fs.readFile)(outputPath);
            const wavBlob = new Blob([wavData], { type: 'audio/wav' });

            // Cleanup temp files
            await promisify(fs.unlink)(inputPath);
            await promisify(fs.unlink)(outputPath);

            console.log(`WAV conversion complete, size: ${wavBlob.size} bytes`);
            return wavBlob;

        } catch (error) {
            console.error('Error converting WebM to WAV:', error);
            throw error;
        }
    }


    /**
     * Transcribes an audio blob.
     * Automatically converts WebM to WAV if needed.
     * @param {Blob} audioBlob
     * @returns {Promise<string>} Transcription text
     */
    async transcribe(audioBlob) {
        try {
            console.log(`WhisperSTT: Transcribing blob of type ${audioBlob.type}, size: ${audioBlob.size}`);

            let blobToProcess = audioBlob;

            // Convert if it's WebM (common from MediaRecorder)
            if (audioBlob.type.includes('webm') || audioBlob.type.includes('x-matroska')) {
                console.log('WhisperSTT: Detected WebM/Matroska, converting to WAV...');
                blobToProcess = await this.webmToWav(audioBlob);
            }

            return await this.transcribeFile(blobToProcess);
        } catch (error) {
            console.error('WhisperSTT: Transcription error:', error);
            throw error;
        }
    }

    async transcribeFile(audioBlob) {
        try {
            const headers = { ...this.headers };

            if (this.service === 'openai') {
                headers.Authorization = `Bearer ${this.apiKey}`;
            } else if (this.service === 'custom') {
                headers.Authorization = this.apiKey;
            }

            const formData = new FormData();
            formData.append('file', new File([audioBlob], 'recording.wav', { type: 'audio/wav' }));
            formData.append('model', this.model);
            formData.append('response_format', 'json');
            formData.append('language', 'auto');
            formData.append('task', 'transcribe');

            console.log("sending audio to: " + this.apiUrl)

            const response = await fetch(`${this.apiUrl}`, {
                method: 'POST',
                headers,
                body: formData
            });

            if (!response.ok) {
                throw new Error(`Server error: ${response.status}`);
            }

            const result = await response.json();
            console.log('Transcription:', result);
            
            // [MODIFIED] Return object with text and confidence
            return {
                text: result.text?.trim() || '',
                confidence: result.confidence, // May be undefined if using direct OpenAI
                language: result.language
            };

        } catch (error) {
            console.error(`Whisper ${this.service} transcription failed:`, error);
            throw error;
        }
    }
}

module.exports = WhisperSTT;
