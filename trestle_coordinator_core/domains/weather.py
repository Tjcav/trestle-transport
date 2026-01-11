"""Weather domain data structures (Slice 8k - Weather Schema v2).

This module defines the weather domain outputs per trestle-spec:
profiles/runtime/home/domains/weather.yaml

Weather schema v2 adds forecast support with the weather_forecast array.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class WeatherCondition(Enum):
    """Valid weather condition states from spec."""

    CLEAR = "clear"
    PARTLY_CLOUDY = "partly_cloudy"
    CLOUDY = "cloudy"
    RAIN = "rain"
    SNOW = "snow"
    STORM = "storm"
    MIXED = "mixed"


@dataclass
class WeatherForecastEntry:
    """A single forecast entry (per spec item_schema).

    Attributes:
        day_id: Canonical day identifier (e.g., "D0", "D1").
        temp_high: High temperature for the day.
        temp_low: Low temperature for the day.
        icon_key: Icon asset key shared across coordinator/device.
        day_label: Short label rendered by UI (e.g., "Tue").
        precipitation_percent: Chance of precipitation (0.0-1.0).
        status: Short condition summary for the forecast entry.
    """

    day_id: str
    temp_high: float
    temp_low: float
    icon_key: str
    day_label: str | None = None
    precipitation_percent: float | None = None
    status: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for wire format."""
        result: dict[str, Any] = {
            "day_id": self.day_id,
            "temp_high": self.temp_high,
            "temp_low": self.temp_low,
            "icon_key": self.icon_key,
        }
        if self.day_label is not None:
            result["day_label"] = self.day_label
        if self.precipitation_percent is not None:
            result["precipitation_percent"] = self.precipitation_percent
        if self.status is not None:
            result["status"] = self.status
        return result


@dataclass
class WeatherOutputs:
    """Weather domain outputs (schema v2).

    All output keys match the spec's outputs section.
    The weather_forecast array is limited to max 5 entries per spec.

    Attributes:
        weather_location: Location name or identifier.
        weather_condition: Current condition enum.
        weather_icon_key: Icon asset key for current conditions.
        weather_temp_current: Current temperature.
        weather_temp_high_today: Today's high.
        weather_temp_low_today: Today's low.
        weather_humidity: Current humidity (0.0-1.0).
        weather_wind_speed: Wind speed.
        weather_precipitation: Precipitation amount.
        weather_pollen: Pollen level indicator.
        weather_observation_ts_ms: Observation timestamp (epoch ms).
        weather_status_line: Human-readable status summary.
        weather_forecast: Up to 5 forecast entries.
    """

    # Required fields
    weather_condition: WeatherCondition

    # Optional string fields
    weather_location: str | None = None
    weather_icon_key: str | None = None
    weather_pollen: str | None = None
    weather_status_line: str | None = None

    # Optional numeric fields
    weather_temp_current: float | None = None
    weather_temp_high_today: float | None = None
    weather_temp_low_today: float | None = None
    weather_humidity: float | None = None
    weather_wind_speed: float | None = None
    weather_precipitation: float | None = None
    weather_observation_ts_ms: int | None = None

    # Forecast array (max 5 entries per spec)
    weather_forecast: list[WeatherForecastEntry] = field(
        default_factory=lambda: list[WeatherForecastEntry]()
    )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for wire format.

        Only includes non-None values to minimize payload.
        """
        result: dict[str, Any] = {
            "weather_condition": self.weather_condition.value,
        }

        # Add optional string fields
        if self.weather_location is not None:
            result["weather_location"] = self.weather_location
        if self.weather_icon_key is not None:
            result["weather_icon_key"] = self.weather_icon_key
        if self.weather_pollen is not None:
            result["weather_pollen"] = self.weather_pollen
        if self.weather_status_line is not None:
            result["weather_status_line"] = self.weather_status_line

        # Add optional numeric fields
        if self.weather_temp_current is not None:
            result["weather_temp_current"] = self.weather_temp_current
        if self.weather_temp_high_today is not None:
            result["weather_temp_high_today"] = self.weather_temp_high_today
        if self.weather_temp_low_today is not None:
            result["weather_temp_low_today"] = self.weather_temp_low_today
        if self.weather_humidity is not None:
            result["weather_humidity"] = self.weather_humidity
        if self.weather_wind_speed is not None:
            result["weather_wind_speed"] = self.weather_wind_speed
        if self.weather_precipitation is not None:
            result["weather_precipitation"] = self.weather_precipitation
        if self.weather_observation_ts_ms is not None:
            result["weather_observation_ts_ms"] = self.weather_observation_ts_ms

        # Add forecast (limit to 5 per spec)
        if self.weather_forecast:
            result["weather_forecast"] = [
                entry.to_dict() for entry in self.weather_forecast[:5]
            ]

        return result

    @classmethod
    def from_ha_weather_entity(
        cls,
        state: str,
        attributes: dict[str, Any],
        location: str | None = None,
    ) -> WeatherOutputs:
        """Create WeatherOutputs from Home Assistant weather entity.

        Args:
            state: HA weather entity state (e.g., "sunny", "cloudy").
            attributes: HA weather entity attributes.
            location: Optional location name.

        Returns:
            WeatherOutputs populated from HA data.
        """
        # Map HA weather state to WeatherCondition
        condition_map = {
            "sunny": WeatherCondition.CLEAR,
            "clear-night": WeatherCondition.CLEAR,
            "partlycloudy": WeatherCondition.PARTLY_CLOUDY,
            "cloudy": WeatherCondition.CLOUDY,
            "rainy": WeatherCondition.RAIN,
            "pouring": WeatherCondition.RAIN,
            "snowy": WeatherCondition.SNOW,
            "snowy-rainy": WeatherCondition.MIXED,
            "lightning": WeatherCondition.STORM,
            "lightning-rainy": WeatherCondition.STORM,
            "hail": WeatherCondition.STORM,
            "windy": WeatherCondition.CLEAR,
            "windy-variant": WeatherCondition.PARTLY_CLOUDY,
            "fog": WeatherCondition.CLOUDY,
            "exceptional": WeatherCondition.MIXED,
        }
        condition = condition_map.get(state, WeatherCondition.MIXED)

        # Extract current conditions
        outputs = cls(
            weather_condition=condition,
            weather_location=location or attributes.get("friendly_name"),
            weather_icon_key=_map_condition_to_icon(condition),
            weather_temp_current=attributes.get("temperature"),
            weather_humidity=_normalize_humidity(attributes.get("humidity")),
            weather_wind_speed=attributes.get("wind_speed"),
            weather_precipitation=attributes.get("precipitation"),
        )

        # Extract forecast if present (HA weather entities have forecast attr)
        ha_forecast = attributes.get("forecast", [])
        if ha_forecast:
            forecast_entries: list[WeatherForecastEntry] = []
            for i, entry in enumerate(ha_forecast[:5]):
                forecast_entries.append(
                    WeatherForecastEntry(
                        day_id=f"D{i}",
                        day_label=_extract_day_label(entry.get("datetime")),
                        temp_high=entry.get("temperature", entry.get("templow", 0)),
                        temp_low=entry.get("templow", entry.get("temperature", 0)),
                        precipitation_percent=_normalize_precipitation(
                            entry.get("precipitation_probability")
                        ),
                        icon_key=_map_ha_condition_to_icon(entry.get("condition")),
                        status=entry.get("condition"),
                    )
                )
            outputs.weather_forecast = forecast_entries

        return outputs


def _map_condition_to_icon(condition: WeatherCondition) -> str:
    """Map WeatherCondition to icon key."""
    icon_map = {
        WeatherCondition.CLEAR: "weather_sunny",
        WeatherCondition.PARTLY_CLOUDY: "weather_partly_cloudy",
        WeatherCondition.CLOUDY: "weather_cloudy",
        WeatherCondition.RAIN: "weather_rainy",
        WeatherCondition.SNOW: "weather_snowy",
        WeatherCondition.STORM: "weather_lightning",
        WeatherCondition.MIXED: "weather_mixed",
    }
    return icon_map.get(condition, "weather_unknown")


def _map_ha_condition_to_icon(ha_condition: str | None) -> str:
    """Map HA weather condition string to icon key."""
    if not ha_condition:
        return "weather_unknown"

    icon_map = {
        "sunny": "weather_sunny",
        "clear-night": "weather_clear_night",
        "partlycloudy": "weather_partly_cloudy",
        "cloudy": "weather_cloudy",
        "rainy": "weather_rainy",
        "pouring": "weather_pouring",
        "snowy": "weather_snowy",
        "snowy-rainy": "weather_mixed",
        "lightning": "weather_lightning",
        "lightning-rainy": "weather_lightning_rainy",
        "hail": "weather_hail",
        "fog": "weather_fog",
        "windy": "weather_windy",
        "windy-variant": "weather_windy",
    }
    return icon_map.get(ha_condition, "weather_unknown")


def _normalize_humidity(humidity: float | None) -> float | None:
    """Normalize humidity to 0.0-1.0 range if needed."""
    if humidity is None:
        return None
    # HA reports humidity as 0-100, spec wants 0.0-1.0
    if humidity > 1.0:
        return humidity / 100.0
    return humidity


def _normalize_precipitation(prob: float | int | None) -> float | None:
    """Normalize precipitation probability to 0.0-1.0 range."""
    if prob is None:
        return None
    # HA reports as 0-100 percentage
    if isinstance(prob, int) or prob > 1.0:
        return float(prob) / 100.0
    return float(prob)


def _extract_day_label(datetime_str: str | None) -> str | None:
    """Extract short day label from datetime string."""
    if not datetime_str:
        return None
    try:
        from datetime import datetime

        dt = datetime.fromisoformat(datetime_str.replace("Z", "+00:00"))
        return dt.strftime("%a")  # e.g., "Mon", "Tue"
    except (ValueError, AttributeError):
        return None
