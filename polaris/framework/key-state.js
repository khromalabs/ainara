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

/**
 * OS-level key state queries (level-triggered), for detecting physical key
 * state regardless of whether the window event stream delivered keyup events.
 *
 * This is the games approach: instead of trusting a keyup *event* (which
 * Electron/Chromium can silently drop, leaving push-to-talk stuck), callers
 * *poll* the actual hardware state: "is the key physically down right now?"
 *
 * Platform backends (all via koffi FFI, no compiled addon of our own):
 *   - Windows: user32!GetAsyncKeyState
 *   - Linux/X11: Xlib XQueryKeymap (XWayland: may not see native Wayland
 *     clients - callers must verify trust before acting on "up" answers,
 *     see the arming pattern in ComRingWindow.startPTTKeyWatch)
 *   - macOS: CoreGraphics CGEventSourceKeyState
 *
 * All failures degrade gracefully: isDown() returns null when the platform
 * backend is unavailable or the key is not mapped, never throws.
 */

const Logger = require('./logger');

// Electron KeyboardEvent.code style names -> per-platform codes
const WIN32_VK = {
    Space: 0x20,
    ShiftLeft: 0x10, ShiftRight: 0xA1,
    ControlLeft: 0x11, ControlRight: 0xA3,
    AltLeft: 0x12, AltRight: 0xA5,
};
const DARWIN_KVK = {
    Space: 49,
    ShiftLeft: 56, ShiftRight: 60,
    ControlLeft: 59, ControlRight: 62,
    AltLeft: 58, AltRight: 61,
};

function win32VirtualKeyCode(codeName) {
    if (WIN32_VK[codeName] !== undefined) return WIN32_VK[codeName];
    let m = codeName.match(/^Key([A-Z])$/);
    if (m) return 0x41 + m[1].charCodeAt(0) - 65; // 'A'..'Z'
    m = codeName.match(/^Digit([0-9])$/);
    if (m) return 0x30 + Number(m[1]); // '0'..'9'
    return null;
}

function x11KeysymName(codeName) {
    if (codeName === 'Space') return 'space';
    let m = codeName.match(/^Key([A-Z])$/);
    if (m) return m[1].toLowerCase();
    m = codeName.match(/^Digit([0-9])$/);
    if (m) return m[1];
    return null;
}

function darwinKeyCode(codeName) {
    if (DARWIN_KVK[codeName] !== undefined) return DARWIN_KVK[codeName];
    let m = codeName.match(/^Key([A-Z])$/);
    if (m) return m[1].charCodeAt(0) - 65; // kVK_ANSI_A = 0
    m = codeName.match(/^Digit([1-9])$/);
    if (m) return 17 + Number(m[1]); // kVK_ANSI_1 = 18 .. kVK_ANSI_9 = 26
    if (codeName === 'Digit0') return 27; // kVK_ANSI_0
    return null;
}

class KeyState {
    constructor() {
        this.platform = process.platform;
        this.backend = null; // lazy-initialized platform backend
        this.unavailable = false;
    }

    /**
     * Attempt platform backend initialization. Returns true when the
     * backend is usable, false otherwise (reason is logged once).
     */
    isAvailable() {
        if (this.backend) return true;
        if (this.unavailable) return false;
        try {
            this._init();
            return !!this.backend;
        } catch (err) {
            Logger.warn(`KeyState: platform backend unavailable (${err.message})`);
            this.unavailable = true;
            return false;
        }
    }

    _init() {
        const koffi = require('koffi'); // lazy: optional native dependency

        if (this.platform === 'win32') {
            const lib = koffi.load('user32.dll');
            const GetAsyncKeyState = lib.func(
                'short __stdcall GetAsyncKeyState(int nVirtKey)'
            );
            this.backend = {
                // MSB set = key currently held down
                isDown: (vk) => (GetAsyncKeyState(vk) & 0x8000) !== 0,
                toCode: win32VirtualKeyCode,
            };
        } else if (this.platform === 'darwin') {
            const cg = koffi.load(
                '/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics'
            );
            const CGEventSourceKeyState = cg.func(
                'bool CGEventSourceKeyState(int stateID, unsigned short keyCode)'
            );
            // kCGEventSourceStateCombinedSessionState = 0
            this.backend = {
                isDown: (vk) => CGEventSourceKeyState(0, vk),
                toCode: darwinKeyCode,
            };
        } else if (this.platform === 'linux') {
            const libNames = ['libX11.so.6', 'libX11.so'];
            let lib = null;
            for (const name of libNames) {
                try { lib = koffi.load(name); break; } catch { /* try next */ }
            }
            if (!lib) throw new Error('libX11 not found');
            const XOpenDisplay = lib.func('void* XOpenDisplay(const char*)');
            const XCloseDisplay = lib.func('int XCloseDisplay(void*)');
            const XStringToKeysym = lib.func(
                'unsigned long XStringToKeysym(const char*)'
            );
            const XKeysymToKeycode = lib.func(
                'unsigned int XKeysymToKeycode(void*, unsigned long)'
            );
            const XQueryKeymap = lib.func('int XQueryKeymap(void*, char *keys)');
            const dpy = XOpenDisplay(null);
            if (!dpy) throw new Error('XOpenDisplay failed');
            const keymap = Buffer.alloc(32);
            this.backend = {
                isDown: (keycode) => {
                    // XQueryKeymap writes directly into the shared Buffer
                    if (XQueryKeymap(dpy, keymap) !== 1) return null;
                    return (keymap[keycode >> 3] & (1 << (keycode & 7))) !== 0;
                },
                toCode: (codeName) => {
                    const keysym = x11KeysymName(codeName);
                    if (!keysym) return null;
                    const keycode = XKeysymToKeycode(
                        dpy, XStringToKeysym(keysym)
                    );
                    return keycode > 0 ? keycode : null;
                },
                destroy: () => { try { XCloseDisplay(dpy); } catch { /* noop */ } },
            };
        } else {
            throw new Error(`unsupported platform: ${this.platform}`);
        }
    }

    /**
     * Query the physical state of a key by Electron KeyboardEvent.code name
     * (e.g. 'Space', 'KeyA', 'Digit1').
     * Returns true/false, or null when the backend is unavailable or the
     * key name has no mapping on this platform.
     */
    isDown(codeName) {
        if (!this.isAvailable()) return null;
        const code = this.backend.toCode(codeName);
        if (code === null || code === undefined) return null;
        try {
            return this.backend.isDown(code);
        } catch (err) {
            Logger.warn(`KeyState: query failed for ${codeName}: ${err.message}`);
            return null;
        }
    }

    destroy() {
        if (this.backend && this.backend.destroy) this.backend.destroy();
        this.backend = null;
    }
}

module.exports = new KeyState();
