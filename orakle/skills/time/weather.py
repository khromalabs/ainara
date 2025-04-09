import logging

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
            "Assistant doesn't need to ask for location, this skill will"
            " retrive the location using the IP"
        )
        self.logger = logging.getLogger(__name__)
        self.api_key = config.get("apis.weather.openweathermap_api_key")

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
                        "latitude": data["lat"],
                        "longitude": data["lon"],
                        "city": data["city"],
                        "country_name": data["country"],
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
        api_key = config.get("apis.weather.openweathermap_api_key")
        if not api_key:
            return {"error": "OpenWeatherMap API key not configured"}

        try:
            url = "https://api.openweathermap.org/data/2.5/weather"
            params = {
                "q": city_name,
                "appid": api_key,
                "units": "metric",
            }
            response = requests.get(url, params=params)

            if response.status_code == 200:
                weather_data = response.json()
                return {
                    "location": (
                        f"{weather_data['name']},"
                        f" {weather_data['sys']['country']}"
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

    def get_weather(self):
        """
        Get weather information based on IP location.
        """
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
                "lat": location["latitude"],
                "lon": location["longitude"],
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

    async def run(self, location: str = None, api_key: str = None):
        """
        Gets weather info.

        Args:
            location: Location name (optional, will use IP-based location
            if not provided).

        Returns:
            Dict containing weather information.
        """
        if location:
            return self.get_weather_by_city(location)
        return self.get_weather()
