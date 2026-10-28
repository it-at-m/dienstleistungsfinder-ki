"""Exercise releases against disposable local Git remotes, never GitHub."""

import contextlib
import io
import json
import os
import subprocess
import tempfile
import unittest
import urllib.error
import urllib.parse
from email.message import Message
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
        for tag in ("core-v1.2.9", "core-v1.2.10", "core-v9.0.0-rc.1", "indexer-v2.3.4", "legacy-v99.0.0", "v1.0.0"):
            self.command("tag", tag)
        self.command("push", "origin", "--tags")
        self.root_patch = patch.object(release, "ROOT", self.root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)
        self.repo_patch = patch.object(release, "github_repo", return_value="example/repository")
        self.repo_patch.start()
        self.addCleanup(self.repo_patch.stop)
        self.build_conclusion = "success"
        self.published = []
        self.drafts = {}
        self.assets = {}
        self.fail_upload = False
        self.api_patch = patch.object(release, "github_api", side_effect=self.fake_api)
        self.api_mock = self.api_patch.start()
        self.addCleanup(self.api_patch.stop)

    def fake_api(self, method, path, payload=None, *, raw=None, allow_missing=False):
        base = "repos/example/repository"
        if path == base:
            return {"full_name": "example/repository"}
        if "/actions/workflows/" in path:
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(path).query)
            tag, commit = query["branch"][0], query["head_sha"][0]
            return {
                "workflow_runs": [
                    {
                        "id": 123,
                        "head_branch": tag,
                        "head_sha": commit,
                        "status": "completed",
                        "conclusion": self.build_conclusion,
                        "html_url": f"https://github.com/example/repository/actions/runs/{tag}",
                    }
                ]
            }
        if method == "GET" and "/releases/tags/" in path:
            return next((draft for draft in self.drafts.values() if draft["tag_name"] == path.rsplit("/", 1)[1]), {})
        if method == "POST" and path == f"{base}/releases":
            assert payload is not None
            identifier = len(self.drafts) + 1
            draft = {**payload, "id": identifier, "html_url": f"https://github.com/example/repository/releases/tag/{payload['tag_name']}"}
            self.drafts[identifier] = draft
            return draft
        if path.startswith("https://uploads.github.com/"):
            if self.fail_upload:
                raise release.ReleaseError("Asset upload failed")
            identifier = int(urllib.parse.urlsplit(path).path.split("/")[-2])
            assert raw is not None
            self.assets[identifier] = json.loads(raw)
            return {"name": "release.json"}
        if method == "PATCH" and path.startswith(f"{base}/releases/"):
            assert payload is not None
            identifier = int(path.rsplit("/", 1)[1])
            draft = self.drafts[identifier]
            draft.update(payload)
            if not draft["draft"]:
                self.published.append((dict(draft), self.assets[identifier]))
            return draft
        raise AssertionError(f"Unexpected GitHub API request: {method} {path}")

    def command(self, *args):
        return subprocess.run(["git", *args], cwd=self.root, check=True, capture_output=True, text=True).stdout.strip()

    def remote_tags(self):
        return set(self.command("--git-dir", str(self.remote), "tag", "--list").splitlines())

    def invoke(self, answers, dry_run=False):
        output = io.StringIO()
        with patch("builtins.input", side_effect=answers), contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            release.release("origin", dry_run)
        return output.getvalue()

    def workflow_publish(self, tag):
        output = io.StringIO()
        with patch.dict(os.environ, {"GITHUB_ACTIONS": "true"}), contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            release.publish_tag("example/repository", tag, 60)
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
        self.assertIn("v1.0.1", self.remote_tags())
        self.api_mock.assert_not_called()
        self.assertEqual(self.published, [])
        publication_output = self.workflow_publish("v1.0.1")
        metadata, manifest = self.published[0]
        self.assertEqual(metadata["tag_name"], "v1.0.1")
        self.assertFalse(metadata["draft"])
        self.assertEqual(manifest["images"]["core"]["version"], "1.2.11")
        self.assertEqual(manifest["images"]["indexer"]["version"], "2.3.5")
        self.assertIn("Project release published", publication_output)

    def test_single_component_minor_and_major(self):
        self.invoke(["core", "minor", "y"])
        self.assertIn("core-v1.3.0", self.remote_tags())
        self.assertNotIn("indexer-v2.4.0", self.remote_tags())
        first_bundle = release.load_bundle("v1.1.0")
        self.assertEqual(first_bundle["tag"], "v1.1.0")
        self.assertEqual(first_bundle["images"]["indexer"]["version"], "2.3.4")
        self.assertFalse(first_bundle["images"]["indexer"]["rebuilt"])
        self.invoke(["indexer", "major", "y"])
        self.assertIn("indexer-v3.0.0", self.remote_tags())

    def test_dry_run_and_cancellation_do_not_create_tags(self):
        before = self.command("tag", "--list")
        remote_before = self.remote_tags()
        self.assertIn("Dry run complete", self.invoke(["1", "1"], dry_run=True))
        self.assertIn("Release cancelled", self.invoke(["both", "patch", ""]))
        self.assertEqual(before, self.command("tag", "--list"))
        self.assertEqual(remote_before, self.remote_tags())
        self.assertEqual(self.published, [])

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
        self.assertNotIn("v1.0.1", self.remote_tags())
        self.assertIn("core-v1.2.11", self.command("tag", "--list").splitlines())
        self.assertIn("Local tags retained", output.getvalue())
        self.assertIn("Retry push", output.getvalue())

    def test_failed_build_can_be_resumed_without_incrementing_versions(self):
        self.invoke(["both", "patch", "yes"])
        self.build_conclusion = "failure"
        with self.assertRaisesRegex(release.ReleaseError, "did not succeed"):
            self.workflow_publish("v1.0.1")
        self.assertEqual(self.published, [])
        tags_before = self.remote_tags()
        self.build_conclusion = "success"
        self.workflow_publish("v1.0.1")
        self.assertEqual(tags_before, self.remote_tags())
        self.assertEqual(self.published[0][1]["tag"], "v1.0.1")

    def test_single_component_requires_an_existing_other_component_release(self):
        self.command("--git-dir", str(self.remote), "tag", "-d", "indexer-v2.3.4")
        with self.assertRaisesRegex(release.ReleaseError, "No stable indexer release"):
            self.invoke(["core", "patch"])
        self.assertEqual(self.published, [])

    def test_failed_asset_upload_resumes_existing_draft(self):
        self.invoke(["both", "patch", "yes"])
        self.fail_upload = True
        with self.assertRaisesRegex(release.ReleaseError, "Asset upload failed"):
            self.workflow_publish("v1.0.1")
        self.assertEqual(self.published, [])
        self.assertTrue(self.drafts[1]["draft"])
        self.fail_upload = False
        self.workflow_publish("v1.0.1")
        self.assertEqual(len(self.drafts), 1)
        self.assertEqual(len(self.published), 1)


class WorkflowTests(unittest.TestCase):
    def test_wait_matches_tag_and_commit_and_waits_for_success(self):
        image = {"version": "1.0.1", "tag": "core-v1.0.1", "commit": "a" * 40, "rebuilt": True}
        wrong = {"id": 999, "head_branch": "core-v1.0.0", "head_sha": "a" * 40, "status": "completed", "conclusion": "success"}
        success = {**wrong, "id": 123, "head_branch": image["tag"], "html_url": "https://example.invalid/run/123"}
        pending = {**success, "status": "in_progress", "conclusion": ""}
        with patch.object(
            release, "github_api", side_effect=[{"workflow_runs": [wrong]}, {"workflow_runs": [pending]}, {"workflow_runs": [success]}]
        ):
            with patch.object(release.time, "sleep"), contextlib.redirect_stdout(io.StringIO()):
                result = release.wait_for_images("example/repository", {"images": {"core": image}}, 60)
        self.assertEqual(result, {"core": success["html_url"]})

    def test_missing_workflow_times_out_without_creating_release(self):
        image = {"tag": "core-v1.0.1", "commit": "a" * 40}
        with (
            patch.object(release, "github_api", return_value={"workflow_runs": []}) as api,
            patch.object(release.time, "monotonic", side_effect=[0, 61]),
        ):
            with contextlib.redirect_stdout(io.StringIO()), self.assertRaisesRegex(release.ReleaseError, "Timed out"):
                release.wait_for_images("example/repository", {"images": {"core": image}}, 60)
        self.assertEqual(api.call_count, 1)


class VersionTests(unittest.TestCase):
    def test_first_release_uses_zero_baseline(self):
        self.assertEqual(release.next_version("core", {"core-v1.0.0-rc.1"}, "patch"), ("0.0.0", "0.0.1"))


class CommandTests(unittest.TestCase):
    def test_missing_git_reports_the_executable(self):
        with patch.object(release.subprocess, "run", side_effect=FileNotFoundError()):
            with self.assertRaisesRegex(release.ReleaseError, "Required executable 'git'"):
                release.git("remote")


class ApiTests(unittest.TestCase):
    def test_workflow_token_is_used_in_request_headers(self):
        with patch.dict(os.environ, {"GITHUB_TOKEN": "example-test-token"}):
            with patch.object(release.urllib.request, "urlopen") as opener:
                opener.return_value.__enter__.return_value.read.return_value = b'{"full_name": "example/repository"}'
                result = release.github_api("GET", "repos/example/repository")
            self.assertEqual(result["full_name"], "example/repository")
            request = opener.call_args[0][0]
            self.assertEqual(request.get_header("Authorization"), "Bearer example-test-token")
            self.assertEqual(opener.call_args.kwargs["timeout"], 60)

    def test_publication_requires_github_actions_instead_of_prompting_locally(self):
        with patch.dict(os.environ, {"GITHUB_ACTIONS": "false"}):
            with self.assertRaisesRegex(release.ReleaseError, "publication runs automatically in GitHub Actions"):
                release.publish_tag("example/repository", "v1.0.1", 60)

    def test_authentication_error_is_clear_and_does_not_expose_token(self):
        error = urllib.error.HTTPError(
            "https://api.github.com/repos/example/repository", 401, "Unauthorized", Message(), io.BytesIO(b'{"message":"Bad credentials"}')
        )
        with (
            patch.dict(os.environ, {"GITHUB_TOKEN": "example-test-token"}),
            patch.object(release.urllib.request, "urlopen", side_effect=error),
        ):
            with self.assertRaisesRegex(release.ReleaseError, "HTTP 401: Bad credentials") as caught:
                release.github_api("GET", "repos/example/repository")
        self.assertNotIn("example-test-token", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
