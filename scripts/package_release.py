#!/usr/bin/env python3
"""Build an allowlisted Relay archive for one supported desktop platform."""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import shutil
import tarfile
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = re.compile(r"^[0-9A-Za-z][0-9A-Za-z._-]{0,63}$")
PLATFORMS = ("windows", "linux", "macos")
LAUNCHERS = (
    "Start Relay.cmd", "Start Router.cmd",
    "Start Relay.sh", "Start Router.sh",
    "Start Relay.command", "Start Router.command",
)


def _copy(source: Path, destination: Path) -> None:
    if not source.is_file():
        raise FileNotFoundError(f"Release source is missing: {source.name}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def _source_version(root: Path) -> str | None:
    try:
        value = (root / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return value or None


def _instructions(version: str, platform: str) -> str:
    if platform == "windows":
        launch = "Double-click Start Router.cmd, then Start Relay.cmd."
        install = r"python scripts\install.py --configure-codex"
    elif platform == "macos":
        launch = "Run ./Start Router.sh, then ./Start Relay.sh. You can also double-click the .command files in Finder."
        install = "python3 scripts/install.py --configure-codex"
    else:
        launch = "Run ./Start Router.sh, then ./Start Relay.sh."
        install = "python3 scripts/install.py --configure-codex"
    return f"""Relay {version} for {platform}

Requirements: Python 3.11 or newer and an existing Codex installation.

Preview without changing Codex configuration:
{launch}
The interface opens at http://127.0.0.1:18766/.

Install into the selected Codex home, with backups:
{install}

The installer does not restart Codex or the running router. API keys and Relay's
Claude OAuth tokens use the current user's protected credential store; Codex's
ChatGPT sign-in stays in Codex. Local models use loopback OpenAI-compatible
endpoints. See README.md for details.
"""


def package(root: Path, platform: str, version: str, output_dir: Path) -> Path:
    if platform not in PLATFORMS:
        raise ValueError(f"Unsupported platform: {platform}")
    if not VERSION.fullmatch(version):
        raise ValueError("Version must contain only letters, numbers, dots, underscores, and hyphens")
    declared = _source_version(root)
    if declared and declared != version:
        raise ValueError(f"Release version {version} does not match VERSION ({declared})")
    if not (root / "app" / "dist" / "index.html").is_file():
        raise RuntimeError("Build the interface first: cd app && npm ci && npm run build")

    output_dir.mkdir(parents=True, exist_ok=True)
    extension = "zip" if platform == "windows" else "tar.gz"
    archive = output_dir / f"relay-{version}-{platform}.{extension}"
    package_name = f"relay-{version}-{platform}"

    with tempfile.TemporaryDirectory(prefix=".relay-package-", dir=output_dir) as directory:
        target = Path(directory) / package_name
        target.mkdir()
        for name in ("README.md", "CHANGELOG.md", "VERSION"):
            _copy(root / name, target / name)
        for name in LAUNCHERS:
            _copy(root / name, target / name)
        for source in sorted((root / "router").glob("*.py")):
            _copy(source, target / "router" / source.name)
        for source in sorted((root / "catalog").glob("*.json")):
            _copy(source, target / "catalog" / source.name)
        for source in sorted((root / "examples").glob("*")):
            if source.is_file():
                _copy(source, target / "examples" / source.name)
        _copy(root / "scripts" / "install.py", target / "scripts" / "install.py")
        shutil.copytree(root / "app" / "dist", target / "app" / "dist")
        (target / "INSTALL.txt").write_text(_instructions(version, platform), encoding="utf-8", newline="\n")

        if platform != "windows":
            for name in ("Start Relay.sh", "Start Router.sh", "Start Relay.command", "Start Router.command"):
                (target / name).chmod(0o755)
            (target / "scripts" / "install.py").chmod(0o755)

        archive.unlink(missing_ok=True)
        if platform == "windows":
            with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
                for source in sorted(target.rglob("*")):
                    if source.is_file():
                        bundle.write(source, source.relative_to(Path(directory)).as_posix())
        else:
            executable = {"Start Relay.sh", "Start Router.sh", "Start Relay.command", "Start Router.command", "scripts/install.py"}

            def archive_mode(item: tarfile.TarInfo) -> tarfile.TarInfo:
                relative = Path(item.name).relative_to(package_name).as_posix()
                if relative in executable:
                    item.mode = 0o755
                elif item.isdir() and relative == ".":
                    item.mode = 0o755
                return item

            with tarfile.open(archive, "w:gz", format=tarfile.PAX_FORMAT) as bundle:
                bundle.add(target, arcname=package_name, recursive=True, filter=archive_mode)
    return archive


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", choices=PLATFORMS, required=True)
    parser.add_argument("--version", default=None, help="Release version; defaults to the repository VERSION file")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "release")
    parser.add_argument("--root", type=Path, default=ROOT, help=argparse.SUPPRESS)
    arguments = parser.parse_args()
    root = arguments.root.resolve()
    selected_version = arguments.version or _source_version(root)
    if not selected_version:
        parser.error("--version is required when the source tree has no VERSION file")
    archive = package(root, arguments.platform, selected_version, arguments.output_dir.resolve())
    print(f"Built {archive}")


if __name__ == "__main__":
    main()
