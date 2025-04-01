from abc import ABC, abstractmethod
import logging
import re
from typing import Tuple


class TTSBackend(ABC):
    """Abstract base class for Text-to-Speech backends"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    @abstractmethod
    def speak(self, text: str) -> bool:
        """Convert text to speech

        Args:
            text: The text to convert to speech

        Returns:
            bool: True if successful, False otherwise
        """
        pass

    @abstractmethod
    def stop(self) -> bool:
        """Stop current speech

        Returns:
            bool: True if successful, False otherwise
        """
        pass

    @abstractmethod
    def generate_audio(self, text: str) -> Tuple[str, float]:
        """Generate audio file for text and return its path and duration

        Args:
            text: The text to convert to speech

        Returns:
            Tuple[str, float]: Path to generated audio file and its duration in seconds
        """
        pass

    @abstractmethod
    def play_audio(self, audio_file: str) -> bool:
        """Play audio file asynchronously

        Args:
            audio_file: Path to audio file to play

        Returns:
            bool: True if playback started successfully, False otherwise
        """
        pass

    def _clean_text(self, text: str) -> str:
        """Clean text for better TTS readability

        Args:
            text: Text to clean

        Returns:
            str: Cleaned text optimized for speech
        """
        # Remove code blocks
        text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
        
        # Remove emoji characters
        import emoji
        text = emoji.replace_emoji(text, replace='')
        self.logger.debug("Removed emoji characters from text")

        # Try to use normalise library if available
        try:
            from normalise import normalise
            text = ' '.join(normalise(text, verbose=False))
            self.logger.debug("Used normalise library for text normalization")
        except ImportError:
            self.logger.debug("normalise library not available, using custom rules")

            # Replace common abbreviations
            abbreviations = {
                "e.g.": "for example",
                "i.e.": "that is",
                "etc.": "etcetera",
                "vs.": "versus",
                "Fig.": "Figure",
                "fig.": "figure",
            }
            for abbr, expansion in abbreviations.items():
                text = text.replace(abbr, expansion)

            # Handle numbers with units more naturally
            text = re.sub(r'(\d+)x(\d+)', r'\1 by \2', text)  # Dimensions
            text = re.sub(r'(\d+)([kKmMgGtT]?[bB])', r'\1 \2', text)  # File sizes

            # Handle version numbers more naturally
            text = re.sub(r'v(\d+\.\d+(?:\.\d+)?)', r'version \1', text)

        # Always apply these rules regardless of which library was used

        # Handle large numbers for better readability
        def format_large_number(match):
            num_str = match.group(0).replace(',', '')
            # Skip if this is part of our specially formatted decimal or scientific notation
            if "point" in num_str or "times 10" in num_str:
                return num_str
            try:
                num = float(num_str)
                if num >= 1_000_000_000_000:  # Trillion
                    return f"{num / 1_000_000_000_000:.1f} trillion".replace('.0 ', ' ')
                elif num >= 1_000_000_000:  # Billion
                    return f"{num / 1_000_000_000:.1f} billion".replace('.0 ', ' ')
                elif num >= 1_000_000:  # Million
                    return f"{num / 1_000_000:.1f} million".replace('.0 ', ' ')
                elif num >= 10_000:  # Thousand
                    return f"{num / 1_000:.1f} thousand".replace('.0 ', ' ')
                return match.group(0)
            except ValueError:
                return match.group(0)

        # Handle long decimal numbers
        def simplify_decimal(match):
            full_decimal = match.group(0)
            integer_part = match.group(1) or "0"
            decimal_part = match.group(2)

            # If decimal part is longer than 4 digits, process it
            if len(decimal_part) > 4:
                # Count leading zeros
                leading_zeros = 0
                for char in decimal_part:
                    if char == '0':
                        leading_zeros += 1
                    else:
                        break

                # Get the first non-zero digit and the next digit for scientific notation
                first_non_zero_idx = leading_zeros
                if first_non_zero_idx < len(decimal_part):
                    first_non_zero = decimal_part[first_non_zero_idx]
                    second_digit = decimal_part[first_non_zero_idx + 1] if first_non_zero_idx + 1 < len(decimal_part) else "0"
                else:
                    # All zeros in decimal part
                    return f"{integer_part} point zero"

                # Use scientific notation for very small numbers (more than 3 leading zeros)
                if leading_zeros > 3:
                    # Format as scientific notation: "2.3 times 10 to the negative 5th power"
                    exponent = leading_zeros + 1
                    if second_digit != "0":
                        return f"{first_non_zero} point {second_digit} times 10 to the negative {exponent}th power"
                    else:
                        return f"{first_non_zero} times 10 to the negative {exponent}th power"
                else:
                    # For moderately small numbers, keep digit-by-digit approach
                    # Keep leading zeros plus 2 significant digits
                    significant_digits = min(2, len(decimal_part) - leading_zeros)
                    total_to_keep = leading_zeros + significant_digits

                    # Format with spaces for digit-by-digit reading
                    formatted_decimal = ""
                    for digit in decimal_part[:total_to_keep]:
                        formatted_decimal += f" {digit}"
                    return f"{integer_part} point{formatted_decimal}"

            return full_decimal

        # First handle decimal numbers
        text = re.sub(r'(\d+)?\.(\d{5,})', simplify_decimal, text)

        # Match numbers with or without commas, avoiding decimal numbers and our specially formatted text
        # Use a more compatible regex approach without variable-width lookbehind
        text = re.sub(r'\b\d{1,3}(?:,\d{3})+\b|\b\d{5,}\b',
                      lambda m: format_large_number(m) if not re.search(r'^\d*\.\d+$|^\d+\.\d*$', m.group(0)) and 
                                                          "point" not in m.group(0) and 
                                                          "times 10" not in m.group(0) else m.group(0),
                      text)

        # Handle long alphanumeric codes
        def truncate_long_code(match):
            code = match.group(0)
            # Check if it looks like a hash (all hex digits)
            if re.match(r'^[0-9a-f]+$', code.lower()):
                return f"{code[:6]}... [hash]"
            return f"{code[:6]}... [etcetera]"

        # Match alphanumeric strings that are at least 12 chars long with both letters and numbers
        text = re.sub(
            r'\b[a-zA-Z0-9]{12,}\b',
            lambda m: truncate_long_code(m) if re.search(r'[a-zA-Z]', m.group(0)) and re.search(r'[0-9]', m.group(0)) else m.group(0),
            text
        )

        # Handle URLs - replace with just the domain name
        text = re.sub(
            r'https?://(?:www\.)?([a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)+)(?:/[^\s]*)?',
            r'\1',
            text
        )

        # Handle email addresses
        text = re.sub(r'\S+@\S+\.\S+', "email address", text)

        # Handle file paths - simplify to just filename
        text = re.sub(r'(?:/|\\)(?:[^/\\]+(?:/|\\))*([^/\\]+)', r'\1', text)

        # Remove markdown symbols
        text = re.sub(r'[*#_~`]', '', text)

        return text
