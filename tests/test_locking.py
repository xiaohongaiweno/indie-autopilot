"""Tests for the per-project lock (scripts/orchestrator.py).

Two `autopilot run` invocations on one project used to interleave and lose each
other's state writes. These tests cover the two properties that matter: other
processes are excluded, and nesting inside one process does not deadlock.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
for _p in (str(REPO_ROOT / "scripts"), str(REPO_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import orchestrator as orch  # noqa: E402
from state_machine import State  # noqa: E402


@pytest.fixture
def project(tmp_path):
    project_dir = tmp_path / "proj-lock"
    project_dir.mkdir()
    (project_dir / "state.json").write_text(
        json.dumps(
            {
                "project_id": "proj-lock",
                "name": "Lock",
                "stage": "discovered",
                "status": "active",
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T00:00:00Z",
                "approved_stages": [],
                "artifacts": {},
                "audit_log": [],
            }
        )
    )
    return project_dir


def test_lock_creates_a_lock_file(project):
    with orch.project_lock(project):
        assert (project / ".lock").is_file()
        assert f"pid={__import__('os').getpid()}" in (project / ".lock").read_text()


def test_lock_is_released_after_use(project):
    with orch.project_lock(project):
        pass
    # re-acquiring must work
    with orch.project_lock(project):
        pass


def test_nesting_in_one_process_does_not_deadlock(project):
    with orch.project_lock(project):
        with orch.project_lock(project):
            pass


def test_run_is_safe_inside_an_outer_lock(project):
    """The CLI locks too, so run() must not deadlock against its own caller."""
    config = orch.load_config()
    with orch.project_lock(project):
        result = orch.run(
            project, target=State.RESEARCHING, config=config, assume_yes=True
        )
    assert result.reached == "researching"


def test_lock_released_when_run_raises(project):
    config = orch.load_config()
    with pytest.raises(orch.PipelineError):
        orch.run(project, target=State.GROWING, config=config)  # no TTY at the gate
    # the lock must not be left held
    with orch.project_lock(project):
        pass


def test_another_process_is_excluded(project):
    """Start a real second process holding the lock, then try to take it."""
    holder = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import sys, time, pathlib\n"
            "sys.path.insert(0, %r)\n"
            "import orchestrator as o\n"
            "with o.project_lock(pathlib.Path(%r)):\n"
            "    print('HELD', flush=True)\n"
            "    time.sleep(10)\n" % (str(REPO_ROOT / "scripts"), str(project)),
        ],
        stdout=subprocess.PIPE,
        text=True,
        cwd=str(REPO_ROOT),
    )
    try:
        assert holder.stdout.readline().strip() == "HELD"
        with pytest.raises(orch.PipelineError, match="另一个 autopilot 进程"):
            with orch.project_lock(project):
                pass
    finally:
        holder.kill()
        holder.wait(5)


def test_another_process_cannot_run(project):
    holder = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import sys, time, pathlib\n"
            "sys.path.insert(0, %r)\n"
            "import orchestrator as o\n"
            "with o.project_lock(pathlib.Path(%r)):\n"
            "    print('HELD', flush=True)\n"
            "    time.sleep(10)\n" % (str(REPO_ROOT / "scripts"), str(project)),
        ],
        stdout=subprocess.PIPE,
        text=True,
        cwd=str(REPO_ROOT),
    )
    try:
        assert holder.stdout.readline().strip() == "HELD"
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys, pathlib\n"
                "sys.path.insert(0, %r)\n"
                "import orchestrator as o\n"
                "try:\n"
                "    o.run(pathlib.Path(%r), target=o.sm.State.RESEARCHING, assume_yes=True)\n"
                "    print('ACQUIRED')\n"
                "except o.PipelineError as e:\n"
                "    print('BLOCKED')\n" % (str(REPO_ROOT / "scripts"), str(project)),
            ],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        assert "BLOCKED" in result.stdout
        # and nothing was written
        state = json.loads((project / "state.json").read_text())
        assert state["stage"] == "discovered"
    finally:
        holder.kill()
        holder.wait(5)


def test_lock_released_by_the_kernel_when_the_holder_dies(project):
    """A crashed run must not leave a permanent lock."""
    holder = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import sys, time, pathlib\n"
            "sys.path.insert(0, %r)\n"
            "import orchestrator as o\n"
            "with o.project_lock(pathlib.Path(%r)):\n"
            "    print('HELD', flush=True)\n"
            "    time.sleep(30)\n" % (str(REPO_ROOT / "scripts"), str(project)),
        ],
        stdout=subprocess.PIPE,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert holder.stdout.readline().strip() == "HELD"
    with pytest.raises(orch.PipelineError):
        with orch.project_lock(project):
            pass

    holder.kill()
    holder.wait(5)
    time.sleep(0.2)
    with orch.project_lock(project):
        pass
