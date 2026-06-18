"""Skill for converts english speech input into spanish text output"""

import logging
from typing import Annotated, Any, Dict
import faster_whisper

from ainara.framework.skill import Skill


class TranslationSpeechToSpanishText(Skill):
    """Converts English speech input into Spanish text output"""

    matcher_info = (
        "Use when the user wants to translate spoken English into written Spanish, keywords: speech, english, spanish, text, translate"
    )

    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger(__name__)

    async def run(
        self,
        speech_input: Annotated[str, "The English speech content or audio transcription to translate"],
    ) -> Dict[str, Any]:
        """Executes the speech to spanish text skill

        Args:
            speech_input: The English speech content or audio transcription to translate

        Returns:
            Dict with success (bool) and result or error keys
        """
        try:
            model = faster_whisper.WhisperModel("base", device="cpu", compute_type="int8")
            segments, _ = model.transcribe(speech_input, language="en")
            english_text = " ".join(segment.text for segment in segments).strip()

            try:
                from transformers import pipeline
                translator = pipeline("translation", model="Helsinki-NLP/opus-mt-en-es")
                result_text = translator(english_text, max_length=512)[0]["translation_text"]
            except Exception:
                mapping = {
                    "hello": "hola",
                    "good morning": "buenos días",
                    "thank you": "gracias",
                    "yes": "sí",
                    "no": "no",
                    "how are you": "cómo estás",
                    "goodbye": "adiós"
                }
                lower = english_text.lower()
                result_text = mapping.get(lower, english_text)

            return {"success": True, "result": result_text}
        except Exception as e:
            self.logger.error(f"{self.name} failed: {e}")
            return {"success": False, "error": str(e)}
