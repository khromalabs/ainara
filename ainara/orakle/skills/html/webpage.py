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
from typing import Annotated, Any, Dict, Literal

import trafilatura
import validators
from ainara.framework.skill import Skill

logger = logging.getLogger(__name__)

try:
    from playwright.async_api import async_playwright

    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False


class HtmlWebpage(Skill):
    """Download the content of a web page from its URL."""

    matcher_info = (
        " Downloads, fetchs, gets or retrieves the content of a web page or"
        " website. DO NOT use this skill if the user only asks for the URL"
        " itself (e.g., 'What is the Google's website?'). Use it only, and"
        " particularly if the intention is to retrieve or access the content"
        " of an specific website.\n\n Keywords: download webpage, get website"
        " text, fetch URL content, extract text from page, summarize website,"
        " analyze page content, read page content."
    )

    def __init__(self):
        super().__init__()

    async def run(
        self,
        url: Annotated[str, "URL of the webpage to download and process"],
        format: Annotated[
            Literal["text", "html"],
            "The format of the returned output: html or text",
        ] = "html",
        render_js: Annotated[
            bool,
            "Whether to use a headless browser to render JavaScript. Set to"
            " True for Single Page Applications (SPAs), sites with dynamically"
            " loaded content, or when the default extraction returns"
            " insufficient content. Default False uses fast static HTML"
            " extraction. True is slower but handles JS-heavy sites.",
        ] = False,
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

        # Download and extract content
        try:
            if render_js and PLAYWRIGHT_AVAILABLE:
                # Use playwright for JS-rendered content
                async with async_playwright() as p:
                    browser = await p.chromium.launch(headless=True)
                    page = await browser.new_page()
                    await page.goto(
                        url, wait_until="networkidle", timeout=20000
                    )

                    if format == "html":
                        output = await page.content()
                    else:
                        output = await page.inner_text("body")

                    await browser.close()
            else:
                if render_js:
                    logger.warning(
                        "render_js required but no PLAYWRIGHT_AVAILABLE"
                    )
                # Use trafilatura for fast static extraction
                downloaded = trafilatura.fetch_url(url)
                if not downloaded:
                    return {"error": f"Failed to download content from {url}"}

                if format == "html":
                    output = downloaded
                else:
                    output = trafilatura.extract(
                        downloaded, include_comments=False, include_tables=True
                    )
                    if not output:
                        return {
                            "error": (
                                "Failed to extract text from the downloaded"
                                " content"
                            )
                        }

            return {"url": url, "output": output}

        except Exception as e:
            return {"error": f"Error processing {url}: {str(e)}"}
