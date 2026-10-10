"""Tests for the opportunity radar (scripts/radar.py)."""

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

import radar  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def radar_env(tmp_path, monkeypatch):
    """Redirect every mutable radar path into tmp_path."""
    monkeypatch.setattr(radar, "RADAR_ROOT", tmp_path / "radar")
    monkeypatch.setattr(radar, "SCANS_DIR", tmp_path / "radar" / "scans")
    monkeypatch.setattr(radar, "RADAR_DATA", tmp_path / "radar-data")
    monkeypatch.setattr(radar, "PROFILE_PATH", tmp_path / "radar-data" / "profile.md")
    monkeypatch.setattr(radar, "PROJECTS_DIR", tmp_path / "projects")
    (tmp_path / "projects").mkdir()
    return tmp_path


def opp(name="Good Idea", oid="2026-10-w2-01", **overrides):
    base = {
        "id": oid,
        "name": name,
        "pos": f"为某人解决某事（{name}）",
        "ind": "tools",
        "s": {
            "demand": 9, "trend": 7, "pay": 8, "gap": 8,
            "acq": 7, "dev": 9, "moat": 4, "fit": 9,
        },
        "sig": ["用户痛点", "商业化", "SEO/需求"],
        "veto": [],
        "status": "validating",
        "fact": "事实",
        "market": "~5000 × $29",
        "notes": "【事实】有证据",
        "links": "https://example.com/a",
    }
    base.update(overrides)
    return base


def scan_envelope(opportunities, **overrides):
    payload = {
        "scan_id": "test-scan",
        "generated_at": "2026-10-10T00:00:00Z",
        "summary": "测试扫描",
        "opportunities": opportunities,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# 1. Scoring must not drift from score.py
# ---------------------------------------------------------------------------


def test_scoring_weights_are_read_from_score_py():
    dims, go, watch = radar._scoring_spec()
    assert dims == [
        ("demand", 18), ("trend", 13), ("pay", 18), ("gap", 13),
        ("acq", 13), ("dev", 10), ("moat", 5), ("fit", 10),
    ]
    assert (go, watch) == (75, 60)


def test_score_matches_score_py_output(tmp_path):
    """Our total must equal what the skill's own script computes."""
    board = [opp(), opp(name="Weak", oid="w2", s={
        "demand": 3, "trend": 3, "pay": 2, "gap": 4, "acq": 2, "dev": 8, "moat": 2, "fit": 3,
    }, sig=["热点/趋势"], fact="推测", links="", notes="【推测】x")]
    path = tmp_path / "sb.json"
    path.write_text(json.dumps(board, ensure_ascii=False))

    proc = subprocess.run(
        [sys.executable, str(radar.SCORE_PY), "rank", str(path)],
        capture_output=True, text=True, check=True,
    )
    script_scores = []
    for line in proc.stdout.splitlines():
        token = line.split()[0] if line.split() else ""
        if token.isdigit():
            script_scores.append(int(token))

    ours = sorted((radar.score_opportunity(o) for o in board), reverse=True)
    assert ours == script_scores


def test_tier_thresholds():
    assert radar.tier_opportunity(opp()) == "go"
    assert radar.tier_opportunity(
        opp(s={"demand": 6, "trend": 6, "pay": 6, "gap": 6, "acq": 6, "dev": 6, "moat": 6, "fit": 6})
    ) == "watch"
    assert radar.tier_opportunity(
        opp(s={"demand": 1, "trend": 1, "pay": 1, "gap": 1, "acq": 1, "dev": 1, "moat": 1, "fit": 1})
    ) == "low"


def test_veto_overrides_score():
    assert radar.tier_opportunity(opp(veto=["重度合规"])) == "veto"


# ---------------------------------------------------------------------------
# 2. score.py validation integration
# ---------------------------------------------------------------------------


def test_validate_scoreboard_accepts_valid(tmp_path):
    errors, _ = radar.validate_scoreboard([opp()], tmp_path)
    assert errors == []


def test_validate_scoreboard_reports_bad_enum(tmp_path):
    errors, _ = radar.validate_scoreboard([opp(sig=["胡编的信号"])], tmp_path)
    assert any("非法 sig" in e for e in errors)


def test_validate_scoreboard_reports_missing_field(tmp_path):
    bad = opp()
    del bad["pos"]
    errors, _ = radar.validate_scoreboard([bad], tmp_path)
    assert any("缺少字段 pos" in e for e in errors)


def test_validate_scoreboard_reports_duplicate_ids(tmp_path):
    errors, _ = radar.validate_scoreboard([opp(), opp()], tmp_path)
    assert any("重复 id" in e for e in errors)


def test_validate_scoreboard_flags_fact_without_links(tmp_path):
    errors, _ = radar.validate_scoreboard([opp(links="")], tmp_path)
    assert any("没有证据链接" in e for e in errors)


def test_validate_scoreboard_writes_the_board_file(tmp_path):
    radar.validate_scoreboard([opp()], tmp_path)
    assert json.loads((tmp_path / "scoreboard.json").read_text())[0]["name"] == "Good Idea"


# ---------------------------------------------------------------------------
# 3. Scan coercion (agent output variety)
# ---------------------------------------------------------------------------


def test_coerce_scan_accepts_our_envelope():
    payload = radar.coerce_scan(scan_envelope([opp()]), "", "s1")
    assert payload["opportunities"][0]["name"] == "Good Idea"


def test_coerce_scan_accepts_bare_scoreboard_array():
    """The skill's native output is a bare array, so it must not be rejected."""
    payload = radar.coerce_scan([opp()], "", "s1")
    assert payload["opportunities"][0]["name"] == "Good Idea"
    assert payload["scan_id"] == "s1"


def test_coerce_scan_accepts_single_opportunity_object():
    payload = radar.coerce_scan(opp(), "", "s1")
    assert len(payload["opportunities"]) == 1


def test_coerce_scan_finds_array_in_prose():
    raw = f"好的，这是结果：\n{json.dumps([opp()], ensure_ascii=False)}\n希望有帮助"
    payload = radar.coerce_scan(None, raw, "s1")
    assert payload["opportunities"][0]["name"] == "Good Idea"


def test_coerce_scan_unwraps_array_inside_envelope():
    raw = json.dumps({"result": json.dumps([opp()], ensure_ascii=False)})
    payload = radar.coerce_scan(None, raw, "s1")
    assert payload["opportunities"][0]["name"] == "Good Idea"


def test_coerce_scan_raises_when_nothing_found():
    with pytest.raises(radar.RadarError, match="opportunities"):
        radar.coerce_scan({"nonsense": True}, "no json here", "s1")


def test_find_json_array_ignores_brackets_in_strings():
    assert radar._find_json_array('x ["a]b", 1] y') == ["a]b", 1]


# ---------------------------------------------------------------------------
# 4. Profile
# ---------------------------------------------------------------------------


def test_ensure_profile_creates_template_once(radar_env):
    path, created = radar.ensure_profile()
    assert created is True and path.is_file()
    assert "可触达的受众与渠道" in path.read_text()

    path.write_text("# 我的画像\n")
    _, created_again = radar.ensure_profile()
    assert created_again is False
    assert path.read_text() == "# 我的画像\n"


# ---------------------------------------------------------------------------
# 5. Prompt construction
# ---------------------------------------------------------------------------


def test_build_scan_prompt_is_self_contained(radar_env):
    radar.ensure_profile()
    (radar_env / "projects" / "old-proj").mkdir()
    (radar_env / "projects" / "old-proj" / "state.json").write_text(
        json.dumps({"stage": "building"})
    )

    prompt = radar.build_scan_prompt("scan-1", ["indie-product-radar"])

    # the skill plus its references travel with the brief
    assert "indie-product-radar" in prompt
    assert "附：references/scoring-rubric.md" in prompt
    assert "附：references/output-schemas.md" in prompt
    # the scoring script is pointed at
    assert str(radar.SCORE_PY) in prompt
    # the workspace is spelled out, since a handoff agent has no cwd context
    assert str(radar.RADAR_DATA) in prompt
    # existing projects are listed so nothing is re-suggested
    assert "old-proj" in prompt and "building" in prompt
    # enum guidance, which is where handoff round-trips are lost
    assert "字段约束速查" in prompt
    assert "只能取" in prompt
    assert "绝不编造搜索量" in prompt


def test_build_scan_prompt_lists_known_opportunities(radar_env):
    radar.RADAR_DATA.mkdir(parents=True)
    (radar.RADAR_DATA / "scoreboard.json").write_text(
        json.dumps([opp(name="Already Seen")], ensure_ascii=False)
    )
    prompt = radar.build_scan_prompt("s", ["indie-product-radar"])
    assert "Already Seen" in prompt


def test_known_opportunity_names_handles_missing_and_bad_file(radar_env):
    assert radar.known_opportunity_names() == []
    radar.RADAR_DATA.mkdir(parents=True)
    (radar.RADAR_DATA / "scoreboard.json").write_text("{ not json")
    assert radar.known_opportunity_names() == []


def test_existing_projects_skips_unreadable(radar_env):
    (radar_env / "projects" / "ok").mkdir()
    (radar_env / "projects" / "ok" / "state.json").write_text('{"stage":"testing"}')
    (radar_env / "projects" / "broken").mkdir()
    (radar_env / "projects" / "broken" / "state.json").write_text("{bad")
    assert radar.existing_projects() == [("ok", "testing")]


# ---------------------------------------------------------------------------
# 6. run_scan from a file
# ---------------------------------------------------------------------------


def test_run_scan_from_file(radar_env, tmp_path):
    src = tmp_path / "scan.json"
    src.write_text(json.dumps(scan_envelope([opp(), opp(name="Low", oid="l2", s={
        "demand": 2, "trend": 2, "pay": 2, "gap": 2, "acq": 2, "dev": 2, "moat": 2, "fit": 2,
    }, sig=["热点/趋势"], status="inbox", fact="推测", links="")]), ensure_ascii=False))

    result = radar.run_scan(from_file=src, scan_id="s1")

    assert result.validation_errors == []
    assert len(result.opportunities) == 2
    # ranked highest first
    assert result.ranked[0]["name"] == "Good Idea"
    assert (result.scan_dir / "scoreboard.json").is_file()


def test_run_scan_from_file_rejects_invalid_json(radar_env, tmp_path):
    src = tmp_path / "bad.json"
    src.write_text("{not json")
    with pytest.raises(radar.RadarError, match="不是合法 JSON"):
        radar.run_scan(from_file=src)


# ---------------------------------------------------------------------------
# 7. Presentation and selection
# ---------------------------------------------------------------------------


def test_describe_scan_shows_cards_and_errors(radar_env, tmp_path):
    src = tmp_path / "scan.json"
    src.write_text(json.dumps(scan_envelope([opp(sig=["非法"])]), ensure_ascii=False))
    result = radar.run_scan(from_file=src, scan_id="s1")

    text = radar.describe_scan(result)
    assert "scan_id" not in text  # label is localized
    assert "扫描 ID" in text
    assert "score.py 校验发现" in text


def test_choose_refuses_to_build_on_invalid_data(radar_env, tmp_path):
    src = tmp_path / "scan.json"
    src.write_text(json.dumps(scan_envelope([opp(sig=["非法"])]), ensure_ascii=False))
    result = radar.run_scan(from_file=src, scan_id="s1")

    with pytest.raises(radar.RadarError, match="校验未通过"):
        radar.choose_opportunities(result, assume_yes=True)


def test_choose_yes_picks_top(radar_env, tmp_path):
    src = tmp_path / "scan.json"
    src.write_text(json.dumps(scan_envelope([opp()]), ensure_ascii=False))
    result = radar.run_scan(from_file=src, scan_id="s1")

    picks = radar.choose_opportunities(result, assume_yes=True)
    assert [p["name"] for p in picks] == ["Good Idea"]


def test_choose_requires_tty_without_yes(radar_env, tmp_path, monkeypatch):
    src = tmp_path / "scan.json"
    src.write_text(json.dumps(scan_envelope([opp()]), ensure_ascii=False))
    result = radar.run_scan(from_file=src, scan_id="s1")
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)

    with pytest.raises(radar.RadarError, match="不是 TTY"):
        radar.choose_opportunities(result, assume_yes=False)


def test_choose_multi_select_by_number(radar_env, tmp_path, monkeypatch):
    src = tmp_path / "scan.json"
    src.write_text(json.dumps(scan_envelope([opp(), opp(name="Second", oid="b2")]), ensure_ascii=False))
    result = radar.run_scan(from_file=src, scan_id="s1")
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda *a: "1,2")

    picks = radar.choose_opportunities(result)
    assert len(picks) == 2


def test_choose_declines_on_n(radar_env, tmp_path, monkeypatch):
    src = tmp_path / "scan.json"
    src.write_text(json.dumps(scan_envelope([opp()]), ensure_ascii=False))
    result = radar.run_scan(from_file=src, scan_id="s1")
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda *a: "n")

    assert radar.choose_opportunities(result) == []


def test_choose_reprompts_on_bad_input(radar_env, tmp_path, monkeypatch):
    src = tmp_path / "scan.json"
    src.write_text(json.dumps(scan_envelope([opp()]), ensure_ascii=False))
    result = radar.run_scan(from_file=src, scan_id="s1")
    answers = iter(["99", "1"])
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda *a: next(answers))

    picks = radar.choose_opportunities(result)
    assert [p["name"] for p in picks] == ["Good Idea"]


# ---------------------------------------------------------------------------
# 8. Project id generation
# ---------------------------------------------------------------------------


def test_slugify():
    assert radar.slugify("Small Business Shift Scheduler") == "small-business-shift-scheduler"
    assert radar.slugify("  Weird!! Name??  ") == "weird-name"
    assert radar.slugify("中文名字") == ""


@pytest.mark.parametrize(
    "candidate,expected",
    [
        ("opp-good-idea", "opp-good-idea"),
        ("short", "short"),
        ("UPPER Case", "upper-case"),
        ("a", None),
        ("ab", None),
        ("", None),
        ("---", None),
    ],
)
def test_fit_project_id(candidate, expected):
    assert radar._fit_project_id(candidate) == expected


def test_project_id_uses_ascii_name_when_possible(radar_env):
    assert radar.project_id_for(opp(), "s1", 1) == "opp-good-idea"


def test_project_id_falls_back_for_chinese_name(radar_env):
    """A Chinese opportunity name cannot be slugified, so fall back to the id."""
    pid = radar.project_id_for(opp(name="中文机会名", oid="2026-10-w2-07"), "scan-x", 1)
    assert pid == "opp-2026-10-w2-07"
    import re

    assert re.match(r"^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$", pid)


def test_project_id_avoids_collisions(radar_env):
    (radar_env / "projects" / "opp-good-idea").mkdir()
    pid = radar.project_id_for(opp(), "s1", 1)
    assert pid == "opp-good-idea-2"


def test_project_id_fits_schema_pattern_for_long_names(radar_env):
    import re

    pid = radar.project_id_for(opp(name="x" * 200), "s1", 1)
    assert len(pid) <= 64
    assert re.match(r"^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$", pid)


# ---------------------------------------------------------------------------
# 9. Project creation
# ---------------------------------------------------------------------------


def make_result(radar_env, tmp_path, opportunities=None, **envelope_overrides):
    src = tmp_path / "scan.json"
    src.write_text(
        json.dumps(
            scan_envelope(opportunities or [opp()], **envelope_overrides),
            ensure_ascii=False,
        )
    )
    return radar.run_scan(from_file=src, scan_id="s1")


def test_create_project_writes_valid_state(radar_env, tmp_path):
    import jsonschema

    result = make_result(radar_env, tmp_path)
    project_dir = radar.create_project(result.ranked[0], result, index=1)

    assert project_dir.name == "opp-good-idea"
    state = json.loads((project_dir / "state.json").read_text())
    schema = json.loads((REPO_ROOT / "schemas" / "project.schema.json").read_text())
    jsonschema.Draft7Validator(schema).validate(state)

    assert state["stage"] == "discovered"
    assert state["status"] == "active"
    assert state["approved_stages"] == []
    assert "opportunity_scan" in state["artifacts"]
    assert (project_dir / state["artifacts"]["opportunity_scan"]["path"]).is_file()
    assert state["audit_log"][0]["action"] == "project_created"
    assert state["audit_log"][0]["actor"]


def test_create_project_seeds_scan_content(radar_env, tmp_path):
    result = make_result(radar_env, tmp_path)
    project_dir = radar.create_project(result.ranked[0], result, index=1)

    seeded = json.loads((project_dir / "radar" / "scan.json").read_text())
    assert seeded["opportunities"][0]["name"] == "Good Idea"
    assert seeded["selected_from_scan"] == "s1"


def test_create_project_copies_report_when_present(radar_env, tmp_path):
    report = tmp_path / "report.md"
    report.write_text("# 雷达报告\n内容")
    result = make_result(radar_env, tmp_path, report_path=str(report))

    project_dir = radar.create_project(result.ranked[0], result, index=1)

    state = json.loads((project_dir / "state.json").read_text())
    assert "radar_report" in state["artifacts"]
    assert (project_dir / "radar" / "report.md").read_text() == "# 雷达报告\n内容"


def test_create_project_skips_missing_report(radar_env, tmp_path):
    result = make_result(radar_env, tmp_path, report_path="radar-data/scans/nope.md")
    project_dir = radar.create_project(result.ranked[0], result, index=1)
    state = json.loads((project_dir / "state.json").read_text())
    assert "radar_report" not in state["artifacts"]
    assert not (project_dir / "radar" / "report.md").exists()


def test_create_project_avoids_overwriting_a_same_named_project(radar_env, tmp_path):
    """Creating twice from the same opportunity yields two distinct projects."""
    result = make_result(radar_env, tmp_path)
    first = radar.create_project(result.ranked[0], result, index=1)
    second = radar.create_project(result.ranked[0], result, index=1)

    assert first != second
    assert first.is_dir() and second.is_dir()
    assert first.name == "opp-good-idea"
    assert second.name == "opp-good-idea-2"


def test_created_project_is_pickable_by_the_orchestrator(radar_env, tmp_path, monkeypatch):
    """The whole point: an approved opportunity enters the normal pipeline."""
    import orchestrator as orch

    result = make_result(radar_env, tmp_path)
    project_dir = radar.create_project(result.ranked[0], result, index=1)
    monkeypatch.setattr(orch, "load_config", lambda *a, **k: orch.PipelineConfig(
        stages={
            orch.sm.State.RESEARCHING: orch.StageSpec(
                stage=orch.sm.State.RESEARCHING,
                agent_stage="research",
                output_dir="research",
                artifact_key="research_result",
            )
        },
        adapters={"mock": {"module": "adapters.mock_agent", "class": "MockAgent"}},
        default_target=orch.sm.State.GROWING,
        policy={},
    ))

    run = orch.run(project_dir, target=orch.sm.State.RESEARCHING, config=orch.load_config())
    assert run.reached == "researching"
    # the registered scan satisfied nothing required, but it travelled with the project
    state = orch.load_state(project_dir)
    assert "opportunity_scan" in state["artifacts"]
