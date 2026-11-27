"""Deliver a guarded NMS public snapshot through the existing Pages source branch."""

import hashlib
import os
import subprocess
import tempfile
import time
from urllib.error import URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import uuid4

from nms_publication import PublicationError
from nms_refresh_contract import instant


REMOTE = "https://github.com/codysilly/spatchin.git"
PUBLIC_URL = "https://www.spatchin.com/data/notams.json"
BRANCH = "refs/heads/main"
SNAPSHOT = "data/notams.json"
MAX_PUBLIC_BYTES = 50 * 1024 * 1024
REMOTE_NAME = "pages-source"


def sha256(body):
    return hashlib.sha256(body).hexdigest()


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


def pages_bytes():
    request = Request(
        f"{PUBLIC_URL}?verify={uuid4().hex}",
        headers={"Cache-Control": "no-cache", "Accept-Encoding": "identity"},
    )
    try:
        with build_opener(NoRedirect()).open(request, timeout=15) as response:
            if response.status == 200 and response.headers.get("Content-Encoding") in (
                None,
                "identity",
            ):
                return response.read(MAX_PUBLIC_BYTES + 1)
    except (OSError, URLError):
        pass
    raise PublicationError("PUBLIC_VERIFICATION_UNAVAILABLE")


def verify(body, manifest):
    if len(body) != manifest["bytes"] or sha256(body) != manifest["sha256"]:
        raise PublicationError("PUBLIC_DIGEST_MISMATCH")


class PagesDelivery:
    def __init__(self, scratch, *, remote=REMOTE, read_public=pages_bytes, wait=time.sleep):
        self.scratch = scratch
        self.remote = remote
        self.read_public = read_public
        self.wait = wait

    @staticmethod
    def _git(cwd, *args, body=None):
        env = {
            key: value
            for key, value in os.environ.items()
            if not key.upper().startswith(("GIT_", "FAA_"))
        }
        env.update(GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="Never")
        options = {"stdin": subprocess.DEVNULL} if body is None else {"input": body}
        try:
            return subprocess.run(
                [
                    "git",
                    "-c",
                    "user.name=Spatchin NOTAM Collector",
                    "-c",
                    "user.email=128643059+codysilly@users.noreply.github.com",
                    *args,
                ],
                cwd=cwd,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=120,
                check=True,
                **options,
            ).stdout
        except (OSError, subprocess.SubprocessError):
            raise PublicationError("GIT_DELIVERY_FAILED") from None

    def _fetch(self, directory):
        self._git(directory, "init", "--bare", "--quiet")
        self._git(directory, "remote", "add", REMOTE_NAME, self.remote)
        expected_url = os.fsencode(self.remote)
        for flags in (("--all",), ("--push", "--all")):
            configured = self._git(directory, "remote", "get-url", *flags, REMOTE_NAME)
            if configured.splitlines() != [expected_url]:
                raise PublicationError("GIT_DESTINATION_CHANGED")
        self._git(directory, "fetch", "--depth=1", "--no-tags", REMOTE_NAME, BRANCH)
        head = self._git(directory, "rev-parse", "FETCH_HEAD").strip().decode("ascii")
        spec = f"{head}:{SNAPSHOT}"
        if int(self._git(directory, "cat-file", "-s", spec)) > MAX_PUBLIC_BYTES:
            raise PublicationError("REPOSITORY_SNAPSHOT_TOO_LARGE")
        return head, self._git(directory, "cat-file", "blob", spec)

    def check_current(self, manifest, *, check_write=False):
        with tempfile.TemporaryDirectory(prefix="git-", dir=self.scratch) as directory:
            head, previous = self._fetch(directory)
            verify(previous, manifest)
            verify(self.read_public(), manifest)
            if check_write:
                self._git(directory, "push", "--dry-run", REMOTE_NAME, f"{head}:{BRANCH}")
        return head

    def publish(self, body, manifest, previous, *, progress, wait_checks=30):
        verify(body, manifest)
        if not 0 < len(body) <= MAX_PUBLIC_BYTES:
            raise PublicationError("PUBLIC_SNAPSHOT_SIZE_LIMIT")
        if instant(manifest["retrieved_utc"]) <= instant(previous["retrieved_utc"]):
            raise PublicationError("OLDER_OR_CONFLICTING_SNAPSHOT")
        with tempfile.TemporaryDirectory(prefix="git-", dir=self.scratch) as directory:
            head, current = self._fetch(directory)
            if current == body:
                progress("The exact candidate is already on the Pages source branch.")
            else:
                verify(current, previous)
                verify(self.read_public(), previous)
                self._git(directory, "read-tree", head)
                blob = (
                    self._git(directory, "hash-object", "-w", "--stdin", body=body).strip().decode()
                )
                self._git(
                    directory, "update-index", "--add", "--cacheinfo", f"100644,{blob},{SNAPSHOT}"
                )
                tree = self._git(directory, "write-tree").strip().decode()
                commit = (
                    self._git(
                        directory,
                        "commit-tree",
                        tree,
                        "-p",
                        head,
                        "-m",
                        "Update NMS-API NOTAM snapshot",
                    )
                    .strip()
                    .decode()
                )
                changed = self._git(
                    directory, "diff-tree", "--no-commit-id", "--name-only", "-r", head, commit
                )
                if changed.splitlines() != [SNAPSHOT.encode()]:
                    raise PublicationError("PUBLICATION_SCOPE_MISMATCH")
                # A normal fast-forward push fails if another writer advances
                # main. Recovery fetches again and preserves that writer's tree.
                self._git(directory, "push", REMOTE_NAME, f"{commit}:{BRANCH}")
                head = commit
                progress("Pages source updated. Waiting for public digest verification.")

        for attempt in range(wait_checks):
            try:
                verify(self.read_public(), manifest)
                return head
            except PublicationError:
                if attempt + 1 < wait_checks:
                    self.wait(20)
        raise PublicationError("PUBLIC_DEPLOYMENT_UNVERIFIED")
