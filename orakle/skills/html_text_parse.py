from newspaper import Article

from orakle.skill import Skill


class HtmlTextParse(Skill):
    def __init__(self):
        super().__init__()

    def start(self):
        pass

    def stop(self):
        pass

    def parse_html(self, text):
        """Extract article text from an HTML page"""
        article = Article("")  # Empty URL since we already have the text
        article.download_state = 2  # Skip download
        article.html = text
        article.parse()

        return {"text": article.text}