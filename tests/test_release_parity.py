"""Keep desktop installers on the same release and exercise Ubuntu upgrades."""
import json
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ReleaseParityTests(unittest.TestCase):
    def test_release_and_revision_match_both_platforms(self):
        package = json.loads((ROOT / "webtool/package.json").read_text())
        version = package["version"]
        sources = [
            "linux-launcher/bootstrap-linux.sh", "linux-launcher/mkva-webtool",
            "windows-launcher/bootstrap-wsl.sh", "windows-launcher/launcher/Program.cs",
        ]
        revisions = []
        for name in sources:
            text = (ROOT / name).read_text()
            self.assertIn("v" + version, text, name)
            revision = re.search(r'(?:RELEASE_REVISION.*:-|ReleaseRevision = ")([^"}]+)', text)
            self.assertIsNotNone(revision, name)
            revisions.append(revision.group(1))
        self.assertEqual(len(set(revisions)), 1)
        for name in ("nextflow.config", "windows-launcher/installer.iss", "linux-launcher/build-deb.sh"):
            self.assertIn(version, (ROOT / name).read_text(), name)

    def test_ubuntu_detects_old_release_old_revision_and_missing_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            data = base / "data"
            source = data / "source"
            for name in ("main.nf", "webtool/start-local.sh", "tools/nf-test", "tools/nf-test.version"):
                path = source / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
            (source / "webtool/dist").mkdir()
            for name in ("nextflow/bin/nextflow", "nextflow/bin/java", "mkva-webtool/bin/node", "mkva-webtool/bin/npm"):
                path = data / "envs" / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
            env = dict(os.environ, MKVA_APP_DATA_DIR=str(data), MKVA_STATE_DIR=str(base / "state"),
                       XDG_RUNTIME_DIR=str(base / "runtime"), MKVA_LAUNCHER_UPDATE_TEST="1",
                       MKVA_RELEASE_REF="vtest", MKVA_RELEASE_REVISION="current")
            marker = source / ".mkva-managed-install"
            def check(expected):
                result = subprocess.run(["bash", str(ROOT / "linux-launcher/mkva-webtool")],
                                        env=env, capture_output=True, text=True, check=True)
                self.assertIn("MKVA_NEEDS_SETUP=" + expected, result.stdout)
            check("true")
            marker.write_text("release=vold\nrevision=current\n")
            check("true")
            marker.write_text("release=vtest\nrevision=old\n")
            check("true")
            marker.write_text("release=vtest\nrevision=current\n")
            check("false")
            (source / "tools/nf-test").unlink()
            check("true")


if __name__ == "__main__":
    unittest.main()
