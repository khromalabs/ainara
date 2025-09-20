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


import logging
import webbrowser
from typing import Annotated, Any, Dict, Optional
from urllib.parse import urlparse

from ainara.framework.skill import Skill

logger = logging.getLogger(__name__)


class SystemUrlopener(Skill):
    """Open or launch one URL or several URLs addresses in the system browser"""

    # embeddings_boost_factor = 1.5

    matcher_info = (
        "Use this skill when the user wants to open or launch a URL or"
        " multiple URLs in the system browser. This skill can handle web"
        " addresses, local file paths, and other supported protocols like FTP."
        "\n\n"
        " Examples include: 'open example.com', 'launch github.com and"
        " stackoverflow.com', 'open file:///home/user/doc.pdf', 'go to"
        " google.com'. Keywords: open, launch, go to, browse, URL, web,"
        " website, link, address, browser, file, local, http, https, ftp."
    )

    def __init__(self):
        super().__init__()
        self.supported_protocols = ["http", "https", "ftp", "file"]

    def _validate_url(self, url: str) -> bool:
        """
        Validate that the URL is properly formatted and uses a supported protocol

        Args:
            url: The URL to validate

        Returns:
            bool: True if the URL is valid, False otherwise
        """
        # Basic URL validation
        if not url or not isinstance(url, str):
            return False

        # Check for proper URL format
        try:
            parsed = urlparse(url)

            # Check if the URL has a scheme and netloc (domain)
            if not parsed.scheme or not parsed.netloc:
                # Special case for file:// URLs which might not have netloc
                if parsed.scheme == "file" and parsed.path:
                    return True
                return False

            # Check if the protocol is supported
            if parsed.scheme and parsed.scheme not in self.supported_protocols:
                return False

            return True
        except Exception as e:
            logger.error(f"Error validating URL: {e}")
            return False

    def _parse_urls(self, url_string: str) -> list:
        """
        Parse a string containing multiple URLs separated by spaces, commas, or pipes

        Args:
            url_string: String containing one or more URLs

        Returns:
            list: List of individual URLs
        """
        if not url_string or not isinstance(url_string, str):
            return []

        # Split by common separators (comma, space, pipe)
        urls = []
        for separator in [",", " ", "|"]:
            if separator in url_string:
                urls = [
                    u.strip() for u in url_string.split(separator) if u.strip()
                ]
                if urls:
                    break

        # If no separators found, treat as single URL
        if not urls:
            urls = [url_string.strip()]

        # Add http:// prefix to URLs that don't have a scheme
        processed_urls = []
        for url in urls:
            if "://" not in url and url.strip():
                # If URL starts with www. or contains a dot, assume it's a web URL
                if url.startswith("www.") or "." in url:
                    url = "http://" + url
            processed_urls.append(url)

        return processed_urls

    async def run(
        self,
        url: Annotated[
            str,
            "A single URL or multiple URLs separated by spaces, commas, or"
            " pipes",
        ],
        force: Annotated[
            Optional[bool], "Skip URL validation if set to True"
        ] = False,
    ) -> Dict[str, Any]:
        """Opens one or more URLs in the system browser or assigned application

        Examples:
            "https://www.example.com" → Opens example.com in default browser.
            "http://127.0.0.1:8080" → Opens local development server.
            "file:///home/user/doc.pdf" → Opens PDF in default application.
            "google.com,microsoft.com" → Opens both sites in separate tabs.
            "github.com | stackoverflow.com" → Opens both sites in separate tabs.
        """
        try:
            # Parse URLs from input string
            urls = self._parse_urls(url)

            if not urls:
                return {
                    "success": False,
                    "error": "No valid URLs provided",
                    "details": "Please provide at least one URL",
                }

            results = []
            success_count = 0

            # Process each URL
            for single_url in urls:
                # Validate URL unless force is True
                if not force and not self._validate_url(single_url):
                    results.append(
                        {
                            "url": single_url,
                            "success": False,
                            "error": (
                                "Invalid URL format or unsupported protocol"
                            ),
                        }
                    )
                    continue

                # Open the URL in the default browser
                browser_opened = webbrowser.open(single_url)

                if browser_opened:
                    results.append({"url": single_url, "success": True})
                    success_count += 1
                else:
                    results.append(
                        {
                            "url": single_url,
                            "success": False,
                            "error": "Failed to open URL",
                        }
                    )

            # Prepare the overall result
            if success_count == len(urls):
                return {
                    "success": True,
                    "message": (
                        f"Successfully opened {success_count} URL(s) in"
                        " default browser"
                    ),
                    "urls": urls,
                    "details": results,
                }
            elif success_count > 0:
                return {
                    "success": True,
                    "message": (
                        f"Opened {success_count} out of {len(urls)} URLs"
                    ),
                    "urls": urls,
                    "details": results,
                }
            else:
                return {
                    "success": False,
                    "error": "Failed to open any URLs",
                    "details": results,
                }

        except Exception as e:
            logger.error(f"Error opening URL(s): {e}")
            return {
                "success": False,
                "error": "Error opening URL(s)",
                "details": str(e),
            }
