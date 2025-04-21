# Ainara AI Companion Framework Project
# Copyright (C) 2025 Rubén Gómez - khromalabs.org
#
# This file is dual-licensed under:
# 1. GNU Lesser General Public License v3.0 (LGPL-3.0)
#    (See the included LICENSE_LGPL3.txt file or look into
#    <https://www.gnu.org/licenses/lgpl-3.0.html> for details)
# 2. Commercial license
#    (Contact: rgomez@khromalabs.org for licensing options)
#
# You may use, distribute and modify this code under the terms of either license.
# This notice must be preserved in all copies or substantial portions of the code.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
# Lesser General Public License for more details.


import getopt
import os
import signal
import sys
from datetime import datetime

import requests
import setproctitle
from colorama import Fore, init
from prompt_toolkit import prompt
from prompt_toolkit.styles import Style

# # Suppress pydantic warning about config keys
# import warnings
# warnings.filterwarnings(
#     "ignore", message="Valid config keys have changed in V2:*"
# )

from ainara.framework.chat_manager import ChatManager
from ainara.framework.config import ConfigManager
from ainara.framework.llm import create_llm_backend
from ainara.framework.logging_setup import logging_manager
from ainara.framework.stt.whisper import WhisperSTT
from ainara.framework.tts.piper import PiperTTS

config_manager = ConfigManager()
config_manager.load_config()

# Get Orakle servers from config
ORAKLE_SERVERS = config_manager.get(
    "orakle.servers", ["http://127.0.0.1:5000"]
)

init()

# Set up logging first, before any logger calls
logging_manager.setup(log_dir="/tmp", log_level="INFO", log_filter="kommander")
# Get logger after setup
logger = logging_manager.logger

# Comment this line to disable the automatic chat backup
BACKUP = f"/tmp/kommander_ai_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
CHAT = []

# Initialize config
config_manager = ConfigManager()
config_manager.load_config()

# Initialize LLM
llm_config = config_manager.get("llm", {})
llm = create_llm_backend(llm_config)


def find_working_provider():
    providers = config_manager.get("llm.providers", [])
    for provider in providers:
        try:
            # Check if the provider's API base is reachable
            response = requests.head(provider["api_base"])
            if response.status_code == 200:
                return provider
        except requests.RequestException:
            continue
    print("No working LLM provider found, exiting...")
    sys.exit(1)


def parse_arguments():
    model = os.environ.get("AI_API_MODEL")
    light_mode = False
    strip_mode = False
    log_dir = None
    log_level = "INFO"
    speak_mode = False
    output_module = None
    voice_input = False
    usage = (
        f"Usage: {os.path.basename(__file__)} [-l|--light] [-m|--model"
        " LLM_MODEL] [-s|--strip] [--log-dir DIR] [--log-level LEVEL]"
        " [--voice] [--output-module MODULE]\n\n-l|--light          Use"
        " colors for light themes\n-m|--model          Model as specified in"
        " the LLMLite definitions\n-s|--strip          Strip everything"
        " except code blocks in non-interactive mode\n--log-dir DIR      "
        " Directory for log files\n--log-level LEVEL   Logging level"
        " (DEBUG,INFO,WARNING,ERROR,CRITICAL)\n--voice             Enable"
        " text-to-speech output\n--output-module MOD Speech output module to"
        " use\n\nFirst message can be sent also with a stdin pipe which will"
        " be processed in non-interactive mode\n"
    )
    try:
        opts, _ = getopt.getopt(
            sys.argv[1:],
            "hlms",
            [
                "help",
                "light",
                "model=",
                "strip",
                "log-dir=",
                "log-dir=",
                "log-level=",
                "voice",
                "voice-input",
                "output-module=",
            ],
        )
        for opt, arg in opts:
            if opt in ("-h", "--help"):
                print(usage)
                sys.exit()
            if opt in ("-l", "--light"):
                light_mode = True
            if opt in ("-m", "--model"):
                if not model:
                    model = arg
            if opt in ("-s", "--strip"):
                strip_mode = True
            if opt == "--log-dir":
                log_dir = arg
            if opt == "--log-level":
                log_level = arg.upper()
            if opt == "--voice":
                speak_mode = True
            if opt in ("-o", "--output-module"):
                output_module = arg
            if opt == "--voice-input":
                voice_input = True
    except getopt.GetoptError as err:
        print(err)
        sys.exit(2)
    return (
        model,
        light_mode,
        strip_mode,
        log_dir,
        log_level,
        speak_mode,
        output_module,
        voice_input,
    )


def trim(s):
    return s.strip()


def backup(content):
    if "BACKUP" in globals() and BACKUP:
        with open(BACKUP, "a") as f:
            f.write(content + "\n")
            f.close()


def signal_handler(sig, frame):
    print(f"{signal.Signals(sig).name} caught, exiting...")
    sys.exit(0)


def extract_code_blocks(text):
    blocks = []
    in_block = False
    current_block = []

    for line in text.split("\n"):
        if line.strip().startswith("```"):
            if in_block:
                in_block = False
            else:
                in_block = True
            continue

        if in_block:
            current_block.append(line)
        elif current_block:
            blocks.append("\n".join(current_block))
            current_block = []

    if current_block:  # Handle case where text ends while still in a block
        blocks.append("\n".join(current_block))

    return "\n\n".join(blocks)


def main():
    global PROVIDER
    (
        model_override,
        light_mode,
        strip_mode,
        log_dir,
        log_level,
        speak_mode,
        output_module,
        voice_input,
    ) = parse_arguments()

    if log_dir or log_level != "INFO":
        logging_manager.setup(
            log_dir=log_dir, log_level=log_level, log_filter="kommander"
        )
    # logger.debug(f"SYSTEM_MESSAGE: {SYSTEM_MESSAGE}")

    # Initialize TTS if voice mode enabled
    tts = None
    stt = None

    if speak_mode:
        logger.debug("Initializing TTS in voice mode")
        try:
            tts = PiperTTS()
            logger.debug("TTS initialization successful")
            if log_level == "DEBUG":
                logger.debug("Testing TTS with a short phrase")
                test_result = tts.speak("TTS test")
                if not test_result:
                    logger.error("TTS test failed")
                    speak_mode = False
                else:
                    logger.info("TTS test successful")
        except RuntimeError as e:
            logger.error(f"Could not initialize speech: {e}")
            print(f"Warning: Could not initialize speech: {e}")
            speak_mode = False

    # Initialize STT if voice input enabled
    if voice_input:
        logger.debug("Initializing Speech-to-Text")
        try:
            stt = WhisperSTT()
            logger.debug("STT initialization successful")
        except Exception as e:
            logger.error(f"Could not initialize speech-to-text: {e}")
            print(f"Warning: Could not initialize speech-to-text: {e}")
            voice_input = False

    if model_override:
        PROVIDER = {"model": model_override, "api_base": None, "api_key": None}
    else:
        PROVIDER = find_working_provider()

    # Initialize ChatManager
    chat_manager = ChatManager(
        llm=llm,
        orakle_servers=ORAKLE_SERVERS,
        # backup_file=BACKUP if "BACKUP" in globals() else None,
        tts=tts,
    )

    setproctitle.setproctitle(os.path.basename(__file__))
    signal.signal(signal.SIGINT, signal_handler)
    prompt_style = Style.from_dict(
        {
            "": "#006600" if light_mode else "#00ff00",
        }
    )

    # Check if input is coming from a pipe (non-interactive)
    if not sys.stdin.isatty():
        initial_message = sys.stdin.read().strip()
        if initial_message:
            # chat_manager.backup(f"> {initial_message}")
            response = chat_manager.chat_completion(
                initial_message, stream=False
            )
            if strip_mode:
                print(extract_code_blocks(response), end="")
            else:
                print()
        # Exit after processing the piped input
        sys.stdin.close()
        sys.stdout.flush()
        return

    # Interactive mode
    while True:
        try:
            if voice_input:
                print(
                    f"{Fore.GREEN}Press Enter to start voice input (or type"
                    f" text):{Fore.RESET}"
                )
                user_input = prompt("> ", style=prompt_style).strip()
                if not user_input:
                    # Empty input triggers voice recording
                    question = stt.listen()
                    print(f"{Fore.GREEN}{question}{Fore.RESET}")
                else:
                    question = user_input
            else:
                question = prompt("> ", style=prompt_style).strip()
            if not question:
                continue
            # chat_manager.backup(f"> {question}")
            response = chat_manager.chat_completion(question, stream=True)
            print()
        except KeyboardInterrupt:
            signal_handler(signal.SIGINT, 0)
            break


if __name__ == "__main__":
    main()
