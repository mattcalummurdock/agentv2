#
# Copyright (c) 2025, Daily
#
# SPDX-License-Identifier: BSD 2-Clause License
#

import asyncio
import atexit
import sys

from dotenv import load_dotenv
from loguru import logger
from pipecat.frames.frames import TTSAudioRawFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.runner.types import RunnerArguments
from pipecat.runner.utils import create_transport, parse_telephony_websocket
from pipecat.transports.base_transport import BaseTransport
from pipecat.turns.user_mute import FunctionCallUserMuteStrategy

from config.transport import transport_params
from post_processor import parse_call_session, process_call_end, shutdown_postprocessor
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
from transports import register_session_handlers
from transports.daily.routes import patch_runner_with_daily_routes
from transports.ngrok import get_cli_port, prepare_public_url, print_startup_banner

load_dotenv(override=True)


def _log_postprocess_task(task: asyncio.Task) -> None:
    try:
        task.result()
    except asyncio.CancelledError:
        logger.warning("Post-processing task was cancelled")
    except Exception as e:
        logger.error(f"Post-processing failed: {e}")


async def run_bot(
    transport: BaseTransport,
    runner_args: RunnerArguments,
    *,
    call_data: dict | None = None,
):
    logger.info("Starting Agent (Gemini 3.1 Flash Live)")

    session = parse_call_session(call_data)
    postprocess_tasks: list[asyncio.Task] = []

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

    async def _on_session_end(label: str) -> None:
        logger.info(f"{label} — scheduling post-processing")
        messages = context.get_messages()
        pp_task = asyncio.create_task(
            process_call_end(
                messages,
                caller_phone=session.customer_phone,
                call_sid=session.call_sid,
            )
        )
        pp_task.add_done_callback(_log_postprocess_task)
        postprocess_tasks.append(pp_task)
        await task.cancel()

    register_session_handlers(transport, task, _on_session_end)

    runner = PipelineRunner(handle_sigint=runner_args.handle_sigint)
    try:
        await runner.run(task)
    finally:
        if postprocess_tasks:
            await asyncio.gather(*postprocess_tasks, return_exceptions=True)
        await close_pool()


async def bot(runner_args: RunnerArguments):
    call_data = None
    if getattr(runner_args, "websocket", None):
        _, call_data = await parse_telephony_websocket(runner_args.websocket)

    transport = await create_transport(runner_args, transport_params)
    await run_bot(transport, runner_args, call_data=call_data)


atexit.register(shutdown_postprocessor)


if __name__ == "__main__":
    from pipecat.runner.run import main

    patch_runner_with_daily_routes(run_bot)

    if "--host" not in sys.argv:
        sys.argv.extend(["--host", "0.0.0.0"])

    port = get_cli_port()
    public_url = prepare_public_url(port)
    print_startup_banner(public_url, port)

    main()
