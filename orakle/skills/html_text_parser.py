from newspaper import Article

from ainara.framework.skill import Skill


class HtmlTextParser(Skill):
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
