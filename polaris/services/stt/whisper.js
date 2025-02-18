const STTBackend = require('./base');
const ConfigManager = require('../../utils/config');
const { ipcRenderer } = require('electron');
const { promisify } = require('util');
const fs = require('fs');
const os = require('os');
const path = require('path');

const ffmpeg = require('fluent-ffmpeg');
// const ffmpegPath = require('ffmpeg-static');
// ffmpeg.setFfmpegPath(ffmpegPath);



class WhisperSTT extends STTBackend {
    /**
     * OpenAI Whisper API implementation of STT backend
     */
    constructor() {
        super();

        const config = new ConfigManager();
        this.service = config.get('stt.modules.whisper.service', 'openai');
        const serviceConfig = config.get(`stt.modules.whisper.${this.service}`, {});

        if (!['openai', 'custom'].includes(this.service)) {
            throw new Error(`Unknown Whisper service: ${this.service}`);
        }

        this.apiKey = serviceConfig.apiKey;
        this.apiUrl = serviceConfig.apiUrl;
        this.model = serviceConfig.model || 'whisper-1';
        this.headers = serviceConfig.headers || {};
        this.mediaRecorder = null;

        if (!this.apiKey || !this.apiUrl) {
            throw new Error(`Whisper ${this.service} service not properly configured`);
        }
    }

    async initialize() {
        try {
            console.log("WhisperSTT initialize starting");
            console.log("apiUrl is:", this.apiUrl);
            // Check if server is available by requesting the root URL
            const baseUrl = this.apiUrl.replace('/inference', '');
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


    async listen() {
        try {
            console.log('Starting audio recording...');
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            this.mediaRecorder = new MediaRecorder(stream, {
                mimeType: 'audio/webm'
            });
            const audioChunks = [];

            this.mediaRecorder.start();

            return new Promise((resolve, reject) => {
                this.mediaRecorder.ondataavailable = (event) => {
                    audioChunks.push(event.data);
                };

                // In whisper.js
                this.mediaRecorder.onstop = async () => {
                    try {
                        console.log('MediaRecorder stopped, creating audio blob...');
                        const audioBlob = new Blob(audioChunks, { type: 'audio/webm' });
                        console.log(`Audio blob created, size: ${audioBlob.size} bytes`);

                        // Convert WebM to WAV
                        const wavBlob = await this.webmToWav(audioBlob);

                        console.log('Sending to Whisper server...');
                        const transcription = await this.transcribeFile(wavBlob);
                        // console.log('Got transcription result:', transcription);

                        if (this.onTranscriptionResult) {
                            console.log('Calling onTranscriptionResult callback');
                            this.onTranscriptionResult(transcription);
                        }
                        resolve(transcription);
                    } catch (error) {
                        console.error('Error in onstop handler:', error);
                        reject(error);
                    }
                };
            });
        } catch (error) {
            console.error('Error in listen():', error);
            throw error;
        }
    }

    async stopRecording() {
         console.log("whisper stopRecording 1")
         console.log("this.mediaRecorder:" + this.mediaRecorder)
         console.log("this.mediaRecorder.state:" + this.mediaRecorder.state)
         if (this.mediaRecorder && this.mediaRecorder.state !== 'inactive') {
             console.log("whisper stopRecording 2")
             console.log('Stopping WhisperSTT recording');
             this.mediaRecorder.stop();
             // // Return a promise that resolves when the recording is actually stopped
             // return new Promise((resolve) => {
             //     this.mediaRecorder.onstop = () => {
             //         console.log('MediaRecorder actually stopped');
             //         resolve();
             //     };
             // });
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
            return result.text?.trim() || '';

        } catch (error) {
            console.error(`Whisper ${this.service} transcription failed:`, error);
            throw error;
        }
    }
}

module.exports = WhisperSTT;
