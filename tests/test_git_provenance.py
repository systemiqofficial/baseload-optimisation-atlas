"""The commit BOA records is its own, never that of the repository it is started from (as under ``uvx``)."""

import importlib.metadata
import json
import subprocess
from pathlib import Path

import pytest

import boa
from boa.config import run_manifest
from boa.config.paths import PathConfig
from boa.model import frontier_cache
from boa.model.bisection import SearchParams

COMMIT = "0123456789abcdef0123456789abcdef01234567"


class _Distribution:
    """Stands in for the installed distribution; ``direct_url`` is the file's text, or None when absent."""

    def __init__(self, direct_url: str | None):
        self._direct_url = direct_url

    def read_text(self, filename: str) -> str | None:
        return self._direct_url if filename == "direct_url.json" else None


def _fake_direct_url(monkeypatch, direct_url: str | None) -> None:
    real = importlib.metadata.distribution

    def distribution(name):
        return _Distribution(direct_url) if name == "baseload-optimisation-atlas" else real(name)

    monkeypatch.setattr(importlib.metadata, "distribution", distribution)


@pytest.fixture
def other_repo(tmp_path, monkeypatch) -> str:
    """A different git repository with one commit, made the current directory. Returns its full commit."""
    repo = tmp_path / "other_repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=test",
            "-c",
            "user.email=test@example.com",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-q",
            "--no-verify",
            "--allow-empty",
            "-m",
            "other",
        ],
        check=True,
    )
    monkeypatch.chdir(repo)
    return subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()


def _recorded(tmp_path) -> tuple[str | None, str]:
    """The commit as the run manifest and the frontier-cache meta record it."""
    cfg = PathConfig.from_root(tmp_path / "boa_root", input_set="cds", cost_set="c1")
    manifest = run_manifest.record_invocation(cfg, "run", [])
    meta = frontier_cache.build_frontier_meta("EU", 1, 0.85, SearchParams(), 2019, 0.25, [])
    return manifest["invocations"][-1]["git_sha"], meta["code_git_sha"]


def test_commit_read_from_direct_url_json(tmp_path, monkeypatch, other_repo):
    """Installed by ``uvx --from git+...@tag``, both records carry ``direct_url.json``'s commit."""
    direct_url = {"url": "https://github.com/example/boa", "vcs_info": {"vcs": "git", "commit_id": COMMIT}}
    _fake_direct_url(monkeypatch, json.dumps(direct_url))

    assert _recorded(tmp_path) == (COMMIT[:12], COMMIT[:12])


@pytest.mark.parametrize(
    "direct_url",
    [
        None,
        json.dumps({"url": "file:///src/boa", "dir_info": {"editable": True}}),
    ],
    ids=["no-direct-url", "editable"],
)
def test_commit_never_from_current_directory(tmp_path, monkeypatch, other_repo, direct_url):
    """Without a VCS entry in ``direct_url.json``, git runs in BOA's own folder, which may not be a checkout."""
    _fake_direct_url(monkeypatch, direct_url)
    own = subprocess.run(
        ["git", "rev-parse", "--short=12", "HEAD"],
        cwd=Path(boa.__file__).parent,
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()

    recorded = _recorded(tmp_path)

    assert not any(sha and other_repo.startswith(sha) for sha in recorded)
    assert recorded == (own or None, own)
