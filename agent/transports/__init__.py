from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from loguru import logger
from pipecat.frames.frames import LLMRunFrame
from pipecat.pipeline.task import PipelineTask
from pipecat.transports.base_transport import BaseTransport

try:
    from pipecat.transports.daily.transport import DailyTransport
except ImportError:
    from pipecat.transports.services.daily import DailyTransport

OnSessionEnd = Callable[[str], Awaitable[None]]


def register_session_handlers(
    transport: BaseTransport,
    task: PipelineTask,
    on_session_end: OnSessionEnd,
) -> None:
    """Wire connect/disconnect handlers for Daily vs telephony/WebRTC transports."""
    if isinstance(transport, DailyTransport):
        @transport.event_handler("on_first_participant_joined")
        async def on_first_participant_joined(transport, participant):
            logger.info("First participant joined — greeting")
            await transport.capture_participant_transcription(participant["id"])
            await asyncio.sleep(0.5)
            await task.queue_frames([LLMRunFrame()])

        @transport.event_handler("on_participant_left")
        async def on_participant_left(transport, participant, reason):
            await on_session_end(f"Participant left (reason={reason})")
    else:
        @transport.event_handler("on_client_connected")
        async def on_client_connected(transport, client):
            logger.info("Client connected")
            await task.queue_frames([LLMRunFrame()])

        @transport.event_handler("on_client_disconnected")
        async def on_client_disconnected(transport, client):
            await on_session_end("Client disconnected")
