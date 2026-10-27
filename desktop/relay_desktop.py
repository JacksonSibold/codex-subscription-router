"""Native Relay companion window with automatic local service startup."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import traceback
import urllib.error
import urllib.request

SOURCE_ROOT = Path(__file__).resolve().parent.parent
RESOURCE_ROOT = Path(getattr(sys, "_MEIPASS", SOURCE_ROOT))
FROZEN = bool(getattr(sys, "frozen", False))
CONTROL_PORT = int(os.environ.get("RELAY_DESKTOP_CONTROL_PORT") or 18768)


def _set_runtime_environment(dev: bool) -> dict[str, str]:
    root = SOURCE_ROOT if not FROZEN else RESOURCE_ROOT
    codex_home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
    if dev:
        data_dir = SOURCE_ROOT / ".dev-codex"
        if not (data_dir / "models_cache.json").is_file():
            data_dir.mkdir(parents=True, exist_ok=True)
            cache = SOURCE_ROOT / "app" / "dist"
            if cache.is_dir():
                (data_dir / "models_cache.json").write_text(
                    json.dumps({"models": [
                        {"slug": "gpt-6.1-sol", "display_name": "GPT-6.1 Sol", "shell_type": "unified_exec", "supported_in_api": True},
                        {"slug": "gpt-6-luna", "display_name": "GPT-6 Luna", "shell_type": "unified_exec", "supported_in_api": True},
                    ]}),
                    encoding="utf-8",
                )
        codex_home = data_dir
    else:
        data_dir = Path(os.environ.get("CODEX_ROUTER_DATA_DIR") or codex_home / "model-router")
    data_dir.mkdir(parents=True, exist_ok=True)
    static_dir = root / "app" / "dist"
    if dev:
        static_dir = SOURCE_ROOT / "app" / "dist"
    values = {
        "CODEX_HOME": str(codex_home),
        "CODEX_ROUTER_DATA_DIR": str(data_dir),
        "CODEX_ROUTER_SETTINGS": os.environ.get("CODEX_ROUTER_SETTINGS") or str(data_dir / "router-settings.json"),
        "CODEX_ROUTER_USAGE_DB": os.environ.get("CODEX_ROUTER_USAGE_DB") or str(data_dir / "router-usage.sqlite"),
        "CODEX_ROUTER_PROVIDER_CACHE": os.environ.get("CODEX_ROUTER_PROVIDER_CACHE") or str(data_dir / "provider-catalog-cache.json"),
        "CODEX_ROUTER_LOG": os.environ.get("CODEX_ROUTER_LOG") or str(data_dir / "router.log"),
        "CODEX_ROUTER_ORIGINS": os.environ.get("CODEX_ROUTER_ORIGINS") or str(data_dir / "reasoning-origins.json"),
        "CODEX_ROUTER_STATIC": os.environ.get("CODEX_ROUTER_STATIC") or str(static_dir),
        "CODEX_ROUTER_MANAGER_PORT": os.environ.get("CODEX_ROUTER_MANAGER_PORT") or ("18766" if dev else "18767"),
        "CODEX_ROUTER_PORT": os.environ.get("CODEX_ROUTER_PORT") or ("18769" if dev else "18765"),
    }
    if dev:
        values.update({
            "CODEX_ROUTER_DEV": "1",
            "CODEX_ROUTER_CREDENTIALS": str(data_dir / "credentials.json"),
            "OPENCODE_AUTH_PATH": str(data_dir / "opencode-auth.json"),
        })
    os.environ.update(values)
    return values


def _json_url(url: str, timeout: float = 2.0) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.load(response)


def _wait_json(url: str, timeout: float = 15.0) -> dict:
    deadline = time.time() + timeout
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            return _json_url(url, timeout=1.5)
        except (OSError, ValueError, urllib.error.URLError) as exc:
            last_error = exc
            time.sleep(0.25)
    raise RuntimeError(f"Relay service did not start at {url}: {last_error}")


def _service_thread(role: str) -> threading.Thread:
    error_path = Path(os.environ["CODEX_ROUTER_DATA_DIR"]) / "desktop-service-error.log"

    def service_log(message: str) -> None:
        try:
            error_path.parent.mkdir(parents=True, exist_ok=True)
            with error_path.open("a", encoding="utf-8") as handle:
                handle.write(f"{time.strftime('%H:%M:%S')} {role}: {message}\n")
        except OSError:
            pass

    service_log("thread setup started")
    root = SOURCE_ROOT if not FROZEN else RESOURCE_ROOT
    sys.path.insert(0, str(root / "router"))
    if role == "router":
        import router
        target = router.main
    else:
        import manager
        target = manager.main
    service_log("service target imported")

    def guarded():
        service_log("service target entered")
        try:
            target()
        except BaseException:
            service_log("service target crashed:\n" + traceback.format_exc())
        else:
            service_log("service target returned")

    thread = threading.Thread(target=guarded, name=f"relay-{role}", daemon=True)
    thread.start()
    return thread


def ensure_services() -> list[threading.Thread]:
    manager_port = int(os.environ["CODEX_ROUTER_MANAGER_PORT"])
    router_port = int(os.environ["CODEX_ROUTER_PORT"])
    owned: list[threading.Thread] = []
    try:
        _json_url(f"http://127.0.0.1:{router_port}/__router_health", timeout=1.0)
    except (OSError, ValueError, urllib.error.URLError):
        owned.append(_service_thread("router"))
        _wait_json(f"http://127.0.0.1:{router_port}/__router_health", timeout=15)
    try:
        manager = _json_url(f"http://127.0.0.1:{manager_port}/api/health", timeout=1.0)
        if not manager.get("ok"):
            raise RuntimeError("Manager health did not report ok")
    except (OSError, ValueError, urllib.error.URLError, RuntimeError):
        owned.append(_service_thread("manager"))
        _wait_json(f"http://127.0.0.1:{manager_port}/api/health", timeout=15)
    return owned


def codex_is_running() -> bool:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    try:
        if os.name == "nt":
            result = subprocess.run(
                ["tasklist.exe", "/FO", "CSV", "/NH", "/FI", "IMAGENAME eq Codex.exe"],
                capture_output=True, text=True, timeout=5, creationflags=flags,
            )
            return "codex.exe" in result.stdout.lower()
        result = subprocess.run(
            ["pgrep", "-ifl", "codex"], capture_output=True, text=True, timeout=5,
        )
        return bool(result.stdout.strip())
    except (OSError, subprocess.TimeoutExpired):
        return False


def _codex_window_rect() -> tuple[int, int, int, int] | None:
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        screen_width = user32.GetSystemMetrics(0)
        screen_height = user32.GetSystemMetrics(1)
        found: list[tuple[int, int, int, int]] = []

        def process_path(hwnd) -> str:
            process_id = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
            handle = kernel32.OpenProcess(0x1000, False, process_id.value)
            if not handle:
                return ""
            try:
                capacity = wintypes.DWORD(32768)
                buffer = ctypes.create_unicode_buffer(capacity.value)
                if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(capacity)):
                    return buffer.value
            finally:
                kernel32.CloseHandle(handle)
            return ""

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def visit(hwnd, _lparam):
            if not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                return True
            title = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, title, length + 1)
            executable = process_path(hwnd).replace("/", "\\").lower()
            is_codex = "codex.exe" in executable.rsplit("\\", 1)[-1] or "codex" in title.value.lower()
            if not is_codex:
                return True
            rect = wintypes.RECT()
            if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                width, height = rect.right - rect.left, rect.bottom - rect.top
                on_screen = (
                    width >= 400
                    and height >= 300
                    and rect.right > 0
                    and rect.bottom > 0
                    and rect.left < screen_width
                    and rect.top < screen_height
                )
                if on_screen:
                    found.append((rect.left, rect.top, rect.right, rect.bottom))
            return True

        user32.EnumWindows(visit, 0)
        return found[0] if found else None
    except Exception:
        return None


def window_geometry() -> dict[str, int]:
    """Place Relay beside Codex when possible, otherwise use a comfortable desktop size."""
    if os.name == "nt":
        try:
            import ctypes

            screen_w = ctypes.windll.user32.GetSystemMetrics(0)
            screen_h = ctypes.windll.user32.GetSystemMetrics(1)
        except Exception:
            screen_w, screen_h = 1920, 1080
        width = min(980, max(720, int(screen_w * 0.46)))
        height = min(900, max(640, screen_h - 100))
        codex = _codex_window_rect()
        if codex:
            left, top, right, bottom = codex
            if screen_w - right >= width:
                x = min(screen_w - width - 10, right + 12)
            elif left >= width:
                x = max(10, left - width - 12)
            else:
                x = max(10, (screen_w - width) // 2)
            y = max(20, min(top + 28, screen_h - height - 20))
            return {"width": width, "height": height, "x": x, "y": y}
        return {"width": width, "height": height, "x": max(10, screen_w - width - 28), "y": 48}
    return {"width": 1040, "height": 820}


class DesktopController:
    def __init__(self, watch_codex: bool, tray_enabled: bool):
        self.watch_codex = watch_codex
        self.tray_enabled = tray_enabled
        self.window = None
        self.codex_seen = False
        self.closed = False
        self.tray = None
        self._lock = threading.Lock()

    def show(self) -> None:
        if self.closed or self.window is None:
            return
        try:
            self.window.restore()
            self.window.show()
        except Exception:
            pass

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        if self.tray is not None:
            try:
                self.tray.stop()
            except Exception:
                pass
        if self.window is not None:
            try:
                self.window.destroy()
            except Exception:
                pass

    def watch(self) -> None:
        while not self.closed:
            running = codex_is_running()
            if running and not self.codex_seen:
                self.codex_seen = True
                self.show()
            elif not running and self.codex_seen:
                self.codex_seen = False
                if self.watch_codex:
                    try:
                        self.window.hide()
                    except Exception:
                        pass
            time.sleep(2)

    def start_tray(self) -> None:
        if not self.tray_enabled:
            return
        try:
            import pystray
            from PIL import Image, ImageDraw

            image = Image.new("RGBA", (64, 64), "#101b2c")
            draw = ImageDraw.Draw(image)
            draw.rounded_rectangle((8, 8, 56, 56), radius=14, fill="#6ba7f3")
            draw.rounded_rectangle((20, 16, 44, 22), radius=3, fill="#101b2c")
            draw.rounded_rectangle((20, 29, 44, 35), radius=3, fill="#101b2c")
            draw.rounded_rectangle((20, 42, 36, 48), radius=3, fill="#101b2c")
            menu = pystray.Menu(
                pystray.MenuItem("Show Relay", lambda *_args: self.show(), default=True),
                pystray.MenuItem("Quit Relay", lambda *_args: self.close()),
            )
            self.tray = pystray.Icon("Relay", image, "Relay for Codex", menu)
            self.tray.run_detached()
        except Exception:
            self.tray = None


def _start_control_server(controller: DesktopController) -> object | None:
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            if self.path == "/show":
                controller.show()
                payload = b'{"ok":true}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            else:
                self.send_response(404)
                self.end_headers()

    try:
        server = ThreadingHTTPServer(("127.0.0.1", CONTROL_PORT), Handler)
    except OSError:
        return None
    threading.Thread(target=server.serve_forever, name="relay-desktop-control", daemon=True).start()
    return server


def _show_existing_instance() -> bool:
    try:
        _json_url(f"http://127.0.0.1:{CONTROL_PORT}/show", timeout=1.5)
        return True
    except (OSError, ValueError, urllib.error.URLError):
        return False


def _ensure_first_run_startup() -> None:
    """Enable the requested launch-with-Codex behavior once for packaged installs."""
    if not FROZEN:
        return
    marker = Path(os.environ["CODEX_ROUTER_DATA_DIR"]) / ".desktop-startup-v1"
    if marker.is_file():
        return
    try:
        from relay_startup import install_startup

        install_startup(Path(sys.executable))
        marker.write_text("Relay starts hidden and opens when Codex is running.\n", encoding="utf-8")
    except Exception:
        # The desktop app remains fully usable even if the OS blocks autostart.
        pass


def run_window(controller: DesktopController) -> None:
    import webview

    controller.window = webview.create_window(
        "Relay for Codex",
        f"http://127.0.0.1:{os.environ['CODEX_ROUTER_MANAGER_PORT']}/?desktop=1#overview",
        hidden=controller.watch_codex,
        min_size=(720, 620),
        background_color="#0d1420",
        **window_geometry(),
    )
    if controller.watch_codex:
        def closing():
            try:
                controller.window.hide()
            except Exception:
                pass
            return False

        controller.window.events.closing += closing
    controller.tray_enabled = True
    if controller.watch_codex:
        threading.Thread(target=controller.watch, name="relay-codex-watch", daemon=True).start()
    elif codex_is_running():
        controller.codex_seen = True
    webview.start(
        lambda: controller.start_tray(),
        gui="edgechromium" if os.name == "nt" else None,
        debug=False,
    )
    controller.close()


def _child(argument: str) -> None:
    root = SOURCE_ROOT if not FROZEN else RESOURCE_ROOT
    sys.path.insert(0, str(root / "router"))
    if argument == "--manager-child":
        import manager

        manager.main()
    elif argument == "--router-child":
        import router

        router.main()
    else:
        raise SystemExit(f"Unknown child role: {argument}")


def server_smoke(dev: bool) -> int:
    _set_runtime_environment(dev)
    data_dir = Path(os.environ["CODEX_ROUTER_DATA_DIR"])
    os.environ["CODEX_ROUTER_DEV"] = "1"
    os.environ["CODEX_ROUTER_CREDENTIALS"] = str(data_dir / "credentials.json")
    os.environ["OPENCODE_AUTH_PATH"] = str(data_dir / "opencode-auth.json")
    os.environ.pop("RELAY_ANTHROPIC_OAUTH", None)
    try:
        owned = ensure_services()
    except Exception as exc:
        error_path = data_dir / "desktop-service-error.log"
        detail = error_path.read_text(encoding="utf-8", errors="replace") if error_path.is_file() else ""
        raise RuntimeError(f"Desktop services failed: {exc}\n{detail}") from exc
    manager_port = os.environ["CODEX_ROUTER_MANAGER_PORT"]
    try:
        state = _json_url(f"http://127.0.0.1:{manager_port}/api/state", timeout=20)
        print(json.dumps({
            "ok": True,
            "version": state.get("version"),
            "models": len(state.get("settings", {}).get("models", [])),
            "settings_location": state.get("settings_location"),
            "router_reachable": bool(state.get("router", {}).get("reachable")),
        }))
        return 0
    finally:
        for process in reversed(owned):
            try:
                process.terminate()
                process.wait(timeout=5)
            except Exception:
                pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dev", action="store_true", help="Use isolated repository development state")
    parser.add_argument("--startup", action="store_true", help="Start hidden, then appear when Codex starts")
    parser.add_argument("--watch-codex", action="store_true", help="Same as --startup")
    parser.add_argument("--install-startup", action="store_true")
    parser.add_argument("--uninstall-startup", action="store_true")
    parser.add_argument("--no-startup-registration", action="store_true")
    parser.add_argument("--server-smoke", action="store_true")
    parser.add_argument("--manager-child", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--router-child", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.manager_child or args.router_child:
        _child("--manager-child" if args.manager_child else "--router-child")
        return 0
    if args.dev or not FROZEN:
        args.dev = True
    _set_runtime_environment(args.dev)
    if args.install_startup or args.uninstall_startup:
        from relay_startup import install_startup, uninstall_startup

        try:
            if args.install_startup:
                paths = install_startup(
                    Path(sys.executable),
                    None if FROZEN else Path(__file__).resolve(),
                )
                print(json.dumps({"ok": True, "startup": [str(path) for path in paths]}))
            else:
                print(json.dumps({"ok": True, "removed": [str(path) for path in uninstall_startup()]}))
            return 0
        except Exception as exc:
            print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
            return 1
    if args.server_smoke:
        return server_smoke(args.dev)
    if not args.dev and not args.no_startup_registration:
        _ensure_first_run_startup()
    if _show_existing_instance():
        return 0
    owned: list[threading.Thread] = []
    try:
        owned = ensure_services()
    except Exception as exc:
        try:
            import webview
            webview.create_window(
                "Relay could not start",
                html=f"<body style='font-family:sans-serif;background:#0d1420;color:#e6eef8;padding:32px'><h2>Relay could not start</h2><p>{exc}</p></main>",
                width=620,
                height=320,
            )
            webview.start()
        except Exception:
            pass
        return 1
    watch = args.startup or args.watch_codex
    controller = DesktopController(watch_codex=watch, tray_enabled=True)
    server = _start_control_server(controller)
    try:
        run_window(controller)
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
