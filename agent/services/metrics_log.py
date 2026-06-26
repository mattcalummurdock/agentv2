"""Pipeline observers that log latency and TTFB at INFO level."""

from loguru import logger
from pipecat.frames.frames import (
    MetricsFrame,
    UserStoppedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.metrics.metrics import TTFBMetricsData
from pipecat.observers.base_observer import BaseObserver, FramePushed
from pipecat.observers.user_bot_latency_observer import UserBotLatencyObserver
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.services.google.gemini_live.llm import GeminiLiveLLMService


class MetricsLogObserver(BaseObserver):
    """Log TTFB (and other MetricsFrame data) at INFO when they flow downstream."""

    async def on_push_frame(self, data: FramePushed):
        if data.direction != FrameDirection.DOWNSTREAM:
            return
        if not isinstance(data.frame, MetricsFrame):
            return
        for item in data.frame.data:
            if isinstance(item, TTFBMetricsData) and item.value > 0:
                model = f" ({item.model})" if item.model else ""
                logger.info(f"{item.processor}{model} TTFB: {item.value:.3f}s")


class TtfbStartOnUserStop(FrameProcessor):
    """Start LLM TTFB timing on VAD user-stop (Gemini Live only starts on UserStoppedSpeaking)."""

    def __init__(self, llm: GeminiLiveLLMService):
        super().__init__()
        self._llm = llm

    async def process_frame(self, frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, (VADUserStoppedSpeakingFrame, UserStoppedSpeakingFrame)):
            await self._llm.start_ttfb_metrics()
        await self.push_frame(frame, direction)


def create_latency_observer() -> UserBotLatencyObserver:
    observer = UserBotLatencyObserver()

    @observer.event_handler("on_latency_measured")
    async def _on_latency(_observer, latency_seconds: float):
        logger.info(f"User→bot latency: {latency_seconds:.3f}s")

    @observer.event_handler("on_latency_breakdown")
    async def _on_breakdown(_observer, breakdown):
        for label in breakdown.chronological_events():
            logger.info(label)

    @observer.event_handler("on_first_bot_speech_latency")
    async def _on_first_speech(_observer, latency_seconds: float):
        logger.info(f"Connect→first speech: {latency_seconds:.3f}s")

    return observer
