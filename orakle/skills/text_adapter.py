from newspaper import Article
from orakle.skill import Skill

class TextAdapter(Skill):
    def __init__(self):
        super().__init__()
        
    def start(self):
        pass
        
    def stop(self):
        pass
        
    def adapt_for_user(self, text, user_profile):
        """Extract and adapt text for a specific user profile"""
        article = Article("") # Empty URL since we already have the text
        article.download_state = 2  # Skip download
        article.html = text
        article.parse()
        
        return {
            "text": article.text,
            "user_profile": user_profile
        }
