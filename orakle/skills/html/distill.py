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

from newspaper import Article

from ainara.framework.skill import Skill


class HtmlDistill(Skill):
    def __init__(self):
        super().__init__()

    def run(self, text):
        """Extract article text from an HTML page"""
        # Handle input whether it's a dictionary or direct text
        if isinstance(text, dict):
            html_content = text.get('content', '')
        else:
            html_content = text

        article = Article("")  # Empty URL since we already have the text
        article.download_state = 2  # Skip download
        article.html = html_content.encode('utf-8').decode('utf-8')
        article.parse()

        return {"text": article.text}
