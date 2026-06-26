"""Pause Gemini Live audio input while tool calls are in flight."""

from pipecat.frames.frames import (
    Frame,
    FunctionCallCancelFrame,
    FunctionCallResultFrame,
    FunctionCallsStartedFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.services.google.gemini_live.llm import GeminiLiveLLMService


class ToolCallInputGate(FrameProcessor):
    """Drop user audio at the Gemini API while any tool call is active.

    ``FunctionCallUserMuteStrategy`` stops frames in the user aggregator, but
    Gemini Live can still accept buffered or in-flight realtime audio unless
    ``set_audio_input_paused`` is set.  This processor watches the
    broadcast function-call lifecycle frames and toggles that flag.
    """

    def __init__(self, llm: GeminiLiveLLMService):
        super().__init__()
        self._llm = llm
        self._active_calls = 0

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, FunctionCallsStartedFrame):
            self._active_calls += len(frame.function_calls)
            self._llm.set_audio_input_paused(True)
        elif isinstance(frame, (FunctionCallResultFrame, FunctionCallCancelFrame)):
            self._active_calls = max(0, self._active_calls - 1)
            if self._active_calls == 0:
                self._llm.set_audio_input_paused(False)

        await self.push_frame(frame, direction)
