"""Tests for Cloudflare deployment (scripts/deploy.py) and its orchestrator hook."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
for _p in (str(REPO_ROOT / "scripts"), str(REPO_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import deploy  # noqa: E402
import orchestrator as orch  # noqa: E402
from state_machine import State  # noqa: E402

GATE_ORDER = ["planning", "plan_approved", "release_pending", "launched"]


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def env_file(tmp_path, monkeypatch):
    """A private .env, with Cloudflare vars cleared from the real environment."""
    path = tmp_path / ".env"
    for key in deploy.REQUIRED_CREDENTIALS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(deploy, "ENV_FILE", path)
    return path


@pytest.fixture
def worker_project(tmp_path):
    project = tmp_path / "my-worker"
    project.mkdir()
    (project / "wrangler.toml").write_text('name = "my-worker"\nmain = "src/index.js"\n')
    return project


@pytest.fixture
def config():
    return orch.load_config()


def fake_proc(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(
        args=["npx", "wrangler"], returncode=returncode, stdout=stdout, stderr=stderr
    )


WORKER_OUTPUT = (
    "Total Upload: 12.34 KiB / gzip: 4.56 KiB\n"
    "Uploaded my-worker (1.23 sec)\n"
    "Deployed my-worker triggers (0.45 sec)\n"
    "  https://my-worker.someone.workers.dev\n"
)


# ---------------------------------------------------------------------------
# 1. .env handling
# ---------------------------------------------------------------------------


def test_load_env_file_parses_and_ignores_comments(tmp_path):
    path = tmp_path / ".env"
    path.write_text(
        "# a comment\n"
        "\n"
        "CLOUDFLARE_API_TOKEN=abc123\n"
        'CLOUDFLARE_ACCOUNT_ID="quoted-value"\n'
        "OTHER=keep\n"
    )
    values = deploy.load_env_file(path)
    assert values["CLOUDFLARE_API_TOKEN"] == "abc123"
    assert values["CLOUDFLARE_ACCOUNT_ID"] == "quoted-value"
    assert values["OTHER"] == "keep"


def test_load_env_file_missing_returns_empty(tmp_path):
    assert deploy.load_env_file(tmp_path / "nope") == {}


def test_save_env_values_merges_and_preserves(tmp_path):
    path = tmp_path / ".env"
    path.write_text("# my secrets\nOTHER=keep\nCLOUDFLARE_API_TOKEN=old\n")

    deploy.save_env_values(
        {"CLOUDFLARE_API_TOKEN": "new", "CLOUDFLARE_ACCOUNT_ID": "acct"}, path
    )

    text = path.read_text()
    assert "# my secrets" in text
    assert "OTHER=keep" in text
    assert "CLOUDFLARE_API_TOKEN=new" in text
    assert "CLOUDFLARE_API_TOKEN=old" not in text
    assert "CLOUDFLARE_ACCOUNT_ID=acct" in text


def test_save_env_values_is_owner_only(tmp_path):
    path = tmp_path / ".env"
    deploy.save_env_values({"CLOUDFLARE_API_TOKEN": "x"}, path)
    mode = stat.S_IMODE(path.stat().st_mode)
    assert mode == 0o600, f"expected 0600, got {oct(mode)}"


def test_save_env_values_does_not_duplicate_keys(tmp_path):
    path = tmp_path / ".env"
    deploy.save_env_values({"CLOUDFLARE_API_TOKEN": "one"}, path)
    deploy.save_env_values({"CLOUDFLARE_API_TOKEN": "two"}, path)
    assert path.read_text().count("CLOUDFLARE_API_TOKEN=") == 1
    assert "CLOUDFLARE_API_TOKEN=two" in path.read_text()


def test_apply_env_file_does_not_override_real_env(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    path.write_text("CLOUDFLARE_API_TOKEN=from-file\n")
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "from-env")
    deploy.apply_env_file(path)
    assert os.environ["CLOUDFLARE_API_TOKEN"] == "from-env"


# ---------------------------------------------------------------------------
# 2. Credentials
# ---------------------------------------------------------------------------


def test_missing_credentials_reports_all(env_file):
    assert set(deploy.missing_credentials()) == set(deploy.REQUIRED_CREDENTIALS)


def test_missing_credentials_accepts_env_file(env_file):
    deploy.save_env_values(
        {"CLOUDFLARE_API_TOKEN": "t", "CLOUDFLARE_ACCOUNT_ID": "a"}, env_file
    )
    assert deploy.missing_credentials() == []


def test_missing_credentials_accepts_environment(env_file, monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "t")
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "a")
    assert deploy.missing_credentials() == []


def test_ensure_credentials_returns_without_prompting_when_present(env_file, monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "t")
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "a")
    monkeypatch.setattr(
        "getpass.getpass", lambda *a: pytest.fail("should not prompt")
    )
    creds = deploy.ensure_credentials()
    assert creds["CLOUDFLARE_API_TOKEN"] == "t"


def test_ensure_credentials_prompts_and_saves(env_file, monkeypatch):
    answers = iter(["secret-token", "secret-account"])
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("getpass.getpass", lambda *a: next(answers))

    creds = deploy.ensure_credentials()

    assert creds == {
        "CLOUDFLARE_API_TOKEN": "secret-token",
        "CLOUDFLARE_ACCOUNT_ID": "secret-account",
    }
    text = env_file.read_text()
    assert "CLOUDFLARE_API_TOKEN=secret-token" in text
    assert stat.S_IMODE(env_file.stat().st_mode) == 0o600


def test_ensure_credentials_reprompts_on_empty(env_file, monkeypatch):
    answers = iter(["", "  ", "token", "acct"])
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("getpass.getpass", lambda *a: next(answers))
    creds = deploy.ensure_credentials()
    assert creds["CLOUDFLARE_API_TOKEN"] == "token"


def test_ensure_credentials_never_echoes_secret(env_file, monkeypatch, capsys):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("getpass.getpass", lambda *a: "SUPER-SECRET-VALUE")
    deploy.ensure_credentials()
    captured = capsys.readouterr()
    assert "SUPER-SECRET-VALUE" not in captured.out
    assert "SUPER-SECRET-VALUE" not in captured.err


def test_ensure_credentials_non_interactive_fails_with_guidance(env_file, monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    with pytest.raises(deploy.DeployError) as excinfo:
        deploy.ensure_credentials()
    message = str(excinfo.value)
    assert "CLOUDFLARE_API_TOKEN" in message
    assert ".env" in message


def test_ensure_credentials_cancelled_input_raises(env_file, monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)

    def cancel(*_a):
        raise KeyboardInterrupt

    monkeypatch.setattr("getpass.getpass", cancel)
    with pytest.raises(deploy.DeployError, match="取消"):
        deploy.ensure_credentials()


# ---------------------------------------------------------------------------
# 3. Target detection
# ---------------------------------------------------------------------------


def test_detect_workers_from_wrangler_toml(tmp_path):
    project = tmp_path / "p"
    project.mkdir()
    (project / "wrangler.toml").write_text('name = "api"\n')
    target = deploy.detect_target(project)
    assert target.kind == "workers"
    assert target.command == ["npx", "wrangler", "deploy"]


@pytest.mark.parametrize("filename", ["wrangler.toml", "wrangler.json", "wrangler.jsonc"])
def test_detect_workers_from_each_config_name(tmp_path, filename):
    project = tmp_path / "p"
    project.mkdir()
    (project / filename).write_text('{"name": "api"}')
    assert deploy.detect_target(project).kind == "workers"


def test_detect_workers_adds_env_flag_for_non_production(tmp_path):
    project = tmp_path / "p"
    project.mkdir()
    (project / "wrangler.toml").write_text('name = "api"\n')
    target = deploy.detect_target(project, environment="preview")
    assert "--env" in target.command
    assert target.command[target.command.index("--env") + 1] == "preview"


def test_detect_pages_from_dist(tmp_path):
    project = tmp_path / "p"
    (project / "dist").mkdir(parents=True)
    (project / "dist" / "index.html").write_text("<h1>hi</h1>")
    target = deploy.detect_target(project)
    assert target.kind == "pages"
    assert "pages" in target.command
    assert "--project-name" in target.command
    assert "--branch" in target.command


def test_detect_ignores_empty_static_dir(tmp_path):
    project = tmp_path / "p"
    (project / "dist").mkdir(parents=True)  # empty
    with pytest.raises(deploy.DeployError, match="没有可部署的内容"):
        deploy.detect_target(project)


def test_detect_error_explains_what_to_add(tmp_path):
    project = tmp_path / "p"
    project.mkdir()
    with pytest.raises(deploy.DeployError) as excinfo:
        deploy.detect_target(project)
    message = str(excinfo.value)
    assert "wrangler.toml" in message
    assert "dist" in message


def test_detect_missing_project_dir(tmp_path):
    with pytest.raises(deploy.DeployError, match="不存在"):
        deploy.detect_target(tmp_path / "nope")


def test_project_name_read_from_config_then_dir(tmp_path):
    project = tmp_path / "dir-name"
    project.mkdir()
    (project / "wrangler.toml").write_text('name = "declared-name"\n')
    assert deploy._project_name(project) == "declared-name"

    other = tmp_path / "no-config"
    other.mkdir()
    assert deploy._project_name(other) == "no-config"


def test_deploy_config_override_for_wrangler_command(tmp_path):
    project = tmp_path / "p"
    project.mkdir()
    (project / "wrangler.toml").write_text('name = "api"\n')
    target = deploy.detect_target(
        project, config={"deploy": {"wrangler": ["pnpm", "dlx", "wrangler"]}}
    )
    assert target.command[:3] == ["pnpm", "dlx", "wrangler"]


# ---------------------------------------------------------------------------
# 4. URL extraction
# ---------------------------------------------------------------------------


def test_extract_url_prefers_workers_dev():
    assert deploy.extract_url(WORKER_OUTPUT) == "https://my-worker.someone.workers.dev"


def test_extract_url_prefers_pages_dev():
    out = "See https://dash.cloudflare.com/abc then https://x.my-proj.pages.dev"
    assert deploy.extract_url(out) == "https://x.my-proj.pages.dev"


def test_extract_url_falls_back_to_last():
    assert deploy.extract_url("a https://one.example b https://two.example") == "https://two.example"


def test_extract_url_none_when_absent():
    assert deploy.extract_url("no urls here") is None
    assert deploy.extract_url("") is None


def test_extract_url_strips_trailing_punctuation():
    assert deploy.extract_url("live at https://x.workers.dev.") == "https://x.workers.dev"


# ---------------------------------------------------------------------------
# 5. deploy()
# ---------------------------------------------------------------------------


def test_deploy_dry_run_needs_no_credentials(worker_project, env_file):
    result = deploy.deploy(worker_project, dry_run=True)
    assert result.ok is True
    assert result.dry_run is True
    assert result.command == ["npx", "wrangler", "deploy"]


def test_deploy_success(worker_project, env_file, monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "t")
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "a")
    monkeypatch.setattr(deploy.subprocess, "run", lambda *a, **k: fake_proc(0, WORKER_OUTPUT))

    result = deploy.deploy(worker_project)

    assert result.ok is True
    assert result.url == "https://my-worker.someone.workers.dev"
    assert result.target_kind == "workers"
    assert result.error is None


def test_deploy_failure_reports_wrangler_error(worker_project, env_file, monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "t")
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "a")
    monkeypatch.setattr(
        deploy.subprocess,
        "run",
        lambda *a, **k: fake_proc(1, "", "✘ [ERROR] Authentication error"),
    )

    result = deploy.deploy(worker_project)

    assert result.ok is False
    assert "Authentication error" in result.error


def test_deploy_missing_binary(worker_project, env_file, monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "t")
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "a")

    def boom(*_a, **_k):
        raise FileNotFoundError("npx not found")

    monkeypatch.setattr(deploy.subprocess, "run", boom)
    result = deploy.deploy(worker_project)
    assert result.ok is False
    assert "npx" in result.error


def test_deploy_timeout(worker_project, env_file, monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "t")
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "a")

    def slow(*_a, **_k):
        raise subprocess.TimeoutExpired(cmd="npx", timeout=1)

    monkeypatch.setattr(deploy.subprocess, "run", slow)
    result = deploy.deploy(worker_project, timeout_seconds=1)
    assert result.ok is False
    assert "超时" in result.error


def test_deploy_passes_environment_through(worker_project, env_file, monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "t")
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "a")
    captured = {}

    def capture(argv, **kwargs):
        captured["argv"] = argv
        return fake_proc(0, WORKER_OUTPUT)

    monkeypatch.setattr(deploy.subprocess, "run", capture)
    deploy.deploy(worker_project, environment="preview")
    assert captured["argv"][-2:] == ["--env", "preview"]


# ---------------------------------------------------------------------------
# 6. Recording
# ---------------------------------------------------------------------------


def make_result(**overrides):
    base = dict(
        ok=True,
        environment="production",
        command=["npx", "wrangler", "deploy"],
        url="https://x.workers.dev",
        target_kind="workers",
        duration_seconds=1.5,
    )
    base.update(overrides)
    return deploy.DeploymentResult(**base)


def test_record_and_load_deployment(worker_project):
    path = deploy.record_deployment(worker_project, make_result(), project_name="my-worker")
    assert path.is_file()

    record = deploy.load_deployment(worker_project)
    assert record["url"] == "https://x.workers.dev"
    assert record["project_name"] == "my-worker"
    assert record["custom_domain_attached"] is False
    assert len(record["history"]) == 1


def test_redeploy_preserves_custom_domain(worker_project):
    deploy.record_deployment(worker_project, make_result())
    deploy.record_domain(worker_project, "example.com", actor="me")
    deploy.record_deployment(worker_project, make_result(url="https://y.workers.dev"))

    record = deploy.load_deployment(worker_project)
    assert record["url"] == "https://y.workers.dev"
    assert record["custom_domain"] == "example.com"
    assert record["custom_domain_attached"] is True
    assert len(record["history"]) == 2


def test_load_deployment_missing_and_corrupt(worker_project):
    assert deploy.load_deployment(worker_project) == {}
    path = deploy.deployment_path(worker_project)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{ not json")
    assert deploy.load_deployment(worker_project) == {}


def test_record_domain_requires_prior_deployment(worker_project):
    with pytest.raises(deploy.DeployError, match="还没有部署记录"):
        deploy.record_domain(worker_project, "example.com")


def test_record_domain_rejects_empty(worker_project):
    deploy.record_deployment(worker_project, make_result())
    with pytest.raises(deploy.DeployError, match="不能为空"):
        deploy.record_domain(worker_project, "   ")


def test_domain_instructions_mention_the_project(worker_project):
    text = deploy.domain_instructions("my-worker")
    assert "my-worker" in text
    assert "Custom Domain" in text


# ---------------------------------------------------------------------------
# 7. deploy_before_launch + orchestrator hook
# ---------------------------------------------------------------------------


def test_deploy_before_launch_records_artifact_and_audit(
    worker_project, env_file, monkeypatch
):
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "t")
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "a")
    monkeypatch.setattr(deploy.subprocess, "run", lambda *a, **k: fake_proc(0, WORKER_OUTPUT))

    state = {"stage": "release_pending", "artifacts": {}, "audit_log": []}
    result = deploy.deploy_before_launch(worker_project, state, assume_yes=True)

    assert result.ok is True
    assert state["artifacts"]["deployment"]["path"] == "deploy/deployment.json"
    assert state["artifacts"]["deployment"]["is_real_data"] is True
    assert state["audit_log"][-1]["action"] == "deployed"
    assert state["audit_log"][-1]["url"] == "https://my-worker.someone.workers.dev"


def test_deploy_before_launch_raises_pipeline_error_on_failure(
    worker_project, env_file, monkeypatch
):
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "t")
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "a")
    monkeypatch.setattr(
        deploy.subprocess, "run", lambda *a, **k: fake_proc(1, "", "✘ [ERROR] boom")
    )
    state = {"stage": "release_pending", "artifacts": {}, "audit_log": []}

    with pytest.raises(orch.PipelineError, match="部署失败"):
        deploy.deploy_before_launch(worker_project, state, assume_yes=True)

    # nothing was recorded
    assert "deployment" not in state["artifacts"]
    assert state["audit_log"] == []


def test_deploy_before_launch_without_target_raises(env_file, tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    state = {"stage": "release_pending", "artifacts": {}, "audit_log": []}
    with pytest.raises(orch.PipelineError, match="部署失败"):
        deploy.deploy_before_launch(empty, state, assume_yes=True)


def _release_pending_project(tmp_path):
    """A project parked at release_pending with every gate pre-approved."""
    project = tmp_path / "proj-deploy"
    project.mkdir()
    state = {
        "project_id": "proj-deploy",
        "name": "Deploy Test",
        "stage": "release_pending",
        "status": "active",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
        "approved_stages": [],
        "artifacts": {
            "test_result": {"path": "testing/mock-testing-result.json"},
        },
        "audit_log": [],
    }
    (project / "testing").mkdir()
    (project / "testing" / "mock-testing-result.json").write_text("{}")
    for stage in GATE_ORDER:
        state["approved_stages"].append({"stage": stage})
    (project / "state.json").write_text(json.dumps(state, indent=2))
    return project


def test_hook_runs_before_transition_is_recorded(tmp_path, config):
    project = _release_pending_project(tmp_path)
    seen = {}

    def action(project_dir, state, **kwargs):
        seen["stage"] = state["stage"]

    orch.register_pre_transition_action("release_pending", "launched", action)
    try:
        orch.run(project, target=State.LAUNCHED, config=config)
    finally:
        orch.unregister_pre_transition_action("release_pending", "launched")

    assert seen["stage"] == "release_pending"
    assert orch.load_state(project)["stage"] == "launched"


def test_failed_hook_leaves_project_retryable_not_launched(tmp_path, config):
    """The whole point: a failed deploy must not produce a `launched` project."""
    project = _release_pending_project(tmp_path)

    def boom(project_dir, state, **kwargs):
        raise orch.PipelineError("部署失败：boom")

    orch.register_pre_transition_action("release_pending", "launched", boom)
    try:
        with pytest.raises(orch.PipelineError, match="部署失败"):
            orch.run(project, target=State.LAUNCHED, config=config)
    finally:
        orch.unregister_pre_transition_action("release_pending", "launched")

    assert orch.load_state(project)["stage"] == "release_pending"


def test_unregistered_hook_means_no_deploy_attempt(tmp_path, config):
    """Library-level runs must never shell out to a deployer by accident."""
    project = _release_pending_project(tmp_path)
    assert ("release_pending", "launched") not in [
        (s.value, d.value) for (s, d) in orch.PRE_TRANSITION_ACTIONS
    ]
    result = orch.run(project, target=State.LAUNCHED, config=config)
    assert result.reached == "launched"


def test_cli_registers_the_deploy_hook():
    """autopilot's main() must wire deployment up, or `run` would lie."""
    import autopilot

    orch.unregister_pre_transition_action("release_pending", "launched")
    try:
        autopilot.main(["list"])
        assert (
            State.RELEASE_PENDING,
            State.LAUNCHED,
        ) in orch.PRE_TRANSITION_ACTIONS
        assert (
            orch.PRE_TRANSITION_ACTIONS[(State.RELEASE_PENDING, State.LAUNCHED)]
            is deploy.deploy_before_launch
        )
    finally:
        orch.unregister_pre_transition_action("release_pending", "launched")


# ---------------------------------------------------------------------------
# 10. Layout: pipeline metadata must never be mistaken for a website
# ---------------------------------------------------------------------------


def test_pipeline_build_dir_is_not_treated_as_a_site(tmp_path):
    """Regression: deploy once offered to publish the build stage's JSON files.

    `build/` holds pipeline metadata (mock-building-result.json and friends),
    and it used to be in STATIC_DIRS, so a project with no product code looked
    deployable and would have published its own bookkeeping.
    """
    project = tmp_path / "proj"
    (project / "build").mkdir(parents=True)
    (project / "build" / "mock-building-result.json").write_text('{"summary": "x"}')

    with pytest.raises(deploy.DeployError, match="没有可部署的内容"):
        deploy.detect_target(project)


def test_build_is_not_a_static_dir():
    assert "build" not in deploy.STATIC_DIRS


def test_detects_worker_inside_the_code_dir(tmp_path):
    project = tmp_path / "proj"
    (project / "app").mkdir(parents=True)
    (project / "app" / "wrangler.toml").write_text('name = "real-app"\n')
    # pipeline metadata alongside must not confuse detection
    (project / "build").mkdir()
    (project / "build" / "mock-building-result.json").write_text("{}")

    target = deploy.detect_target(project)

    assert target.kind == "workers"
    assert target.cwd == project / "app"


def test_detects_pages_inside_the_code_dir(tmp_path):
    project = tmp_path / "proj"
    (project / "app" / "dist").mkdir(parents=True)
    (project / "app" / "dist" / "index.html").write_text("<h1>hi</h1>")

    target = deploy.detect_target(project)

    assert target.kind == "pages"
    assert target.asset_dir == project / "app" / "dist"


def test_code_dir_takes_priority_over_project_root(tmp_path):
    project = tmp_path / "proj"
    (project / "app").mkdir(parents=True)
    (project / "app" / "wrangler.toml").write_text('name = "from-app"\n')
    (project / "wrangler.toml").write_text('name = "from-root"\n')

    target = deploy.detect_target(project)

    assert target.cwd == project / "app"
    assert deploy._project_name(project) == "from-root"


def test_project_root_still_works_for_hand_made_projects(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    (project / "wrangler.toml").write_text('name = "legacy"\n')
    assert deploy.detect_target(project).kind == "workers"


def test_source_dir_is_configurable(tmp_path):
    project = tmp_path / "proj"
    (project / "src").mkdir(parents=True)
    (project / "src" / "wrangler.toml").write_text('name = "custom"\n')

    target = deploy.detect_target(project, config={"deploy": {"source_dir": "src"}})

    assert target.cwd == project / "src"


def test_empty_code_dir_is_not_deployable(tmp_path):
    project = tmp_path / "proj"
    (project / "app").mkdir(parents=True)
    with pytest.raises(deploy.DeployError, match="没有可部署的内容"):
        deploy.detect_target(project)
