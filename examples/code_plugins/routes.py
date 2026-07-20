"""A minimal fictional HTTP route plugin.

``@tai42_app.http.custom_route`` registers a Starlette handler and its
self-describing OpenAPI metadata in one call — ``summary``, ``tags``, and
``response_model`` are required so the route describes itself to the API
reference. Load the module under ``routers_modules``.
"""

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from tai42_contract.app import tai42_app


@tai42_app.http.custom_route(
    "/api/weather/regions",
    methods=["GET"],
    summary="List available weather regions",
    tags=["weather"],
    response_model=None,
)
async def regions(request: Request) -> Response:
    return JSONResponse({"data": ["north", "south"]})
