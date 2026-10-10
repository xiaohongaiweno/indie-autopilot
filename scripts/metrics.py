#!/usr/bin/env python3
"""Real feedback data: Google Search Console and Google Analytics 4.

This closes the loop. Everything upstream of `growing` produces guesses; this is
the only place the pipeline reads what actually happened -- what people searched
for, what they clicked, and whether they converted.

Design notes
------------
* **Read-only, and only two sources.** GSC answers "what did Google show us and
  did anyone click" (the click-through rate the workflow cares about); GA4
  answers "what happened after they arrived".
* **Service-account auth.** Both APIs grant read access to a service-account
  email, which needs no browser flow and no expiring refresh token -- the right
  trade-off for something that runs unattended.
* **Everything is injectable.** Network access goes through a ``session``
  object and tokens through a ``token_provider``, so the whole client is
  testable without credentials, without ``google-auth``, and without network.
* **Opportunities are computed here, not guessed by a model.** "Seen a lot but
  rarely clicked" and "ranking just off page one" are arithmetic, and they are
  the two SEO levers that actually move traffic.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import quote

_HERE = Path(__file__).resolve().parent
REPO_ROOT = _HERE.parent
for _p in (str(_HERE), str(REPO_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

logger = logging.getLogger(__name__)

SOURCES_CONFIG = REPO_ROOT / "config" / "sources.yml"
ENV_FILE = REPO_ROOT / ".env"

GSC_SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"
GA4_SCOPE = "https://www.googleapis.com/auth/analytics.readonly"

GSC_ENDPOINT = (
    "https://searchconsole.googleapis.com/webmasters/v3/sites/{site}/searchAnalytics/query"
)
GA4_ENDPOINT = "https://analyticsdata.googleapis.com/v1beta/properties/{prop}:runReport"

DEFAULT_LOOKBACK_DAYS = 28

#: GSC data lags; asking for "today" usually returns a partial, confusing day.
GSC_LAG_DAYS = 2

#: Thresholds for the two SEO opportunities we compute.
LOW_CTR_MIN_IMPRESSIONS = 50
LOW_CTR_MAX_CTR = 0.02
STRIKING_DISTANCE_MIN_POSITION = 11
STRIKING_DISTANCE_MAX_POSITION = 20
STRIKING_DISTANCE_MIN_IMPRESSIONS = 30

TOP_N = 15


class MetricsError(Exception):
    """Raised for any user-facing metrics failure."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        import yaml

        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not read %s: %s", path, exc)
        return {}


def project_source_config(project_dir: Path | str) -> dict[str, Any]:
    """Per-project overrides, because site/property are per-product."""
    return _load_yaml(Path(project_dir) / "metrics.yml")


def global_source_config() -> dict[str, Any]:
    return (_load_yaml(SOURCES_CONFIG).get("sources") or {})


def merged_sources(project_dir: Path | str) -> dict[str, dict[str, Any]]:
    """Global connection settings merged with per-project selection.

    ``config/sources.yml`` says *how* to connect (provider, credential env,
    lookback). ``projects/<id>/metrics.yml`` says *which* site/property, since
    that differs per product.
    """
    project = project_source_config(project_dir)
    sources: dict[str, dict[str, Any]] = {}
    for name in ("search_console", "analytics"):
        base = dict(global_source_config().get(name) or {})
        base.update(project.get(name) or {})
        base.setdefault("enabled", False)
        base.setdefault("lookback_days", DEFAULT_LOOKBACK_DAYS)
        sources[name] = base
    return sources


def save_project_source_config(project_dir: Path | str, updates: dict[str, Any]) -> Path:
    """Merge *updates* into ``projects/<id>/metrics.yml``."""
    import yaml

    path = Path(project_dir) / "metrics.yml"
    existing = project_source_config(project_dir)
    for key, value in updates.items():
        existing.setdefault(key, {})
        existing[key].update(value)
    path.write_text(
        yaml.safe_dump(existing, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    return path


# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------


class TokenProvider(Protocol):
    """Anything that can produce a bearer token."""

    def token(self) -> str:  # pragma: no cover - protocol
        ...


class ServiceAccountTokenProvider:
    """Access tokens from a Google service-account JSON key.

    Caches the token until shortly before it expires, so a run that queries both
    APIs authenticates once.
    """

    def __init__(self, key_file: Path | str, scopes: list[str]) -> None:
        self.key_file = Path(key_file)
        self.scopes = scopes
        self._credentials: Any = None
        self._expires_at: float = 0.0
        self._token: str | None = None

    def _load(self) -> Any:
        if self._credentials is not None:
            return self._credentials
        if not self.key_file.is_file():
            raise MetricsError(f"服务账号密钥文件不存在：{self.key_file}")
        try:
            from google.oauth2 import service_account
        except ImportError as exc:
            raise MetricsError(
                "缺少 google-auth 依赖，无法读取服务账号密钥。\n"
                "  安装：pip install -r requirements.txt   （或 pip install google-auth）"
            ) from exc
        try:
            self._credentials = service_account.Credentials.from_service_account_file(
                str(self.key_file), scopes=self.scopes
            )
        except ValueError as exc:
            raise MetricsError(
                f"无法解析服务账号密钥 {self.key_file}：{exc}"
            ) from exc
        return self._credentials

    def _refresh(self, credentials: Any) -> None:
        """Exchange the service-account key for an access token.

        Isolated so tests can exercise token caching without google-auth
        installed (and without network).
        """
        import google.auth.transport.requests as google_requests

        credentials.refresh(google_requests.Request())

    def token(self) -> str:
        now = time.time()
        if self._token and now < self._expires_at - 60:
            return self._token
        credentials = self._load()
        try:
            self._refresh(credentials)
        except MetricsError:
            raise
        except Exception as exc:  # noqa: BLE001 - network/auth failures vary
            raise MetricsError(f"获取 Google 访问令牌失败：{exc}") from exc
        self._token = credentials.token
        expiry = getattr(credentials, "expiry", None)
        self._expires_at = (
            expiry.replace(tzinfo=timezone.utc).timestamp()
            if expiry is not None
            else now + 3000
        )
        return self._token

    @property
    def service_account_email(self) -> str | None:
        try:
            return self._load().service_account_email
        except MetricsError:
            return None


def key_file_path(env_path: Path | None = None) -> Path | None:
    """Where the service-account key is, from env or ``.env``."""
    from deploy import load_env_file

    value = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") or load_env_file(
        env_path or ENV_FILE
    ).get("GOOGLE_APPLICATION_CREDENTIALS")
    return Path(value).expanduser() if value else None


def ensure_key_file(*, interactive: bool = True, env_path: Path | None = None) -> Path:
    """Return the key file path, asking for it once if it is not configured.

    Points the human at the exact Google Cloud steps, because "make a service
    account" is the part that actually stops people.
    """
    from deploy import load_env_file, save_env_values

    existing = key_file_path(env_path)
    if existing and existing.is_file():
        return existing

    if not interactive or not sys.stdin.isatty():
        raise MetricsError(
            "缺少 Google 服务账号密钥。\n"
            "  把密钥 JSON 的路径写入 .env（已 gitignore）：\n"
            "    GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json\n"
            "  或在交互式终端运行本命令，会提示你输入。"
        )

    print("\n读取 Search Console / Analytics 需要一个 Google 服务账号密钥。")
    print("一次性设置：")
    print("  1. https://console.cloud.google.com → 新建/选择项目")
    print("  2. 启用两个 API：Search Console API、Google Analytics Data API")
    print("  3. IAM & Admin → Service Accounts → Create，创建后 Keys → Add key → JSON")
    print("  4. 把下载到的 JSON 路径填到下面")
    print("  5. 之后在 Search Console 里把这个服务账号邮箱加为「完全」用户，")
    print("     在 GA4 里把它加为「查看者」（否则会返回 403）\n")

    while True:
        try:
            raw = input("service-account.json 路径 > ").strip()
        except (EOFError, KeyboardInterrupt) as exc:
            raise MetricsError("已取消，未读取任何数据。") from exc
        if not raw:
            print("  路径不能为空。")
            continue
        path = Path(raw).expanduser()
        if not path.is_file():
            print(f"  找不到文件：{path}")
            continue
        save_env_values({"GOOGLE_APPLICATION_CREDENTIALS": str(path)}, env_path)
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(path)
        print(f"\n✅ 已保存到 {env_path or ENV_FILE}\n")
        return path


# ---------------------------------------------------------------------------
# Dates
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Window:
    start: str
    end: str
    days: int

    @property
    def label(self) -> str:
        return f"{self.start} → {self.end}"


def window(days: int, *, offset_days: int = 0, today: date | None = None) -> Window:
    """A GSC-safe window; the most recent day or two of data is incomplete."""
    today = today or datetime.now(timezone.utc).date()
    end = today - timedelta(days=GSC_LAG_DAYS + offset_days)
    start = end - timedelta(days=days - 1)
    return Window(start=start.isoformat(), end=end.isoformat(), days=days)


# ---------------------------------------------------------------------------
# HTTP plumbing
# ---------------------------------------------------------------------------


def _post_json(
    session: Any,
    url: str,
    token: str,
    payload: dict[str, Any],
    *,
    timeout: int = 60,
) -> dict[str, Any]:
    """POST JSON with a bearer token, turning HTTP errors into clear messages."""
    try:
        response = session.post(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=timeout,
        )
    except Exception as exc:  # noqa: BLE001 - requests raises many types
        raise MetricsError(f"请求失败：{exc}") from exc

    status = getattr(response, "status_code", 200)
    text = getattr(response, "text", "")
    if status == 401:
        raise MetricsError("认证被拒绝（401）：服务账号密钥无效或已撤销。")
    if status == 403:
        raise MetricsError(
            "权限不足（403）：请把服务账号邮箱加到对应属性上——"
            "Search Console 需要「完全」权限，GA4 需要「查看者」。"
        )
    if status == 404:
        raise MetricsError(
            f"找不到资源（404）：站点或属性 ID 可能不对。\n  请求：{url}"
        )
    if status >= 400:
        raise MetricsError(f"HTTP {status}：{text[:400]}")

    try:
        return response.json()
    except Exception as exc:  # noqa: BLE001
        raise MetricsError(f"响应不是合法 JSON：{text[:200]}") from exc


# ---------------------------------------------------------------------------
# Search Console
# ---------------------------------------------------------------------------


class SearchConsoleClient:
    """Search Console search-analytics queries."""

    def __init__(self, token_provider: TokenProvider, site_url: str, session: Any = None):
        if not site_url:
            raise MetricsError("未配置 search_console.site_url")
        self.token_provider = token_provider
        self.site_url = site_url
        self._session = session

    @property
    def session(self) -> Any:
        if self._session is None:
            import requests

            self._session = requests.Session()
        return self._session

    def query(
        self,
        window_: Window,
        *,
        dimensions: list[str],
        row_limit: int = 100,
    ) -> list[dict[str, Any]]:
        url = GSC_ENDPOINT.format(site=quote(self.site_url, safe=""))
        payload = {
            "startDate": window_.start,
            "endDate": window_.end,
            "dimensions": dimensions,
            "rowLimit": row_limit,
            "type": "web",
        }
        data = _post_json(self.session, url, self.token_provider.token(), payload)
        return [_normalise_gsc_row(row, dimensions) for row in data.get("rows") or []]


def _normalise_gsc_row(row: dict[str, Any], dimensions: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, value in zip(dimensions, row.get("keys") or []):
        out[name] = value
    out["clicks"] = float(row.get("clicks") or 0)
    out["impressions"] = float(row.get("impressions") or 0)
    out["ctr"] = float(row.get("ctr") or 0)
    out["position"] = float(row.get("position") or 0)
    return out


def summarize_search_console(
    rows: list[dict[str, Any]],
    previous_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Totals, period-over-period delta, top movers, and computed opportunities."""
    totals = _gsc_totals(rows)
    summary: dict[str, Any] = {
        "totals": totals,
        "top_queries": _top_by(rows, "query", "clicks", TOP_N),
        "top_pages": _top_by(rows, "page", "clicks", TOP_N),
        "opportunities": find_opportunities(rows),
        "row_count": len(rows),
    }
    if previous_rows is not None:
        previous = _gsc_totals(previous_rows)
        summary["previous_totals"] = previous
        summary["delta"] = {
            "clicks": _relative_delta(totals["clicks"], previous["clicks"]),
            "impressions": _relative_delta(
                totals["impressions"], previous["impressions"]
            ),
            "ctr": _relative_delta(totals["ctr"], previous["ctr"]),
        }
    return summary


def _gsc_totals(rows: list[dict[str, Any]]) -> dict[str, Any]:
    clicks = sum(r.get("clicks", 0) for r in rows)
    impressions = sum(r.get("impressions", 0) for r in rows)
    # CTR and position must be impression-weighted, not averaged across rows.
    weighted_position = sum(
        r.get("position", 0) * r.get("impressions", 0) for r in rows
    )
    return {
        "clicks": round(clicks, 1),
        "impressions": round(impressions, 1),
        "ctr": round(clicks / impressions, 4) if impressions else 0.0,
        "position": round(weighted_position / impressions, 2) if impressions else 0.0,
    }


def _top_by(
    rows: list[dict[str, Any]], dimension: str, metric: str, limit: int
) -> list[dict[str, Any]]:
    usable = [r for r in rows if r.get(dimension)]
    ordered = sorted(usable, key=lambda r: r.get(metric, 0), reverse=True)[:limit]
    return [
        {
            dimension: r.get(dimension),
            "clicks": round(r.get("clicks", 0), 1),
            "impressions": round(r.get("impressions", 0), 1),
            "ctr": round(r.get("ctr", 0), 4),
            "position": round(r.get("position", 0), 1),
        }
        for r in ordered
    ]


def find_opportunities(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deterministic SEO actions, not model guesses.

    * ``striking_distance``: ranking 11-20, so a small push reaches page one.
      This is checked first because ranking lifts impressions *and* clicks.
    * ``low_ctr``: plenty of impressions, almost no clicks -- the title and meta
      description are the lever.

    A row can warrant both; the higher-leverage one becomes the action and the
    other is recorded under ``also`` rather than emitted as a duplicate.
    """
    out: list[dict[str, Any]] = []
    for row in rows:
        query = row.get("query")
        if not query:
            continue
        impressions = row.get("impressions", 0)
        clicks = row.get("clicks", 0)
        ctr = row.get("ctr", 0)
        position = row.get("position", 0)
        base = {
            "query": query,
            "impressions": round(impressions, 1),
            "clicks": round(clicks, 1),
            "ctr": round(ctr, 4),
            "position": round(position, 1),
        }
        poor_ctr = impressions >= LOW_CTR_MIN_IMPRESSIONS and ctr < LOW_CTR_MAX_CTR
        near_page_one = (
            STRIKING_DISTANCE_MIN_POSITION
            <= position
            <= STRIKING_DISTANCE_MAX_POSITION
            and impressions >= STRIKING_DISTANCE_MIN_IMPRESSIONS
        )

        if near_page_one:
            entry = {
                **base,
                "type": "striking_distance",
                "action": "补内容深度与内链，把排名从第二页推进第一页",
            }
            if poor_ctr:
                entry["also"] = "点击率同样偏低，标题与 meta 也值得改写"
            out.append(entry)
        elif poor_ctr:
            out.append(
                {
                    **base,
                    "type": "low_ctr",
                    "action": "改写标题与 meta description，让搜索结果更值得点",
                }
            )
    # Biggest impression pools first: that is where the upside is.
    return sorted(out, key=lambda o: o["impressions"], reverse=True)[:TOP_N]


def _relative_delta(current: float, previous: float) -> float | None:
    if not previous:
        return None
    return round((current - previous) / previous, 4)


# ---------------------------------------------------------------------------
# Analytics (GA4)
# ---------------------------------------------------------------------------


class AnalyticsClient:
    """GA4 Data API reports."""

    def __init__(
        self, token_provider: TokenProvider, property_id: str, session: Any = None
    ):
        if not property_id:
            raise MetricsError("未配置 analytics.property_id")
        self.token_provider = token_provider
        self.property_id = str(property_id).replace("properties/", "")
        self._session = session

    @property
    def session(self) -> Any:
        if self._session is None:
            import requests

            self._session = requests.Session()
        return self._session

    def report(
        self,
        window_: Window,
        *,
        dimensions: list[str],
        metrics: list[str],
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        url = GA4_ENDPOINT.format(prop=quote(self.property_id, safe=""))
        payload = {
            "dateRanges": [{"startDate": window_.start, "endDate": window_.end}],
            "dimensions": [{"name": d} for d in dimensions],
            "metrics": [{"name": m} for m in metrics],
            "limit": limit,
        }
        data = _post_json(self.session, url, self.token_provider.token(), payload)
        headers = [h.get("name") for h in data.get("metricHeaders") or []]
        rows: list[dict[str, Any]] = []
        for raw in data.get("rows") or []:
            row: dict[str, Any] = {}
            for name, value in zip(
                dimensions, [d.get("value") for d in raw.get("dimensionValues") or []]
            ):
                row[name] = value
            for name, value in zip(
                headers or metrics,
                [m.get("value") for m in raw.get("metricValues") or []],
            ):
                try:
                    row[name] = float(value)
                except (TypeError, ValueError):
                    row[name] = value
            rows.append(row)
        return rows


def summarize_analytics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    totals: dict[str, Any] = {}
    for key in ("sessions", "totalUsers", "conversions"):
        if any(key in r for r in rows):
            totals[key] = round(sum(r.get(key, 0) or 0 for r in rows), 1)
    return {
        "totals": totals,
        "top_sources": _rank(rows, "sessionSourceMedium", "sessions"),
        "top_landing_pages": _rank(rows, "landingPagePlusQueryString", "sessions"),
        "row_count": len(rows),
    }


def _rank(rows: list[dict[str, Any]], dimension: str, metric: str, limit: int = TOP_N):
    usable = [r for r in rows if r.get(dimension)]
    ordered = sorted(usable, key=lambda r: r.get(metric, 0) or 0, reverse=True)[:limit]
    return [
        {
            dimension: r.get(dimension),
            metric: round(r.get(metric, 0) or 0, 1),
        }
        for r in ordered
    ]


# ---------------------------------------------------------------------------
# Report building
# ---------------------------------------------------------------------------


@dataclass
class SourceOutcome:
    name: str
    status: str  # "ok" | "unavailable" | "disabled"
    summary: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


def _provider_for(key_file: Path, scopes: list[str]) -> TokenProvider:
    return ServiceAccountTokenProvider(key_file, scopes)


def collect(
    project_dir: Path | str,
    *,
    days: int | None = None,
    interactive: bool = True,
    session: Any = None,
    token_provider: TokenProvider | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    """Fetch every enabled source. Never raises for one source failing."""
    project_dir = Path(project_dir)
    sources = merged_sources(project_dir)
    outcomes: list[SourceOutcome] = []

    enabled = [name for name, cfg in sources.items() if cfg.get("enabled")]
    key_file: Path | None = None
    if enabled:
        try:
            key_file = ensure_key_file(interactive=interactive)
        except MetricsError as exc:
            # No credentials: report every enabled source as unavailable rather
            # than failing the whole command.
            for name in enabled:
                outcomes.append(SourceOutcome(name, "unavailable", error=str(exc)))
            return _assemble(project_dir, sources, outcomes, days)

    for name in ("search_console", "analytics"):
        cfg = sources[name]
        if not cfg.get("enabled"):
            outcomes.append(
                SourceOutcome(
                    name,
                    "disabled",
                    error="未启用（config/sources.yml 里 enabled: false）",
                )
            )
            continue

        lookback = days or int(cfg.get("lookback_days") or DEFAULT_LOOKBACK_DAYS)
        current = window(lookback, today=today)
        previous = window(lookback, offset_days=lookback, today=today)
        try:
            if name == "search_console":
                outcomes.append(
                    _collect_gsc(
                        cfg, current, previous, project_dir, key_file,
                        interactive, session, token_provider,
                    )
                )
            else:
                outcomes.append(
                    _collect_ga4(
                        cfg, current, lookback, project_dir, key_file,
                        interactive, session, token_provider,
                    )
                )
        except MetricsError as exc:
            outcomes.append(SourceOutcome(name, "unavailable", error=str(exc)))
        except Exception as exc:  # noqa: BLE001 - never lose the other source
            outcomes.append(
                SourceOutcome(name, "unavailable", error=f"未预期的错误：{exc}")
            )

    return _assemble(project_dir, sources, outcomes, days)


def _collect_gsc(
    cfg, current, previous, project_dir, key_file, interactive, session, token_provider
) -> SourceOutcome:
    site_url = _prompt_and_save(
        cfg.get("site_url"),
        project_dir=project_dir,
        section="search_console",
        key="site_url",
        hint='例如 "sc-domain:example.com"（域名属性）或 "https://example.com/"（网址前缀属性）',
        interactive=interactive,
    )
    provider = token_provider or _provider_for(key_file, [GSC_SCOPE])
    client = SearchConsoleClient(provider, site_url, session=session)

    rows = client.query(current, dimensions=["query"], row_limit=500)
    previous_rows = client.query(previous, dimensions=["query"], row_limit=500)
    pages = client.query(current, dimensions=["page"], row_limit=100)

    summary = summarize_search_console(rows, previous_rows)
    summary["top_pages"] = _top_by(pages, "page", "clicks", TOP_N)
    summary["site_url"] = site_url
    summary["window"] = current.label
    return SourceOutcome("search_console", "ok", summary)


def _collect_ga4(
    cfg, current, lookback, project_dir, key_file, interactive, session, token_provider
) -> SourceOutcome:
    property_id = _prompt_and_save(
        cfg.get("property_id"),
        project_dir=project_dir,
        section="analytics",
        key="property_id",
        hint='GA4 属性 ID，例如 "properties/123456789" 或纯数字 "123456789"',
        interactive=interactive,
    )
    provider = token_provider or _provider_for(key_file, [GA4_SCOPE])
    client = AnalyticsClient(provider, property_id, session=session)

    rows = client.report(
        current,
        dimensions=["sessionSourceMedium", "landingPagePlusQueryString"],
        metrics=["sessions", "totalUsers"],
        limit=500,
    )
    summary = summarize_analytics(rows)
    summary["property_id"] = property_id
    summary["window"] = current.label
    return SourceOutcome("analytics", "ok", summary)


def _prompt_and_save(
    value, *, project_dir, section, key, hint, interactive
) -> str:
    """Return *value*, or ask for it once and persist it for next time.

    Without persisting, every run would re-ask for the site/property.
    """
    if value:
        return str(value)
    if not interactive or not sys.stdin.isatty():
        raise MetricsError(
            f"未配置 {section}.{key}（{hint}）。\n"
            f"  写入 projects/{Path(project_dir).name}/metrics.yml 即可：\n"
            f"    {section}:\n      {key}: <值>"
        )

    print(f"\n还需要 {section}.{key}：{hint}")
    try:
        answer = input(f"{section}.{key} > ").strip()
    except (EOFError, KeyboardInterrupt) as exc:
        raise MetricsError(f"已取消，未配置 {section}.{key}。") from exc
    if not answer:
        raise MetricsError(f"未配置 {section}.{key}")

    saved = save_project_source_config(project_dir, {section: {key: answer}})
    print(f"✅ 已保存到 {saved}")
    return answer


def _assemble(
    project_dir: Path,
    sources: dict[str, Any],
    outcomes: list[SourceOutcome],
    days: int | None,
    *,
    today: date | None = None,
) -> dict[str, Any]:
    resolved: dict[str, Any] = {}
    unavailable: list[str] = []
    for outcome in outcomes:
        resolved[outcome.name] = {
            "status": outcome.status,
            "config": {
                k: v
                for k, v in sources[outcome.name].items()
                if k in ("enabled", "provider", "site_url", "property_id", "lookback_days")
            },
        }
        if outcome.status == "ok":
            resolved[outcome.name].update(outcome.summary)
        else:
            resolved[outcome.name]["reason"] = outcome.error
            if outcome.status != "disabled":
                unavailable.append(f"{outcome.name}: {outcome.error}")

    any_live = any(o.status == "ok" for o in outcomes)
    return {
        "project_id": project_dir.name,
        "fetched_at": utc_now(),
        "lookback_days": days or DEFAULT_LOOKBACK_DAYS,
        "mode": "live" if any_live else "unavailable",
        "is_real_data": any_live,
        "sources": resolved,
        "unavailable": unavailable,
        "notes": (
            "GSC 的点击率(ctr)与平均排名(position)按展示量加权；"
            "opportunities 是确定性计算的 SEO 机会，不是模型猜测。"
            if any_live
            else "没有取到任何真实数据；下游不要把它当作真实反馈。"
        ),
    }


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------


def metrics_dir(project_dir: Path | str) -> Path:
    return Path(project_dir) / "metrics"


def save_report(project_dir: Path | str, report: dict[str, Any]) -> tuple[Path, Path]:
    """Write a compact summary (for prompts) and the full report."""
    directory = metrics_dir(project_dir)
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    summary_path = directory / f"{stamp}-metrics.json"
    summary_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    latest = directory / "latest-metrics.json"
    latest.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return summary_path, latest


def record_metrics(project_dir: Path | str, state: dict[str, Any], report: dict[str, Any]) -> Path:
    """Register the metrics as an artifact so the growth prompt inlines it."""
    project_dir = Path(project_dir)
    _, latest = save_report(project_dir, report)
    rel = str(latest.relative_to(project_dir))
    state.setdefault("artifacts", {})["metrics"] = {
        "path": rel,
        "stage": state.get("stage"),
        "generated_at": utc_now(),
        "mode": report.get("mode", "unavailable"),
        "is_real_data": bool(report.get("is_real_data")),
    }
    state.setdefault("audit_log", []).append(
        {
            "timestamp": utc_now(),
            "action": "metrics_collected",
            "actor": "autopilot",
            "mode": report.get("mode"),
            "unavailable": report.get("unavailable") or [],
        }
    )
    return latest


def describe_config(project_dir: Path | str) -> str:
    """What is configured, and what is still missing -- without calling any API."""
    project_dir = Path(project_dir)
    sources = merged_sources(project_dir)
    key = key_file_path()
    lines = [
        f"服务账号密钥 : {key if key else '（未配置）'}",
        f"项目配置文件 : {project_dir / 'metrics.yml'}"
        + ("" if (project_dir / "metrics.yml").is_file() else "（尚未创建）"),
    ]
    for name, cfg in sources.items():
        if not cfg.get("enabled"):
            lines.append(f"\n⏸ {name}: 未启用")
            lines.append("     在 config/sources.yml 里设为 enabled: true 才会拉取")
            continue
        missing = []
        if key is None:
            missing.append("GOOGLE_APPLICATION_CREDENTIALS（写入 .env）")
        if name == "search_console" and not cfg.get("site_url"):
            missing.append("search_console.site_url")
        if name == "analytics" and not cfg.get("property_id"):
            missing.append("analytics.property_id")
        lines.append(f"\n{'✅' if not missing else '⚠️ '} {name}: 已启用")
        lines.append(f"     provider: {cfg.get('provider')}")
        lines.append(f"     回看天数: {cfg.get('lookback_days')}")
        if missing:
            lines.append("     还缺：" + "、".join(missing))
            lines.append("     （命令运行时会在交互式终端提示你输入，并保存下来）")
    return "\n".join(lines)


def describe_report(report: dict[str, Any]) -> str:
    lines = [
        f"数据源模式 : {report.get('mode')}   （真实数据：{report.get('is_real_data')}）",
        f"拉取时间   : {report.get('fetched_at')}",
        f"回看天数   : {report.get('lookback_days')}",
    ]
    for name, data in (report.get("sources") or {}).items():
        status = data.get("status")
        mark = {"ok": "✅", "disabled": "⏸", "unavailable": "❌"}.get(status, "?")
        lines.append(f"\n{mark} {name}  [{status}]")
        if status != "ok":
            lines.append(f"     {data.get('reason')}")
            continue
        totals = data.get("totals") or {}
        if totals:
            lines.append(
                "     合计: "
                + ", ".join(f"{k}={v}" for k, v in totals.items())
            )
        delta = data.get("delta") or {}
        if delta:
            parts = [
                f"{k} {'+' if (v or 0) >= 0 else ''}{round((v or 0) * 100, 1)}%"
                for k, v in delta.items()
                if v is not None
            ]
            if parts:
                lines.append("     环比: " + ", ".join(parts))
        opportunities = data.get("opportunities") or []
        if opportunities:
            lines.append(f"     机会: {len(opportunities)} 条（展示多但点击少 / 逼近第一页）")
            for opp in opportunities[:3]:
                lines.append(
                    f"       · {opp['type']}: {opp['query']}  "
                    f"展示 {opp['impressions']}  点击 {opp['clicks']}  "
                    f"排名 {opp['position']}"
                )
    unavailable = report.get("unavailable") or []
    if unavailable:
        lines.append("\n不可用：")
        for item in unavailable:
            lines.append(f"  · {item}")
    return "\n".join(lines)
