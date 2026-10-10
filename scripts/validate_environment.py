#!/usr/bin/env python3
"""Validate that the runtime environment is properly configured."""

import argparse
import importlib
import json
import logging
import os
import subprocess
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


def _check_env_var(name: str) -> dict:
    value = os.environ.get(name)
    if value:
        return {
            "name": f"Env: {name}",
            "category": "required",
            "status": "PASS",
            "detail": "set (value hidden)",
        }
    else:
        return {
            "name": f"Env: {name}",
            "category": "required",
            "status": "WARN",
            "detail": "not set",
        }


def _check_gh_cli() -> dict:
    try:
        result = subprocess.run(
            ["gh", "auth", "status"],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode == 0:
            return {
                "name": "gh CLI auth",
                "category": "optional",
                "status": "PASS",
                "detail": "authenticated",
            }
        else:
            return {
                "name": "gh CLI auth",
                "category": "optional",
                "status": "WARN",
                "detail": f"not authenticated: {result.stderr.strip().splitlines()[-1] if result.stderr.strip() else 'unknown error'}",
            }
    except FileNotFoundError:
        return {
            "name": "gh CLI auth",
            "category": "optional",
            "status": "WARN",
            "detail": "gh CLI not found",
        }
    except subprocess.TimeoutExpired:
        return {
            "name": "gh CLI auth",
            "category": "optional",
            "status": "WARN",
            "detail": "timed out",
        }
    except OSError as exc:
        return {
            "name": "gh CLI auth",
            "category": "optional",
            "status": "WARN",
            "detail": f"error: {exc}",
        }


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

    # Environment variables
    results.append(_check_env_var("GITHUB_TOKEN"))

    # gh CLI
    results.append(_check_gh_cli())

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
