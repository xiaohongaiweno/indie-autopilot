"""Tests for running a project's own tests (scripts/verify.py)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
for _p in (str(REPO_ROOT / "scripts"), str(REPO_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import verify  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def runner_returning(exit_code=0, output="ok"):
    """A fake command runner that records calls."""
    calls = []

    def run(argv, cwd, timeout):
        calls.append({"argv": argv, "cwd": Path(cwd), "timeout": timeout})
        return exit_code, output

    run.calls = calls
    return run


def runner_raising(exc):
    def run(argv, cwd, timeout):
        raise exc

    return run


def node_project(tmp_path, script="jest", lockfile=None, install_deps=False):
    app = tmp_path / "app"
    app.mkdir(parents=True)
    (app / "package.json").write_text(json.dumps({"name": "x", "scripts": {"test": script}}))
    if lockfile:
        (app / lockfile).write_text("")
    if not install_deps:
        (app / "node_modules").mkdir()
    return app


def python_project(tmp_path, body="def test_ok():\n    assert 1 == 1\n", failing=False):
    app = tmp_path / "app"
    (app / "tests").mkdir(parents=True)
    (app / "tests" / "test_x.py").write_text(
        "def test_bad():\n    assert 1 == 2\n" if failing else body
    )
    return app


# ---------------------------------------------------------------------------
# 1. Detection
# ---------------------------------------------------------------------------


def test_detects_npm_test(tmp_path):
    app = node_project(tmp_path)
    detected = verify.detect_command(app)
    assert detected.argv == ["npm", "test", "--silent"]
    assert "package.json" in detected.source


@pytest.mark.parametrize(
    "lockfile,runner",
    [
        ("pnpm-lock.yaml", "pnpm"),
        ("yarn.lock", "yarn"),
        ("bun.lockb", "bun"),
    ],
)
def test_lockfile_selects_the_runner(tmp_path, lockfile, runner):
    app = node_project(tmp_path, lockfile=lockfile)
    detected = verify.detect_command(app)
    assert detected.argv[0] == runner
    assert detected.install[0] == runner


def test_npm_placeholder_is_not_a_test_suite(tmp_path):
    """`npm init` writes a test script that always exits 1.

    Reading it as a failing suite would report a red build for a project that
    simply has no tests.
    """
    app = node_project(tmp_path, script='echo "Error: no test specified" && exit 1')
    assert verify.detect_command(app) is None


def test_detects_pytest_from_tests_dir(tmp_path):
    app = python_project(tmp_path)
    detected = verify.detect_command(app)
    assert detected.argv[1:] == ["-m", "pytest", "-q"]
    assert "Python" in detected.source


def test_detects_pytest_from_config_file(tmp_path):
    app = tmp_path / "app"
    app.mkdir()
    (app / "pytest.ini").write_text("[pytest]\n")
    assert verify.detect_command(app) is not None


def test_detects_makefile_test_target(tmp_path):
    app = tmp_path / "app"
    app.mkdir()
    (app / "Makefile").write_text("build:\n\techo hi\n\ntest:\n\techo testing\n")
    detected = verify.detect_command(app)
    assert detected.argv == ["make", "test"]
    assert "Makefile" in detected.source


def test_makefile_without_test_target_is_not_a_test_command(tmp_path):
    app = tmp_path / "app"
    app.mkdir()
    (app / "Makefile").write_text("build:\n\techo hi\n")
    assert verify.detect_command(app) is None


def test_nothing_declared_is_not_configured(tmp_path):
    app = tmp_path / "app"
    app.mkdir()
    (app / "README.md").write_text("hi")
    assert verify.detect_command(app) is None


def test_detect_missing_dir(tmp_path):
    assert verify.detect_command(tmp_path / "nope") is None


def test_corrupt_package_json_falls_through(tmp_path):
    app = tmp_path / "app"
    app.mkdir()
    (app / "package.json").write_text("{ not json")
    (app / "Makefile").write_text("test:\n\techo hi\n")
    detected = verify.detect_command(app)
    assert detected.argv == ["make", "test"]


# ---------------------------------------------------------------------------
# 2. Running
# ---------------------------------------------------------------------------


def test_no_code_skips_verification(tmp_path):
    result = verify.run_verification(tmp_path, code_dir=tmp_path / "app")
    assert result.status == "no_code"
    assert result.ok is True
    assert result.is_real_data is False


def test_not_configured_is_reported_not_passed(tmp_path):
    app = tmp_path / "app"
    app.mkdir()
    (app / "index.js").write_text("console.log(1)")

    result = verify.run_verification(tmp_path, code_dir=app)

    assert result.status == "not_configured"
    assert "不会凭空造测试" in result.notes
    # matters: an unverified project must not look like a verified one
    assert result.status != "passed"


def test_passing_suite(tmp_path):
    app = node_project(tmp_path)
    runner = runner_returning(0, "Tests: 3 passed")

    result = verify.run_verification(tmp_path, code_dir=app, runner=runner)

    assert result.status == "passed"
    assert result.exit_code == 0
    assert result.is_real_data is True
    assert "3 passed" in result.output_tail
    assert runner.calls[0]["cwd"] == app


def test_failing_suite(tmp_path):
    app = node_project(tmp_path)
    runner = runner_returning(1, "Tests: 1 failed")

    result = verify.run_verification(tmp_path, code_dir=app, runner=runner)

    assert result.status == "failed"
    assert result.exit_code == 1
    assert result.ok is False


def test_timeout_is_its_own_status(tmp_path):
    app = node_project(tmp_path)
    runner = runner_raising(subprocess.TimeoutExpired(cmd="npm", timeout=1))

    result = verify.run_verification(tmp_path, code_dir=app, runner=runner, timeout_seconds=1)

    assert result.status == "timeout"
    assert "超时" in result.notes
    assert result.ok is False


def test_missing_binary_is_reported(tmp_path):
    app = node_project(tmp_path)
    runner = runner_raising(FileNotFoundError("npm not found"))

    result = verify.run_verification(tmp_path, code_dir=app, runner=runner)

    assert result.status == "error"
    assert "npm" in result.notes


def test_installs_dependencies_when_missing(tmp_path):
    app = node_project(tmp_path, install_deps=False)
    (app / "node_modules").rmdir()
    calls = []

    def runner(argv, cwd, timeout):
        calls.append(argv)
        return (0, "installed") if argv[-1] == "install" else (0, "Tests: 2 passed")

    result = verify.run_verification(tmp_path, code_dir=app, runner=runner)

    assert result.status == "passed"
    assert calls[0] == ["npm", "install"]
    assert calls[1] == ["npm", "test", "--silent"]


def test_install_failure_is_its_own_status(tmp_path):
    app = node_project(tmp_path, install_deps=False)
    (app / "node_modules").rmdir()

    def runner(argv, cwd, timeout):
        return (1, "npm ERR! network") if argv[-1] == "install" else (0, "should not run")

    result = verify.run_verification(tmp_path, code_dir=app, runner=runner)

    assert result.status == "dependencies_missing"
    assert "依赖安装失败" in result.notes
    assert result.ok is False


def test_install_can_be_disabled(tmp_path):
    app = node_project(tmp_path, install_deps=False)
    (app / "node_modules").rmdir()
    calls = []

    def runner(argv, cwd, timeout):
        calls.append(argv)
        return 1, "Cannot find module"

    result = verify.run_verification(
        tmp_path,
        code_dir=app,
        runner=runner,
        config={"verify": {"install_dependencies": False}},
    )

    # the test command ran and failed, rather than an install being attempted
    assert result.status == "failed"
    assert calls == [["npm", "test", "--silent"]]


def test_output_is_tailed_not_truncated_from_the_front(tmp_path):
    app = node_project(tmp_path)
    runner = runner_returning(1, "x" * 20000 + "\nFINAL FAILURE")
    result = verify.run_verification(tmp_path, code_dir=app, runner=runner)
    assert "FINAL FAILURE" in result.output_tail
    assert len(result.output_tail) <= verify.OUTPUT_TAIL_CHARS + 20


# ---------------------------------------------------------------------------
# 3. Config
# ---------------------------------------------------------------------------


def test_verify_config_defaults():
    cfg = verify.load_verify_config({})
    assert cfg["timeout_seconds"] == verify.DEFAULT_TIMEOUT_SECONDS
    assert cfg["install_dependencies"] is True
    assert cfg["require_tests"] is False


def test_verify_config_from_pipeline_yaml():
    """The shipped config must parse and be sane."""
    cfg = verify.load_verify_config()
    assert isinstance(cfg["timeout_seconds"], int)
    assert cfg["timeout_seconds"] > 0


def test_verify_config_overrides():
    cfg = verify.load_verify_config(
        {"verify": {"timeout_seconds": 5, "require_tests": True}}
    )
    assert cfg["timeout_seconds"] == 5
    assert cfg["require_tests"] is True


# ---------------------------------------------------------------------------
# 4. Recording
# ---------------------------------------------------------------------------


def test_to_artifact_shape():
    result = verify.VerifyResult(
        status="passed",
        code_dir="/tmp/app",
        command=["npm", "test"],
        source="package.json",
        exit_code=0,
        output_tail="ok",
        is_real_data=True,
    )
    artifact = verify.to_artifact(result)
    assert artifact["status"] == "passed"
    assert artifact["command"] == ["npm", "test"]
    assert artifact["detected_from"] == "package.json"
    assert artifact["verified_at"]
    assert artifact["is_real_data"] is True


def test_describe_covers_every_status():
    for status in (
        "passed",
        "failed",
        "timeout",
        "not_configured",
        "no_code",
        "dependencies_missing",
        "error",
    ):
        text = verify.describe(verify.VerifyResult(status=status, code_dir="/tmp"))
        assert status in text


# ---------------------------------------------------------------------------
# 5. Real execution (no fakes) -- pytest is available, so this is genuinely run
# ---------------------------------------------------------------------------


def test_really_runs_a_passing_pytest_suite(tmp_path):
    app = python_project(tmp_path)
    result = verify.run_verification(tmp_path, code_dir=app)

    assert result.status == "passed", result.output_tail
    assert result.exit_code == 0
    assert result.is_real_data is True


def test_really_runs_a_failing_pytest_suite(tmp_path):
    app = python_project(tmp_path, failing=True)
    result = verify.run_verification(tmp_path, code_dir=app)

    assert result.status == "failed"
    assert result.exit_code != 0
    assert "test_bad" in result.output_tail


# ---------------------------------------------------------------------------
# 6. Release readiness
# ---------------------------------------------------------------------------


def release_project(tmp_path, *, code=True, deployable=True, test=None, name="rel"):
    project = tmp_path / name
    (project / "app").mkdir(parents=True)
    if code:
        (project / "app" / "index.js").write_text("console.log(1)")
    if deployable:
        (project / "app" / "wrangler.toml").write_text('name = "x"\n')
    state = {"artifacts": {}}
    if test is not None:
        (project / "testing").mkdir(parents=True)
        (project / "testing" / "test-run.json").write_text(json.dumps(test))
        state["artifacts"]["test_run"] = {"path": "testing/test-run.json"}
    return project, state


def check_release(project, state, **config):
    return verify.check_release_readiness(
        project,
        state=state,
        code_dir=project / "app",
        config={"verify": config} if config else None,
    )


def test_release_without_code_is_not_a_failure(tmp_path):
    """A mock build has no product; deploy will refuse it later anyway."""
    project, state = release_project(tmp_path, code=False, deployable=False)
    result = check_release(project, state)
    assert result.status == "no_code"
    assert result.ok is True


def test_release_requires_a_test_run(tmp_path):
    project, state = release_project(tmp_path, test=None)
    result = check_release(project, state)
    assert result.status == "failed"
    assert "没有测试记录" in result.notes


def test_release_accepts_green_tests_and_a_deployable_target(tmp_path):
    project, state = release_project(
        tmp_path, test={"status": "passed", "command": ["npm", "test"]}
    )
    result = check_release(project, state)
    assert result.status == "passed"
    assert "测试已通过" in result.notes
    assert "部署目标可识别" in result.notes


def test_release_refuses_red_tests(tmp_path):
    project, state = release_project(
        tmp_path, test={"status": "failed", "command": ["npm", "test"], "exit_code": 1}
    )
    result = check_release(project, state)
    assert result.status == "failed"
    assert "不能发布测试未通过的代码" in result.notes


@pytest.mark.parametrize("status", ["timeout", "no_code", "dependencies_missing", "error"])
def test_release_refuses_every_non_passing_test_status(tmp_path, status):
    project, state = release_project(tmp_path, test={"status": status})
    result = check_release(project, state)
    assert result.status == "failed"
    assert status in result.notes


def test_release_refuses_when_nothing_is_deployable(tmp_path):
    project, state = release_project(
        tmp_path, deployable=False, test={"status": "passed"}
    )
    result = check_release(project, state)
    assert result.status == "failed"
    assert "没有可部署的内容" in result.notes


def test_release_allows_unverified_only_when_permitted(tmp_path):
    """No declared tests is a warning by default, and fatal when required."""
    project, state = release_project(tmp_path, test={"status": "not_configured"})

    lenient = check_release(project, state)
    assert lenient.status == "passed"
    assert "未经验证" in lenient.notes

    strict = check_release(project, state, require_tests=True)
    assert strict.status == "failed"
    assert "require_tests" in strict.notes


def test_release_readiness_is_wired_to_the_release_stage():
    import yaml

    cfg = yaml.safe_load((REPO_ROOT / "config" / "pipeline.yaml").read_text())
    stage = cfg["stages"]["release_pending"]
    assert stage["verify"] == "release"
    assert stage["code_dir"] == "app"
