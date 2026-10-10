#!/usr/bin/env python3
"""Validate that the runtime environment is properly configured."""

import argparse
import importlib
import json
import logging
import os
import sys

logger = logging.getLogger(__name__)


def _setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s: %(message)s",
        stream=sys.stderr,
    )


# ---------------------------------------------------------------------------
# Check definitions
# ---------------------------------------------------------------------------

REQUIRED_PACKAGES = ["jsonschema", "pyyaml"]
OPTIONAL_PACKAGES = ["pytest"]

# Packages whose import name differs from their pip name
_IMPORT_NAME_MAP = {
    "pyyaml": "yaml",
}
REQUIRED_DIRS = ["schemas", "config", "scripts", "projects"]


def _check_python_version() -> dict:
    major, minor = sys.version_info[:2]
    ok = (major, minor) >= (3, 10)
    return {
        "name": "Python version >= 3.10",
        "category": "required",
        "status": "PASS" if ok else "FAIL",
        "detail": f"{major}.{minor}.{sys.version_info.micro}",
    }


def _check_package(name: str, required: bool) -> dict:
    import_name = _IMPORT_NAME_MAP.get(name, name)
    try:
        importlib.import_module(import_name)
        try:
            from importlib.metadata import version as pkg_version
            version = pkg_version(name)
        except Exception:
            version = "unknown"
        return {
            "name": f"Package: {name}",
            "category": "required" if required else "optional",
            "status": "PASS",
            "detail": f"version {version}",
        }
    except ImportError:
        return {
            "name": f"Package: {name}",
            "category": "required" if required else "optional",
            "status": "FAIL" if required else "WARN",
            "detail": "not installed",
        }


def _check_directory(name: str, repo_root: str) -> dict:
    path = os.path.join(repo_root, name)
    exists = os.path.isdir(path)
    return {
        "name": f"Directory: {name}/",
        "category": "required",
        "status": "PASS" if exists else "FAIL",
        "detail": path if exists else "missing",
    }


def _check_schema_files(repo_root: str) -> list[dict]:
    schemas_dir = os.path.join(repo_root, "schemas")
    results = []
    if not os.path.isdir(schemas_dir):
        results.append({
            "name": "Schema files",
            "category": "required",
            "status": "FAIL",
            "detail": "schemas/ directory not found",
        })
        return results

    for fname in sorted(os.listdir(schemas_dir)):
        if not fname.endswith(".json"):
            continue
        fpath = os.path.join(schemas_dir, fname)
        try:
            with open(fpath, "r", encoding="utf-8") as fh:
                json.load(fh)
            results.append({
                "name": f"Schema: {fname}",
                "category": "required",
                "status": "PASS",
                "detail": "valid JSON",
            })
        except json.JSONDecodeError as exc:
            results.append({
                "name": f"Schema: {fname}",
                "category": "required",
                "status": "FAIL",
                "detail": f"invalid JSON: {exc}",
            })
        except OSError as exc:
            results.append({
                "name": f"Schema: {fname}",
                "category": "required",
                "status": "FAIL",
                "detail": f"cannot read: {exc}",
            })

    return results


def _check_env_var(name: str, required: bool = False) -> dict:
    value = os.environ.get(name)
    if value:
        return {
            "name": f"Env: {name}",
            "category": "required" if required else "optional",
            "status": "PASS",
            "detail": "set (value hidden)",
        }
    else:
        return {
            "name": f"Env: {name}",
            "category": "required" if required else "optional",
            "status": "FAIL" if required else "WARN",
            "detail": "not set",
        }


def _check_pipeline_config(repo_root: str) -> list[dict]:
    """Verify the local driver and its stage configuration are present."""
    results = []

    cli = os.path.join(repo_root, "autopilot.py")
    results.append({
        "name": "autopilot CLI",
        "category": "required",
        "status": "PASS" if os.path.isfile(cli) else "FAIL",
        "detail": cli if os.path.isfile(cli) else "autopilot.py not found",
    })

    config_path = os.path.join(repo_root, "config", "pipeline.yaml")
    if not os.path.isfile(config_path):
        results.append({
            "name": "Pipeline config",
            "category": "required",
            "status": "FAIL",
            "detail": "config/pipeline.yaml not found",
        })
        return results

    try:
        import yaml

        with open(config_path, "r", encoding="utf-8") as fh:
            config = yaml.safe_load(fh) or {}
        stages = config.get("stages") or {}
        ok = bool(stages)
        results.append({
            "name": "Pipeline config",
            "category": "required",
            "status": "PASS" if ok else "FAIL",
            "detail": f"{len(stages)} stage(s) configured" if ok else "no stages defined",
        })
    except Exception as exc:  # noqa: BLE001 - report any parse failure
        results.append({
            "name": "Pipeline config",
            "category": "required",
            "status": "FAIL",
            "detail": f"could not parse: {exc}",
        })

    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_checks(strict: bool = False) -> list[dict]:
    """Run all environment checks and return list of result dicts."""
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    results: list[dict] = []

    # Python version
    results.append(_check_python_version())

    # Required packages
    for pkg in REQUIRED_PACKAGES:
        results.append(_check_package(pkg, required=True))

    # Optional packages
    for pkg in OPTIONAL_PACKAGES:
        result = _check_package(pkg, required=False)
        if strict and result["status"] == "WARN":
            result["status"] = "FAIL"
        results.append(result)

    # Directory structure
    for d in REQUIRED_DIRS:
        results.append(_check_directory(d, repo_root))

    # Schema files
    results.extend(_check_schema_files(repo_root))

    # Local pipeline configuration (replaces the GitHub Actions driver)
    results.extend(_check_pipeline_config(repo_root))

    # Optional data-source API keys (see config/sources.yml). Values are never
    # printed -- only whether they are set.
    for var in ("SERPAPI_KEY", "AHREFS_API_KEY", "REDDIT_CLIENT_ID"):
        results.append(_check_env_var(var))

    return results


def _format_table(results: list[dict]) -> str:
    """Format results as a human-readable table."""
    lines = []
    lines.append(f"{'Check':<40} {'Status':<8} {'Detail'}")
    lines.append(f"{'-' * 40} {'-' * 8} {'-' * 40}")
    for r in results:
        status_marker = {
            "PASS": "PASS",
            "WARN": "WARN",
            "FAIL": "FAIL",
        }.get(r["status"], r["status"])
        lines.append(f"{r['name']:<40} {status_marker:<8} {r['detail']}")
    return "\n".join(lines)


def main(argv=None):
    _setup_logging()
    parser = argparse.ArgumentParser(
        description="Check that the runtime environment is properly configured.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail on missing optional dependencies (not just warn).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Output results as structured JSON.",
    )

    args = parser.parse_args(argv)
    results = run_checks(strict=args.strict)

    # Determine exit code
    has_failure = any(r["status"] == "FAIL" for r in results)

    if args.json_output:
        output = {
            "checks": results,
            "summary": {
                "total": len(results),
                "pass": sum(1 for r in results if r["status"] == "PASS"),
                "warn": sum(1 for r in results if r["status"] == "WARN"),
                "fail": sum(1 for r in results if r["status"] == "FAIL"),
            },
            "ok": not has_failure,
        }
        print(json.dumps(output, indent=2))
    else:
        print(_format_table(results))

    sys.exit(1 if has_failure else 0)


if __name__ == "__main__":
    main()
