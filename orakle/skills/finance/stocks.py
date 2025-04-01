import logging
from typing import Any, Dict, List, Optional

import requests

from ainara.framework.config import config
from ainara.framework.skill import Skill


class FinanceStocks(Skill):
    """Get stock market information"""

    matcher_info = (
        "Valid only for queries in which the user asks about last day's or"
        " yesterday's stock share value, a general report about a stock share"
        " whenever the user query has no time or date constrains, or for which"
        " is the symbol for some stock share. Only use this skill for stock"
        " queries."
    )

    def __init__(self):
        super().__init__()
        self.name = "stocks"
        self.logger = logging.getLogger(__name__)
        self.base_url = "https://www.alphavantage.co/query"

    def get_api_key(self) -> Optional[str]:
        """Get Alpha Vantage API key from config"""
        api_key = config.get("apis.finance.alphavantage_api_key")
        if not api_key:
            self.logger.error("Alpha Vantage API key not configured")
        return api_key

    async def get_quote(self, symbol: str) -> Dict[str, Any]:
        """Get current stock quote information"""
        api_key = self.get_api_key()
        if not api_key:
            return {"error": "Alpha Vantage API key not configured"}

        try:
            params = {
                "function": "GLOBAL_QUOTE",
                "symbol": symbol,
                "apikey": api_key,
            }

            response = requests.get(self.base_url, params=params)

            if response.status_code == 200:
                data = response.json()

                # Check for error messages
                if "Error Message" in data:
                    return {"error": data["Error Message"]}

                # Check if we got the expected data
                if "Global Quote" in data and data["Global Quote"]:
                    quote = data["Global Quote"]
                    return {
                        "symbol": quote.get("01. symbol", symbol),
                        "price": float(quote.get("05. price", 0)),
                        "change": float(quote.get("09. change", 0)),
                        "change_percent": quote.get(
                            "10. change percent", "0%"
                        ),
                        "volume": int(quote.get("06. volume", 0)),
                        "latest_trading_day": quote.get(
                            "07. latest trading day", ""
                        ),
                        "previous_close": float(
                            quote.get("08. previous close", 0)
                        ),
                        "open": float(quote.get("02. open", 0)),
                        "high": float(quote.get("03. high", 0)),
                        "low": float(quote.get("04. low", 0)),
                    }

                return {"error": "No data found for the symbol"}

            return {
                "error": (
                    "API request failed with status code:"
                    f" {response.status_code}"
                )
            }

        except Exception as e:
            self.logger.error(f"Error getting stock quote: {str(e)}")
            return {"error": f"Failed to get stock data: {str(e)}"}

    async def get_company_overview(self, symbol: str) -> Dict[str, Any]:
        """Get company overview information"""
        api_key = self.get_api_key()
        if not api_key:
            return {"error": "Alpha Vantage API key not configured"}

        try:
            params = {
                "function": "OVERVIEW",
                "symbol": symbol,
                "apikey": api_key,
            }

            response = requests.get(self.base_url, params=params)

            if response.status_code == 200:
                data = response.json()

                # Check for error messages
                if "Error Message" in data:
                    return {"error": data["Error Message"]}

                # If we got an empty response or just a few fields
                if len(data) <= 1:
                    return {
                        "error": "No company information found for the symbol"
                    }

                # Return relevant company information
                return {
                    "symbol": data.get("Symbol", symbol),
                    "name": data.get("Name", ""),
                    "description": data.get("Description", ""),
                    "exchange": data.get("Exchange", ""),
                    "industry": data.get("Industry", ""),
                    "sector": data.get("Sector", ""),
                    "market_cap": data.get("MarketCapitalization", ""),
                    "pe_ratio": data.get("PERatio", ""),
                    "dividend_yield": data.get("DividendYield", ""),
                    "52_week_high": data.get("52WeekHigh", ""),
                    "52_week_low": data.get("52WeekLow", ""),
                }

            return {
                "error": (
                    "API request failed with status code:"
                    f" {response.status_code}"
                )
            }

        except Exception as e:
            self.logger.error(f"Error getting company overview: {str(e)}")
            return {"error": f"Failed to get company data: {str(e)}"}

    async def search_symbol(self, keywords: str) -> List[Dict[str, str]]:
        """Search for stock symbols based on keywords"""
        api_key = self.get_api_key()
        if not api_key:
            return [{"error": "Alpha Vantage API key not configured"}]

        try:
            params = {
                "function": "SYMBOL_SEARCH",
                "keywords": keywords,
                "apikey": api_key,
            }

            response = requests.get(self.base_url, params=params)

            if response.status_code == 200:
                data = response.json()

                # Check for error messages
                if "Error Message" in data:
                    return [{"error": data["Error Message"]}]

                # Check if we got the expected data
                if "bestMatches" in data:
                    matches = data["bestMatches"]
                    results = []

                    for match in matches:
                        results.append(
                            {
                                "symbol": match.get("1. symbol", ""),
                                "name": match.get("2. name", ""),
                                "type": match.get("3. type", ""),
                                "region": match.get("4. region", ""),
                                "currency": match.get("8. currency", ""),
                            }
                        )

                    return results

                return [{"error": "No matching symbols found"}]

            return [
                {
                    "error": (
                        "API request failed with status code:"
                        f" {response.status_code}"
                    )
                }
            ]

        except Exception as e:
            self.logger.error(f"Error searching symbols: {str(e)}")
            return [{"error": f"Failed to search symbols: {str(e)}"}]

    async def run(
        self, action: str = "quote", symbol: str = None, keywords: str = None
    ) -> Dict[str, Any]:
        """
        Gets stock market information

        Args:
            action: The type of information to retrieve:
                   - "quote": Get current stock price and trading info
                   - "overview": Get company overview
                   - "search": Search for stock symbols
            symbol: Stock symbol (required for quote and overview)
            keywords: Search terms (required for search)

        Returns:
            Dict containing the requested stock information
        """
        if action == "quote":
            if not symbol:
                return {"error": "Symbol is required for quote action"}
            return await self.get_quote(symbol)

        elif action == "overview":
            if not symbol:
                return {"error": "Symbol is required for overview action"}
            return await self.get_company_overview(symbol)

        elif action == "search":
            if not keywords:
                return {"error": "Keywords are required for search action"}
            return await self.search_symbol(keywords)

        else:
            return {
                "error": (
                    f"Unknown action: {action}. Valid actions are: quote,"
                    " overview, search"
                )
            }
