"""Entry point for the repository launchers.

Prepares the managed Python environment and starts Open Nest. Runs under whatever Python
the Mac already has, so it must stay Python 3.9-compatible (PLAN.md section 2.1).

    python3 bootstrap/bootstrap.py --setup     # prepare, then launch
    python3 bootstrap/bootstrap.py --launch    # launch an already-prepared install
"""

from __future__ import annotations

import argparse
import contextlib
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bootstrap import environment as env  # noqa: E402
from bootstrap import python_setup  # noqa: E402
from bootstrap.environment import SetupError  # noqa: E402

TITLE = "Open Nest Setup"

#: Imports that must work before setup is allowed to report success.
REQUIRED_IMPORTS = ("PySide6.QtWidgets", "keyring")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare and launch Open Nest.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--setup", action="store_true", help="prepare the environment, then launch")
    mode.add_argument("--launch", action="store_true", help="launch an existing installation")
    args = parser.parse_args(argv)

    try:
        if args.launch and not args.setup:
            return _launch_only()
        return _setup_then_launch()
    except SetupError as exc:
        report_error(str(exc))
        return 1
    except KeyboardInterrupt:
        _say("\nSetup cancelled.")
        return 130


def _setup_then_launch() -> int:
    machine = env.detect_machine()
    _report_machine(machine)

    problems = machine.problems()
    if problems:
        # Warn, but let the parent decide -- an unsupported Mac is not always a broken one.
        report_error("\n\n".join(problems), caution=True)

    if not env.venv_is_usable():
        python_exe = env.find_python() or _install_python()
        _say("Creating the Open Nest environment...")
        env.create_venv(python_exe)

    _say("Installing what Open Nest needs. This can take a few minutes...")
    env.install_requirements([_requirements("base.txt")])

    missing = env.verify_imports(REQUIRED_IMPORTS)
    if missing:
        raise SetupError(
            "Open Nest installed, but these components could not be loaded:\n\n  "
            + "\n  ".join(missing)
            + "\n\nTry running Setup again."
        )

    _say("Ready.")
    return _run_app()


def _install_python() -> str:
    """This Mac has no suitable Python, so Open Nest installs its own."""
    _say(
        f"This Mac does not have Python {env.MIN_PYTHON[0]}.{env.MIN_PYTHON[1]} yet, so "
        f"Open Nest will install its own copy.\nIt is used only by Open Nest and nothing "
        f"else on this Mac changes.\n"
    )
    # Same rounding the progress line uses, so "about 24 MB" is not followed by "24.0 MB".
    megabytes = round(python_setup.PINNED_SIZE_BYTES / (1024 * 1024))
    _say(f"Downloading Python {python_setup.PINNED_VERSION} (about {megabytes} MB)...")
    executable = python_setup.install(progress=_download_progress)
    _say(f"\nInstalled Python {python_setup.PINNED_VERSION}.")
    return executable


def _download_progress(downloaded: int, total: int) -> None:
    if not total:
        return
    percent = int(downloaded * 100 / total)
    megabyte = 1024.0 * 1024.0
    sys.stdout.write(
        f"\r  {percent:3d}%  {downloaded / megabyte:.1f} of {total / megabyte:.1f} MB"
    )
    sys.stdout.flush()


def _launch_only() -> int:
    if not env.venv_is_usable():
        raise SetupError(
            'Open Nest is not set up on this Mac yet.\n\nOpen "Setup Open Nest.command" first.'
        )
    return _run_app()


def _run_app() -> int:
    """Start Open Nest and let the launcher exit.

    Detached on purpose: a .command keeps its Terminal window open for as long as the
    script runs, and WORKORDER_01 section 35A wants no visible Terminal dependency.
    """
    # Phase 8 replaces this with the setup-wizard / app decision described in
    # WORKORDER_01 section 35A ("Relaunch behavior").
    try:
        subprocess.Popen(
            [env.venv_python(), "-m", "opennest.app"],
            cwd=env.repo_root(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as exc:
        raise SetupError(f"Open Nest could not start.\n\n{exc}") from exc
    return 0


def _requirements(name: str) -> str:
    return os.path.join(env.repo_root(), "requirements", name)


def _report_machine(machine: env.MachineInfo) -> None:
    hardware = "Apple silicon" if machine.is_apple_silicon else machine.arch
    _say(f"Mac detected:   {hardware}")
    _say(f"macOS:          {machine.macos_version or 'unknown'}")
    _say(f"Memory:         {machine.memory_gb:.0f} GB")
    _say(f"Free storage:   {machine.free_disk_gb:.0f} GB")
    _say("")


def _say(message: str) -> None:
    sys.stdout.write(message + "\n")
    sys.stdout.flush()


def report_error(message: str, title: str = TITLE, caution: bool = False) -> None:
    """Show a GUI dialog, because the launcher may be double-clicked from Finder."""
    sys.stderr.write(f"\n{title}\n{message}\n")
    sys.stderr.flush()
    icon = "caution" if caution else "stop"
    script = (
        f"display dialog {_applescript_string(message)} "
        f"with title {_applescript_string(title)} "
        f'buttons {{"OK"}} default button 1 with icon {icon}'
    )
    with contextlib.suppress(OSError, subprocess.SubprocessError):
        subprocess.run(
            ["osascript", "-e", script],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=300,
        )


def _applescript_string(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return '"' + escaped.replace("\n", "\\n") + '"'


if __name__ == "__main__":
    sys.exit(main())
