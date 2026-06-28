import asyncio

from fastapi import Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger

from transports.daily.room import create_daily_room


def patch_runner_with_daily_routes(run_bot) -> None:
    """Pipecat builds the FastAPI app inside main(); hook Daily session routes."""
    import pipecat.runner.run as runner_run

    from transports.daily.session import run_daily_session

    original_create = runner_run._create_server_app

    def create_server_app_with_daily(**kwargs):
        app = original_create(**kwargs)

        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

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

        return app

    runner_run._create_server_app = create_server_app_with_daily
