"""GET /health — connection status."""

from aiohttp import web

from client import TRADING_MODE, IBClient
from models_remote_client import HealthResponse


async def handle_health(request: web.Request) -> web.Response:
    client: IBClient = request.app["client"]
    resp = HealthResponse(
        connected=client.is_connected,
        tradingMode=TRADING_MODE,
    )
    return web.json_response(resp.model_dump())
