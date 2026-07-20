"""A minimal fictional OAuth connector: a ``weather`` provider.

A connector provider is pure data. It declares one ``ProviderDescriptor`` — the
OAuth endpoints, the per-sub-service MCP servers, and the environment-variable
names that hold the client credentials — and registers it through the ``tai42_app``
handle at import. It carries no OAuth, probe, or launch code: the connector
engine drives all of that generically from the descriptor.
"""

from tai42_contract.app import tai42_app
from tai42_contract.connectors.providers import (
    OAuthEndpoints,
    ProviderDescriptor,
    SubServiceDescriptor,
)


def build_descriptor() -> ProviderDescriptor:
    return ProviderDescriptor(
        id="weather",
        kind="oauth",
        origin="system",
        category="productivity",
        display_name="Weather",
        description="Connect forecasts and severe-weather alerts.",
        icon_url="/static/connector-icons/weather.svg",
        oauth=OAuthEndpoints(
            authorize="https://auth.example-weather.test/oauth/authorize",
            token="https://auth.example-weather.test/oauth/token",
            revoke="https://auth.example-weather.test/oauth/revoke",
        ),
        client_id_env="WEATHER_CLIENT_ID",
        client_secret_env="WEATHER_CLIENT_SECRET",
        pkg_manager="uvx",
        sub_services={
            "forecast": SubServiceDescriptor(
                id="forecast",
                display_name="Forecast",
                description="Read daily and hourly forecasts.",
                scopes=["openid", "forecast.read"],
                entry_point="example-weather-mcp-forecast",
            ),
        },
        # Authorize-URL parameters this provider requires. The client credentials
        # are named, never stored: the ``*_env`` fields hold env-var names the
        # engine resolves from the process environment at connect time.
        extra_authorize_params={"audience": "https://api.example-weather.test"},
    )


# Manifest-load registration: importing this module registers the provider. A
# connector ships pure data, so this is a plain call, not a decorator.
tai42_app.connectors.register_connector(build_descriptor())
