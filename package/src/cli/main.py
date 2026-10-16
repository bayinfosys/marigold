"""marigold -- CLI for running Marigold applications.

Three nouns
-----------
platform     postgres, api, worker, cache-init. One per host, shared by
             every application, in its own compose project. Configured
             entirely from the system config, so it starts, stops and
             reports with no application in hand.
application  a directory or archive holding marigold.toml, models.yaml
             files and application code. Installing one puts it in the
             cache under its name; populating the cache from it writes
             the model catalogue.
instance     an application's running containers, in compose project
             'marigold-<application>'. Started, stopped and inspected
             without touching the platform or any other application.

'marigold app ...' is an alias for 'marigold application ...'. Stopping
an application stops its containers alone: bringing the platform down
is 'marigold platform stop'.

Layout
------
config.py        the two TOML layers
paths.py         the cache layout and its creation
archives.py      writing and extracting application archives
applications.py  identity, declared models, installation, resolution
compose.py       compose projects, environment, invocation
commands.py      the cmd_* functions; the only layer that exits
main.py          the parser

The application root is mounted read-only at /app in the executor, so a
flat application runs main.py and a larger one adds modules and
subdirectories as it needs them. Layout beyond marigold.toml is private
to the application -- see APPLICATIONS.md.

This CLI never runs a model or touches torch. cache validate imports
models.catalogue for schema validation only -- that module's import
chain was checked directly to confirm it has no eager side effects (no
DB connection, no network call) at import time.
"""

import argparse
import logging
import os
import sys

from cli import commands
from cli.config import marigold_version
from cli.paths import CacheNotWritable

TARGET_HELP = "installed application name, directory, or archive"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="marigold")
    parser.add_argument(
        "--version", action="version", version=f"marigold {marigold_version()}"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # platform
    plat = sub.add_parser("platform", help="manage the shared platform")
    plat_sub = plat.add_subparsers(dest="platform_command", required=True)

    plat_start_p = plat_sub.add_parser("start", help="start the platform")
    plat_start_p.add_argument(
        "target", nargs="?", default=None,
        help=f"optional application whose compose files to add ({TARGET_HELP})",
    )
    plat_start_p.set_defaults(func=commands.cmd_platform_start)

    plat_stop_p = plat_sub.add_parser("stop", help="stop the platform")
    plat_stop_p.add_argument(
        "--applications", action="store_true",
        help="stop applications first",
    )
    plat_stop_p.set_defaults(func=commands.cmd_platform_stop)

    plat_status_p = plat_sub.add_parser("status", help="show platform and application container status")
    plat_status_p.set_defaults(func=commands.cmd_platform_status)

    plat_logs_p = plat_sub.add_parser("logs", help="tail platform logs")
    plat_logs_p.add_argument("service", nargs="?", default=None, help="restrict to one service")
    plat_logs_p.add_argument("--no-follow", action="store_true", help="print current logs and exit, don't tail")
    plat_logs_p.set_defaults(func=commands.cmd_platform_logs)

    # application: build, install and run
    app = sub.add_parser(
        "application",
        aliases=["app"],
        help="build, install and run applications",
    )
    app_sub = app.add_subparsers(dest="application_command", required=True)

    for name, fn, help_text in [
        ("start", commands.cmd_application_start, "start the platform and the application"),
        ("stop", commands.cmd_application_stop, "stop the application, leaving the platform up"),
        ("status", commands.cmd_application_status, "show container status"),
    ]:
        p = app_sub.add_parser(name, help=help_text)
        p.add_argument("target", nargs="?", default=".", help=TARGET_HELP)
        p.set_defaults(func=fn)

    app_logs_p = app_sub.add_parser("logs", help="tail application logs")
    app_logs_p.add_argument("target", nargs="?", default=".", help=TARGET_HELP)
    app_logs_p.add_argument("service", nargs="?", default=None, help="restrict to one service")
    app_logs_p.add_argument("--no-follow", action="store_true", help="print current logs and exit, don't tail")
    app_logs_p.set_defaults(func=commands.cmd_application_logs)

    create_p = app_sub.add_parser("create", help="build an application archive from a directory")
    create_p.add_argument("target", nargs="?", default=".", help="application directory")
    create_p.add_argument("-o", "--output", default=".", help="output directory, or a filename ending in .tar.gz")
    create_p.set_defaults(func=commands.cmd_application_create)

    install_p = app_sub.add_parser("install", help="install an application archive")
    install_p.add_argument("archive", help="application archive to install")
    install_p.set_defaults(func=commands.cmd_application_install)

    list_p = app_sub.add_parser("list", help="list installed applications")
    list_p.set_defaults(func=commands.cmd_application_list)

    uninstall_p = app_sub.add_parser("uninstall", help="remove an installed application")
    uninstall_p.add_argument("name", help="installed application name")
    uninstall_p.set_defaults(func=commands.cmd_application_uninstall)

    # config
    cfg = sub.add_parser("config", help="inspect marigold configuration")
    cfg_sub = cfg.add_subparsers(dest="config_command", required=True)

    path_p = cfg_sub.add_parser("path", help="print the system config file in use")
    path_p.set_defaults(func=commands.cmd_config_path)

    show_p = cfg_sub.add_parser("show", help="print resolved config and where each value came from")
    show_p.add_argument(
        "target", nargs="?", default=None,
        help=f"{TARGET_HELP}, to include application-level values",
    )
    show_p.set_defaults(func=commands.cmd_config_show)

    # cache
    cache = sub.add_parser("cache", help="manage the shared model cache")
    cache_sub = cache.add_subparsers(dest="cache_command", required=True)

    init_p = cache_sub.add_parser("init", help="create the cache layout for this host")
    init_p.set_defaults(func=commands.cmd_cache_init)

    validate_p = cache_sub.add_parser("validate", help="check an application's models.yaml loads cleanly")
    validate_p.add_argument("target", nargs="?", default=".", help=TARGET_HELP)
    validate_p.set_defaults(func=commands.cmd_cache_validate)

    populate_p = cache_sub.add_parser("populate", help="download the models an installed application declares")
    populate_p.add_argument("target", nargs="?", default=".", help="installed application name")
    populate_p.add_argument("--prune", action="store_true", help="remove cached models this application does not declare")
    populate_p.set_defaults(func=commands.cmd_cache_populate)

    inspect_p = cache_sub.add_parser("inspect", help="list cached models, disk usage, and cache location")
    inspect_p.set_defaults(func=commands.cmd_cache_inspect)

    seed_p = cache_sub.add_parser("seed", help="share cached models with the network via torrent (not yet implemented)")
    seed_p.set_defaults(func=commands.cmd_cache_stub)

    return parser


def main():
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(levelname)s:%(name)s:%(message)s",
        stream=sys.stderr,
    )

    args = build_parser().parse_args()

    try:
        args.func(args)
    except KeyboardInterrupt:
        print("\nmarigold: interrupted", file=sys.stderr)
        sys.exit(130)
    except (
        FileNotFoundError,
        NotImplementedError,
        PermissionError,
        ValueError,
        CacheNotWritable,
    ) as e:
        print(f"marigold: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
