# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

import sys

ROOT = Path(SPECPATH).resolve().parent
ICON = ROOT / "desktop" / ("relay.ico" if sys.platform == "win32" else "relay.png")

datas = [
    (str(ROOT / "app" / "dist"), "app/dist"),
    (str(ROOT / "catalog"), "catalog"),
    (str(ROOT / "VERSION"), "VERSION"),
]
for source in sorted((ROOT / "router").glob("*.py")):
    datas.append((str(source), "router"))

hiddenimports = [
    "manager",
    "router",
    "settings",
    "credentials",
    "anthropic_adapter",
    "anthropic_oauth",
    "codex_config",
    "error_explainer",
    "local_adapter",
    "namespace_tools",
    "provider_catalog",
    "subscription_usage",
    "usage_store",
    "version",
    "relay_startup",
]

a = Analysis(
    [str(ROOT / "desktop" / "relay_desktop.py")],
    pathex=[str(ROOT / "router"), str(ROOT / "desktop")],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Relay",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=str(ICON) if ICON.is_file() else None,
)
collection = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Relay",
)
if sys.platform == "darwin":
    app = BUNDLE(
        collection,
        name="Relay.app",
        icon=str(ICON) if ICON.is_file() else None,
        bundle_identifier="com.relay.codex-router",
    )
