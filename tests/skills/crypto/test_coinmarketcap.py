# Ainara AI Companion Framework Project
# Copyright (C) 2025 Rubén Gómez - khromalabs.org
#
# This file is dual-licensed under:
# 1. GNU Lesser General Public License v3.0 (LGPL-3.0)
#    (See the included LICENSE_LGPL3.txt file or look into
#    <https://www.gnu.org/licenses/lgpl-3.0.html> for details)
# 2. Commercial license
#    (Contact: rgomez@khromalabs.org for licensing options)
#
# You may use, distribute and modify this code under the terms of either license.
# This notice must be preserved in all copies or substantial portions of the code.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
# Lesser General Public License for more details.

import pytest
from unittest.mock import patch, MagicMock
from orakle.skills.crypto.coinmarketcap import CryptoCoinmarketcap

@pytest.fixture
def crypto_skill():
    return CryptoCoinmarketcap()

@pytest.fixture
def mock_response():
    return {
        "data": {
            "BTC": {
                "name": "Bitcoin",
                "symbol": "BTC",
                "quote": {
                    "USD": {
                        "price": 42000.0,
                        "volume_24h": 30000000000.0,
                        "market_cap": 800000000000.0,
                        "percent_change_24h": 2.5,
                        "last_updated": "2024-01-26T12:00:00Z"
                    }
                }
            }
        }
    }

@pytest.mark.asyncio
async def test_crypto_market_cap(crypto_skill, mock_response):
    with patch.object(crypto_skill.config, 'get') as mock_get_config:
        mock_get_config.return_value = "fake-api-key"
        
        with patch.object(crypto_skill.session, 'get') as mock_get:
            mock_response_obj = MagicMock()
            mock_response_obj.json.return_value = mock_response
            mock_get.return_value = mock_response_obj
            
            result = await crypto_skill.run(symbol="BTC", convert="USD")
            
            assert result["name"] == "Bitcoin"
            assert result["symbol"] == "BTC"
            assert result["price"] == 42000.0
            assert result["volume_24h"] == 30000000000.0
            assert result["market_cap"] == 800000000000.0
            assert result["percent_change_24h"] == 2.5

@pytest.mark.asyncio
async def test_crypto_market_cap_error(crypto_skill):
    with patch.object(crypto_skill.config, 'get') as mock_get_config:
        mock_get_config.return_value = None
        
        with pytest.raises(ValueError, match="CoinMarketCap API key is required"):
            await crypto_skill.run(symbol="BTC", convert="USD")