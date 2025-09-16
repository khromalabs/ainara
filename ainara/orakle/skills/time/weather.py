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

import logging
from typing import Annotated, Any, Dict, Optional

import pycountry
import requests

from ainara.framework.config import config
from ainara.framework.skill import Skill


class TimeWeather(Skill):
    """Get weather info determining location with geolocation, optionally allowing a location parameter"""

    if not config.get("apis.weather.openweathermap_api_key"):
        hiddenCapability = True

    def __init__(self):
        super().__init__()
        self.name = "weather"
        self.matcher_info = (
            "Use this skill when the user wants to get current real-time"
            " weather information for their location or a specific location."
            " This skill can determine the user's location using IP-based"
            " geolocation if no location is provided. This skill is not apt"
            " for forecasts involving several days ahead, just for real-time"
            " data. Examples include: 'what is the weather like today', 'tell"
            " me the forecast for London', 'how hot is it in New York',"
            " 'current temperature in Paris'.\n\nKeywords: weather, forecast,"
            " temperature, current, today, location, city, country, climate,"
            " rain, sun, wind, humidity."
        )
        self.logger = logging.getLogger(__name__)
        self.api_key = config.get("apis.weather.openweathermap_api_key")

    # def reload(self):
    #     super().reload(config)
    #     self.api_key = config.get("apis.weather.openweathermap_api_key")
    #     # self.logger.info("TimeWeather RELOAD self.api_key = " + self.api_key)

    def get_country_name(self, code):
        try:
            country = pycountry.countries.get(alpha_2=code.upper())
            return country.name
        except AttributeError:
            return None  # or handle invalid code

    def get_location_from_ip(self):
        """Get location information from IP address"""
        try:
            # First try to get public IP
            ip_response = requests.get("https://api.ipify.org?format=json")
            if ip_response.status_code != 200:
                self.logger.error("Could not determine IP address")
                return None

            ip_address = ip_response.json()["ip"]

            # Then get location data for that IP
            location_response = requests.get(
                f"http://ip-api.com/json/{ip_address}"
            )
            if location_response.status_code == 200:
                data = location_response.json()
                if data.get("status") == "success":
                    return {
                        "lat": data["lat"],
                        "lon": data["lon"],
                        "city": (
                            data["city"]
                            # .encode("latin1")
                            # .decode("unicode_escape")
                        ),
                        "country_name": (
                            data["country"]
                            # .encode("latin1")
                            # .decode("unicode_escape")
                        ),
                    }
                self.logger.error(
                    f"IP-API error: {data.get('message', 'Unknown error')}"
                )
            else:
                self.logger.error(
                    f"IP-API HTTP error: {location_response.status_code}"
                )
            return None
        except Exception as e:
            self.logger.error(f"Error getting location: {str(e)}")
            return None

    def get_weather_by_city(self, city_name: str):
        """Get weather information for a specific city"""
        try:
            # Step 1: Geocoding to convert city name to lat/lon
            geo_url = "http://api.openweathermap.org/geo/1.0/direct"
            geo_params = {"q": city_name, "limit": 1, "appid": self.api_key}
            geo_response = requests.get(geo_url, params=geo_params)

            if geo_response.status_code != 200 or not geo_response.json():
                self.logger.error(
                    "Geocoding API error:"
                    f" {geo_response.status_code} - {geo_response.text}"
                )
                return {"error": f"Could not find location: {city_name}"}

            location = geo_response.json()[0]
            location["city"] = location["name"]
            location["country_name"] = self.get_country_name(
                location["country"]
            )
            # lat, lon = location["lat"], location["lon"]
            # self.logger.info(f"location: {location}")

            # Step 2: Get weather using One Call API 3.0 with coordinates
            return self.get_weather(location)

        except Exception as e:
            self.logger.error(f"Error getting weather: {str(e)}")
            return {"error": f"Failed to get weather data: {str(e)}"}

    def get_weather(self, location=None):
        """
        Get weather information based on IP location.
        """
        if not location:
            location = self.get_location_from_ip()
            if not location:
                return {"error": "Could not determine location"}

        # Using OpenWeatherMap API (you'll need to add API key to config)
        api_key = config.get("apis.weather.openweathermap_api_key")
        if not self.api_key:
            return {"error": "OpenWeatherMap API key not configured"}

        try:
            url = "https://api.openweathermap.org/data/2.5/weather"
            params = {
                "lat": location["lat"],
                "lon": location["lon"],
                "appid": api_key,
                "units": "metric",  # Use metric units
            }
            response = requests.get(url, params=params)

            if response.status_code == 200:
                weather_data = response.json()
                return {
                    "location": (
                        f"{location.get('city', '')},"
                        f" {location.get('country_name', '')}"
                    ),
                    "temperature": weather_data["main"]["temp"],
                    "description": weather_data["weather"][0]["description"],
                    "humidity": weather_data["main"]["humidity"],
                    "wind_speed": weather_data["wind"]["speed"],
                }
            return {"error": f"Weather API error: {response.status_code}"}

        except Exception as e:
            self.logger.error(f"Error getting weather: {str(e)}")
            return {"error": f"Failed to get weather data: {str(e)}"}

    async def run(
        self,
        city: Annotated[
            Optional[str],
            "City or town name. If not provided, IP-based geolocation will be"
            " used.",
        ] = None,
        country: Annotated[
            Optional[str],
            "Country name or code (e.g., US, UK). Used to make the city search"
            " more specific.",
        ] = None,
        api_key: Annotated[
            Optional[str],
            "OpenWeatherMap API key (optional, will use configured key if not"
            " provided)",
        ] = None,
    ) -> Dict[str, Any]:
        """Gets current weather information for a location"""
        if city:
            location_query = f"{city},{country}" if country else city
            return self.get_weather_by_city(location_query)
        return self.get_weather()
