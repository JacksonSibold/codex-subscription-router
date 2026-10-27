"""Install Relay without restarting Codex or changing provider credentials."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
from datetime import datetime, timezone
import tomllib

ROOT = Path(__file__).resolve().parents[1]
STAMP = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        shutil.copy2(path, path.with_name(path.name + ".backup-" + STAMP))
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".tmp-", dir=path.parent)
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    os.replace(temporary, path)


def _set_toml_key(section: str, key: str, value: str) -> str:
    pattern = re.compile(rf"(?m)^\s*{re.escape(key)}\s*=.*$")
    line = f"{key} = {value}"
    if pattern.search(section):
        return pattern.sub(lambda _match: line, section, count=1)
    return section.rstrip() + ("\n" if section.strip() else "") + line + "\n"


def _remove_toml_key(section: str, key: str) -> str:
    pattern = re.compile(rf"(?m)^\s*{re.escape(key)}\s*=.*(?:\r?\n)?")
    return pattern.sub("", section, count=1)


def _set_toml_table(document: str, table: str, values: dict[str, str]) -> str:
    pattern = re.compile(rf"(?ms)^\[{re.escape(table)}\]\s*\n.*?(?=^\[|\Z)")
    match = pattern.search(document)
    body = f"[{table}]\n"
    if match:
        body = match.group(0)
    for key, value in values.items():
        body = _set_toml_key(body, key, value)
    if match:
        return document[:match.start()] + body.rstrip() + "\n\n" + document[match.end():]
    return document.rstrip() + "\n\n" + body


def configure_codex(path: Path, default_model: str, reasoning_effort: str | None, catalog_path: Path) -> None:
    original = path.read_text(encoding="utf-8") if path.exists() else ""
    if original:
        tomllib.loads(original)
    split = re.search(r"(?m)^\[", original)
    header = original[:split.start()] if split else original
    rest = original[split.start():] if split else ""
    for key, value in {
        "model": json.dumps(default_model),
        "model_provider": '"mixed"',
        "model_catalog_json": json.dumps(str(catalog_path)),
    }.items():
        header = _set_toml_key(header, key, value)
    if reasoning_effort:
        header = _set_toml_key(header, "model_reasoning_effort", json.dumps(reasoning_effort))
    else:
        header = _remove_toml_key(header, "model_reasoning_effort")
    result = header.rstrip() + "\n\n" + rest.lstrip("\n")
    result = _set_toml_table(result, "model_providers.mixed", {
        "name": '"Relay — OpenAI + OpenCode Go + Claude + Kimi + Local"',
        "base_url": '"http://127.0.0.1:18765"',
        "wire_api": '"responses"',
        "requires_openai_auth": "true",
        "supports_websockets": "false",
    })
    result = _set_toml_table(result, "desktop", {
        "enabled-reasoning-efforts": '["minimal", "low", "medium", "high", "xhigh", "max"]',
    })
    result = _set_toml_table(result, "agents", {"enabled": "true"})
    tomllib.loads(result)
    atomic_write(path, result)


def configure_codex_for_settings(path: Path, document: dict, catalog_path: Path) -> None:
    selected = next(model for model in document["models"] if model["id"] == document["runtime"]["default_model"])
    configure_codex(path, selected["id"], selected["reasoning"]["default"], catalog_path)


def install(codex_home: Path, configure: bool) -> None:
    target = codex_home / "model-router"
    target.mkdir(parents=True, exist_ok=True)
    static = ROOT / "app" / "dist"
    if not (static / "index.html").is_file():
        raise RuntimeError("Build the interface first: cd app && npm ci && npm run build")
    for source in (ROOT / "router").glob("*.py"):
        destination = target / source.name
        if destination.exists():
            shutil.copy2(destination, destination.with_name(destination.name + ".backup-" + STAMP))
        shutil.copy2(source, destination)
    version_source = ROOT / "VERSION"
    if version_source.is_file():
        shutil.copy2(version_source, target / "VERSION")
    if (target / "app").exists():
        shutil.rmtree(target / "app")
    shutil.copytree(static, target / "app")
    desktop_source = ROOT / "desktop" / "dist" / ("Relay.app" if sys.platform == "darwin" else "Relay")
    if desktop_source.is_dir():
        desktop_target = target / ("desktop/Relay.app" if sys.platform == "darwin" else "desktop")
        if desktop_target.exists():
            shutil.rmtree(desktop_target)
        shutil.copytree(desktop_source, desktop_target)
    for name in ("Start Relay.cmd", "Start Router.cmd", "Start Relay.sh", "Start Router.sh", "Start Relay.command", "Start Router.command"):
        source = ROOT / name
        if source.is_file():
            shutil.copy2(source, codex_home / name)
    catalog_target = codex_home / "opencode-go-models.json"
    if catalog_target.exists():
        shutil.copy2(catalog_target, catalog_target.with_name(catalog_target.name + ".backup-" + STAMP))
    shutil.copy2(ROOT / "catalog" / "opencode-go-models.json", catalog_target)

    os.environ["CODEX_HOME"] = str(codex_home)
    os.environ["CODEX_ROUTER_SETTINGS"] = str(target / "router-settings.json")
    sys.path.insert(0, str(target))
    import router
    import settings
    document = settings.load(target / "router-settings.json")
    if not (target / "router-settings.json").exists():
        settings.save(target / "router-settings.json", document)
    models = router.build_catalog(document)
    if configure:
        configure_codex_for_settings(codex_home / "config.toml", document, codex_home / "mixed-models.json")
    print(f"Installed Relay in {target}")
    print(f"Generated {len(models)} picker entries in {codex_home / 'mixed-models.json'}")
    print("Codex and the running router were not restarted. Start the new router when convenient.")
    launcher = "Start Relay.cmd" if os.name == "nt" else "Start Relay.sh"
    print(f"Management app: {codex_home / launcher}")
    if desktop_source.is_dir():
        desktop_app = desktop_target / "Contents" / "MacOS" / "Relay" if sys.platform == "darwin" else desktop_target / (
            "Relay.exe" if os.name == "nt" else "Relay"
        )
        print(f"Desktop app: {desktop_app}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex-home", type=Path, default=Path.home() / ".codex")
    parser.add_argument("--configure-codex", action="store_true", help="Merge the mixed provider into config.toml with a backup")
    arguments = parser.parse_args()
    install(arguments.codex_home.expanduser().resolve(), arguments.configure_codex)


if __name__ == "__main__":
    main()
