import json
from typing import Dict

from requests import Session
from requests.exceptions import RequestException

from ainara.framework.config import config
from ainara.framework.skill import Skill
# from ainara.framework.logging_setup import logger


class CryptoCoinmarketcap(Skill):
    """Gives real time current valuations of cryptocurrencies accesing the CoinMarketCap site API"""

    if not config.get("apis.crypto.coinmarketcap_api_key"):
        hiddenCapability = True

    matcher_info = (
        "Not valid for regular market stock options, only provides info related with cryptocurrencies. This skill only provides real time, current valuations of cryptocurrencies, not historical valuations."
    )

    def __init__(self):
        super().__init__()
        self.name = "crypto_market_cap"
        self.base_url = "https://pro-api.coinmarketcap.com/v1"
        self.session = Session()
        self.api_key = config.get("apis.crypto.coinmarketcap_api_key")

    async def run(
        self,
        symbol: str = "BTC",
        convert: str = "USD",
    ) -> Dict:
        """
        Get current price and market data for a cryptocurrency.

        Args:
            symbol: Cryptocurrency symbol (e.g. BTC, ETH).
            convert: Currency to convert to (e.g. USD, EUR).

        Returns:
            Dict containing price and market data.
        """

        if not self.api_key:
            raise ValueError("CoinMarketCap API key is required")

        try:
            # Set up headers with API key
            self.session.headers.update(
                {"X-CMC_PRO_API_KEY": self.api_key, "Accept": "application/json"}
            )

            # Make API request
            response = self.session.get(
                f"{self.base_url}/cryptocurrency/quotes/latest",
                params={"symbol": symbol.upper(), "convert": convert.upper()},
            )
            response.raise_for_status()
            data = response.json()

            # Extract relevant data
            crypto_data = data["data"][symbol.upper()]
            quote = crypto_data["quote"][convert.upper()]

            return {
                "name": crypto_data["name"],
                "symbol": crypto_data["symbol"],
                "price": quote["price"],
                "volume_24h": quote["volume_24h"],
                "market_cap": quote["market_cap"],
                "percent_change_24h": quote["percent_change_24h"],
                "last_updated": quote["last_updated"],
            }

        except RequestException as e:
            raise RuntimeError(
                f"Failed to fetch cryptocurrency data: {str(e)}"
            )
        except (KeyError, json.JSONDecodeError) as e:
            raise RuntimeError(
                f"Failed to parse cryptocurrency data: {str(e)}"
            )
        finally:
            self.session.close()
