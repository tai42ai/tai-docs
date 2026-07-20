"""A minimal fictional pooled client.

A pooled client shares one connection per event loop across tool calls. Subclass
the kit's ``PooledClient`` (which implements the contract ``BaseClient``), then
open it through ``tai42_app.clients.client_ctx`` from inside a tool, route, or
lifecycle handler. The context manager yields a connected client, pooled per loop
and connection params (or one-shot with ``fresh=True``).
"""

from tai42_contract.app import tai42_app
from tai42_kit.clients import PooledClient


class GeoConnection:
    """The live connection object the pool hands out."""

    async def lookup(self, name: str) -> str:
        return f"region:{name}"


class GeoClient(PooledClient[GeoConnection]):
    async def _create(self, **kwargs: object) -> GeoConnection:
        return GeoConnection()

    async def _close(self, client: GeoConnection) -> None:
        return None


async def resolve_region(name: str) -> str:
    async with tai42_app.clients.client_ctx(GeoClient) as connection:
        return await connection.lookup(name)
