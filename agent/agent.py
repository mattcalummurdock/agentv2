#
# Copyright (c) 2025, Daily
#
# SPDX-License-Identifier: BSD 2-Clause License
#

from dotenv import load_dotenv
from loguru import logger
from pipecat.frames.frames import LLMRunFrame, TTSAudioRawFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.runner.types import RunnerArguments
from pipecat.runner.utils import create_transport
from pipecat.transports.base_transport import BaseTransport
from pipecat.turns.user_mute import FunctionCallUserMuteStrategy

from config.transport import transport_params
from prompts.system import INITIAL_USER_MESSAGE
from services import hold_phrases
from services.google_llm import create_llm, fix_credentials
from services.metrics_log import (
    MetricsLogObserver,
    TtfbStartOnUserStop,
    create_latency_observer,
)
from services.tool_call_input_gate import ToolCallInputGate
from tools.medicine_detail.db import close_pool, init_pool
from tools.medicine_detail.semantic import prewarm_embedding_model
from tools.registry import build_tools_schema, register_tools

load_dotenv(override=True)


async def run_bot(transport: BaseTransport, runner_args: RunnerArguments):
    logger.info("Starting Agent (Gemini 3.1 Flash Live)")

    await init_pool()
    if prewarm_embedding_model():
        logger.info("Semantic search embedding model ready")

    credentials_json = fix_credentials()
    await hold_phrases.prewarm(credentials_json)

    llm = create_llm(tools=build_tools_schema())
    register_tools(llm)

    @llm.event_handler("on_function_calls_started")
    async def _on_tool_start(llm, function_calls):
        llm.set_audio_input_paused(True)
        pcm = hold_phrases.get_random_pcm()
        if not pcm:
            return
        chunk_size = 3200
        for i in range(0, len(pcm), chunk_size):
            await llm.push_frame(
                TTSAudioRawFrame(
                    audio=pcm[i : i + chunk_size],
                    sample_rate=16000,
                    num_channels=1,
                )
            )

    context = LLMContext([{"role": "user", "content": INITIAL_USER_MESSAGE}])
    context_aggregator = LLMContextAggregatorPair(
        context,
        realtime_service_mode=True,
        user_params=LLMUserAggregatorParams(
            user_mute_strategies=[FunctionCallUserMuteStrategy()]
        ),
    )

    input_gate = ToolCallInputGate(llm)
    ttfb_starter = TtfbStartOnUserStop(llm)
    latency_observer = create_latency_observer()
    metrics_observer = MetricsLogObserver()

    pipeline = Pipeline(
        [
            transport.input(),
            context_aggregator.user(),
            ttfb_starter,
            llm,
            input_gate,
            transport.output(),
            context_aggregator.assistant(),
        ]
    )

    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            audio_in_sample_rate=16000,
            audio_out_sample_rate=16000,
            enable_metrics=True,
            enable_usage_metrics=True,
            report_only_initial_ttfb=False,
        ),
        observers=[latency_observer, metrics_observer],
        idle_timeout_secs=runner_args.pipeline_idle_timeout_secs,
    )

    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client):
        logger.info("Client connected")
        await task.queue_frames([LLMRunFrame()])

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        logger.info("Client disconnected")
        await task.cancel()

    runner = PipelineRunner(handle_sigint=runner_args.handle_sigint)
    try:
        await runner.run(task)
    finally:
        await close_pool()


async def bot(runner_args: RunnerArguments):
    transport = await create_transport(runner_args, transport_params)
    await run_bot(transport, runner_args)


if __name__ == "__main__":
    from pipecat.runner.run import main

    main()
