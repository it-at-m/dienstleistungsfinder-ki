"""Interactively publish component release tags using the existing image workflows."""

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class ReleaseError(Exception):
    """A release cannot proceed."""


def git(*args: str) -> str:
    result = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=False)
    if result.returncode:
        raise ReleaseError(f"git {' '.join(args)} failed:\n{result.stderr.strip()}")
    return result.stdout.strip()


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
    pattern = re.compile(rf"{component}-v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")
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


def release(remote: str, dry_run: bool) -> None:
    # Resolve only configured remotes, so arguments cannot be interpreted as Git options.
    if remote not in git("remote").splitlines():
        raise ReleaseError(f"Remote {remote!r} is not configured.")
    print(f"Reading release tags and main from {remote}...")
    refs = dict((ref, sha) for sha, ref in (line.split() for line in git("ls-remote", "--heads", "--tags", remote).splitlines()))
    commit = refs.get("refs/heads/main")
    if not commit:
        raise ReleaseError(f"Remote {remote!r} does not have a main branch.")
    remote_tags = {ref.removeprefix("refs/tags/") for ref in refs if ref.startswith("refs/tags/") and not ref.endswith("^{}")}
    local_tags = set(git("tag", "--list").splitlines())

    selection = choose("Which images should be released?", ("both", "core", "indexer"))
    bump = choose("Which version increment?", ("patch", "minor", "major"))
    components = ("core", "indexer") if selection == "both" else (selection,)
    tags = []
    print(f"\nRelease commit: {commit}\nRemote: {remote}")
    for component in components:
        current, following = next_version(component, remote_tags, bump)
        tag = f"{component}-v{following}"
        if tag in local_tags or tag in remote_tags:
            raise ReleaseError(f"Tag {tag} already exists. Resolve the existing tag before trying again.")
        tags.append(tag)
        print(f"  {component}: {current} -> {following} ({tag})")
        print(f"    ghcr.io/it-at-m/dienstleistungsfinder-ki-{component}:{following}")

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
            git("tag", "-a", tag, "-m", f"Release {tag}", commit)
            created.append(tag)
        print(git(*push_args))
    except ReleaseError:
        if created:
            print(f"\nLocal tags retained: {', '.join(created)}", file=sys.stderr)
            print("Inspect the remote before retrying; a network failure can occur after a successful push.", file=sys.stderr)
            print(f"Retry push: git {' '.join(push_args)}", file=sys.stderr)
            print(f"Or remove the local tags: git tag -d {' '.join(created)}", file=sys.stderr)
        raise
    print("\nRelease tags pushed. Follow the image builds in GitHub Actions:")
    print("https://github.com/it-at-m/Dienstleistungsfinder-KI/actions")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--remote", default="origin", help="Configured Git remote to publish to (default: origin)")
    parser.add_argument("--dry-run", action="store_true", help="Read remote state and preview versions without creating or pushing tags")
    args = parser.parse_args()
    try:
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
