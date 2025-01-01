from newspaper import Article

from orakle.framework.skill import Skill


class HtmlTextParse(Skill):
    def __init__(self):
        super().__init__()

    def start(self):
        pass

    def stop(self):
        pass

    def run(self, text):
        """Extract article text from an HTML page"""
        # Handle input whether it's a dictionary or direct text
        if isinstance(text, dict):
            html_content = text.get('text', '')
        else:
            html_content = text
        
        article = Article("")  # Empty URL since we already have the text
        article.download_state = 2  # Skip download
        article.html = html_content
        article.parse()

        return {"text": article.text}
