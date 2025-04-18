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

from ainara.framework.skill import Skill


class HtmlWebpage(Skill):
    """Download the text of a website or webpage represented by a URL."""

    matcher_info = (
        "Download a webpage and extract its text content. Don't use this skill"
        " if the user is not explicitely asking for the download of the"
        " content of the website, eg query `Which is the website of company"
        " ACME` this skill DOESN'T APPLY, in that case we must return just the"
        " website URL. For a query `Download the website of company ACME` or"
        " `Download this page in this URL www.acme.com` this skill IT DOES"
        " APPLY, the user is requesting a website download."
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

    async def run(self, url, format="text"):
        """
        Downloads the text of a website or webpage represented by a URL.

        Args:
            - url: URL of the webpage to download and process.
            - format: The format of the returned output: html or text.
        Returns:
            Tumple containing:
                - url: URL of the webpage downloader and optionally processed.
                - output: Downloaded html or processed text.
        """
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