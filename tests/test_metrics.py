"""Tests for real feedback data (scripts/metrics.py)."""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
for _p in (str(REPO_ROOT / "scripts"), str(REPO_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import metrics  # noqa: E402


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeResponse:
    def __init__(self, payload=None, status=200, text=None):
        self._payload = payload if payload is not None else {}
        self.status_code = status
        self.text = text if text is not None else json.dumps(self._payload)

    def json(self):
        if self.status_code >= 400:
            raise ValueError("not json")
        return self._payload


class FakeSession:
    """Dispatches on URL, so one session can serve both APIs."""

    def __init__(self, gsc=None, ga4=None, status=None):
        self.gsc = gsc if gsc is not None else {"rows": []}
        self.ga4 = ga4 if ga4 is not None else {"rows": []}
        self.status = status or {}
        self.calls: list[dict] = []

    def post(self, url, headers=None, json=None, timeout=None):
        self.calls.append({"url": url, "payload": json, "headers": headers or {}})
        if "searchAnalytics" in url:
            return FakeResponse(self.gsc, self.status.get("gsc", 200))
        return FakeResponse(self.ga4, self.status.get("ga4", 200))


class FakeTokenProvider:
    def __init__(self, token="fake-token"):
        self._token = token
        self.calls = 0

    def token(self):
        self.calls += 1
        return self._token


def gsc_row(query, clicks, impressions, ctr, position):
    """A raw Search Console API row, as returned by the API."""
    return {
        "keys": [query],
        "clicks": clicks,
        "impressions": impressions,
        "ctr": ctr,
        "position": position,
    }


def norm(query, clicks, impressions, ctr, position):
    """A normalised row, as produced by SearchConsoleClient.query()."""
    return {
        "query": query,
        "clicks": clicks,
        "impressions": impressions,
        "ctr": ctr,
        "position": position,
    }


@pytest.fixture
def project(tmp_path):
    p = tmp_path / "proj-metrics"
    p.mkdir()
    (p / "state.json").write_text(
        json.dumps(
            {
                "project_id": "proj-metrics",
                "name": "Metrics",
                "stage": "growing",
                "status": "active",
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T00:00:00Z",
                "approved_stages": [],
                "artifacts": {},
                "audit_log": [],
            }
        )
    )
    return p


# ---------------------------------------------------------------------------
# 1. Windows
# ---------------------------------------------------------------------------


def test_window_ends_before_todays_incomplete_data():
    w = metrics.window(28, today=date(2026, 10, 10))
    assert w.end == "2026-10-08"  # GSC lag
    assert w.start == "2026-09-11"
    assert w.days == 28


def test_window_offset_gives_the_previous_period():
    current = metrics.window(28, today=date(2026, 10, 10))
    previous = metrics.window(28, offset_days=28, today=date(2026, 10, 10))
    assert previous.end < current.start
    assert previous.days == current.days


def test_window_label():
    w = metrics.Window("2026-01-01", "2026-01-28", 28)
    assert w.label == "2026-01-01 → 2026-01-28"


# ---------------------------------------------------------------------------
# 2. Search Console client
# ---------------------------------------------------------------------------


def test_gsc_url_encodes_the_site_property():
    session = FakeSession()
    client = metrics.SearchConsoleClient(
        FakeTokenProvider(), "sc-domain:example.com", session=session
    )
    client.query(metrics.Window("2026-01-01", "2026-01-28", 28), dimensions=["query"])
    assert "sc-domain%3Aexample.com" in session.calls[0]["url"]


def test_gsc_payload_shape():
    session = FakeSession()
    client = metrics.SearchConsoleClient(FakeTokenProvider(), "https://x.com/", session=session)
    client.query(
        metrics.Window("2026-01-01", "2026-01-28", 28),
        dimensions=["query", "page"],
        row_limit=10,
    )
    payload = session.calls[0]["payload"]
    assert payload["startDate"] == "2026-01-01"
    assert payload["endDate"] == "2026-01-28"
    assert payload["dimensions"] == ["query", "page"]
    assert payload["rowLimit"] == 10
    assert session.calls[0]["headers"]["Authorization"] == "Bearer fake-token"


def test_gsc_normalises_rows():
    session = FakeSession(
        gsc={"rows": [gsc_row("crm", 3, 100, 0.03, 8.5)]}
    )
    client = metrics.SearchConsoleClient(FakeTokenProvider(), "https://x.com/", session=session)
    rows = client.query(metrics.Window("2026-01-01", "2026-01-28", 28), dimensions=["query"])
    assert rows == [
        {"query": "crm", "clicks": 3.0, "impressions": 100.0, "ctr": 0.03, "position": 8.5}
    ]


def test_gsc_empty_rows():
    client = metrics.SearchConsoleClient(
        FakeTokenProvider(), "https://x.com/", session=FakeSession(gsc={})
    )
    assert client.query(metrics.Window("2026-01-01", "2026-01-28", 28), dimensions=["query"]) == []


def test_gsc_requires_site_url():
    with pytest.raises(metrics.MetricsError, match="site_url"):
        metrics.SearchConsoleClient(FakeTokenProvider(), "")


@pytest.mark.parametrize(
    "status,expected",
    [
        (401, "认证被拒绝"),
        (403, "权限不足"),
        (404, "找不到资源"),
        (500, "HTTP 500"),
    ],
)
def test_http_errors_become_actionable_messages(status, expected):
    client = metrics.SearchConsoleClient(
        FakeTokenProvider(), "https://x.com/", session=FakeSession(status={"gsc": status})
    )
    with pytest.raises(metrics.MetricsError, match=expected):
        client.query(metrics.Window("2026-01-01", "2026-01-28", 28), dimensions=["query"])


def test_network_exception_is_wrapped():
    class Dead:
        def post(self, *a, **k):
            raise OSError("connection refused")

    client = metrics.SearchConsoleClient(FakeTokenProvider(), "https://x.com/", session=Dead())
    with pytest.raises(metrics.MetricsError, match="请求失败"):
        client.query(metrics.Window("2026-01-01", "2026-01-28", 28), dimensions=["query"])


# ---------------------------------------------------------------------------
# 3. GA4 client
# ---------------------------------------------------------------------------


def test_ga4_payload_shape():
    session = FakeSession()
    client = metrics.AnalyticsClient(FakeTokenProvider(), "properties/123", session=session)
    client.report(
        metrics.Window("2026-01-01", "2026-01-28", 28),
        dimensions=["sessionSourceMedium"],
        metrics=["sessions"],
    )
    payload = session.calls[0]["payload"]
    assert payload["dateRanges"] == [{"startDate": "2026-01-01", "endDate": "2026-01-28"}]
    assert payload["dimensions"] == [{"name": "sessionSourceMedium"}]
    assert payload["metrics"] == [{"name": "sessions"}]
    assert "properties/123:runReport" in session.calls[0]["url"]


def test_ga4_accepts_bare_property_id():
    client = metrics.AnalyticsClient(FakeTokenProvider(), "123456789", session=FakeSession())
    client.report(metrics.Window("2026-01-01", "2026-01-28", 28), dimensions=[], metrics=[])
    assert "properties/123456789:runReport" in client._session.calls[0]["url"]


def test_ga4_normalises_rows():
    session = FakeSession(
        ga4={
            "metricHeaders": [{"name": "sessions"}, {"name": "totalUsers"}],
            "rows": [
                {
                    "dimensionValues": [{"value": "google / organic"}],
                    "metricValues": [{"value": "120"}, {"value": "90"}],
                }
            ],
        }
    )
    client = metrics.AnalyticsClient(FakeTokenProvider(), "properties/1", session=session)
    rows = client.report(
        metrics.Window("2026-01-01", "2026-01-28", 28),
        dimensions=["sessionSourceMedium"],
        metrics=["sessions", "totalUsers"],
    )
    assert rows == [
        {"sessionSourceMedium": "google / organic", "sessions": 120.0, "totalUsers": 90.0}
    ]


def test_ga4_requires_property_id():
    with pytest.raises(metrics.MetricsError, match="property_id"):
        metrics.AnalyticsClient(FakeTokenProvider(), "")


# ---------------------------------------------------------------------------
# 4. Search Console summary
# ---------------------------------------------------------------------------


def test_totals_are_impression_weighted():
    rows = [
        {"query": "a", "clicks": 10, "impressions": 100, "ctr": 0.1, "position": 1.0},
        {"query": "b", "clicks": 0, "impressions": 900, "ctr": 0.0, "position": 20.0},
    ]
    totals = metrics.summarize_search_console(rows)["totals"]
    assert totals["clicks"] == 10
    assert totals["impressions"] == 1000
    assert totals["ctr"] == 0.01
    # a plain average would be 10.5; weighting must pull it toward the big row
    assert totals["position"] == 18.1


def test_totals_handle_no_impressions():
    totals = metrics.summarize_search_console([])["totals"]
    assert totals == {"clicks": 0, "impressions": 0, "ctr": 0.0, "position": 0.0}


def test_delta_vs_previous_period():
    rows = [norm("a", 20, 100, 0.2, 1)]
    previous = [norm("a", 10, 100, 0.1, 1)]
    summary = metrics.summarize_search_console(rows, previous)
    assert summary["delta"]["clicks"] == 1.0
    assert summary["delta"]["impressions"] == 0.0
    assert summary["previous_totals"]["clicks"] == 10


def test_delta_is_none_without_previous_data():
    summary = metrics.summarize_search_console([norm("a", 5, 50, 0.1, 2)], [])
    assert summary["delta"]["clicks"] is None


def test_top_queries_and_pages():
    rows = [
        norm("low", 1, 100, 0.01, 9),
        norm("high", 50, 200, 0.25, 2),
    ]
    summary = metrics.summarize_search_console(rows)
    assert summary["top_queries"][0]["query"] == "high"


# ---------------------------------------------------------------------------
# 5. Opportunities
# ---------------------------------------------------------------------------


def test_striking_distance_beats_low_ctr():
    """Ranking lifts both impressions and clicks, so it is the primary action."""
    rows = [norm("page two", 3, 200, 0.015, 12.5)]
    opps = metrics.find_opportunities(rows)
    assert len(opps) == 1
    assert opps[0]["type"] == "striking_distance"
    assert "also" in opps[0]


def test_low_ctr_when_ranking_is_already_good():
    rows = [norm("visible but ignored", 0, 300, 0.0, 4.0)]
    opps = metrics.find_opportunities(rows)
    assert opps[0]["type"] == "low_ctr"
    assert "also" not in opps[0]


def test_healthy_query_is_not_flagged():
    assert metrics.find_opportunities([norm("great", 40, 500, 0.08, 3.2)]) == []


def test_low_impressions_are_not_flagged():
    assert metrics.find_opportunities([norm("tiny", 0, 5, 0.0, 3.0)]) == []


def test_opportunities_sorted_by_impressions_and_capped():
    rows = [norm(f"q{i}", 0, i * 10, 0.0, 5.0) for i in range(1, 30)]
    opps = metrics.find_opportunities(rows)
    assert len(opps) == metrics.TOP_N
    assert opps[0]["impressions"] > opps[-1]["impressions"]


def test_opportunities_skip_rows_without_a_query():
    assert metrics.find_opportunities([{"clicks": 1, "impressions": 900, "ctr": 0.0}]) == []


# ---------------------------------------------------------------------------
# 6. Analytics summary
# ---------------------------------------------------------------------------


def test_analytics_totals_and_ranking():
    rows = [
        {"sessionSourceMedium": "google / organic", "sessions": 120, "totalUsers": 90},
        {"sessionSourceMedium": "direct / none", "sessions": 30, "totalUsers": 25},
    ]
    summary = metrics.summarize_analytics(rows)
    assert summary["totals"]["sessions"] == 150
    assert summary["totals"]["totalUsers"] == 115
    assert summary["top_sources"][0]["sessionSourceMedium"] == "google / organic"
    assert summary["row_count"] == 2


def test_analytics_totals_only_include_present_metrics():
    summary = metrics.summarize_analytics([{"sessions": 10}])
    assert summary["totals"] == {"sessions": 10}


# ---------------------------------------------------------------------------
# 7. Token provider
# ---------------------------------------------------------------------------


def test_token_provider_missing_key_file():
    provider = metrics.ServiceAccountTokenProvider("/nope/sa.json", [metrics.GSC_SCOPE])
    with pytest.raises(metrics.MetricsError, match="不存在"):
        provider.token()


def test_token_provider_explains_missing_dependency(tmp_path, monkeypatch):
    key = tmp_path / "sa.json"
    key.write_text("{}")
    # A None entry in sys.modules makes `import` raise ImportError.
    monkeypatch.setitem(sys.modules, "google.oauth2", None)
    provider = metrics.ServiceAccountTokenProvider(key, [metrics.GSC_SCOPE])
    with pytest.raises(metrics.MetricsError, match="google-auth"):
        provider.token()


def test_token_provider_caches_until_expiry(monkeypatch):
    """A run that queries both APIs should authenticate once, not twice."""
    provider = metrics.ServiceAccountTokenProvider("ignored.json", [metrics.GSC_SCOPE])
    loads = {"n": 0}

    class FakeCreds:
        token = "tok-1"
        expiry = None

    def fake_load():
        loads["n"] += 1
        return FakeCreds()

    monkeypatch.setattr(provider, "_load", fake_load)
    monkeypatch.setattr(provider, "_refresh", lambda credentials: None)

    assert provider.token() == "tok-1"
    assert provider.token() == "tok-1"
    assert loads["n"] == 1


def test_token_provider_refresh_failure_is_explained(monkeypatch):
    provider = metrics.ServiceAccountTokenProvider("ignored.json", [metrics.GSC_SCOPE])

    class FakeCreds:
        token = None
        expiry = None

    monkeypatch.setattr(provider, "_load", lambda: FakeCreds())
    with pytest.raises(metrics.MetricsError, match="获取 Google 访问令牌失败"):
        provider.token()


# ---------------------------------------------------------------------------
# 8. Credentials + config
# ---------------------------------------------------------------------------


@pytest.fixture
def env_file(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    monkeypatch.setattr(metrics, "ENV_FILE", path)
    import deploy

    monkeypatch.setattr(deploy, "ENV_FILE", path)
    return path


def test_key_file_path_from_environment(env_file, monkeypatch):
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "/tmp/a.json")
    assert metrics.key_file_path() == Path("/tmp/a.json")


def test_key_file_path_from_env_file(env_file):
    env_file.write_text("GOOGLE_APPLICATION_CREDENTIALS=/tmp/b.json\n")
    assert metrics.key_file_path() == Path("/tmp/b.json")


def test_key_file_path_absent(env_file):
    assert metrics.key_file_path() is None


def test_ensure_key_file_prompts_and_saves(env_file, tmp_path, monkeypatch):
    key = tmp_path / "sa.json"
    key.write_text("{}")
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda *a: str(key))

    result = metrics.ensure_key_file()

    assert result == key
    assert "GOOGLE_APPLICATION_CREDENTIALS=" in env_file.read_text()


def test_ensure_key_file_reprompts_on_bad_path(env_file, tmp_path, monkeypatch):
    key = tmp_path / "sa.json"
    key.write_text("{}")
    answers = iter(["/does/not/exist", str(key)])
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda *a: next(answers))

    assert metrics.ensure_key_file() == key


def test_ensure_key_file_non_interactive_explains_what_to_do(env_file, monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    with pytest.raises(metrics.MetricsError) as excinfo:
        metrics.ensure_key_file()
    message = str(excinfo.value)
    assert "GOOGLE_APPLICATION_CREDENTIALS" in message
    assert ".env" in message


def test_merged_sources_lets_project_override_globals(project, monkeypatch):
    monkeypatch.setattr(
        metrics,
        "global_source_config",
        lambda: {"search_console": {"enabled": True, "site_url": None, "lookback_days": 28}},
    )
    metrics.save_project_source_config(project, {"search_console": {"site_url": "sc-domain:x.com"}})

    merged = metrics.merged_sources(project)
    assert merged["search_console"]["site_url"] == "sc-domain:x.com"
    assert merged["search_console"]["enabled"] is True
    assert merged["analytics"]["enabled"] is False


def test_save_project_source_config_merges(project):
    metrics.save_project_source_config(project, {"search_console": {"site_url": "a"}})
    metrics.save_project_source_config(project, {"analytics": {"property_id": "b"}})
    cfg = metrics.project_source_config(project)
    assert cfg["search_console"]["site_url"] == "a"
    assert cfg["analytics"]["property_id"] == "b"


# ---------------------------------------------------------------------------
# 9. collect()
# ---------------------------------------------------------------------------


def enable_both(monkeypatch):
    monkeypatch.setattr(
        metrics,
        "global_source_config",
        lambda: {
            "search_console": {
                "enabled": True,
                "site_url": "sc-domain:example.com",
                "lookback_days": 28,
            },
            "analytics": {"enabled": True, "property_id": "properties/1", "lookback_days": 28},
        },
    )
    monkeypatch.setattr(metrics, "ensure_key_file", lambda **kw: Path("/fake/sa.json"))


def test_collect_reports_disabled_sources(project, monkeypatch):
    monkeypatch.setattr(metrics, "global_source_config", lambda: {})
    report = metrics.collect(project, interactive=False)

    assert report["mode"] == "unavailable"
    assert report["is_real_data"] is False
    assert report["sources"]["search_console"]["status"] == "disabled"
    assert report["sources"]["analytics"]["status"] == "disabled"
    # disabled is not a failure
    assert report["unavailable"] == []


def test_collect_reports_missing_credentials(project, monkeypatch):
    enable_both(monkeypatch)

    def missing(**kwargs):
        raise metrics.MetricsError("缺少 Google 服务账号密钥")

    monkeypatch.setattr(metrics, "ensure_key_file", missing)
    report = metrics.collect(project, interactive=False)

    assert report["mode"] == "unavailable"
    assert len(report["unavailable"]) == 2
    assert "服务账号" in report["unavailable"][0]


def test_collect_live_data_from_both_sources(project, monkeypatch):
    enable_both(monkeypatch)
    session = FakeSession(
        gsc={
            "rows": [
                gsc_row("cheap crm", 8, 900, 0.0089, 13.1),
                gsc_row("shift scheduler", 40, 500, 0.08, 3.2),
            ]
        },
        ga4={
            "metricHeaders": [{"name": "sessions"}, {"name": "totalUsers"}],
            "rows": [
                {
                    "dimensionValues": [{"value": "google / organic"}, {"value": "/"}],
                    "metricValues": [{"value": "120"}, {"value": "90"}],
                }
            ],
        },
    )

    report = metrics.collect(
        project,
        interactive=False,
        session=session,
        token_provider=FakeTokenProvider(),
        today=date(2026, 10, 10),
    )

    assert report["mode"] == "live"
    assert report["is_real_data"] is True
    gsc = report["sources"]["search_console"]
    assert gsc["status"] == "ok"
    assert gsc["totals"]["clicks"] == 48
    assert gsc["site_url"] == "sc-domain:example.com"
    assert gsc["window"].endswith("2026-10-08")
    assert gsc["opportunities"][0]["query"] == "cheap crm"

    ga4 = report["sources"]["analytics"]
    assert ga4["status"] == "ok"
    assert ga4["totals"]["sessions"] == 120


def test_collect_keeps_the_other_source_when_one_fails(project, monkeypatch):
    enable_both(monkeypatch)
    session = FakeSession(
        gsc={"rows": [gsc_row("ok", 5, 100, 0.05, 4)]},
        status={"ga4": 403},
    )

    report = metrics.collect(
        project,
        interactive=False,
        session=session,
        token_provider=FakeTokenProvider(),
        today=date(2026, 10, 10),
    )

    assert report["sources"]["search_console"]["status"] == "ok"
    assert report["sources"]["analytics"]["status"] == "unavailable"
    assert "权限不足" in report["sources"]["analytics"]["reason"]
    # one live source is enough to call the run real
    assert report["is_real_data"] is True


def test_collect_prompts_and_persists_site_url(project, monkeypatch):
    """Asking every run would be unusable, so the answer must be saved."""
    monkeypatch.setattr(
        metrics,
        "global_source_config",
        lambda: {"search_console": {"enabled": True, "site_url": None, "lookback_days": 28}},
    )
    monkeypatch.setattr(metrics, "ensure_key_file", lambda **kw: Path("/fake/sa.json"))
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda *a: "sc-domain:typed.com")

    report = metrics.collect(
        project,
        interactive=True,
        session=FakeSession(gsc={"rows": []}),
        token_provider=FakeTokenProvider(),
        today=date(2026, 10, 10),
    )

    assert report["sources"]["search_console"]["site_url"] == "sc-domain:typed.com"
    assert metrics.project_source_config(project)["search_console"]["site_url"] == "sc-domain:typed.com"


# ---------------------------------------------------------------------------
# 10. Storage and reporting
# ---------------------------------------------------------------------------


def test_record_metrics_registers_artifact_and_audit(project):
    report = {"mode": "live", "is_real_data": True, "unavailable": []}
    state = json.loads((project / "state.json").read_text())

    latest = metrics.record_metrics(project, state, report)

    assert latest.is_file()
    assert latest.name == "latest-metrics.json"
    assert state["artifacts"]["metrics"]["path"] == "metrics/latest-metrics.json"
    assert state["artifacts"]["metrics"]["is_real_data"] is True
    assert state["audit_log"][-1]["action"] == "metrics_collected"


def test_record_metrics_writes_a_timestamped_copy(project):
    state = {"artifacts": {}, "audit_log": []}
    metrics.record_metrics(project, state, {"mode": "live", "is_real_data": True})
    stamped = [
        p for p in metrics.metrics_dir(project).glob("*-metrics.json")
        if not p.name.startswith("latest-")
    ]
    assert len(stamped) == 1


def test_metrics_become_visible_to_the_growth_prompt(project):
    """The loop closing: the registered metrics are inlined into the brief."""
    from adapters.skill_agent import build_prompt, load_skill_map
    from adapters.adapter_interface import StageRequest

    state = json.loads((project / "state.json").read_text())
    metrics.record_metrics(
        project,
        state,
        {
            "mode": "live",
            "is_real_data": True,
            "sources": {"search_console": {"status": "ok", "totals": {"clicks": 48}}},
        },
    )
    (project / "state.json").write_text(json.dumps(state))

    request = StageRequest(
        project_id="proj-metrics",
        stage="growth",
        task_description="分析增长",
        allowed_read_paths=[str(project)],
        expected_output_schema="schemas/stage-result.schema.json",
    )
    prompt = build_prompt(
        request,
        project,
        load_skill_map().get("growth", []),
        json.loads((REPO_ROOT / "schemas" / "stage-result.schema.json").read_text()),
    )

    assert "metrics" in prompt
    assert '"clicks": 48' in prompt or "clicks" in prompt


def test_describe_report_shows_status_and_opportunities():
    report = {
        "mode": "live",
        "is_real_data": True,
        "fetched_at": "2026-10-10T00:00:00Z",
        "lookback_days": 28,
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
                    }
                ],
            },
            "analytics": {"status": "disabled", "reason": "未启用"},
        },
        "unavailable": [],
    }
    text = metrics.describe_report(report)
    assert "✅ search_console" in text
    assert "⏸ analytics" in text
    assert "+20.0%" in text
    assert "cheap crm" in text


def test_describe_report_lists_unavailable():
    text = metrics.describe_report(
        {
            "mode": "unavailable",
            "is_real_data": False,
            "sources": {"search_console": {"status": "unavailable", "reason": "403 权限不足"}},
            "unavailable": ["search_console: 403 权限不足"],
        }
    )
    assert "❌ search_console" in text
    assert "不可用" in text


def test_describe_config_reports_what_is_missing(project, monkeypatch):
    monkeypatch.setattr(
        metrics,
        "global_source_config",
        lambda: {"search_console": {"enabled": True, "site_url": None, "provider": "gsc"}},
    )
    monkeypatch.setattr(metrics, "key_file_path", lambda: None)

    text = metrics.describe_config(project)

    assert "未配置" in text
    assert "GOOGLE_APPLICATION_CREDENTIALS" in text
    assert "search_console.site_url" in text
