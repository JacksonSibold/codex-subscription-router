from __future__ import annotations

from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import package_release
import verify_release


class ReleasePackageTests(unittest.TestCase):
    def _fixture(self, directory: Path) -> Path:
        root = directory / "source"
        (root / "app" / "dist").mkdir(parents=True)
        (root / "app" / "dist" / "index.html").write_text("<html>Relay</html>", encoding="utf-8")
        (root / "router").mkdir()
        (root / "router" / "router.py").write_text("print('router')\n", encoding="utf-8")
        (root / "catalog").mkdir()
        (root / "catalog" / "models.json").write_text("{}\n", encoding="utf-8")
        (root / "scripts").mkdir()
        (root / "scripts" / "install.py").write_text("print('install')\n", encoding="utf-8")
        (root / "examples").mkdir()
        (root / "examples" / "config.toml").write_text("model = \"example\"\n", encoding="utf-8")
        for name in ("README.md", "CHANGELOG.md", *package_release.LAUNCHERS):
            (root / name).write_text(f"{name}\n", encoding="utf-8")
        (root / "VERSION").write_text("9.9.9\n", encoding="utf-8")
        return root

    def test_windows_archive_uses_allowlisted_contents(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self._fixture(Path(directory))
            archive = package_release.package(root, "windows", "9.9.9", Path(directory) / "release")
            with zipfile.ZipFile(archive) as bundle:
                names = set(bundle.namelist())
            prefix = "relay-9.9.9-windows/"
            self.assertIn(prefix + "app/dist/index.html", names)
            self.assertIn(prefix + "router/router.py", names)
            self.assertIn(prefix + "Start Relay.cmd", names)
            self.assertIn(prefix + "INSTALL.txt", names)
            self.assertIn(prefix + "VERSION", names)
            self.assertFalse(any("auth.json" in name or "router.log" in name for name in names))

    def test_unix_archives_mark_all_launchers_executable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self._fixture(Path(directory))
            for platform in ("linux", "macos"):
                archive = package_release.package(root, platform, "9.9.9", Path(directory) / "release")
                with tarfile.open(archive) as bundle:
                    for name in ("Start Relay.sh", "Start Router.sh", "Start Relay.command",
                                 "Start Router.command", "scripts/install.py"):
                        member = bundle.getmember(f"relay-9.9.9-{platform}/{name}")
                        self.assertEqual(member.mode & 0o777, 0o755)

    def test_version_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self._fixture(Path(directory))
            with self.assertRaisesRegex(ValueError, "does not match VERSION"):
                package_release.package(root, "windows", "1.2.3", Path(directory) / "release")

    def test_catalog_verification_requires_codex_instruction_metadata(self):
        valid = {"models": [{"slug": "relay-test", "base_instructions": "You are Codex."}]}
        verify_release._assert_catalog_ready(valid, "test catalog", expected_count=1)
        with self.assertRaisesRegex(RuntimeError, "missing Codex instruction metadata"):
            verify_release._assert_catalog_ready(
                {"models": [{"slug": "relay-test"}]}, "test catalog", expected_count=1
            )

    def test_release_verifier_uses_the_archive_package_folder(self):
        cases = {
            "relay-1.0.0-windows.zip": ("windows", "1.0.0", "relay-1.0.0-windows"),
            "relay-1.0.0-linux.tar.gz": ("linux", "1.0.0", "relay-1.0.0-linux"),
            "relay-1.0.0-macos.tar.gz": ("macos", "1.0.0", "relay-1.0.0-macos"),
        }
        for name, expected in cases.items():
            self.assertEqual(verify_release._archive_details(Path(name)), expected)


if __name__ == "__main__":
    unittest.main()
