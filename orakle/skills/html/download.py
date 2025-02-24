# Ainara - Open Source AI Assistant Framework
# Copyright (C) 2025 Rubén Gómez http://www.khromalabs.org

# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, see
# <https://www.gnu.org/licenses/>.

import requests
import validators

from ainara.framework.skill import Skill


class HtmlDownload(Skill):
    def __init__(self):
        super().__init__()

    def _download_url(self, url):
        """Helper function to download and process URL content"""
        try:
            response = requests.get(url)
            response.raise_for_status()
            response.encoding = 'utf-8'
            return {"content": response.text}
        except Exception as e:
            return {"error": str(e)}

    async def run(self, url):
        """Download content from a URL"""
        # Try adding https:// prefix if no protocol specified
        if not url.startswith(('http://', 'https://')):
            # First try https://
            https_url = f"https://{url}"
            if validators.url(https_url):
                result = self._download_url(https_url)
                if "content" in result:
                    return result

                # If https fails, try http://
                http_url = f"http://{url}"
                if validators.url(http_url):
                    result = self._download_url(http_url)
                    if "content" in result:
                        return result
                    return {"error": "Failed to download with both http and https prefixes"}
                return {"error": "Invalid URL with http prefix"}
            return {"error": "Invalid URL even with http/https prefixes"}

        # Original URL validation and download if protocol is already specified
        if not validators.url(url):
            return {"error": "The provided address is not a valid URL"}

        return self._download_url(url)
