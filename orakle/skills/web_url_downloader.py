import requests
import validators

from orakle.skill import Skill


class WebUrlDownloader(Skill):
    def __init__(self):
        super().__init__()

    def start(self):
        pass

    def stop(self):
        pass

    async def download(self, url):
        """Download content from a URL"""
        if not validators.url(url):
            return {"error": "The provided address is not a valid URL"}

        try:
            response = requests.get(url)
            response.raise_for_status()
            return {"content": response.text}
        except Exception as e:
            return {"error": str(e)}
