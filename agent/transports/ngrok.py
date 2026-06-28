import atexit
import os
import sys
from urllib.parse import urlparse

from loguru import logger

DEFAULT_PORT = 7860

_ngrok_tunnel = None


def get_cli_port() -> int:
    if "--port" in sys.argv:
        idx = sys.argv.index("--port")
        if idx + 1 < len(sys.argv):
            try:
                return int(sys.argv[idx + 1])
            except ValueError:
                pass
    port_env = os.getenv("PORT", "").strip()
    if port_env.isdigit():
        return int(port_env)
    return DEFAULT_PORT


def _is_cloud_run() -> bool:
    return bool(os.getenv("K_SERVICE"))


def _use_ngrok_locally() -> bool:
    if _is_cloud_run():
        return False
    flag = os.getenv("USE_NGROK", "").strip().lower()
    if flag in ("0", "false", "no"):
        return False
    if flag in ("1", "true", "yes"):
        return True
    return not os.getenv("AGENT_PUBLIC_URL", "").strip()


def _set_agent_public_url(public_url: str) -> str:
    url = public_url.rstrip("/")
    os.environ["AGENT_PUBLIC_URL"] = url
    os.environ["AGENT_SERVER_URL"] = url
    logger.info(f"Agent public URL: {url}")
    return url


def start_ngrok_tunnel(port: int) -> str:
    """Start ngrok HTTP tunnel and return the public hostname (no scheme)."""
    global _ngrok_tunnel
    from pyngrok import ngrok

    token = os.getenv("NGROK_AUTH_TOKEN", "").strip()
    if token:
        ngrok.set_auth_token(token)
        logger.info("Using NGROK_AUTH_TOKEN from environment")
    else:
        logger.warning(
            "NGROK_AUTH_TOKEN not set — using free ngrok (URLs change each restart)"
        )

    _ngrok_tunnel = ngrok.connect(port, "http")
    public_url = _ngrok_tunnel.public_url
    hostname = urlparse(public_url).netloc
    atexit.register(cleanup_ngrok)
    return hostname


def cleanup_ngrok() -> None:
    global _ngrok_tunnel
    if not _ngrok_tunnel:
        return
    try:
        from pyngrok import ngrok

        ngrok.disconnect(_ngrok_tunnel.public_url)
        ngrok.kill()
        logger.info("ngrok tunnel closed")
    except Exception as e:
        logger.error(f"Error closing ngrok tunnel: {e}")
    finally:
        _ngrok_tunnel = None


def prepare_public_url(port: int) -> str:
    """Expose the agent API publicly (ngrok locally, AGENT_PUBLIC_URL on Cloud Run)."""
    if _is_cloud_run():
        url = os.getenv("AGENT_PUBLIC_URL", "").strip().rstrip("/")
        if url:
            return _set_agent_public_url(url)
        return f"http://127.0.0.1:{port}"

    if not _use_ngrok_locally():
        url = (
            os.getenv("AGENT_PUBLIC_URL", "").strip()
            or f"http://127.0.0.1:{port}"
        ).rstrip("/")
        return _set_agent_public_url(url)

    hostname = start_ngrok_tunnel(port)
    return _set_agent_public_url(f"https://{hostname}")


def print_startup_banner(public_url: str, port: int) -> None:
    print()
    print("Mr. Med Daily voice agent:")
    print(f"   Public API: POST {public_url}/daily/start")
    print(f"   Local API:  POST http://127.0.0.1:{port}/daily/start")
    print(f"   Health:     GET  {public_url}/health")
    print()
    print("AGENT_PUBLIC_URL is set in this process (use the same value for the")
    print("separately hosted frontend's AGENT_SERVER_URL env var).")
    print()
