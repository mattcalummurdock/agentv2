from loguru import logger

try:
    from pipecat.transports.daily.transport import DailyTransport
except ImportError:
    from pipecat.transports.services.daily import DailyTransport

from config.transport import transport_params
from transports.daily.config import get_bot_name


async def run_daily_session(room_url: str, token: str, run_bot) -> None:
    """Join a Daily room as the voice bot and run the existing agent pipeline."""
    transport = DailyTransport(
        room_url,
        token,
        get_bot_name(),
        transport_params["daily"](),
    )
    runner_args = type(
        "DailyRunnerArgs",
        (),
        {"pipeline_idle_timeout_secs": 300, "handle_sigint": False},
    )()
    try:
        await run_bot(transport, runner_args, call_data=None)
    finally:
        try:
            await transport.cleanup()
        except Exception as e:
            logger.debug(f"Daily transport cleanup: {e}")
