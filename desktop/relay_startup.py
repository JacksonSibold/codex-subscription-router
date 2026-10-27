"""Small cross-platform autostart registrar for the Relay desktop companion."""
from __future__ import annotations

import base64
import os
from pathlib import Path
import plistlib
import subprocess
import sys

APP_ID = "com.relay.codex-router"


def _startup_paths() -> tuple[Path, Path | None]:
    home = Path.home()
    if sys.platform == "win32":
        startup = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
        start_menu = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
        return startup / "Relay.lnk", start_menu / "Relay.lnk"
    if sys.platform == "darwin":
        return home / "Library" / "LaunchAgents" / f"{APP_ID}.plist", home / "Applications" / "Relay.app"
    config = Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config")
    return config / "autostart" / "relay.desktop", None


def _powershell_shortcut(shortcut: Path, target: Path, arguments: str, working_directory: Path) -> None:
    shortcut.parent.mkdir(parents=True, exist_ok=True)
    script = "\n".join((
        "$ErrorActionPreference = 'Stop'",
        "$shell = New-Object -ComObject WScript.Shell",
        f"$link = $shell.CreateShortcut({str(shortcut)!r})",
        f"$link.TargetPath = {str(target)!r}",
        f"$link.Arguments = {arguments!r}",
        f"$link.WorkingDirectory = {str(working_directory)!r}",
        "$link.Description = 'Relay companion for Codex'",
        "$link.Save()",
    ))
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
        capture_output=True,
        text=True,
        timeout=20,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if result.returncode:
        raise RuntimeError(f"Could not create Relay startup shortcut: {result.stderr.strip()}")


def install_startup(executable: Path, script: Path | None = None) -> list[Path]:
    """Register Relay to start hidden with the desktop session and appear with Codex."""
    executable = executable.resolve()
    startup, start_menu = _startup_paths()
    startup.parent.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        if script is not None:
            pythonw = Path(sys.executable).with_name("pythonw.exe")
            target, arguments = pythonw, f'"{script.resolve()}" --startup'
            working = script.resolve().parent.parent
        else:
            target, arguments, working = executable, "--startup", executable.parent
        _powershell_shortcut(startup, target, arguments, working)
        if start_menu is not None:
            menu_target = executable if script is None else Path(sys.executable)
            menu_args = "" if script is None else f'"{script.resolve()}"'
            _powershell_shortcut(start_menu, menu_target, menu_args, working)
        return [startup] + ([start_menu] if start_menu else [])

    if sys.platform == "darwin":
        startup.parent.mkdir(parents=True, exist_ok=True)
        command = [str(executable)]
        if script is not None:
            command = [sys.executable, str(script.resolve())]
        document = {
            "Label": APP_ID,
            "ProgramArguments": [*command, "--startup"],
            "RunAtLoad": True,
            "KeepAlive": False,
            "ProcessType": "Interactive",
        }
        startup.write_bytes(plistlib.dumps(document))
        return [startup]

    command = [str(executable)] if script is None else [sys.executable, str(script.resolve())]
    quoted = " ".join(f'"{item}"' if " " in item else item for item in command)
    startup.write_text(
        "\n".join((
            "[Desktop Entry]",
            "Type=Application",
            "Name=Relay",
            "Comment=Subscription router companion for Codex",
            f"Exec={quoted} --startup",
            "Terminal=false",
            "X-GNOME-Autostart-enabled=true",
            "",
        )),
        encoding="utf-8",
    )
    return [startup]


def uninstall_startup() -> list[Path]:
    startup, start_menu = _startup_paths()
    removed: list[Path] = []
    for path in (startup, start_menu):
        if path is not None and path.is_file():
            path.unlink()
            removed.append(path)
    return removed
