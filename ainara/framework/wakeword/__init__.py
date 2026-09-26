from ainara.framework.wakeword.base import WakeWordBackend
from ainara.framework.wakeword.openwakeword import OpenWakeWordBackend
from ainara.framework.config import ConfigManager


def create_wakeword_backend(config: ConfigManager) -> WakeWordBackend:
    """
    Factory function to create a wake word backend.
    Currently defaults to openWakeWord.
    """
    # In the future, we could switch based on config['wakeword']['backend']
    return OpenWakeWordBackend(config)
