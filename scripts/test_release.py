"""Exercise releases against disposable local Git remotes, never GitHub."""

import contextlib
import io
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import release


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "checkout"
        self.remote = Path(self.temp.name) / "remote.git"
        self.root.mkdir()
        self.environment = patch.dict(
            os.environ,
            {
                "GIT_AUTHOR_NAME": "Release Test",
                "GIT_AUTHOR_EMAIL": "release-test@example.invalid",
                "GIT_COMMITTER_NAME": "Release Test",
                "GIT_COMMITTER_EMAIL": "release-test@example.invalid",
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_GLOBAL": os.devnull,
            },
        )
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.command("init", "--bare", str(self.remote))
        self.command("init", "-b", "main")
        self.command("-c", "commit.gpgSign=false", "commit", "--allow-empty", "-m", "Initial commit")
        self.command("remote", "add", "origin", str(self.remote))
        self.command("push", "origin", "main")
        for tag in ("core-v1.2.9", "core-v1.2.10", "core-v9.0.0-rc.1", "indexer-v2.3.4", "v99.0.0"):
            self.command("tag", tag)
            self.command("push", "origin", f"refs/tags/{tag}")
        self.root_patch = patch.object(release, "ROOT", self.root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)

    def command(self, *args):
        return subprocess.run(["git", *args], cwd=self.root, check=True, capture_output=True, text=True).stdout.strip()

    def remote_tags(self):
        return set(self.command("--git-dir", str(self.remote), "tag", "--list").splitlines())

    def invoke(self, answers, dry_run=False):
        output = io.StringIO()
        with patch("builtins.input", side_effect=answers), contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            release.release("origin", dry_run)
        return output.getvalue()

    def test_both_components_increment_independently_and_use_annotated_tags(self):
        self.command("tag", "-a", "unpublished-local-tag", "-m", "Unrelated tag")
        output = self.invoke(["both", "patch", "yes"])
        for tag in ("core-v1.2.11", "indexer-v2.3.5"):
            self.assertIn(tag, self.remote_tags())
            self.assertEqual(self.command("cat-file", "-t", f"refs/tags/{tag}"), "tag")
            self.assertEqual(self.command("rev-parse", f"{tag}^{{}}"), self.command("rev-parse", "HEAD"))
        self.assertNotIn("unpublished-local-tag", self.remote_tags())
        self.assertIn("Release tags pushed", output)

    def test_single_component_minor_and_major(self):
        self.invoke(["core", "minor", "y"])
        self.assertIn("core-v1.3.0", self.remote_tags())
        self.assertNotIn("indexer-v2.4.0", self.remote_tags())
        self.invoke(["indexer", "major", "y"])
        self.assertIn("indexer-v3.0.0", self.remote_tags())

    def test_dry_run_and_cancellation_do_not_create_tags(self):
        before = self.command("tag", "--list")
        remote_before = self.remote_tags()
        self.assertIn("Dry run complete", self.invoke(["1", "1"], dry_run=True))
        self.assertIn("Release cancelled", self.invoke(["both", "patch", ""]))
        self.assertEqual(before, self.command("tag", "--list"))
        self.assertEqual(remote_before, self.remote_tags())

    def test_local_collision_does_not_publish_any_tags(self):
        self.command("tag", "indexer-v2.3.5")
        before = self.remote_tags()
        with self.assertRaisesRegex(release.ReleaseError, "already exists"):
            self.invoke(["both", "patch"])
        self.assertEqual(before, self.remote_tags())
        self.assertNotIn("core-v1.2.11", self.command("tag", "--list").splitlines())

    def test_dirty_feature_branch_releases_only_remote_main(self):
        published_main = self.command("--git-dir", str(self.remote), "rev-parse", "main")
        self.command("switch", "-c", "feature/local-work")
        tracked = self.root / "tracked.txt"
        tracked.write_text("local feature", encoding="utf-8")
        self.command("add", "tracked.txt")
        self.command("-c", "commit.gpgSign=false", "commit", "-m", "Unpublished feature")
        tracked.write_text("local edits", encoding="utf-8")
        self.command("add", "tracked.txt")
        tracked.write_text("more local edits", encoding="utf-8")
        dirty = self.root / "untracked.txt"
        dirty.write_text("unreleased change", encoding="utf-8")
        status_before = self.command("status", "--porcelain")
        head_before = self.command("rev-parse", "HEAD")
        self.invoke(["both", "patch", "yes"])
        for tag in ("core-v1.2.11", "indexer-v2.3.5"):
            self.assertEqual(self.command("--git-dir", str(self.remote), "rev-parse", f"{tag}^{{}}"), published_main)
        self.assertEqual(self.command("status", "--porcelain"), status_before)
        self.assertEqual(self.command("rev-parse", "HEAD"), head_before)
        self.assertEqual(self.command("branch", "--show-current"), "feature/local-work")
        self.assertEqual(tracked.read_text(encoding="utf-8"), "more local edits")
        self.assertEqual(dirty.read_text(encoding="utf-8"), "unreleased change")

    def test_atomic_push_rejects_both_tags_when_one_remote_tag_changes(self):
        answers = iter(["both", "patch"])

        def respond(prompt):
            if prompt.startswith("\nCreate"):
                self.command("--git-dir", str(self.remote), "tag", "-a", "indexer-v2.3.5", "-m", "Concurrent release", "main")
                return "yes"
            return next(answers)

        output = io.StringIO()
        with patch("builtins.input", side_effect=respond), contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            with self.assertRaises(release.ReleaseError):
                release.release("origin", False)
        self.assertNotIn("core-v1.2.11", self.remote_tags())
        self.assertIn("core-v1.2.11", self.command("tag", "--list").splitlines())
        self.assertIn("Local tags retained", output.getvalue())
        self.assertIn("Retry push", output.getvalue())


class VersionTests(unittest.TestCase):
    def test_first_release_uses_zero_baseline(self):
        self.assertEqual(release.next_version("core", {"core-v1.0.0-rc.1"}, "patch"), ("0.0.0", "0.0.1"))


if __name__ == "__main__":
    unittest.main()
