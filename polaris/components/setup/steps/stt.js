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
    id: 'stt',

    async init(ctx) {
        await setupSTTEventListeners(ctx);
    },

    async save(ctx) {
        await saveSTTConfig(ctx);
    },

    validate(ctx) {
        return !document.getElementById('main-next-btn').disabled;
    }
};

// Add event listeners for STT options
async function setupSTTEventListeners(ctx) {
    const { config, api } = ctx;
    const sttNextButton = document.getElementById('main-next-btn');
    const languageSelect = document.getElementById('stt-language-select');
    const voiceSelect = document.getElementById('tts-voice-select');
    const warningDiv = document.getElementById('stt-ram-warning');

    // Define supported languages (Intersection of Faster-Whisper and Kokoro)
    const sttLanguages = [
        { code: 'en', name: 'English', flag: '🇬🇧' },
        { code: 'es', name: 'Spanish (Español)', flag: '🇪🇸' },
        { code: 'fr', name: 'French (Français)', flag: '🇫🇷' },
        { code: 'it', name: 'Italian (Italiano)', flag: '🇮🇹' },
        { code: 'pt', name: 'Portuguese (Português)', flag: '🇵🇹' },
        // { code: 'ja', name: 'Japanese (日本語)', flag: '🇯🇵', highMem: true },
        // { code: 'zh', name: 'Chinese (中文)', flag: '🇨🇳', highMem: true },
        { code: 'hi', name: 'Hindi (हिन्दी)', flag: '🇮🇳', highMem: true },
    ];

    // Kokoro Voice Data
    const kokoroVoices = {
        'en': [ // English (US & UK)
            { id: 'af_heart',   name: 'Heart',   lang: 'en-us', flag: '🇺🇸', grade: 'A',  desc: 'High quality' },
            { id: 'af_bella',   name: 'Bella',   lang: 'en-us', flag: '🇺🇸', grade: 'A-', desc: 'High quality' },
            { id: 'af_nicole',  name: 'Nicole',  lang: 'en-us', flag: '🇺🇸', grade: 'B-', desc: 'Good quality' },
            { id: 'bf_emma',    name: 'Emma',    lang: 'en-gb', flag: '🇬🇧', grade: 'B-', desc: 'Good quality' },
            // { id: 'af_alloy',   name: 'Alloy',   lang: 'en-us', flag: '🇺🇸', grade: 'C',  desc: 'Average quality' },
            { id: 'bf_isabella',name: 'Isabella',lang: 'en-gb', flag: '🇬🇧', grade: 'C',  desc: 'Average quality' },
            // { id: 'bf_fable',   name: 'Fable',   lang: 'en-gb', flag: '🇬🇧', grade: 'C',  desc: 'Average quality' },
            // { id: 'bf_george',  name: 'George',  lang: 'en-gb', flag: '🇬🇧', grade: 'C',  desc: 'Average quality' }
        ],
        'es': [ // Spanish
            { id: 'ef_dora',  name: 'Dora',  lang: 'es', flag: '🇪🇸', grade: '', desc: 'Female' },
            { id: 'em_alex',  name: 'Alex',  lang: 'es', flag: '🇪🇸', grade: '', desc: 'Male' },
            { id: 'em_santa', name: 'Santa', lang: 'es', flag: '🇪🇸', grade: '', desc: 'Male' }
        ],
        'fr': [ // French
            { id: 'ff_siwis', name: 'Siwis', lang: 'fr-fr', flag: '🇫🇷', grade: 'B-', desc: 'Female' }
        ],
        'it': [ // Italian
            { id: 'if_sara',   name: 'Sara',   lang: 'it', flag: '🇮🇹', grade: 'C', desc: 'Female' },
            { id: 'im_nicola', name: 'Nicola', lang: 'it', flag: '🇮🇹', grade: 'C', desc: 'Male' }
        ],
        'pt': [ // Portuguese (Brazilian)
            { id: 'pf_dora',  name: 'Dora',  lang: 'pt-br', flag: '🇧🇷', grade: '', desc: 'Female' },
            { id: 'pm_alex',  name: 'Alex',  lang: 'pt-br', flag: '🇧🇷', grade: '', desc: 'Male' },
            { id: 'pm_santa', name: 'Santa', lang: 'pt-br', flag: '🇧🇷', grade: '', desc: 'Male' }
        ],
        'ja': [ // Japanese
            { id: 'jf_alpha',      name: 'Alpha',      lang: 'ja', flag: '🇯🇵', grade: 'C+', desc: 'Female' },
            { id: 'jf_gongitsune', name: 'Gongitsune', lang: 'ja', flag: '🇯🇵', grade: 'C',  desc: 'Female' },
            { id: 'jf_tebukuro',   name: 'Tebukuro',   lang: 'ja', flag: '🇯🇵', grade: 'C',  desc: 'Female' }
        ],
        'zh': [ // Chinese (Mandarin)
            { id: 'zf_xiaobei', name: 'Xiaobei', lang: 'zh', flag: '🇨🇳', grade: 'D', desc: 'Female' },
            { id: 'zf_xiaoni',  name: 'Xiaoni',  lang: 'zh', flag: '🇨🇳', grade: 'D', desc: 'Female' },
            { id: 'zm_yunjian', name: 'Yunjian', lang: 'zh', flag: '🇨🇳', grade: 'D', desc: 'Male' }
        ],
        'hi': [ // Hindi
            { id: 'hf_alpha', name: 'Alpha', lang: 'hi', flag: '🇮🇳', grade: 'C', desc: 'Female' },
            { id: 'hf_beta',  name: 'Beta',  lang: 'hi', flag: '🇮🇳', grade: 'C', desc: 'Female' },
            { id: 'hm_omega', name: 'Omega', lang: 'hi', flag: '🇮🇳', grade: 'C', desc: 'Male' },
            { id: 'hm_psi',   name: 'Psi',   lang: 'hi', flag: '🇮🇳', grade: 'C', desc: 'Male' }
        ]
    };

    // Function to update voice options based on selected language
    function updateVoiceOptions(langCode, backendConfig = null) {
        if (!voiceSelect) return;

        voiceSelect.innerHTML = '';
        const voices = kokoroVoices[langCode] || [];

        if (voices.length === 0) {
            const option = document.createElement('option');
            option.textContent = "No voices available";
            voiceSelect.appendChild(option);
            return;
        }

        voices.forEach(voice => {
            const option = document.createElement('option');
            option.value = voice.id;
            // Store specific lang code (e.g. en-us) in dataset for saving
            option.dataset.lang = voice.lang;

            let text = `${voice.flag} ${voice.name}`;
            if (voice.grade) text += ` (Grade: ${voice.grade})`;
            if (voice.desc) text += ` - ${voice.desc}`;

            option.textContent = text;
            voiceSelect.appendChild(option);
        });

        // Select previously configured voice if it matches current language
        // TODO Fixed in kokoro
        const configuredVoice = backendConfig?.tts?.modules?.kokoro?.default_voice
        if (configuredVoice && voices.some(v => v.id === configuredVoice)) {
            voiceSelect.value = configuredVoice;
        }
    }

    // Populate language dropdown
    if (languageSelect && languageSelect.options.length === 0) {
        sttLanguages.forEach(lang => {
            const option = document.createElement('option');
            option.value = lang.code;
            option.textContent = `${lang.flag} ${lang.name}`;
            if (lang.highMem) {
                option.dataset.highMem = "true";
            }
            languageSelect.appendChild(option);
        });

        // Auto-detect language
        const systemLang = navigator.language.split('-')[0];
        const supportedLang = sttLanguages.find(l => l.code === systemLang);

        // Set default: Configured > System > English
        const backendConfig = await api.loadBackendConfig();
        const configuredLang = backendConfig?.stt?.language;
        if (configuredLang) {
            languageSelect.value = configuredLang;
        } else if (supportedLang) {
            languageSelect.value = systemLang;
        } else {
            languageSelect.value = 'en';
        }

        // Initialize voices for the selected language
        updateVoiceOptions(languageSelect.value, backendConfig);
    }

    // Check RAM and handle warnings
    async function checkRamAndWarn() {
        try {
            const response = await fetch(config.get('pybridge.api_url') + '/hardware/acceleration');
            const hwInfo = await response.json();
            const totalRam = hwInfo.details?.total_ram_gb || 0;

            const selectedOption = languageSelect.options[languageSelect.selectedIndex];
            const isHighMemLang = selectedOption.dataset.highMem === "true";

            warningDiv.classList.add('hidden');
            warningDiv.innerHTML = '';

            if (totalRam < 8) {
                warningDiv.innerHTML = `Your system has less than 8GB of RAM (${totalRam.toFixed(1)} GB detected). Speech recognition might be slow or have lower quality.`;
                warningDiv.classList.remove('hidden');
            } else if (totalRam < 15 && isHighMemLang) {
                warningDiv.innerHTML = `The selected language requires significant memory. With less than 16GB of RAM (${totalRam.toFixed(1)} GB detected), performance may be impacted.`;
                warningDiv.classList.remove('hidden');
            }
        } catch (error) {
            console.error('Error checking RAM for STT:', error);
        }
    }

    // Event listener for language change
    if (languageSelect) {
        languageSelect.addEventListener('change', () => {
            ctx.modifiedFields.stt.add('stt.language');
            updateVoiceOptions(languageSelect.value);
            checkRamAndWarn();
        });
    }

    // Event listener for voice change
    if (voiceSelect) {
        voiceSelect.addEventListener('change', () => {
            ctx.modifiedFields.stt.add('tts.voice');
        });
    }

    // Initial check
    checkRamAndWarn();

    // Enable next button (always valid now that we removed custom config)
    if (sttNextButton) sttNextButton.disabled = false;
}

// Function to save Voice (STT & TTS) config
async function saveSTTConfig(ctx) {
    const { config, api, modifiedFields } = ctx;

    // If no fields were modified, skip saving
    if (modifiedFields.stt.size === 0) {
        return;
    }

    const languageSelect = document.getElementById('stt-language-select');
    const voiceSelect = document.getElementById('tts-voice-select');

    const selectedLanguage = languageSelect ? languageSelect.value : 'en';
    const selectedSttBackend = 'faster_whisper';

    const selectedVoiceId = voiceSelect ? voiceSelect.value : 'af_heart';
    // Get the specific lang code (e.g. en-us) from the selected option's dataset
    const selectedOption = voiceSelect ? voiceSelect.options[voiceSelect.selectedIndex] : null;
    const selectedVoiceLang = selectedOption ? selectedOption.dataset.lang : 'en-us';
    const selectedTtsBackend = 'kokoro';

    try {
        // Load current backend config
        const backendConfig = await api.loadBackendConfig();

        // --- Update STT Config ---
        if (!backendConfig.stt) {
            backendConfig.stt = {
                language: selectedLanguage,
                modules: { faster_whisper: { model_size: "small" } },
                selected_module: selectedSttBackend
            };
        } else {
            backendConfig.stt.language = selectedLanguage;
            backendConfig.stt.selected_module = selectedSttBackend;
            if (!backendConfig.stt.modules) backendConfig.stt.modules = {};
            if (!backendConfig.stt.modules.faster_whisper) {
                backendConfig.stt.modules.faster_whisper = { model_size: "small" };
            }
        }

        // --- Update TTS Config ---
        if (!backendConfig.tts) {
            backendConfig.tts = {
                selected_module: selectedTtsBackend,
                modules: {}
            };
        }

        backendConfig.tts.selected_module = "kokoro";
        if (!backendConfig.tts.modules) backendConfig.tts.modules = {};

        // Set Kokoro specific settings
        backendConfig.tts.modules.kokoro = {
            default_lang: selectedVoiceLang,
            default_voice: selectedVoiceId
        };

        // Save the updated backend config
        await api.saveBackendConfig(backendConfig, config.get('pybridge.api_url'));

        // After successful save, clear the modified fields tracking
        modifiedFields.stt.clear();
    } catch (error) {
        console.error('Error updating Voice config:', error);
    }
}
