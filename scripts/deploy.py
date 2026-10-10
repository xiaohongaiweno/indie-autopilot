#!/usr/bin/env python3
"""Cloudflare deployment for a project at the end of the pipeline.

Deployment is the one step that is *not* an agent task: it is a deterministic
shell command whose success is what makes the `launched` state true rather than
merely declared. Two consequences shape this module:

1. It runs **before** the `release_pending -> launched` transition, so a failed
   deploy leaves the project at `release_pending` where it can be retried --
   never falsely `launched`.
2. Credentials are asked for only when they are actually needed, and are stored
   in `.env` (already gitignored) rather than anywhere that could be committed.

Wrangler is invoked as a subprocess. The sandbox used by some environments
blocks writes to the npm cache, so use ``dry_run=True`` to see the exact command
without executing it.
"""

from __future__ import annotations

import getpass
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
REPO_ROOT = _HERE.parent
for _p in (str(_HERE), str(REPO_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

logger = logging.getLogger(__name__)

ENV_FILE = REPO_ROOT / ".env"
PIPELINE_CONFIG = REPO_ROOT / "config" / "pipeline.yaml"

#: Credentials Cloudflare needs. Never printed, never committed.
REQUIRED_CREDENTIALS = ("CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID")

#: Wrangler config filenames, in the order wrangler itself resolves them.
WRANGLER_CONFIGS = ("wrangler.toml", "wrangler.json", "wrangler.jsonc")

#: Directories treated as a static site to publish with `wrangler pages deploy`.
#:
#: NOTE: `build` is deliberately **not** here. The pipeline writes its own build
#: stage metadata to `projects/<id>/build/`, and including it made deploy
#: mistake those JSON files for a website and offer to publish them.
STATIC_DIRS = ("dist", "public")

#: Where product source lives, relative to the project directory. The building
#: stage writes real code here (see `code_dir` in pipeline.yaml).
DEFAULT_SOURCE_DIR = "app"

DEFAULT_WRANGLER = ["npx", "wrangler"]


class DeployError(Exception):
    """Raised for any user-facing deployment failure."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def display_path(path: Path) -> str:
    """Repo-relative when possible, absolute otherwise.

    Projects are not required to live under the repository root, so a bare
    ``relative_to(REPO_ROOT)`` would raise for an out-of-tree project.
    """
    try:
        return str(Path(path).relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------


def load_env_file(path: Path | None = None) -> dict[str, str]:
    """Read KEY=VALUE pairs from ``.env``. Does not modify the environment."""
    path = path or ENV_FILE
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'\"")
        if key:
            values[key] = value
    return values


def apply_env_file(path: Path | None = None) -> None:
    """Load ``.env`` into ``os.environ`` without overriding real env vars."""
    for key, value in load_env_file(path).items():
        os.environ.setdefault(key, value)


def save_env_values(values: dict[str, str], path: Path | None = None) -> Path:
    """Merge *values* into ``.env``, preserving other lines. Mode 0600."""
    path = path or ENV_FILE
    existing: list[str] = []
    seen: set[str] = set()
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            key = stripped.split("=", 1)[0].strip() if "=" in stripped else ""
            if key in values:
                existing.append(f"{key}={values[key]}")
                seen.add(key)
            else:
                existing.append(line)
    for key, value in values.items():
        if key not in seen:
            existing.append(f"{key}={value}")

    path.write_text("\n".join(existing).rstrip("\n") + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:  # pragma: no cover - best effort
        pass
    return path


def missing_credentials(*, env_path: Path | None = None) -> list[str]:
    """Which required credentials are absent, checking env then ``.env``."""
    file_values = load_env_file(env_path)
    missing = []
    for key in REQUIRED_CREDENTIALS:
        if not (os.environ.get(key) or file_values.get(key)):
            missing.append(key)
    return missing


def ensure_credentials(
    *, interactive: bool = True, env_path: Path | None = None
) -> dict[str, str]:
    """Return the credentials, prompting for any that are missing.

    Values are never echoed. Whatever the human types is written to ``.env``
    with mode 0600 so the next run does not ask again.
    """
    apply_env_file(env_path)
    missing = missing_credentials(env_path=env_path)
    if not missing:
        return {k: os.environ[k] for k in REQUIRED_CREDENTIALS if os.environ.get(k)}

    if not interactive or not sys.stdin.isatty():
        raise DeployError(
            "缺少 Cloudflare 凭据："
            + ", ".join(missing)
            + f"\n请把它们写入 {env_path or ENV_FILE}（该文件已在 .gitignore 中），"
            "或在交互式终端运行以便按提示输入。"
        )

    print("\n部署到 Cloudflare 需要凭据。输入的值会写入 "
          f"{env_path or ENV_FILE}（已 gitignore），不会出现在日志里。")
    print("获取方式：Cloudflare Dashboard → My Profile → API Tokens → Create Token")
    print("          （模板选 Edit Cloudflare Workers），Account ID 在 Workers 页面右侧。\n")

    collected: dict[str, str] = {}
    for key in missing:
        while True:
            try:
                value = getpass.getpass(f"{key}: ").strip()
            except (EOFError, KeyboardInterrupt) as exc:
                raise DeployError("已取消凭据输入，未执行部署。") from exc
            if value:
                collected[key] = value
                break
            print("  值不能为空，请重试。")

    save_env_values(collected, env_path)
    os.environ.update(collected)
    print(f"\n✅ 已保存 {len(collected)} 项到 {env_path or ENV_FILE}\n")
    return collected


# ---------------------------------------------------------------------------
# Target detection
# ---------------------------------------------------------------------------


@dataclass
class DeployTarget:
    """What will be deployed, and with which command."""

    kind: str  # "workers" | "pages"
    cwd: Path
    command: list[str]
    config_file: Path | None = None
    asset_dir: Path | None = None

    def describe(self) -> str:
        if self.kind == "workers":
            return f"Cloudflare Worker (config: {self.config_file.name})"
        return f"Cloudflare Pages (assets: {self.asset_dir.name}/)"


def load_deploy_config(config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Read the ``deploy:`` block of pipeline.yaml."""
    if config is None:
        config = {}
        if PIPELINE_CONFIG.is_file():
            try:
                import yaml

                config = yaml.safe_load(PIPELINE_CONFIG.read_text(encoding="utf-8")) or {}
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not read %s: %s", PIPELINE_CONFIG, exc)
                config = {}
    block = config.get("deploy") or {}
    block.setdefault("provider", "cloudflare")
    block.setdefault("wrangler", list(DEFAULT_WRANGLER))

    # Escape hatch so the command can be overridden per-run without editing
    # config -- e.g. a globally installed wrangler, or a wrapper script.
    override = os.environ.get("AUTOPILOT_WRANGLER")
    if override:
        import shlex

        block["wrangler"] = shlex.split(override)
    return block


def detect_target(
    project_dir: Path | str,
    *,
    environment: str = "production",
    config: dict[str, Any] | None = None,
) -> DeployTarget:
    """Decide whether this project is a Worker or a Pages site.

    Raises :class:`DeployError` with guidance when there is nothing to deploy,
    rather than inventing a placeholder site.
    """
    project_dir = Path(project_dir)
    if not project_dir.is_dir():
        raise DeployError(f"项目目录不存在：{project_dir}")

    deploy_config = load_deploy_config(config)
    wrangler = list(deploy_config.get("wrangler") or DEFAULT_WRANGLER)
    project_name = _project_name(project_dir)
    source_dir = deploy_config.get("source_dir") or DEFAULT_SOURCE_DIR

    # Look inside the product source directory first, then at the project root
    # for hand-made projects that keep their config there.
    candidates = [project_dir / source_dir]
    if (project_dir / source_dir) != project_dir:
        candidates.append(project_dir)

    for base in candidates:
        if not base.is_dir():
            continue
        for name in WRANGLER_CONFIGS:
            config_file = base / name
            if config_file.is_file():
                command = [*wrangler, "deploy"]
                if environment and environment != "production":
                    command += ["--env", environment]
                return DeployTarget(
                    kind="workers",
                    cwd=base,
                    command=command,
                    config_file=config_file,
                )
        for name in STATIC_DIRS:
            asset_dir = base / name
            if asset_dir.is_dir() and any(asset_dir.iterdir()):
                command = [*wrangler, "pages", "deploy", str(asset_dir)]
                if project_name:
                    command += ["--project-name", project_name]
                if environment == "production":
                    command += ["--branch", "main"]
                return DeployTarget(
                    kind="pages",
                    cwd=base,
                    command=command,
                    asset_dir=asset_dir,
                )

    raise DeployError(
        f"{project_dir} 里没有可部署的内容（已查找 {source_dir}/ 和项目根目录）。\n"
        f"  · Worker: 放一个 {WRANGLER_CONFIGS[0]} 在 {source_dir}/ 里\n"
        f"  · Pages : 放一个 {STATIC_DIRS[0]}/ 目录在 {source_dir}/ 里，里面是要发布的静态文件\n"
        "（构建阶段的产物是 mock，所以还没有真实代码可部署；"
        "真实代码由 building 阶段写到 app/。）"
    )


def _project_name(project_dir: Path) -> str:
    """Prefer the name declared in wrangler config, else the directory name."""
    for name in WRANGLER_CONFIGS:
        config_file = project_dir / name
        if not config_file.is_file():
            continue
        text = config_file.read_text(encoding="utf-8")
        match = re.search(r'^\s*name\s*[=:]\s*["\']([^"\']+)["\']', text, re.MULTILINE)
        if match:
            return match.group(1)
    return project_dir.name


# ---------------------------------------------------------------------------
# Deployment
# ---------------------------------------------------------------------------


@dataclass
class DeploymentResult:
    ok: bool
    environment: str
    command: list[str] = field(default_factory=list)
    url: str | None = None
    output: str = ""
    error: str | None = None
    duration_seconds: float = 0.0
    dry_run: bool = False
    target_kind: str | None = None


_URL_RE = re.compile(r"https?://[^\s\"'<>)\]]+")
_PREFERRED_HOSTS = ("workers.dev", "pages.dev")


def extract_url(output: str) -> str | None:
    """Pull the deployment URL out of wrangler's chatter.

    Prefers a ``*.workers.dev`` / ``*.pages.dev`` URL; otherwise takes the last
    URL printed, which is where wrangler puts the result.
    """
    urls = _URL_RE.findall(output or "")
    if not urls:
        return None
    for url in urls:
        if any(host in url for host in _PREFERRED_HOSTS):
            return url.rstrip(".,")
    return urls[-1].rstrip(".,")


def deploy(
    project_dir: Path | str,
    *,
    environment: str = "production",
    dry_run: bool = False,
    interactive: bool = True,
    timeout_seconds: int = 900,
    config: dict[str, Any] | None = None,
) -> DeploymentResult:
    """Run the deployment. Never raises for a failed deploy -- inspect `.ok`."""
    project_dir = Path(project_dir)
    target = detect_target(project_dir, environment=environment, config=config)

    if dry_run:
        return DeploymentResult(
            ok=True,
            environment=environment,
            command=target.command,
            dry_run=True,
            target_kind=target.kind,
        )

    ensure_credentials(interactive=interactive)

    started = time.monotonic()
    try:
        proc = subprocess.run(
            target.command,
            capture_output=True,
            text=True,
            cwd=str(target.cwd),
            timeout=timeout_seconds,
            env=os.environ.copy(),
        )
    except FileNotFoundError as exc:
        return DeploymentResult(
            ok=False,
            environment=environment,
            command=target.command,
            error=f"找不到 {target.command[0]}：{exc}",
            duration_seconds=round(time.monotonic() - started, 3),
            target_kind=target.kind,
        )
    except subprocess.TimeoutExpired:
        return DeploymentResult(
            ok=False,
            environment=environment,
            command=target.command,
            error=f"部署超时（{timeout_seconds}s）",
            duration_seconds=round(time.monotonic() - started, 3),
            target_kind=target.kind,
        )
    except OSError as exc:
        return DeploymentResult(
            ok=False,
            environment=environment,
            command=target.command,
            error=f"无法执行部署命令：{exc}",
            duration_seconds=round(time.monotonic() - started, 3),
            target_kind=target.kind,
        )

    combined = (proc.stdout or "") + (proc.stderr or "")
    duration = round(time.monotonic() - started, 3)
    if proc.returncode != 0:
        return DeploymentResult(
            ok=False,
            environment=environment,
            command=target.command,
            output=combined,
            error=_first_error_line(combined) or f"wrangler 退出码 {proc.returncode}",
            duration_seconds=duration,
            target_kind=target.kind,
        )

    return DeploymentResult(
        ok=True,
        environment=environment,
        command=target.command,
        url=extract_url(combined),
        output=combined,
        duration_seconds=duration,
        target_kind=target.kind,
    )


def _first_error_line(output: str) -> str | None:
    for line in (output or "").splitlines():
        if line.strip().startswith(("✘", "X [ERROR]", "ERROR", "error")):
            return line.strip()[:300]
    return None


# ---------------------------------------------------------------------------
# Recording
# ---------------------------------------------------------------------------


def deployment_path(project_dir: Path | str) -> Path:
    return Path(project_dir) / "deploy" / "deployment.json"


def load_deployment(project_dir: Path | str) -> dict[str, Any]:
    path = deployment_path(project_dir)
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def record_deployment(
    project_dir: Path | str,
    result: DeploymentResult,
    *,
    project_name: str | None = None,
) -> Path:
    """Persist deployment metadata. Returns the file path."""
    project_dir = Path(project_dir)
    path = deployment_path(project_dir)
    path.parent.mkdir(parents=True, exist_ok=True)

    previous = load_deployment(project_dir)
    record = {
        "provider": "cloudflare",
        "kind": result.target_kind,
        "environment": result.environment,
        "url": result.url,
        "deployed_at": utc_now(),
        "command": result.command,
        "duration_seconds": result.duration_seconds,
        "project_name": project_name,
        # The domain is attached by hand in the Cloudflare dashboard; keep the
        # previous answer if this is a redeploy.
        "custom_domain": previous.get("custom_domain"),
        "custom_domain_attached": bool(previous.get("custom_domain_attached")),
        "history": (previous.get("history") or [])[-9:]
        + [
            {
                "deployed_at": utc_now(),
                "environment": result.environment,
                "url": result.url,
            }
        ],
    }
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def record_domain(project_dir: Path | str, domain: str, *, actor: str | None = None) -> dict[str, Any]:
    """Record that a custom domain has been attached by hand."""
    project_dir = Path(project_dir)
    cleaned = domain.strip()
    if not cleaned:
        raise DeployError("域名不能为空")
    record = load_deployment(project_dir)
    if not record:
        raise DeployError(
            "还没有部署记录，无法挂域名。先运行 `autopilot deploy <project>`。"
        )
    record["custom_domain"] = cleaned
    record["custom_domain_attached"] = True
    record["custom_domain_at"] = utc_now()
    record["custom_domain_by"] = actor

    path = deployment_path(project_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return record


def domain_instructions(project_name: str) -> str:
    return (
        "下一步（需要你手动做一次）：\n"
        f"  1. 打开 https://dash.cloudflare.com → Workers & Pages → {project_name}\n"
        "  2. Settings → Domains & Routes → Add → Custom Domain\n"
        "  3. 输入你的域名，按提示把 DNS 指过去（若域名已托管在 Cloudflare 会自动配好）\n"
        f"  4. 生效后运行：./autopilot.py domain <project> --domain 你的域名"
    )


# ---------------------------------------------------------------------------
# Orchestrator integration
# ---------------------------------------------------------------------------


def deploy_before_launch(
    project_dir: Path | str,
    state: dict[str, Any],
    *,
    assume_yes: bool = False,
    environment: str = "production",
    dry_run: bool = False,
    **_: Any,
) -> DeploymentResult:
    """Pre-transition action for ``release_pending -> launched``.

    Runs the deployment **before** the state machine records `launched`, so a
    failure leaves the project retryable at `release_pending`.
    """
    from orchestrator import PipelineError

    project_dir = Path(project_dir)
    print(f"\n🚀 部署到 Cloudflare（{environment}）...")

    try:
        result = deploy(
            project_dir,
            environment=environment,
            dry_run=dry_run,
            interactive=not assume_yes or sys.stdin.isatty(),
        )
    except DeployError as exc:
        raise PipelineError(f"部署失败：{exc}") from exc

    if result.dry_run:
        print("   dry-run，将执行： " + " ".join(result.command))
        return result

    if not result.ok:
        raise PipelineError(
            f"部署失败：{result.error}\n"
            f"  命令：{' '.join(result.command)}\n"
            "  状态仍是 release_pending，修好后重跑即可。"
        )

    path = record_deployment(
        project_dir, result, project_name=_project_name(project_dir)
    )
    print(f"   ✅ 部署成功：{result.url or '(未解析到 URL)'}")
    print(f"   记录：{display_path(path)}")

    # Relative to the project, matching how every other artifact is recorded.
    # (The project need not live under the repo root.)
    state.setdefault("artifacts", {})["deployment"] = {
        "path": str(path.relative_to(project_dir)),
        "stage": state.get("stage"),
        "generated_at": utc_now(),
        "mode": "live",
        "is_real_data": True,
    }
    state.setdefault("audit_log", []).append(
        {
            "timestamp": utc_now(),
            "action": "deployed",
            "actor": "autopilot",
            "stage": state.get("stage"),
            "url": result.url,
            "environment": result.environment,
            "command": " ".join(result.command),
        }
    )

    if result.url:
        print("\n" + domain_instructions(_project_name(project_dir)))
    return result


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - thin CLI
    import argparse

    parser = argparse.ArgumentParser(description="Deploy a project to Cloudflare.")
    parser.add_argument("--project-dir", required=True)
    parser.add_argument("--environment", default="production")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        result = deploy(
            args.project_dir,
            environment=args.environment,
            dry_run=args.dry_run,
        )
    except DeployError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if result.dry_run:
        print(" ".join(result.command))
        return 0
    print(result.url or result.error or "done")
    return 0 if result.ok else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
