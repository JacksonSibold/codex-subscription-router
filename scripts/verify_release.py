#!/usr/bin/env python3
"""Extract a release archive and smoke-test its packaged manager and router."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
import tomllib
import urllib.error
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PLATFORMS = ("windows", "linux", "macos")
LAUNCHERS = {
    "Start Relay.cmd", "Start Router.cmd", "Start Relay.sh", "Start Router.sh",
    "Start Relay.command", "Start Router.command",
}
FORBIDDEN = (
    "auth.json", "credentials.json", "router-settings.json", "mixed-models.json",
    "router.log", "reasoning-origins.json", ".sqlite", ".dev-codex", "__pycache__",
)


def _archive_details(archive: Path) -> tuple[str, str, str]:
    for platform in PLATFORMS:
        extension = ".zip" if platform == "windows" else ".tar.gz"
        suffix = f"-{platform}{extension}"
        if archive.name.endswith(suffix) and archive.name.startswith("relay-"):
            package_name = archive.name[:-len(extension)]
            version = package_name.removeprefix("relay-").removesuffix(f"-{platform}")
            return platform, version, package_name
    raise ValueError(f"Unrecognized release archive name: {archive.name}")


def _safe_target(base: Path, name: str) -> Path:
    target = (base / name).resolve()
    try:
        target.relative_to(base.resolve())
    except ValueError:
        raise ValueError(f"Archive member escapes extraction directory: {name}") from None
    return target


def _extract(archive: Path, destination: Path, platform: str) -> list[str]:
    names: list[str] = []
    if platform == "windows":
        with zipfile.ZipFile(archive) as bundle:
            for info in bundle.infolist():
                _safe_target(destination, info.filename)
                names.append(info.filename)
            bundle.extractall(destination)
        return names
    with tarfile.open(archive, "r:gz") as bundle:
        for member in bundle.getmembers():
            _safe_target(destination, member.name)
            if member.issym() or member.islnk() or not (member.isfile() or member.isdir()):
                raise ValueError(f"Unexpected archive member type: {member.name}")
            names.append(member.name)
            if member.name.rsplit("/", 1)[-1] in ("Start Relay.sh", "Start Router.sh", "Start Relay.command", "Start Router.command", "install.py"):
                if member.mode & 0o777 != 0o755:
                    raise ValueError(f"Executable mode is wrong for {member.name}: {member.mode & 0o777:o}")
        try:
            bundle.extractall(destination, filter="fully_trusted")
        except TypeError:  # Python 3.11 releases before PEP 706 added the filter argument.
            bundle.extractall(destination)
    return names


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _wait_json(url: str, timeout: float = 20.0) -> dict:
    deadline = time.time() + timeout
    last: Exception | None = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                value = json.load(response)
            if isinstance(value, dict):
                return value
        except (OSError, ValueError, urllib.error.URLError) as exc:
            last = exc
        time.sleep(0.2)
    raise RuntimeError(f"Timed out waiting for {url}: {type(last).__name__ if last else 'unknown'}")


def _environment(home: Path) -> dict[str, str]:
    env = dict(os.environ)
    env.update({
        "CODEX_HOME": str(home),
        "CODEX_ROUTER_DEV": "1",
        "CODEX_ROUTER_SETTINGS": str(home / "router-settings.json"),
        "CODEX_ROUTER_CREDENTIALS": str(home / "credentials.json"),
        "CODEX_ROUTER_USAGE_DB": str(home / "router-usage.sqlite"),
        "OPENCODE_AUTH_PATH": str(home / "opencode-auth.json"),
        "PYTHONUNBUFFERED": "1",
    })
    return env


def _start(script: Path, env: dict[str, str]) -> subprocess.Popen:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    return subprocess.Popen(
        [sys.executable, str(script)], env=env, cwd=script.parent.parent,
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        creationflags=flags,
    )


def _stop(process: subprocess.Popen) -> str:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    stdout, stderr = process.communicate(timeout=5)
    return (stdout + stderr).decode("utf-8", "replace")[-4000:]


def _verify_installer(package: Path, workspace: Path, version: str) -> None:
    """Run the shipped installer and launch the installed manager layout."""
    home = workspace / "installed-codex"
    home.mkdir()
    (home / "config.toml").write_text(
        'custom_marker = "preserve-me"\n\n[projects.verification]\ntrust_level = "trusted"\n',
        encoding="utf-8",
    )
    environment = _environment(home)
    result = subprocess.run(
        [sys.executable, str(package / "scripts" / "install.py"),
         "--codex-home", str(home), "--configure-codex"],
        cwd=package, env=environment, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=120,
    )
    if result.returncode:
        output = result.stdout.decode("utf-8", "replace")[-4000:]
        raise RuntimeError(f"Packaged installer failed ({result.returncode}):\n{output}")

    installed = home / "model-router"
    for required in ("VERSION", "manager.py", "router.py", "version.py", "app/index.html",
                     "router-settings.json"):
        if not (installed / required).is_file():
            raise RuntimeError(f"Installer did not create model-router/{required}")
    if (installed / "VERSION").read_text(encoding="utf-8").strip() != version:
        raise RuntimeError("Installer wrote the wrong installed VERSION")
    for launcher in LAUNCHERS:
        if not (home / launcher).is_file():
            raise RuntimeError(f"Installer did not create {launcher}")
    if os.name != "nt":
        for launcher in ("Start Relay.sh", "Start Router.sh", "Start Relay.command", "Start Router.command"):
            if (home / launcher).stat().st_mode & 0o111 != 0o111:
                raise RuntimeError(f"Installer did not preserve executable mode for {launcher}")

    catalog = json.loads((home / "mixed-models.json").read_text(encoding="utf-8"))
    if len(catalog.get("models", [])) != 11:
        raise RuntimeError("Installer did not generate all eleven default model routes")
    config = tomllib.loads((home / "config.toml").read_text(encoding="utf-8"))
    if config.get("custom_marker") != "preserve-me" or config.get("model_provider") != "mixed":
        raise RuntimeError("Installer did not preserve and configure Codex safely")
    if config.get("projects", {}).get("verification", {}).get("trust_level") != "trusted":
        raise RuntimeError("Installer changed an unrelated Codex project setting")
    if config.get("model_catalog_json") != str(home / "mixed-models.json"):
        raise RuntimeError("Installer did not point Codex at the isolated generated catalog")

    port = _free_port()
    installed_environment = _environment(home)
    installed_environment.pop("CODEX_ROUTER_DEV", None)
    installed_environment.update({
        "CODEX_ROUTER_MANAGER_PORT": str(port),
        "CODEX_ROUTER_PORT": str(_free_port()),
        "CODEX_ROUTER_SETTINGS": str(installed / "router-settings.json"),
        "CODEX_ROUTER_CREDENTIALS": str(home / "credentials.json"),
        "CODEX_ROUTER_USAGE_DB": str(installed / "router-usage.sqlite"),
    })
    manager = _start(installed / "manager.py", installed_environment)
    try:
        state = _wait_json(f"http://127.0.0.1:{port}/api/state")
        if state.get("version") != version or len(state.get("settings", {}).get("models", [])) != 11:
            raise RuntimeError("Installed manager did not expose the complete 1.0 state")
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as response:
            if b'<div id="root">' not in response.read():
                raise RuntimeError("Installed manager did not serve the production interface")
    finally:
        logs = _stop(manager)
        if manager.returncode not in (0, -15, 143, 1, 3221225786):
            raise RuntimeError(f"Installed manager exited unexpectedly ({manager.returncode}):\n{logs}")


def verify(archive: Path) -> None:
    archive = archive.resolve()
    platform, version, package_name = _archive_details(archive)
    with tempfile.TemporaryDirectory(prefix="relay-verify-", dir=archive.parent) as directory:
        workspace = Path(directory)
        names = _extract(archive, workspace, platform)
        package = workspace / package_name
        if not (package / "app" / "dist" / "index.html").is_file():
            raise RuntimeError("Packaged production interface is missing")
        if not LAUNCHERS.issubset({name.rsplit("/", 1)[-1] for name in names}):
            raise RuntimeError("One or more portable launchers are missing")
        declared = (package / "VERSION").read_text(encoding="utf-8").strip()
        if declared != version:
            raise RuntimeError(f"Packaged VERSION is {declared}, expected {version}")
        lowered = "\n".join(names).lower()
        for forbidden in FORBIDDEN:
            if forbidden in lowered:
                raise RuntimeError(f"Archive contains forbidden runtime state: {forbidden}")
        for required in ("router/manager.py", "router/router.py", "router/version.py", "scripts/install.py"):
            if not (package / required).is_file():
                raise RuntimeError(f"Archive is missing {required}")

        home = workspace / "home"
        home.mkdir()
        manager_port = _free_port()
        router_port = _free_port()
        manager_env = _environment(home)
        manager_env["CODEX_ROUTER_MANAGER_PORT"] = str(manager_port)
        manager = _start(package / "router" / "manager.py", manager_env)
        router = None
        try:
            base = f"http://127.0.0.1:{manager_port}"
            state = _wait_json(base + "/api/state")
            if state.get("version") != version:
                raise RuntimeError(f"Manager reports version {state.get('version')!r}, expected {version}")
            if len(state.get("settings", {}).get("models", [])) != 11:
                raise RuntimeError("Packaged manager did not load the eleven default routes")
            providers = {row.get("provider") for row in state.get("available_models", [])}
            if not {"openai", "anthropic", "kimi", "opencode"}.issubset(providers):
                raise RuntimeError("Packaged add-model catalog is incomplete")
            if not state.get("usage", {}).get("accounts"):
                raise RuntimeError("Packaged usage inventory is empty")
            with urllib.request.urlopen(base + "/", timeout=5) as response:
                if b'<div id="root">' not in response.read():
                    raise RuntimeError("Packaged interface index was not served")
            payload = json.dumps({"settings": state["settings"]}).encode()
            preview_request = urllib.request.Request(
                base + "/api/preview", data=payload, method="POST",
                headers={"Content-Type": "application/json", "X-Router-Manager": "1"},
            )
            with urllib.request.urlopen(preview_request, timeout=10) as response:
                preview = json.load(response)
            if len(preview.get("models", [])) != 11:
                raise RuntimeError("Packaged catalog preview did not include all default routes")

            router_env = _environment(home)
            router_env["CODEX_ROUTER_PORT"] = str(router_port)
            router = _start(package / "router" / "router.py", router_env)
            health = _wait_json(f"http://127.0.0.1:{router_port}/__router_health")
            if health.get("relay_version") != version or health.get("models") != 11:
                raise RuntimeError(f"Packaged router health is incomplete: {health}")
            catalog = json.loads((home / "mixed-models.json").read_text(encoding="utf-8"))
            if len(catalog.get("models", [])) != 11:
                raise RuntimeError("Packaged router did not generate all default catalog routes")
        finally:
            if router is not None:
                _stop(router)
            logs = _stop(manager)
            if manager.returncode not in (0, -15, 143, 1, 3221225786):
                raise RuntimeError(f"Packaged manager exited unexpectedly ({manager.returncode}):\n{logs}")
        _verify_installer(package, workspace, version)
    print(f"PASS packaged {platform} archive: version, launchers, UI, API, catalog, usage, router, installer")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    arguments = parser.parse_args()
    verify(arguments.archive)


if __name__ == "__main__":
    main()
