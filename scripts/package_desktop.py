#!/usr/bin/env python3
"""Build and smoke-test the native Relay desktop bundle for one platform."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = re.compile(r"^[0-9A-Za-z][0-9A-Za-z._-]{0,63}$")
FORBIDDEN = (
    "router-settings.json",
    "router-usage.sqlite",
    "provider-catalog-cache.json",
    "reasoning-origins.json",
    "credentials.json",
    "auth.json",
    ".log",
)


def _free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def _platform() -> str:
    if sys.platform == "win32":
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux"


def _executable(root: Path, platform: str) -> Path:
    if platform == "windows":
        return root / "Relay" / "Relay.exe"
    if platform == "macos":
        return root / "Relay.app" / "Contents" / "MacOS" / "Relay"
    return root / "Relay" / "Relay"


def _smoke(binary: Path, package_dir: Path, version: str) -> None:
    with tempfile.TemporaryDirectory(prefix="relay-desktop-smoke-") as directory:
        home = Path(directory) / "codex"
        home.mkdir()
        environment = os.environ.copy()
        environment.update({
            "CODEX_HOME": str(home),
            "CODEX_ROUTER_DATA_DIR": str(home / "model-router"),
            "CODEX_ROUTER_MANAGER_PORT": str(_free_port()),
            "CODEX_ROUTER_PORT": str(_free_port()),
            "RELAY_DESKTOP_CONTROL_PORT": str(_free_port()),
        })
        result = subprocess.run(
            [str(binary), "--server-smoke"],
            cwd=package_dir,
            env=environment,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode:
            raise RuntimeError(f"Desktop smoke test failed:\n{result.stdout}\n{result.stderr}")
        if f'"version": "{version}"' not in result.stdout:
            raise RuntimeError(f"Desktop smoke test reported the wrong version: {result.stdout}")


def _instructions(version: str, platform: str) -> str:
    if platform == "windows":
        open_app = r"Double-click Relay\Relay.exe."
    elif platform == "macos":
        open_app = "Open Relay.app from Finder."
    else:
        open_app = "Run Relay/Relay from your desktop or application menu."
    return f"""Relay {version} desktop for {platform}

{open_app}

Relay opens in its own native window beside Codex. On first launch it
registers a per-user startup entry that waits quietly in the background and
opens Relay when Codex starts. No terminal commands or browser tabs are needed.

Closing the Relay window hides it. Use the Relay tray/menu-bar icon to show it
again or quit the companion. The local router and manager bind to loopback only.

This portable desktop build is not code-signed. Windows SmartScreen or macOS
Gatekeeper may show a warning because the project has no commercial signing
certificate. Verify the published SHA-256 checksum before opening it.
"""


def package(version: str, output_dir: Path) -> Path:
    if not VERSION.fullmatch(version):
        raise ValueError("Version contains unsupported characters")
    declared = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    if declared != version:
        raise ValueError(f"Version {version} does not match VERSION ({declared})")
    if not (ROOT / "app" / "dist" / "index.html").is_file():
        raise RuntimeError("Build the interface first")
    python = Path(sys.executable)
    subprocess.run([str(python), str(ROOT / "desktop" / "create_icon.py")], check=True)
    dist = ROOT / "desktop" / "dist"
    work = ROOT / "desktop" / "build"
    shutil.rmtree(dist, ignore_errors=True)
    shutil.rmtree(work, ignore_errors=True)
    result = subprocess.run(
        [
            str(python), "-m", "PyInstaller", "--noconfirm", "--clean",
            "--distpath", str(dist), "--workpath", str(work),
            str(ROOT / "desktop" / "Relay.spec"),
        ],
        cwd=ROOT,
    )
    if result.returncode:
        raise RuntimeError("PyInstaller desktop build failed")
    platform = _platform()
    binary = _executable(dist, platform)
    if not binary.is_file():
        raise RuntimeError(f"Desktop executable is missing: {binary}")
    _smoke(binary, binary.parent, version)
    shutil.copy2(ROOT / "README.md", dist / "README.md")
    shutil.copy2(ROOT / "VERSION", dist / "VERSION")
    (dist / "INSTALL.txt").write_text(_instructions(version, platform), encoding="utf-8", newline="\n")
    for source in dist.rglob("*"):
        lowered = source.name.lower()
        if any(token in lowered for token in FORBIDDEN):
            raise RuntimeError(f"Desktop bundle contains forbidden runtime state: {source}")
    output_dir.mkdir(parents=True, exist_ok=True)
    extension = "zip" if platform == "windows" else "tar.gz"
    archive = output_dir / f"relay-{version}-{platform}-desktop.{extension}"
    archive.unlink(missing_ok=True)
    if extension == "zip":
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
            for source in sorted(dist.rglob("*")):
                if source.is_file():
                    bundle.write(source, source.relative_to(dist).as_posix())
    else:
        with tarfile.open(archive, "w:gz") as bundle:
            for source in sorted(dist.rglob("*")):
                bundle.add(source, arcname=source.relative_to(dist).as_posix())
    with tempfile.TemporaryDirectory(prefix="relay-desktop-archive-", dir=output_dir) as directory:
        extracted = Path(directory)
        if extension == "zip":
            with zipfile.ZipFile(archive) as bundle:
                bundle.extractall(extracted)
        else:
            with tarfile.open(archive) as bundle:
                try:
                    bundle.extractall(extracted, filter="data")
                except TypeError:  # Python releases before PEP 706 added the filter argument.
                    bundle.extractall(extracted)
        archived_binary = _executable(extracted, platform)
        if not archived_binary.is_file():
            raise RuntimeError("Desktop executable is missing after archive extraction")
        _smoke(archived_binary, archived_binary.parent, version)
    print(f"PASS native {platform} desktop bundle and server smoke test: {archive}")
    return archive


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default=(ROOT / "VERSION").read_text(encoding="utf-8").strip())
    parser.add_argument("--output", type=Path, default=ROOT / "release")
    arguments = parser.parse_args()
    package(arguments.version, arguments.output.resolve())


if __name__ == "__main__":
    main()
