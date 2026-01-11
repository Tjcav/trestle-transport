"""Domain-specific data structures and helpers.

This package contains domain-specific types aligned with trestle-spec.
"""

from .weather import (
    WeatherCondition,
    WeatherForecastEntry,
    WeatherOutputs,
)

__all__ = [
    "WeatherCondition",
    "WeatherForecastEntry",
    "WeatherOutputs",
]
