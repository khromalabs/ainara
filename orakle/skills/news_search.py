from newsapi import NewsApiClient
from orakle.framework.skill import Skill

SUPPORTED_LANGUAGES = {
    'ar', 'de', 'en', 'es', 'fr', 'he', 'it', 'nl', 'no', 'pt', 'ru', 'sv', 'zh'
}


class NewsSearch(Skill):
    """Skill for searching news articles using NewsAPI"""

    def __init__(self):
        super().__init__()
        # api_key = os.getenv('NEWSAPI_KEY')
        api_key = "f7a41568e4cd4a2ab5e8aefed810fa6b"
        if not api_key:
            raise ValueError("NEWSAPI_KEY environment variable is required")
        self.newsapi = NewsApiClient(api_key=api_key)

    async def run(
        self, query: str, language: str = "en", sort_by: str = "relevancy"
    ):
        """
        Search for news articles matching the query

        Args:
            query: Search query string
            language: Language code (default: 'en'). Must be one of: ar, de, en, es, fr, he, it, nl, no, pt, ru, sv, zh
            sort_by: Sort order ('relevancy', 'popularity', 'publishedAt')

        Returns:
            Dict containing search results
        """
        # Validate language code
        language = language.lower()
        if language not in SUPPORTED_LANGUAGES:
            return {
                "status": "error",
                "message": f"Invalid language code. Must be one of: {', '.join(sorted(SUPPORTED_LANGUAGES))}"
            }
        try:
            response = self.newsapi.get_everything(
                q=query, language=language, sort_by=sort_by
            )

            # Format the results
            articles = []
            for article in response["articles"][:5]:  # Limit to top 5 results
                articles.append(
                    {
                        "title": article["title"],
                        "description": article["description"],
                        "url": article["url"],
                        "source": article["source"]["name"],
                        "published": article["publishedAt"],
                    }
                )

            return {
                "status": "success",
                "total_results": len(articles),
                "articles": articles,
            }

        except Exception as e:
            return {"status": "error", "message": str(e)}
