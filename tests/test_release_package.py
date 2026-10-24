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
            self.assertFalse(any("auth.json" in name or "router.log" in name for name in names))

    def test_unix_archive_marks_launchers_executable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self._fixture(Path(directory))
            archive = package_release.package(root, "linux", "9.9.9", Path(directory) / "release")
            with tarfile.open(archive) as bundle:
                member = bundle.getmember("relay-9.9.9-linux/Start Relay.sh")
                self.assertEqual(member.mode & 0o777, 0o755)


if __name__ == "__main__":
    unittest.main()
