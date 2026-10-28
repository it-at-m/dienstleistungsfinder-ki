"""Publish component images and bundle them into one project-level GitHub Release."""

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COMPONENTS = ("core", "indexer")
VERSION_PATTERN = r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"


class ReleaseError(Exception):
    """A release cannot proceed."""


def command(executable: str, *args: str) -> str:
    try:
        result = subprocess.run([executable, *args], cwd=ROOT, capture_output=True, text=True, check=False)
    except FileNotFoundError as error:
        raise ReleaseError(f"Required executable {executable!r} was not found on PATH. Install it and reopen your terminal.") from error
    if result.returncode:
        raise ReleaseError(f"{executable} {' '.join(args)} failed:\n{result.stderr.strip()}")
    return result.stdout.strip()


def git(*args: str) -> str:
    return command("git", *args)


def github_api(method: str, path: str, payload: dict | None = None, *, raw: bytes | None = None, allow_missing: bool = False) -> dict:
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        raise ReleaseError("The project release workflow must provide GitHub Actions' automatic GITHUB_TOKEN.")
    url = path if path.startswith("https://uploads.github.com/") else f"https://api.github.com/{path}"
    data = raw if raw is not None else json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "Dienstleistungsfinder-KI-release-script",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            body = response.read()
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as error:
        if allow_missing and error.code == 404:
            return {}
        try:
            message = json.loads(error.read()).get("message", error.reason)
        except (ValueError, AttributeError) as _error:
            message = error.reason
        raise ReleaseError(f"GitHub API returned HTTP {error.code}: {message}") from error
    except urllib.error.URLError as error:
        raise ReleaseError(f"Could not reach the GitHub API: {error.reason}") from error


def github_repo(remote: str) -> str:
    def parse(url: str) -> str:
        match = re.fullmatch(
            r"(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/)([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.git)?/?", url
        )
        if not match:
            raise ReleaseError("Bundled releases require a github.com remote using an HTTPS or SSH URL.")
        return match[1]

    repository = parse(git("remote", "get-url", remote))
    push_urls = git("remote", "get-url", "--push", "--all", remote).splitlines()
    if len(push_urls) != 1 or parse(push_urls[0]) != repository:
        raise ReleaseError("The remote must fetch and push to the same GitHub repository.")
    return repository


def choose(prompt: str, options: tuple[str, ...]) -> str:
    print(f"\n{prompt}")
    for number, option in enumerate(options, start=1):
        print(f"  {number}. {option}")
    while True:
        answer = input("Choose a number or name: ").strip().lower()
        if answer in options:
            return answer
        if answer.isascii() and answer.isdigit() and 1 <= int(answer) <= len(options):
            return options[int(answer) - 1]
        print("Please choose one of the listed options.")


def next_version(component: str, tags: set[str], bump: str) -> tuple[str, str]:
    prefix = f"{component}-v" if component else "v"
    pattern = re.compile(rf"{prefix}{VERSION_PATTERN}")
    versions = [tuple(map(int, match.groups())) for tag in tags if (match := pattern.fullmatch(tag))]
    current = max(versions, default=(0, 0, 0))
    major, minor, patch = current
    if bump == "major":
        following = (major + 1, 0, 0)
    elif bump == "minor":
        following = (major, minor + 1, 0)
    else:
        following = (major, minor, patch + 1)
    return ".".join(map(str, current)), ".".join(map(str, following))


def wait_for_images(repository: str, bundle: dict, timeout: int) -> dict[str, str]:
    deadline = time.monotonic() + timeout
    pending = dict(bundle["images"])
    build_urls = {}
    print("\nWaiting for successful image workflows (including reused images)...")
    while pending:
        for component, image in list(pending.items()):
            query = urllib.parse.urlencode({"branch": image["tag"], "head_sha": image["commit"], "event": "push", "per_page": 100})
            runs = github_api("GET", f"repos/{repository}/actions/workflows/release-{component}.yml/runs?{query}")["workflow_runs"]
            matches = [run for run in runs if run["head_branch"] == image["tag"] and run["head_sha"] == image["commit"]]
            if not matches:
                continue
            run = max(matches, key=lambda item: item["id"])
            if run["status"] != "completed":
                continue
            if run["conclusion"] != "success":
                raise ReleaseError(
                    f"{component} image build did not succeed: {run['html_url']}\nRerun the workflow, then resume this release."
                )
            build_urls[component] = run["html_url"]
            del pending[component]
            print(f"  {component} {image['version']}: build succeeded")
        if pending:
            if time.monotonic() >= deadline:
                raise ReleaseError(f"Timed out waiting for image workflows: {', '.join(pending)}.")
            time.sleep(min(10, max(0, deadline - time.monotonic())))
    return build_urls


def publish_bundle(repository: str, bundle: dict, timeout: int) -> None:
    tag = bundle["tag"]
    try:
        build_urls = wait_for_images(repository, bundle, timeout)
        notes = [
            f"## Dienstleistungsfinder KI {tag}",
            "",
            f"Release source commit on `main`: `{bundle['commit']}`.",
            "",
            "| Component | Container image | Build |",
            "| --- | --- | --- |",
        ]
        for component, image in bundle["images"].items():
            reference = f"ghcr.io/it-at-m/dienstleistungsfinder-ki-{component}:{image['version']}"
            status = "New image" if image["rebuilt"] else "Reused image"
            notes.append(f"| {component} | `{reference}` | [{status}]({build_urls[component]}) |")
        notes.extend(["", "The attached `release.json` records the component versions and source commits for this bundle."])
        manifest = {**bundle, "build_urls": build_urls}
        release_path = f"repos/{repository}/releases"
        existing = github_api("GET", f"{release_path}/tags/{tag}", allow_missing=True)
        if existing and not existing["draft"]:
            print(f"\nProject release already published: {existing['html_url']}")
            return
        payload = {
            "tag_name": tag,
            "target_commitish": bundle["commit"],
            "name": f"Dienstleistungsfinder KI {tag}",
            "body": "\n".join(notes),
            "draft": True,
        }
        draft = existing or github_api("POST", release_path, payload)
        draft_path = f"{release_path}/{draft['id']}"
        if existing:
            github_api("PATCH", draft_path, payload)
            for asset in existing.get("assets", []):
                if asset["name"] == "release.json":
                    github_api("DELETE", f"{release_path}/assets/{asset['id']}")
        github_api(
            "POST",
            f"https://uploads.github.com/repos/{repository}/releases/{draft['id']}/assets?name=release.json",
            raw=(json.dumps(manifest, indent=2) + "\n").encode("utf-8"),
        )
        published = github_api("PATCH", draft_path, {"draft": False})
        print(f"\nProject release published: {published['html_url']}")
    except (ReleaseError, OSError) as error:
        print(f"\nProject tag retained: {tag}. The component tags do not need another version increment.", file=sys.stderr)
        print(f"Rerun the Release project workflow for {tag} in https://github.com/{repository}/actions", file=sys.stderr)
        raise ReleaseError(str(error)) from error


def load_bundle(tag: str) -> dict:
    if not re.fullmatch(rf"v{VERSION_PATTERN}", tag):
        raise ReleaseError("The project tag must be a stable tag such as v1.0.0.")
    ref = f"refs/tags/{tag}"
    try:
        annotation = git("cat-file", "tag", ref).split("\n\n", 1)[1].splitlines()[0]
        bundle = json.loads(annotation)
        if bundle["schema_version"] != 1 or bundle["tag"] != tag or set(bundle["images"]) != set(COMPONENTS):
            raise ValueError("Invalid bundle metadata")
        if git("rev-parse", f"{ref}^{{}}") != bundle["commit"]:
            raise ValueError("Bundle source does not match the project tag")
        for component, image in bundle["images"].items():
            if not re.fullmatch(VERSION_PATTERN, image["version"]) or image["tag"] != f"{component}-v{image['version']}":
                raise ValueError("Invalid component version")
            if not re.fullmatch(r"[0-9a-f]{40}", image["commit"]) or not isinstance(image["rebuilt"], bool):
                raise ValueError("Invalid component metadata")
            if image["rebuilt"] and image["commit"] != bundle["commit"]:
                raise ValueError("Rebuilt images must use the project source commit")
    except (KeyError, ValueError, IndexError, TypeError) as error:
        raise ReleaseError(f"Tag {tag} does not contain valid bundle metadata from this script.") from error
    return bundle


def publish_tag(repository: str, tag: str, timeout: int) -> None:
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise ReleaseError("Project publication runs automatically in GitHub Actions. Run this script without --publish-tag locally.")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ReleaseError("A valid GitHub repository is required for workflow publication.")
    bundle = load_bundle(tag)
    git("merge-base", "--is-ancestor", bundle["commit"], "refs/remotes/origin/main")
    publish_bundle(repository, bundle, timeout)


def release(remote: str, dry_run: bool) -> None:
    # Resolve only configured remotes, so arguments cannot be interpreted as Git options.
    if remote not in git("remote").splitlines():
        raise ReleaseError(f"Remote {remote!r} is not configured.")
    repository = github_repo(remote)
    print(f"Reading release tags and main from {remote}...")
    refs = dict((ref, sha) for sha, ref in (line.split() for line in git("ls-remote", "--heads", "--tags", remote).splitlines()))
    commit = refs.get("refs/heads/main")
    if not commit:
        raise ReleaseError(f"Remote {remote!r} does not have a main branch.")
    remote_tags = {ref.removeprefix("refs/tags/") for ref in refs if ref.startswith("refs/tags/") and not ref.endswith("^{}")}
    local_tags = set(git("tag", "--list").splitlines())

    selection = choose("Which images should be released?", ("both", "core", "indexer"))
    bump = choose("Which increment for the project release and selected images?", ("patch", "minor", "major"))
    components = COMPONENTS if selection == "both" else (selection,)
    project_current, project_version = next_version("", remote_tags, bump)
    project_tag = f"v{project_version}"
    tags = []
    bundle = {"schema_version": 1, "tag": project_tag, "commit": commit, "remote": remote, "images": {}}
    print(f"\nRelease commit: {commit}\nRemote: {remote}")
    print(f"Project release: {project_current} -> {project_version} ({project_tag})")
    for component in COMPONENTS:
        current, following = next_version(component, remote_tags, bump)
        rebuilt = component in components
        if not rebuilt:
            following = current
        tag = f"{component}-v{following}"
        if not rebuilt and tag not in remote_tags:
            raise ReleaseError(f"No stable {component} release exists to reuse. Select both images for the first bundle.")
        if rebuilt and (tag in local_tags or tag in remote_tags):
            raise ReleaseError(f"Tag {tag} already exists. Resolve the existing tag before trying again.")
        if rebuilt:
            tags.append(tag)
        source = commit if rebuilt else refs.get(f"refs/tags/{tag}^{{}}", refs[f"refs/tags/{tag}"])
        bundle["images"][component] = {"version": following, "tag": tag, "commit": source, "rebuilt": rebuilt}
        print(f"  {component}: {current} -> {following} ({tag}; {'build' if rebuilt else 'reuse'})")
        print(f"    ghcr.io/it-at-m/dienstleistungsfinder-ki-{component}:{following}")
    if project_tag in local_tags or project_tag in remote_tags:
        raise ReleaseError(
            f"Tag {project_tag} already exists. For an unfinished release, rerun its Release project workflow in GitHub Actions."
        )
    tags.append(project_tag)

    refspecs = [f"refs/tags/{tag}:refs/tags/{tag}" for tag in tags]
    push_args = ("-c", "push.followTags=false", "push", "--atomic", remote, *refspecs)
    if dry_run:
        print("\nDry run complete. No tags were created or pushed.")
        return
    if input("\nCreate and push these release tags? [y/N]: ").strip().lower() not in ("y", "yes"):
        print("Release cancelled. No tags were created or pushed.")
        return

    # Download main's commit without changing the checkout or including local changes.
    git("fetch", "--no-tags", remote, "refs/heads/main")
    if git("rev-parse", "FETCH_HEAD") != commit:
        raise ReleaseError("Remote main changed while preparing the release. Run the script again.")
    created = []
    try:
        for tag in tags:
            message = json.dumps(bundle, sort_keys=True) if tag == project_tag else f"Release {tag}"
            git("tag", "-a", tag, "-m", message, commit)
            created.append(tag)
        print(git(*push_args))
    except ReleaseError:
        if created:
            print(f"\nLocal tags retained: {', '.join(created)}", file=sys.stderr)
            print("Inspect the remote before retrying; a network failure can occur after a successful push.", file=sys.stderr)
            print(f"Retry push: git {' '.join(push_args)}", file=sys.stderr)
            print(f"Or remove the local tags: git tag -d {' '.join(created)}", file=sys.stderr)
        raise
    print("\nRelease tags pushed. GitHub Actions will build the selected images and publish one bundled project release:")
    print("  Release core image / Release indexer image / Release project")
    print(f"https://github.com/{repository}/actions")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--remote", default="origin", help="Configured Git remote to publish to (default: origin)")
    parser.add_argument("--dry-run", action="store_true", help="Read remote state and preview versions without creating or pushing tags")
    parser.add_argument("--publish-tag", metavar="TAG", help="Internal GitHub Actions mode: publish a pushed project tag")
    parser.add_argument("--repository", help="GitHub repository for workflow publication (owner/name)")
    parser.add_argument("--timeout", type=int, default=3600, help="Maximum seconds to wait for image workflows (default: 3600)")
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    if args.publish_tag and (not args.repository or args.dry_run):
        parser.error("--publish-tag requires --repository and cannot be combined with --dry-run")
    try:
        if args.publish_tag:
            publish_tag(args.repository, args.publish_tag, args.timeout)
        else:
            release(args.remote, args.dry_run)
    except (EOFError, KeyboardInterrupt) as _error:
        print("\nRelease interrupted.", file=sys.stderr)
        return 1
    except (ReleaseError, OSError) as error:
        print(f"Release failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
