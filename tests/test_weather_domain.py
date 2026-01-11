"""Tests for weather domain data structures (schema v2)."""

from __future__ import annotations

from trestle_coordinator_core.domains.weather import (
    WeatherCondition,
    WeatherForecastEntry,
    WeatherOutputs,
)


class TestWeatherConditionEnum:
    """Tests for WeatherCondition enum."""

    def test_all_spec_conditions_exist(self) -> None:
        """Verify all spec-defined conditions are present."""
        expected = [
            "clear",
            "partly_cloudy",
            "cloudy",
            "rain",
            "snow",
            "storm",
            "mixed",
        ]
        for condition in expected:
            assert hasattr(WeatherCondition, condition.upper())

    def test_condition_values_match_spec(self) -> None:
        """Condition values match spec output values."""
        assert WeatherCondition.CLEAR.value == "clear"
        assert WeatherCondition.PARTLY_CLOUDY.value == "partly_cloudy"
        assert WeatherCondition.CLOUDY.value == "cloudy"
        assert WeatherCondition.RAIN.value == "rain"
        assert WeatherCondition.SNOW.value == "snow"
        assert WeatherCondition.STORM.value == "storm"
        assert WeatherCondition.MIXED.value == "mixed"


class TestWeatherForecastEntry:
    """Tests for WeatherForecastEntry dataclass."""

    def test_create_forecast_entry(self) -> None:
        """Can create a forecast entry with required fields."""
        entry = WeatherForecastEntry(
            day_id=0,
            temp_high=75,
            temp_low=55,
            icon_key="sunny",
        )
        assert entry.day_id == 0
        assert entry.temp_high == 75
        assert entry.temp_low == 55
        assert entry.icon_key == "sunny"

    def test_forecast_entry_optional_fields(self) -> None:
        """Forecast entry has optional fields with defaults."""
        entry = WeatherForecastEntry(
            day_id=1,
            temp_high=80,
            temp_low=60,
            icon_key="rainy",
            day_label="Tuesday",
            precipitation_percent=40,
            status="Rainy",
        )
        assert entry.day_label == "Tuesday"
        assert entry.precipitation_percent == 40
        assert entry.status == "Rainy"

    def test_forecast_entry_to_dict(self) -> None:
        """Forecast entry converts to dict correctly."""
        entry = WeatherForecastEntry(
            day_id=2,
            temp_high=72,
            temp_low=58,
            icon_key="cloudy",
            day_label="Wednesday",
        )
        result = entry.to_dict()

        assert result["day_id"] == 2
        assert result["temp_high"] == 72
        assert result["temp_low"] == 58
        assert result["icon_key"] == "cloudy"
        assert result["day_label"] == "Wednesday"


class TestWeatherOutputs:
    """Tests for WeatherOutputs dataclass."""

    def test_create_weather_outputs(self) -> None:
        """Can create weather outputs with all fields."""
        outputs = WeatherOutputs(
            weather_location="Home",
            weather_condition=WeatherCondition.CLEAR,
            weather_icon_key="sunny",
            weather_temp_current=72,
            weather_humidity=45,
        )
        assert outputs.weather_location == "Home"
        assert outputs.weather_condition == WeatherCondition.CLEAR
        assert outputs.weather_temp_current == 72

    def test_weather_outputs_to_dict(self) -> None:
        """Weather outputs converts to dict with all keys."""
        outputs = WeatherOutputs(
            weather_location="Office",
            weather_condition=WeatherCondition.RAIN,
            weather_icon_key="rainy",
            weather_temp_current=65,
            weather_humidity=80,
            weather_wind_speed=12.5,
            weather_status_line="Rainy, 65°",
        )
        result = outputs.to_dict()

        assert result["weather_location"] == "Office"
        assert result["weather_condition"] == "rain"  # Enum value
        assert result["weather_icon_key"] == "rainy"
        assert result["weather_temp_current"] == 65
        assert result["weather_humidity"] == 80
        assert result["weather_wind_speed"] == 12.5
        assert result["weather_status_line"] == "Rainy, 65°"

    def test_weather_outputs_forecast_in_dict(self) -> None:
        """Weather outputs includes forecast array in dict."""
        forecast = [
            WeatherForecastEntry(day_id=0, temp_high=75, temp_low=55, icon_key="sunny"),
            WeatherForecastEntry(
                day_id=1, temp_high=72, temp_low=52, icon_key="cloudy"
            ),
        ]
        outputs = WeatherOutputs(
            weather_location="Home",
            weather_condition=WeatherCondition.CLEAR,
            weather_icon_key="sunny",
            weather_forecast=forecast,
        )
        result = outputs.to_dict()

        assert "weather_forecast" in result
        assert len(result["weather_forecast"]) == 2
        assert result["weather_forecast"][0]["day_id"] == 0
        assert result["weather_forecast"][1]["day_id"] == 1


class TestWeatherOutputsFromHAEntity:
    """Tests for from_ha_weather_entity factory method."""

    def test_basic_sunny_weather(self) -> None:
        """Can extract weather from basic sunny HA state."""
        outputs = WeatherOutputs.from_ha_weather_entity(
            state="sunny",
            attributes={
                "temperature": 75,
                "humidity": 40,  # HA reports 0-100
                "wind_speed": 5.2,
            },
            location="Home",
        )

        assert outputs.weather_location == "Home"
        assert outputs.weather_condition == WeatherCondition.CLEAR
        assert outputs.weather_temp_current == 75
        # Humidity normalized to 0-1 range per spec
        assert outputs.weather_humidity == 0.4

    def test_rainy_weather_condition_mapping(self) -> None:
        """Rainy HA state maps to rain condition."""
        outputs = WeatherOutputs.from_ha_weather_entity(
            state="rainy",
            attributes={"temperature": 60, "humidity": 85},
        )

        assert outputs.weather_condition == WeatherCondition.RAIN
        # Icon keys use weather_ prefix
        assert outputs.weather_icon_key == "weather_rainy"

    def test_cloudy_weather_condition_mapping(self) -> None:
        """Cloudy HA state maps to cloudy condition."""
        outputs = WeatherOutputs.from_ha_weather_entity(
            state="cloudy",
            attributes={"temperature": 68},
        )

        assert outputs.weather_condition == WeatherCondition.CLOUDY

    def test_partly_cloudy_condition_mapping(self) -> None:
        """Partlycloudy HA state maps to partly_cloudy condition."""
        outputs = WeatherOutputs.from_ha_weather_entity(
            state="partlycloudy",
            attributes={"temperature": 70},
        )

        assert outputs.weather_condition == WeatherCondition.PARTLY_CLOUDY

    def test_snowy_weather_condition_mapping(self) -> None:
        """Snowy HA state maps to snow condition."""
        outputs = WeatherOutputs.from_ha_weather_entity(
            state="snowy",
            attributes={"temperature": 28},
        )

        assert outputs.weather_condition == WeatherCondition.SNOW

    def test_stormy_weather_condition_mapping(self) -> None:
        """Lightning states map to storm condition."""
        for state in ["lightning", "lightning-rainy"]:
            outputs = WeatherOutputs.from_ha_weather_entity(
                state=state,
                attributes={"temperature": 75},
            )
            assert outputs.weather_condition == WeatherCondition.STORM

    def test_unknown_condition_maps_to_mixed(self) -> None:
        """Unknown HA states map to mixed condition."""
        outputs = WeatherOutputs.from_ha_weather_entity(
            state="exceptional",
            attributes={"temperature": 65},
        )

        assert outputs.weather_condition == WeatherCondition.MIXED

    def test_humidity_normalization(self) -> None:
        """Humidity is normalized from 0-100 to 0.0-1.0 per spec."""
        # HA reports 0-100, spec wants 0.0-1.0
        outputs = WeatherOutputs.from_ha_weather_entity(
            state="sunny",
            attributes={"humidity": 75},
        )
        assert outputs.weather_humidity == 0.75

        # Already normalized values stay as-is
        outputs = WeatherOutputs.from_ha_weather_entity(
            state="sunny",
            attributes={"humidity": 0.5},
        )
        assert outputs.weather_humidity == 0.5

    def test_forecast_extraction(self) -> None:
        """Forecast array is extracted from HA attributes."""
        outputs = WeatherOutputs.from_ha_weather_entity(
            state="sunny",
            attributes={
                "temperature": 72,
                "forecast": [
                    {
                        "datetime": "2025-01-15",
                        "temperature": 75,
                        "templow": 55,
                        "condition": "sunny",
                        "precipitation_probability": 10,
                    },
                    {
                        "datetime": "2025-01-16",
                        "temperature": 72,
                        "templow": 52,
                        "condition": "cloudy",
                        "precipitation_probability": 30,
                    },
                ],
            },
        )

        assert len(outputs.weather_forecast) == 2
        assert outputs.weather_forecast[0].temp_high == 75
        assert outputs.weather_forecast[0].temp_low == 55
        assert outputs.weather_forecast[1].temp_high == 72

    def test_forecast_capped_at_five(self) -> None:
        """Forecast array is capped at 5 entries per spec."""
        outputs = WeatherOutputs.from_ha_weather_entity(
            state="sunny",
            attributes={
                "temperature": 72,
                "forecast": [
                    {
                        "datetime": f"2025-01-{15 + i}",
                        "temperature": 70 + i,
                        "templow": 50 + i,
                        "condition": "sunny",
                    }
                    for i in range(10)  # 10 days
                ],
            },
        )

        assert len(outputs.weather_forecast) == 5

    def test_missing_attributes_handled(self) -> None:
        """Missing attributes result in None values."""
        outputs = WeatherOutputs.from_ha_weather_entity(
            state="sunny",
            attributes={},  # Empty attributes
        )

        assert outputs.weather_temp_current is None
        assert outputs.weather_humidity is None
        assert outputs.weather_wind_speed is None

    def test_high_low_today_from_attributes(self) -> None:
        """Today's high/low use forecast entry temps."""
        outputs = WeatherOutputs.from_ha_weather_entity(
            state="sunny",
            attributes={
                "temperature": 72,
                "forecast": [
                    {
                        "datetime": "2025-01-15",
                        "temperature": 78,  # High
                        "templow": 52,  # Low
                        "condition": "sunny",
                    },
                ],
            },
        )

        # Forecast entries have the temps
        assert len(outputs.weather_forecast) == 1
        assert outputs.weather_forecast[0].temp_high == 78
        assert outputs.weather_forecast[0].temp_low == 52
