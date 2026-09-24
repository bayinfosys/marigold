"""marigold -- CLI for running Marigold packages.

Three nouns
-----------
platform     postgres, api, worker, cache-init. One per host, shared by
             every package, compose project 'marigold'. Configured
             entirely from the system config, so it starts, stops and
             reports with no package in hand.
package      a directory or archive holding marigold.toml, models.yaml
             files, and application code. Installing one puts it in the
             cache under its name; populating the cache from it writes
             the model catalogue.
application  a package's containers, compose project
             'marigold-<application>'. Started, stopped and resized
             without touching the platform or any other application.

'marigold app ...' is an alias for 'marigold application ...',
Note that it stops the application alone: bringing the platform down is
'marigold platform stop'.

Layout
------
config.py    two TOML layers, package over system, with provenance
paths.py     the cache layout and its creation
packages.py  package identity, archives, installation, resolution
compose.py   compose projects, environment, invocation
commands.py  the cmd_* functions; the only layer that exits
main.py      the parser

The package root is mounted read-only at /app in the executor, so a
flat package runs main.py and a larger one adds modules, workflows and
subdirectories as it needs them. Package layout beyond marigold.toml is
the package's own business -- see PACKAGES.md.

This CLI never runs a model or touches torch. cache validate and
package create import models.catalogue for schema validation only --
that module's import chain was checked directly to confirm it has no
eager side effects (no DB connection, no network call) at import time.
"""

import argparse
import logging
import os
import sys

from cli import commands
from cli.config import package_version
from cli.paths import CacheNotWritable

TARGET_HELP = "installed package name, package directory, or archive"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="marigold")
    parser.add_argument(
        "--version", action="version", version=f"marigold {package_version()}"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # platform
    plat = sub.add_parser("platform", help="manage the shared platform")
    plat_sub = plat.add_subparsers(dest="platform_command", required=True)

    plat_start_p = plat_sub.add_parser("start", help="start the platform")
    plat_start_p.add_argument(
        "target", nargs="?", default=None,
        help=f"optional package whose compose files to add ({TARGET_HELP})",
    )
    plat_start_p.set_defaults(func=commands.cmd_platform_start)

    plat_stop_p = plat_sub.add_parser("stop", help="stop the platform")
    plat_stop_p.add_argument(
        "--applications", action="store_true",
        help="stop every application first",
    )
    plat_stop_p.set_defaults(func=commands.cmd_platform_stop)

    plat_status_p = plat_sub.add_parser("status", help="show platform and application container status")
    plat_status_p.set_defaults(func=commands.cmd_platform_status)

    plat_logs_p = plat_sub.add_parser("logs", help="tail platform logs")
    plat_logs_p.add_argument("service", nargs="?", default=None, help="restrict to one service")
    plat_logs_p.add_argument("--no-follow", action="store_true", help="print current logs and exit, don't tail")
    plat_logs_p.set_defaults(func=commands.cmd_platform_logs)

    # application ('deployment' kept as an alias while marigold.run is updated)
    app = sub.add_parser(
        "application",
        aliases=["app"],
        help="run a package's application against the platform",
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

    # config
    cfg = sub.add_parser("config", help="inspect marigold configuration")
    cfg_sub = cfg.add_subparsers(dest="config_command", required=True)

    path_p = cfg_sub.add_parser("path", help="print the system config file in use")
    path_p.set_defaults(func=commands.cmd_config_path)

    show_p = cfg_sub.add_parser("show", help="print resolved config and where each value came from")
    show_p.add_argument(
        "target", nargs="?", default=None,
        help=f"{TARGET_HELP}, to include package-level values",
    )
    show_p.set_defaults(func=commands.cmd_config_show)

    # cache
    cache = sub.add_parser("cache", help="manage the shared model cache")
    cache_sub = cache.add_subparsers(dest="cache_command", required=True)

    init_p = cache_sub.add_parser("init", help="create the cache layout for this host")
    init_p.set_defaults(func=commands.cmd_cache_init)

    validate_p = cache_sub.add_parser("validate", help="check a package's models.yaml loads cleanly")
    validate_p.add_argument("target", nargs="?", default=".", help=TARGET_HELP)
    validate_p.set_defaults(func=commands.cmd_cache_validate)

    populate_p = cache_sub.add_parser("populate", help="download the models an installed package declares")
    populate_p.add_argument("target", nargs="?", default=".", help="installed package name")
    populate_p.add_argument("--prune", action="store_true", help="remove cached models this package does not declare")
    populate_p.set_defaults(func=commands.cmd_cache_populate)

    inspect_p = cache_sub.add_parser("inspect", help="list cached models, disk usage, and cache location")
    inspect_p.set_defaults(func=commands.cmd_cache_inspect)

    seed_p = cache_sub.add_parser("seed", help="share cached models with the network via torrent (not yet implemented)")
    seed_p.set_defaults(func=commands.cmd_cache_stub)

    # package
    pkg = sub.add_parser("package", help="build and install Marigold packages")
    pkg_sub = pkg.add_subparsers(dest="package_command", required=True)

    create_p = pkg_sub.add_parser("create", help="build a package archive from a directory")
    create_p.add_argument("target", nargs="?", default=".", help="package directory")
    create_p.add_argument("-o", "--output", default=".", help="output directory, or a filename ending in .tar.gz")
    create_p.set_defaults(func=commands.cmd_package_create)

    install_p = pkg_sub.add_parser("install", help="install a package archive")
    install_p.add_argument("archive", help="package archive to install")
    install_p.set_defaults(func=commands.cmd_package_install)

    list_p = pkg_sub.add_parser("list", help="list installed packages")
    list_p.set_defaults(func=commands.cmd_package_list)

    uninstall_p = pkg_sub.add_parser("uninstall", help="remove an installed package")
    uninstall_p.add_argument("name", help="installed package name")
    uninstall_p.set_defaults(func=commands.cmd_package_uninstall)

    for name in ["repo", "update", "sign", "publish"]:
        p = pkg_sub.add_parser(name)
        p.set_defaults(func=commands.cmd_package_stub)

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
