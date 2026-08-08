let initialized = false;

function init(ctx) {
    if (initialized) return;
    initialized = true;

    const config = ctx.config;
    const modifiedFields = ctx.modifiedFields;
    if (!modifiedFields.shortcuts) modifiedFields.shortcuts = new Set();

    const showInput = document.getElementById('show-shortcut');
    const hideInput = document.getElementById('hide-shortcut');
    const triggerInput = document.getElementById('trigger-shortcut');
    const showDisplay = document.getElementById('show-key-display');
    const hideDisplay = document.getElementById('hide-key-display');
    const triggerDisplay = document.getElementById('trigger-key-display');

    if (!showInput || !hideInput || !triggerInput || !showDisplay || !hideDisplay || !triggerDisplay) {
        return;
    }

    const currentShow = config.get('shortcuts.show', 'F1');
    const currentHide = config.get('shortcuts.hide', 'Escape');
    const currentTrigger = config.get('shortcuts.trigger', 'Space');

    showInput.value = currentShow;
    hideInput.value = currentHide;
    triggerInput.value = currentTrigger;
    showDisplay.textContent = currentShow;
    hideDisplay.textContent = currentHide;
    triggerDisplay.textContent = currentTrigger;

    function captureKey(input, displayElement) {
        input.addEventListener('focus', () => {
            input.value = 'Press a key...';
            input.classList.add('capturing');
        });

        input.addEventListener('blur', () => {
            if (input.value === 'Press a key...') {
                input.value = displayElement.textContent;
            }
            input.classList.remove('capturing');
        });

        input.addEventListener('keydown', (e) => {
            e.preventDefault();

            let keyName;
            if (e.key === ' ') {
                keyName = 'Space';
            } else if (e.key === 'Escape') {
                keyName = displayElement.textContent;
            } else {
                keyName = e.key;
            }

            if (e.ctrlKey && e.key !== 'Control') keyName = 'Ctrl+' + keyName;
            if (e.altKey && e.key !== 'Alt') keyName = 'Alt+' + keyName;
            if (e.shiftKey && e.key !== 'Shift') keyName = 'Shift+' + keyName;

            input.value = keyName;
            displayElement.textContent = keyName;
            input.blur();
        });
    }

    captureKey(showInput, showDisplay);
    captureKey(hideInput, hideDisplay);
    captureKey(triggerInput, triggerDisplay);

    showInput.addEventListener('input', () => {
        showDisplay.textContent = showInput.value;
        modifiedFields.shortcuts.add('show-shortcut');
    });

    hideInput.addEventListener('input', () => {
        hideDisplay.textContent = hideInput.value;
        modifiedFields.shortcuts.add('hide-shortcut');
    });

    triggerInput.addEventListener('input', () => {
        triggerDisplay.textContent = triggerInput.value;
        modifiedFields.shortcuts.add('trigger-shortcut');
    });
}

function save(ctx) {
    const modifiedFields = ctx.modifiedFields;
    if (!modifiedFields.shortcuts || modifiedFields.shortcuts.size === 0) {
        return true;
    }

    try {
        const showShortcut = document.getElementById('show-shortcut').value.trim();
        const hideShortcut = document.getElementById('hide-shortcut').value.trim();
        const triggerShortcut = document.getElementById('trigger-shortcut').value.trim();

        if (showShortcut && modifiedFields.shortcuts.has('show-shortcut')) {
            ctx.config.set('shortcuts.show', showShortcut);
        }
        if (hideShortcut && modifiedFields.shortcuts.has('hide-shortcut')) {
            ctx.config.set('shortcuts.hide', hideShortcut);
        }
        if (triggerShortcut && modifiedFields.shortcuts.has('trigger-shortcut')) {
            ctx.config.set('shortcuts.trigger', triggerShortcut);
        }

        ctx.config.saveConfig();
        modifiedFields.shortcuts.clear();
        return true;
    } catch (error) {
        console.error('Error saving shortcuts config:', error);
        return false;
    }
}

module.exports = { id: 'shortcuts', init, save };
