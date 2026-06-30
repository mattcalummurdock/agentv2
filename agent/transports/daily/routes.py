import asyncio

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from loguru import logger

from transports.daily.room import create_daily_room


def _register_daily_routes(app: FastAPI, run_bot) -> None:
    from transports.daily.session import run_daily_session

    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        logger.info(f"{request.method} {request.url.path}")
        return await call_next(request)

    @app.get("/health")
    async def health_check():
        return JSONResponse({"status": "ok", "transport": "daily"})

    @app.post("/daily/start")
    async def start_daily_voice_session(request: Request):
        """Create a Daily room, start the agent, and return connection details."""
        try:
            logger.info("Creating Daily room for voice session...")
            room_url, token = await create_daily_room()
            asyncio.create_task(run_daily_session(room_url, token, run_bot))
            return JSONResponse({"room_url": room_url, "token": token})
        except Exception as e:
            logger.error(f"Failed to start Daily session: {e}")
            return JSONResponse(status_code=500, content={"error": str(e)})


def patch_runner_with_daily_routes(run_bot) -> None:
    """Register Daily session routes on Pipecat's runner FastAPI app."""
    import pipecat.runner.run as runner_run

    # Pipecat >= 1.4: module-level app, configured by main() via _configure_server_app
    if hasattr(runner_run, "app"):
        _register_daily_routes(runner_run.app, run_bot)
        return

    # Pipecat < 1.4: monkey-patch internal app factory
    if hasattr(runner_run, "_create_server_app"):
        from fastapi.middleware.cors import CORSMiddleware

        original_create = runner_run._create_server_app

        def create_server_app_with_daily(args):
            app = original_create(args)
            app.add_middleware(
                CORSMiddleware,
                allow_origins=["*"],
                allow_credentials=True,
                allow_methods=["*"],
                allow_headers=["*"],
            )
            _register_daily_routes(app, run_bot)
            return app

        runner_run._create_server_app = create_server_app_with_daily
        return

    raise RuntimeError(
        "Unsupported pipecat runner: expected pipecat.runner.run.app "
        "(>= 1.4) or _create_server_app (< 1.4)"
    )
