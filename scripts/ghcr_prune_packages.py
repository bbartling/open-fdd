#!/usr/bin/env python3
"""Plan and optionally delete old GHCR container package versions (dry-run by default)."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_IMAGES_YAML = REPO_ROOT / "docker" / "images.yaml"
DEFAULT_PROTECTED = REPO_ROOT / "scripts" / "ghcr-retention-protected-tags.txt"

SEMVER_RE = re.compile(r"^v?(\d+\.\d+\.\d+)(?:[-+].*)?$", re.I)
SHA_TAG_RE = re.compile(r"^(sha-)?[a-f0-9]{7,40}$", re.I)
DEV_TAG_RE = re.compile(
    r"^(chore|fix|feat|dev|test|pr|branch|wip|experimental|tmp|debug)[/_-]",
    re.I,
)

REASON_KEEP_PROTECTED = "keep_protected"
REASON_KEEP_RELEASE_WINDOW = "keep_latest_release_window"
REASON_KEEP_ACME_CURRENT = "keep_current_acme"
REASON_KEEP_ACME_PREVIOUS = "keep_previous_acme"
REASON_KEEP_LATEST_EDGE = "keep_latest_or_edge"
REASON_DELETE_UNTAGGED = "delete_untagged_old"
REASON_DELETE_SHA = "delete_sha_old"
REASON_DELETE_DEV = "delete_dev_old"
REASON_DELETE_OLD_RELEASE = "delete_old_release_beyond_retention"
REASON_KEEP_UNKNOWN = "keep_unknown"

DELETE_REASONS = {
    REASON_DELETE_UNTAGGED,
    REASON_DELETE_SHA,
    REASON_DELETE_DEV,
    REASON_DELETE_OLD_RELEASE,
}


@dataclass
class VersionPlan:
    package: str
    version_id: int
    created_at: str
    updated_at: str
    tags: list[str]
    reason: str
    action: str  # keep | delete


@dataclass
class PruneReport:
    owner: str
    images: list[str]
    dry_run: bool
    generated_at: str
    keep_releases: int
    versions: list[VersionPlan] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def summary(self) -> dict[str, int]:
        out = {"keep": 0, "delete": 0}
        for v in self.versions:
            out[v.action] = out.get(v.action, 0) + 1
        return out


def load_protected_tags(path: Path) -> set[str]:
    tags: set[str] = set()
    if not path.is_file():
        return tags
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        tags.add(line)
    return tags


def load_image_names(images_yaml: Path, image_filter: list[str] | None) -> list[str]:
    if image_filter:
        return image_filter
    if not images_yaml.is_file():
        return [
            "openfdd-bridge",
            "openfdd-commission",
            "openfdd-mcp-rag",
            "openfdd-cloud-exporter",
        ]
    names: list[str] = []
    in_images = False
    for line in images_yaml.read_text(encoding="utf-8").splitlines():
        if line.strip() == "images:":
            in_images = True
            continue
        if in_images:
            if line.startswith("  - name:"):
                names.append(line.split(":", 1)[1].strip())
            elif line and not line.startswith(" "):
                break
    return names or [
        "openfdd-bridge",
        "openfdd-commission",
        "openfdd-mcp-rag",
        "openfdd-cloud-exporter",
    ]


def _parse_ts(raw: str) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _semver_key(tag: str) -> tuple[int, int, int] | None:
    m = SEMVER_RE.match(tag.strip())
    if not m:
        return None
    parts = m.group(1).split(".")
    return int(parts[0]), int(parts[1]), int(parts[2])


def _is_sha_tag(tag: str) -> bool:
    return bool(SHA_TAG_RE.match(tag.strip()))


def _is_dev_tag(tag: str) -> bool:
    t = tag.strip()
    if _semver_key(t) or t in {"latest", "edge"}:
        return False
    return bool(DEV_TAG_RE.match(t)) or "/" in t or "_" in t


def list_package_versions(owner: str, package: str, token: str | None) -> list[dict[str, Any]]:
    env = os.environ.copy()
    if token:
        env["GH_TOKEN"] = token
    rows: list[dict[str, Any]] = []
    page = 1
    while True:
        cmd = [
            "gh",
            "api",
            f"users/{owner}/packages/container/{package}/versions",
            "-f",
            f"per_page=100",
            "-f",
            f"page={page}",
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, env=env, check=False)
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "gh api failed")
        batch = json.loads(proc.stdout or "[]")
        if not batch:
            break
        rows.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return rows


def version_tags(version: dict[str, Any]) -> list[str]:
    tags: list[str] = []
    meta = version.get("metadata") or {}
    if isinstance(meta, dict):
        container = meta.get("container") or {}
        if isinstance(container, dict):
            raw = container.get("tags") or []
            if isinstance(raw, list):
                tags.extend(str(t) for t in raw if t)
    for key in ("name", "tag"):
        if version.get(key):
            tags.append(str(version[key]))
    # GHCR often exposes tag list at top level in some API responses
    if isinstance(version.get("tags"), list):
        tags.extend(str(t) for t in version["tags"] if t)
    # dedupe preserve order
    seen: set[str] = set()
    out: list[str] = []
    for t in tags:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def classify_versions(
    package: str,
    versions: list[dict[str, Any]],
    *,
    protected: set[str],
    keep_releases: int,
    delete_untagged_days: int,
    delete_sha_days: int,
    delete_dev_days: int,
    current_acme_tag: str,
    previous_acme_tag: str,
    now: datetime | None = None,
) -> list[VersionPlan]:
    now = now or datetime.now(timezone.utc)
    semver_versions: dict[str, list[dict[str, Any]]] = {}
    plans: list[VersionPlan] = []

    for ver in versions:
        tags = version_tags(ver)
        for tag in tags:
            if _semver_key(tag):
                semver_versions.setdefault(tag, []).append(ver)

    semver_sorted = sorted(
        semver_versions.keys(),
        key=lambda t: _semver_key(t) or (0, 0, 0),
        reverse=True,
    )
    keep_semver = set(semver_sorted[: max(0, keep_releases)])

    for ver in versions:
        vid = int(ver["id"])
        created = str(ver.get("created_at") or "")
        updated = str(ver.get("updated_at") or created)
        tags = version_tags(ver)
        ts = _parse_ts(updated) or _parse_ts(created) or now
        age_days = (now - ts).total_seconds() / 86400.0

        reason = REASON_KEEP_UNKNOWN
        if not tags:
            if age_days >= delete_untagged_days:
                reason = REASON_DELETE_UNTAGGED
        else:
            tag_set = {t.strip() for t in tags}
            if tag_set & protected:
                reason = REASON_KEEP_PROTECTED
            elif current_acme_tag and current_acme_tag in tag_set:
                reason = REASON_KEEP_ACME_CURRENT
            elif previous_acme_tag and previous_acme_tag in tag_set:
                reason = REASON_KEEP_ACME_PREVIOUS
            elif "latest" in tag_set or "edge" in tag_set:
                reason = REASON_KEEP_LATEST_EDGE
            elif any(t in keep_semver for t in tag_set):
                reason = REASON_KEEP_RELEASE_WINDOW
            else:
                sha_only = all(_is_sha_tag(t) for t in tag_set)
                dev_only = all(_is_dev_tag(t) for t in tag_set)
                semver_tags = [t for t in tag_set if _semver_key(t)]
                if semver_tags and not (tag_set & keep_semver):
                    reason = REASON_DELETE_OLD_RELEASE
                elif sha_only and age_days >= delete_sha_days:
                    reason = REASON_DELETE_SHA
                elif dev_only and age_days >= delete_dev_days:
                    reason = REASON_DELETE_DEV
                elif semver_tags and age_days >= delete_sha_days:
                    reason = REASON_DELETE_OLD_RELEASE

        action = "delete" if reason in DELETE_REASONS else "keep"
        plans.append(
            VersionPlan(
                package=package,
                version_id=vid,
                created_at=created,
                updated_at=updated,
                tags=tags,
                reason=reason,
                action=action,
            )
        )
    return plans


def delete_version(owner: str, package: str, version_id: int, token: str | None) -> None:
    env = os.environ.copy()
    if token:
        env["GH_TOKEN"] = token
    cmd = [
        "gh",
        "api",
        "-X",
        "DELETE",
        f"users/{owner}/packages/container/{package}/versions/{version_id}",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env, check=False)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "delete failed")


def print_table(report: PruneReport) -> None:
    print(f"\nGHCR prune plan — owner={report.owner} dry_run={report.dry_run}\n")
    print(f"{'IMAGE':<28} {'VERSION_ID':<12} {'ACTION':<8} {'REASON':<34} TAGS")
    print("-" * 110)
    for v in sorted(report.versions, key=lambda x: (x.package, x.action != "delete", x.version_id)):
        tags = ",".join(v.tags) if v.tags else "(untagged)"
        print(f"{v.package:<28} {v.version_id:<12} {v.action:<8} {v.reason:<34} {tags}")
    s = report.summary()
    print("-" * 110)
    print(f"keep={s.get('keep', 0)} delete={s.get('delete', 0)} errors={len(report.errors)}")


def write_json_report(report: PruneReport, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "owner": report.owner,
        "images": report.images,
        "dry_run": report.dry_run,
        "generated_at": report.generated_at,
        "keep_releases": report.keep_releases,
        "summary": report.summary(),
        "errors": report.errors,
        "versions": [asdict(v) for v in report.versions],
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def write_markdown_report(report: PruneReport, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    s = report.summary()
    lines = [
        "# GHCR prune plan",
        "",
        f"- **Owner:** {report.owner}",
        f"- **Dry run:** {report.dry_run}",
        f"- **Keep release tags:** {report.keep_releases}",
        f"- **Keep:** {s.get('keep', 0)} | **Delete:** {s.get('delete', 0)}",
        "",
        "| Image | Version ID | Action | Reason | Tags |",
        "|-------|------------|--------|--------|------|",
    ]
    for v in report.versions:
        tags = ", ".join(v.tags) if v.tags else "(untagged)"
        lines.append(f"| {v.package} | {v.version_id} | {v.action} | {v.reason} | {tags} |")
    if report.errors:
        lines.extend(["", "## Errors", ""])
        for err in report.errors:
            lines.append(f"- {err}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def verify_packages_api_access(token: str | None) -> None:
    """Fail fast when gh token cannot list container packages."""
    env = os.environ.copy()
    if token:
        env["GH_TOKEN"] = token
    proc = subprocess.run(
        ["gh", "api", "user/packages", "-f", "package_type=container", "-f", "per_page=1"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    if proc.returncode == 0:
        return
    detail = (proc.stderr or proc.stdout or "").strip()
    if "read:packages" in detail:
        raise SystemExit(
            "GHCR dry-run requires read:packages on your gh token.\n"
            "  gh auth refresh -h github.com -s read:packages,delete:packages\n"
            "Then re-run: ./scripts/ghcr_prune_packages.sh --all-images --dry-run"
        )
    raise SystemExit(f"Cannot list GHCR packages: {detail}")


def resolve_token(explicit: str | None) -> str | None:
    if explicit:
        return explicit
    if os.environ.get("GH_TOKEN"):
        return os.environ["GH_TOKEN"]
    proc = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, check=False)
    if proc.returncode == 0 and proc.stdout.strip():
        return proc.stdout.strip()
    return None


def build_plan(args: argparse.Namespace) -> PruneReport:
    token = resolve_token(args.token)
    verify_packages_api_access(token)
    protected = load_protected_tags(Path(args.protected_tags_file))
    if args.current_acme_tag:
        protected.add(args.current_acme_tag.strip())
    if args.previous_acme_tag:
        protected.add(args.previous_acme_tag.strip())

    images = load_image_names(Path(args.images_yaml), args.image or None)
    if args.all_images:
        images = load_image_names(Path(args.images_yaml), None)

    report = PruneReport(
        owner=args.owner,
        images=images,
        dry_run=not args.confirm_delete,
        generated_at=datetime.now(timezone.utc).isoformat(),
        keep_releases=args.keep_releases,
    )

    for pkg in images:
        try:
            versions = list_package_versions(args.owner, pkg, token)
        except Exception as exc:  # noqa: BLE001
            report.errors.append(f"{pkg}: list failed: {exc}")
            continue
        plans = classify_versions(
            pkg,
            versions,
            protected=protected,
            keep_releases=args.keep_releases,
            delete_untagged_days=args.delete_untagged_older_than_days,
            delete_sha_days=args.delete_sha_older_than_days,
            delete_dev_days=args.delete_dev_older_than_days,
            current_acme_tag=args.current_acme_tag.strip(),
            previous_acme_tag=args.previous_acme_tag.strip(),
        )
        report.versions.extend(plans)

    return report


def execute_deletes(report: PruneReport, token: str | None) -> int:
    failures = 0
    for v in report.versions:
        if v.action != "delete":
            continue
        try:
            delete_version(report.owner, v.package, v.version_id, token)
        except Exception as exc:  # noqa: BLE001
            failures += 1
            report.errors.append(f"delete {v.package} id={v.version_id}: {exc}")
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner", default="bbartling")
    parser.add_argument("--repo", default="open-fdd", help="Repo name (informational)")
    parser.add_argument("--image", action="append", default=None)
    parser.add_argument("--all-images", action="store_true")
    parser.add_argument("--images-yaml", default=str(DEFAULT_IMAGES_YAML))
    parser.add_argument("--keep-releases", type=int, default=5)
    parser.add_argument("--delete-untagged-older-than-days", type=int, default=7)
    parser.add_argument("--delete-sha-older-than-days", type=int, default=30)
    parser.add_argument("--delete-dev-older-than-days", type=int, default=30)
    parser.add_argument("--protected-tags-file", default=str(DEFAULT_PROTECTED))
    parser.add_argument("--current-acme-tag", default="")
    parser.add_argument("--previous-acme-tag", default="")
    parser.add_argument("--dry-run", action="store_true", help="Plan only (default unless --confirm-delete)")
    parser.add_argument("--confirm-delete", action="store_true", help="Delete planned versions")
    parser.add_argument("--json-out", default="")
    parser.add_argument("--markdown-out", default="")
    parser.add_argument("--token", default="", help="GH token (default: gh auth token)")
    args = parser.parse_args(argv)

    if not args.all_images and not args.image:
        args.all_images = True

    report = build_plan(args)
    print_table(report)

    if args.json_out:
        write_json_report(report, Path(args.json_out))
    if args.markdown_out:
        write_markdown_report(report, Path(args.markdown_out))

    if args.confirm_delete:
        token = resolve_token(args.token or None)
        if not token:
            print(
                "Deleting GHCR package versions requires package delete permissions. "
                "Use a token with read:packages and delete:packages, or configure "
                "GitHub Actions package permissions appropriately.",
                file=sys.stderr,
            )
            return 2
        failures = execute_deletes(report, token)
        if failures:
            print(f"\nCompleted with {failures} deletion failure(s).", file=sys.stderr)
            return 1
        print("\nDeletion complete.")
    else:
        print("\nDry-run only — pass --confirm-delete to delete listed versions.")

    return 0 if not report.errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
