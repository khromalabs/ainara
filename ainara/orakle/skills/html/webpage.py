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


import requests
import validators
from newspaper import Article
from typing import Dict, Any, Annotated, Literal

from ainara.framework.skill import Skill


class HtmlWebpage(Skill):
    """Download the text of a website or webpage represented by a URL."""

    matcher_info = (
        "Use ONLY when the user explicitly asks to download, fetch, get, retrieve,"
        " summarize, or analyze the CONTENT of a specific webpage or URL."
        " Keywords: download webpage, get website text, fetch URL content,"
        " extract text from page, summarize website, analyze page content."
        " DO NOT use if the user only asks FOR the URL itself (e.g., 'What is"
        " the website for X?'). Use ONLY if a specific URL is provided or"
        " clearly implied in the request for its content."
    )

    def __init__(self):
        super().__init__()

    def _download_url(self, url):
        """Helper function to download URL content"""
        try:
            response = requests.get(url)
            response.raise_for_status()
            response.encoding = "utf-8"
            return response.text
        except Exception as e:
            return None, str(e)

    def _extract_text(self, html_content):
        """Helper function to extract text from HTML content"""
        try:
            article = Article("")  # Empty URL since we already have the text
            article.download_state = 2  # Skip download
            article.html = html_content
            article.parse()
            return article.text
        except Exception as e:
            return None, str(e)

    async def run(
        self, 
        url: Annotated[
            str,
            "URL of the webpage to download and process"
        ],
        format: Annotated[
            Literal["text", "html"],
            "The format of the returned output: html or text"
        ] = "text"
    ) -> Dict[str, Any]:
        """Downloads the text of a website or webpage represented by a URL"""
        # Try adding https:// prefix if no protocol specified
        original_url = url
        if not url.startswith(("http://", "https://")):
            # First try https://
            https_url = f"https://{url}"
            if validators.url(https_url):
                url = https_url
            else:
                # If https validation fails, try http://
                http_url = f"http://{url}"
                if validators.url(http_url):
                    url = http_url
                else:
                    return {"error": f"Invalid URL: {original_url}"}

        # Validate URL
        if not validators.url(url):
            return {"error": f"The provided address is not a valid URL: {url}"}

        # Download the content
        html_content = self._download_url(url)
        if not html_content:
            return {"error": f"Failed to download content from {url}"}

        # Extract the text
        if format == "text":
            text = self._extract_text(html_content)
            if not text:
                return (
                    "ERROR: Failed to extract text from the downloaded content"
                )
            output = text
        else:
            output = html_content

        return {"url": url, "output": output}
