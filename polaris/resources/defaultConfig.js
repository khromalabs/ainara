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
    setup: {
        completed: false,
        version: 0,
        timestamp: 0
    }
};
