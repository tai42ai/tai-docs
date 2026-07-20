"""A minimal fictional tool: a weather forecast lookup.

Registers one tool through the ``tai_app`` handle. The function signature becomes
the input schema and the docstring becomes the description.
"""

from tai_contract.app import tai_app


@tai_app.tools.tool
def get_forecast(city: str, days: int = 1) -> dict[str, object]:
    """Return a short weather forecast for a city.

    ``city`` names the place to look up; ``days`` is how many days ahead to
    report. The return value's shape becomes the tool's output schema.
    """
    return {
        "city": city,
        "days": days,
        "summary": "clear",
        "high_c": 21,
    }
