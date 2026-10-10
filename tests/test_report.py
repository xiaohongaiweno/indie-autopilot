"""Tests for the markdown reports (scripts/report.py)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
for _p in (str(REPO_ROOT / "scripts"), str(REPO_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import report  # noqa: E402


def make_project(tmp_path, name="proj-demo", stage="discovered", **state_overrides):
    # Lives under projects/ because that is what discover_projects() scans.
    project = tmp_path / "projects" / name
    project.mkdir(parents=True, exist_ok=True)
    state = {
        "project_id": name,
        "name": "Demo",
        "stage": stage,
        "status": "active",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
        "approved_stages": [],
        "artifacts": {},
        "audit_log": [],
    }
    state.update(state_overrides)
    (project / "state.json").write_text(json.dumps(state, ensure_ascii=False))
    return project


# ---------------------------------------------------------------------------
# pending_gate -- the "why is nothing happening" answer
# ---------------------------------------------------------------------------


def test_pending_gate_is_none_when_next_step_is_ungated(tmp_path):
    project = make_project(tmp_path, stage="discovered")
    assert report.pending_gate(report.load_state(project)) is None


def test_pending_gate_reports_the_ungranted_gate(tmp_path):
    project = make_project(tmp_path, stage="validation_approved")
    gate = report.pending_gate(report.load_state(project))

    assert gate == {
        "from": "validation_approved",
        "to": "planning",
        "gate": "before_design",
        "required_artifacts": [],
    }


def test_pending_gate_disappears_once_approved(tmp_path):
    project = make_project(
        tmp_path,
        stage="validation_approved",
        approved_stages=[{"stage": "planning"}],
    )
    assert report.pending_gate(report.load_state(project)) is None


def test_pending_gate_handles_unknown_and_missing_stage(tmp_path):
    assert report.pending_gate({}) is None
    assert report.pending_gate({"stage": "not-a-stage"}) is None


# ---------------------------------------------------------------------------
# project_report
# ---------------------------------------------------------------------------


def test_project_report_has_the_essentials(tmp_path):
    project = make_project(tmp_path)
    text = report.project_report(project)

    assert "proj-demo" in text
    assert "discovered" in text
    assert "## 概览" in text
    assert "## 待办" in text
    assert "## 产物" in text
    assert "## 批准记录" in text


def test_project_report_leads_with_the_pending_gate(tmp_path):
    project = make_project(tmp_path, stage="testing")
    text = report.project_report(project)

    pending = text.index("## 待办")
    artifacts = text.index("## 产物")
    assert pending < artifacts, "the actionable fact should come first"
    assert "before_code_merge" in text
    assert "等待你批准" in text


def test_project_report_marks_mock_artifacts_as_not_evidence(tmp_path):
    project = make_project(
        tmp_path,
        artifacts={
            "research_result": {
                "path": "research/mock-research-result.json",
                "mode": "mock",
                "is_real_data": False,
                "generated_at": "2026-01-01T00:00:00Z",
            }
        },
    )
    (project / "research").mkdir()
    (project / "research" / "mock-research-result.json").write_text("{}")

    text = report.project_report(project)
    assert "mock" in text
    assert "不是证据" in text


def test_project_report_flags_a_missing_artifact_file(tmp_path):
    project = make_project(
        tmp_path,
        artifacts={
            "research_result": {
                "path": "research/gone.json",
                "mode": "live",
                "is_real_data": True,
                "generated_at": "2026-01-01T00:00:00Z",
            }
        },
    )
    text = report.project_report(project)
    assert "❌" in text


def test_project_report_includes_real_metrics(tmp_path):
    project = make_project(tmp_path, stage="growing")
    (project / "metrics").mkdir()
    (project / "metrics" / "latest-metrics.json").write_text(
        json.dumps(
            {
                "mode": "live",
                "is_real_data": True,
                "fetched_at": "2026-10-10T09:00:00Z",
                "sources": {
                    "search_console": {
                        "status": "ok",
                        "totals": {"clicks": 48, "impressions": 1400},
                        "delta": {"clicks": 0.2},
                        "opportunities": [
                            {
                                "type": "striking_distance",
                                "query": "cheap crm",
                                "impressions": 900,
                                "clicks": 8,
                                "position": 13.1,
                                "action": "补内容",
                            }
                        ],
                    },
                    "analytics": {"status": "ok", "totals": {"sessions": 120}},
                },
                "unavailable": [],
            },
            ensure_ascii=False,
        )
    )
    state = report.load_state(project)
    state["artifacts"]["metrics"] = {
        "path": "metrics/latest-metrics.json",
        "mode": "live",
        "is_real_data": True,
        "generated_at": "2026-10-10T09:00:00Z",
    }
    (project / "state.json").write_text(json.dumps(state, ensure_ascii=False))

    text = report.project_report(project)

    assert "clicks=48" in text
    assert "cheap crm" in text
    assert "+20.0%" in text
    assert "sessions=120" in text


def test_project_report_includes_deployment_and_tests(tmp_path):
    project = make_project(tmp_path, stage="launched")
    (project / "deploy").mkdir()
    (project / "deploy" / "deployment.json").write_text(
        json.dumps(
            {
                "url": "https://x.workers.dev",
                "kind": "workers",
                "environment": "production",
                "deployed_at": "2026-10-10T10:00:00Z",
                "custom_domain": "app.example.com",
            }
        )
    )
    (project / "testing").mkdir()
    (project / "testing" / "test-run.json").write_text(
        json.dumps({"status": "passed", "command": ["npm", "test"], "exit_code": 0})
    )
    state = report.load_state(project)
    state["artifacts"] = {
        "deployment": {"path": "deploy/deployment.json", "is_real_data": True},
        "test_run": {"path": "testing/test-run.json", "is_real_data": True},
    }
    (project / "state.json").write_text(json.dumps(state, ensure_ascii=False))

    text = report.project_report(project)

    assert "https://x.workers.dev" in text
    assert "app.example.com" in text
    assert "npm test" in text
    assert "passed" in text


def test_project_report_shows_the_code_manifest(tmp_path):
    project = make_project(
        tmp_path,
        artifacts={
            "build_result": {
                "path": "build/x.json",
                "mode": "live",
                "is_real_data": True,
                "generated_at": "2026-01-01T00:00:00Z",
                "code": {
                    "file_count": 2,
                    "bytes": 100,
                    "files": ["src/index.js", "wrangler.toml"],
                },
            }
        },
    )
    text = report.project_report(project)
    assert "## 代码" in text
    assert "`src/index.js`" in text


def test_project_report_shows_recent_activity(tmp_path):
    project = make_project(
        tmp_path,
        audit_log=[
            {
                "timestamp": "2026-01-01T00:00:00Z",
                "action": "transition",
                "from_stage": "discovered",
                "to_stage": "researching",
            }
        ],
    )
    text = report.project_report(project)
    assert "`transition`" in text
    assert "from_stage=discovered" in text


def test_project_report_handles_unreadable_state(tmp_path):
    project = tmp_path / "broken"
    project.mkdir()
    assert "错误" in report.project_report(project)


def test_project_report_caps_the_audit_timeline(tmp_path):
    project = make_project(
        tmp_path,
        audit_log=[
            {"timestamp": f"2026-01-01T00:00:{i:02d}Z", "action": "noise"}
            for i in range(50)
        ]
        + [{"timestamp": "2026-02-01T00:00:00Z", "action": "the-latest"}],
    )
    text = report.project_report(project)
    assert "the-latest" in text
    assert text.count("`noise`") < 50


# ---------------------------------------------------------------------------
# portfolio_report
# ---------------------------------------------------------------------------


def test_portfolio_lists_every_project(tmp_path, monkeypatch):
    monkeypatch.setattr(report, "REPO_ROOT", tmp_path)
    make_project(tmp_path, "alpha")
    make_project(tmp_path, "beta", stage="testing")

    text = report.portfolio_report()

    assert "`alpha`" in text
    assert "`beta`" in text


def test_portfolio_surfaces_waiting_projects(tmp_path, monkeypatch):
    monkeypatch.setattr(report, "REPO_ROOT", tmp_path)
    make_project(tmp_path, "waiting", stage="testing")
    make_project(tmp_path, "flowing", stage="discovered")

    text = report.portfolio_report()

    assert "等待你处理" in text
    assert "before_code_merge" in text
    assert "⏸ before_code_merge" in text


def test_portfolio_handles_no_projects(tmp_path, monkeypatch):
    monkeypatch.setattr(report, "REPO_ROOT", tmp_path)
    (tmp_path / "projects").mkdir()
    assert "没有可识别的项目" in report.portfolio_report()


def test_portfolio_counts_real_data_artifacts(tmp_path, monkeypatch):
    monkeypatch.setattr(report, "REPO_ROOT", tmp_path)
    make_project(
        tmp_path,
        "withdata",
        artifacts={
            "metrics": {"path": "m.json", "is_real_data": True},
            "research_result": {"path": "r.json", "is_real_data": False},
        },
    )
    assert "1 项" in report.portfolio_report()


def test_discover_projects_ignores_dirs_without_state(tmp_path, monkeypatch):
    monkeypatch.setattr(report, "REPO_ROOT", tmp_path)
    make_project(tmp_path, "real")
    (tmp_path / "projects" / "empty").mkdir(parents=True)
    assert [p.name for p in report.discover_projects()] == ["real"]
