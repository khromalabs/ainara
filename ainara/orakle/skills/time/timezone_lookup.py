"""Skill for looking up timezone and current local time by city, country, or timezone name."""

import logging
from datetime import datetime
from typing import Annotated, Any, Dict, Optional

import pytz
import requests

from ainara.framework.skill import Skill

_NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
_TIMEAPI_URL = "https://timeapi.io/api/time/current/coordinate"
_HEADERS = {"User-Agent": "Ainara/1.0 timezone-lookup-skill"}


class TimeTimezoneLookup(Skill):
    """Look up timezone information and current local time for a city, country, or named timezone"""

    matcher_info = (
        "Use when the user asks for the timezone, time zone, or current time in a specific "
        "city, state, country, or named timezone (e.g. America/New_York). "
        "Keywords: what time is it in, current time in, timezone for, what timezone is, time zone."
    )

    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger(__name__)

    def _time_for_named_tz(self, tz_name: str) -> Dict[str, Any]:
        """Return current time for a pytz-named timezone."""
        try:
            tz = pytz.timezone(tz_name)
        except pytz.UnknownTimeZoneError:
            return {"success": False, "error": f"Unknown timezone: {tz_name}"}
        now = datetime.now(tz)
        return {
            "success": True,
            "timezone": tz_name,
            "current_time": now.strftime("%Y-%m-%d %H:%M:%S"),
            "utc_offset": now.strftime("%z"),
        }

    def _geocode(self, query: str) -> Optional[Dict[str, float]]:
        """Return {'lat': ..., 'lon': ...} for a place name, or None on failure."""
        try:
            resp = requests.get(
                _NOMINATIM_URL,
                params={"q": query, "format": "json", "limit": 1},
                headers=_HEADERS,
                timeout=8,
            )
            resp.raise_for_status()
            results = resp.json()
            if not results:
                return None
            return {"lat": float(results[0]["lat"]), "lon": float(results[0]["lon"])}
        except Exception as e:
            self.logger.warning(f"Nominatim geocoding failed: {e}")
            return None

    def _time_for_coords(self, lat: float, lon: float) -> Dict[str, Any]:
        """Return current time at lat/lon via timeapi.io."""
        try:
            resp = requests.get(
                _TIMEAPI_URL,
                params={"latitude": lat, "longitude": lon},
                headers=_HEADERS,
                timeout=8,
            )
            resp.raise_for_status()
            data = resp.json()
            tz_name = data.get("timeZone", "Unknown")
            dt_str = data.get("dateTime", "")
            # dateTime is ISO-8601 like "2024-01-15T14:30:00.123456"
            try:
                dt = datetime.fromisoformat(dt_str)
                formatted = dt.strftime("%Y-%m-%d %H:%M:%S")
            except ValueError:
                formatted = dt_str
            tz = pytz.timezone(tz_name) if tz_name != "Unknown" else pytz.utc
            now = datetime.now(tz)
            return {
                "success": True,
                "timezone": tz_name,
                "current_time": formatted,
                "utc_offset": now.strftime("%z"),
            }
        except Exception as e:
            self.logger.warning(f"timeapi.io lookup failed: {e}")
            return {"success": False, "error": str(e)}

    async def run(
        self,
        city: Annotated[Optional[str], "City name to look up timezone for"] = None,
        state: Annotated[Optional[str], "State or province name (optional, narrows search)"] = None,
        country: Annotated[Optional[str], "Country name (optional, narrows search)"] = None,
        timezone: Annotated[Optional[str], "Named timezone such as America/New_York"] = None,
    ) -> Dict[str, Any]:
        """Returns current local time and timezone info for the requested location.

        Args:
            city: City name
            state: State or province (optional)
            country: Country name (optional)
            timezone: IANA timezone name (optional, e.g. Europe/Madrid)

        Returns:
            Dict with success, timezone, current_time, and utc_offset keys
        """
        # Named timezone takes priority — no network call needed
        if timezone:
            return self._time_for_named_tz(timezone)

        # Build a geocoding query from whatever location parts were provided
        parts = [p for p in [city, state, country] if p]
        if not parts:
            return {"success": False, "error": "Please provide a city, country, or timezone name."}

        query = ", ".join(parts)
        coords = self._geocode(query)
        if coords is None:
            return {"success": False, "error": f"Could not find location: {query}"}

        result = self._time_for_coords(coords["lat"], coords["lon"])
        if result["success"]:
            result["location"] = query
        return result
