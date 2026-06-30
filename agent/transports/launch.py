from __future__ import annotations

import sys

from transports.daily.routes import patch_runner_with_daily_routes
from transports.ngrok import get_cli_port, prepare_public_url, print_startup_banner, print_webrtc_startup_banner


def is_web_mode(argv: list[str] | None = None) -> bool:
    args = argv if argv is not None else sys.argv
    return "-web" in args or "--web" in args


def _strip_flag(argv: list[str], flag: str) -> None:
    while flag in argv:
        idx = argv.index(flag)
        del argv[idx]


def _strip_transport_arg(argv: list[str]) -> None:
    for flag in ("-t", "--transport"):
        while flag in argv:
            idx = argv.index(flag)
            if idx + 1 < len(argv):
                del argv[idx : idx + 2]
            else:
                del argv[idx]


def configure_launch(argv: list[str] | None = None) -> bool:
    """Normalize argv for Daily (default) or WebRTC (-web) launch modes."""
    args = argv if argv is not None else sys.argv
    web_mode = is_web_mode(args)

    for flag in ("-web", "--web"):
        _strip_flag(args, flag)

    if "--host" not in args:
        args.extend(["--host", "0.0.0.0"])

    if web_mode:
        _strip_transport_arg(args)
        if "-t" not in args and "--transport" not in args:
            args.extend(["-t", "webrtc"])
    elif "-t" not in args and "--transport" not in args:
        args.extend(["-t", "daily"])

    return web_mode


def prepare_runner(run_bot, *, web_mode: bool) -> None:
    port = get_cli_port()

    if web_mode:
        print_webrtc_startup_banner(port)
        return

    patch_runner_with_daily_routes(run_bot)
    public_url = prepare_public_url(port)
    print_startup_banner(public_url, port)
