from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop"))
sys.path.insert(0, str(ROOT / "router"))
import relay_desktop
import relay_startup


class DesktopTests(unittest.TestCase):
    def test_dev_runtime_is_completely_isolated_from_live_codex_state(self):
        keys = (
            "CODEX_HOME", "CODEX_ROUTER_DATA_DIR", "CODEX_ROUTER_SETTINGS",
            "CODEX_ROUTER_MANAGER_PORT", "CODEX_ROUTER_PORT", "CODEX_ROUTER_DEV",
            "CODEX_ROUTER_CREDENTIALS",
        )
        with patch.dict(os.environ, {}, clear=False):
            for key in keys:
                os.environ.pop(key, None)
            values = relay_desktop._set_runtime_environment(dev=True)
        self.assertEqual(Path(values["CODEX_HOME"]), ROOT / ".dev-codex")
        self.assertTrue(values["CODEX_ROUTER_SETTINGS"].startswith(str(ROOT / ".dev-codex")))
        self.assertEqual(values["CODEX_ROUTER_DEV"], "1")
        self.assertEqual(values["CODEX_ROUTER_MANAGER_PORT"], "18766")
        self.assertEqual(values["CODEX_ROUTER_PORT"], "18769")

    def test_codex_process_detection_is_case_insensitive_on_windows(self):
        completed = subprocess.CompletedProcess([], 0, stdout='"Codex.exe","1234","Console","1","10 K"\n')
        with patch.object(relay_desktop.os, "name", "nt"), \
             patch.object(relay_desktop.subprocess, "run", return_value=completed) as run:
            self.assertTrue(relay_desktop.codex_is_running())
        self.assertIn("Codex.exe", " ".join(run.call_args.args[0]))

    def test_service_start_attaches_when_both_services_are_healthy(self):
        with patch.dict(os.environ, {"CODEX_ROUTER_MANAGER_PORT": "19001", "CODEX_ROUTER_PORT": "19002"}), \
             patch.object(relay_desktop, "_json_url", side_effect=[
                 {"relay_version": "1.1.0"}, {"ok": True},
             ]), patch.object(relay_desktop, "_launch_child") as launch:
            owned = relay_desktop.ensure_services()
        self.assertEqual(owned, [])
        launch.assert_not_called()

    def test_window_geometry_stays_on_the_visible_screen(self):
        with patch.object(relay_desktop, "_codex_window_rect", return_value=None):
            geometry = relay_desktop.window_geometry()
        self.assertGreaterEqual(geometry.get("x", 0), 0)
        self.assertGreaterEqual(geometry.get("y", 0), 0)
        self.assertGreaterEqual(geometry["width"], 720)
        self.assertGreaterEqual(geometry["height"], 620)

    def test_show_uses_restore_then_show(self):
        controller = relay_desktop.DesktopController(False, False)
        controller.window = Mock()
        controller.show()
        self.assertEqual(
            [call[0] for call in controller.window.mock_calls[:2]],
            ["restore", "show"],
        )

    def test_linux_startup_file_contains_hidden_codex_watcher(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(relay_startup.sys, "platform", "linux"), \
             patch.object(relay_startup, "_startup_paths", return_value=(
                 Path(directory) / "autostart" / "relay.desktop", None,
             )):
            paths = relay_startup.install_startup(Path("/opt/relay/Relay"))
            contents = paths[0].read_text(encoding="utf-8")
            removed = relay_startup.uninstall_startup()
        self.assertIn("--startup", contents)
        self.assertIn("Terminal=false", contents)
        self.assertEqual(removed, paths)


if __name__ == "__main__":
    unittest.main()
