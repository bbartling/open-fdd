#!/usr/bin/env bash
# Daily release easy button — merge → tag → PyPI + GHCR + docs/PDF CI.
#
# Typical day (PR already green):
#   ./scripts/daily_release.sh --pr 210 --merge --watch
#   ./scripts/daily_release.sh --post-merge --watch
#   ./scripts/daily_release.sh --prep-next 3.0.1
#
# Dry run (no git/gh mutations):
#   ./scripts/daily_release.sh --pr 210 --merge --dry-run
#
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PR=""
MERGE=false
POST_MERGE=false
PREP_NEXT=""
WATCH=false
DRY_RUN=false
IMAGE_TAG=""
SKIP_DOCKER=false

usage() {
  sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'
  echo ""
  echo "Options:"
  echo "  --pr <n>           PR number to merge (requires --merge)"
  echo "  --merge            Squash-merge PR into master"
  echo "  --post-merge       Tag + push PyPI tag + trigger GHCR publish (run on master)"
  echo "  --image-tag <tag>  GHCR tag (default: YYYY.MM.DD-edge from UTC date)"
  echo "  --skip-docker      Skip GHCR workflow_dispatch"
  echo "  --prep-next <ver>  Create fix/<ver>-bugfixes branch and bump pyproject + open_fdd"
  echo "  --watch            Poll gh until CI checks finish (up to ~12 min)"
  echo "  --dry-run          Print actions only"
  echo "  -h|--help"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --pr) PR="$2"; shift 2 ;;
    --merge) MERGE=true; shift ;;
    --post-merge) POST_MERGE=true; shift ;;
    --image-tag) IMAGE_TAG="$2"; shift 2 ;;
    --skip-docker) SKIP_DOCKER=true; shift ;;
    --prep-next) PREP_NEXT="$2"; shift 2 ;;
    --watch) WATCH=true; shift ;;
    --dry-run) DRY_RUN=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown arg: $1" >&2; usage >&2; exit 1 ;;
  esac
done

run() {
  if [[ "$DRY_RUN" == true ]]; then
    echo "[dry-run] $*"
  else
    "$@"
  fi
}

pkg_version() {
  python3 -c "import tomllib; print(tomllib.load(open('pyproject.toml', 'rb'))['project']['version'])"
}

bump_version() {
  local ver="$1"
  python3 - "$ver" <<'PY'
import pathlib, re, sys
ver = sys.argv[1]
for path in (pathlib.Path("pyproject.toml"), pathlib.Path("open_fdd/__init__.py")):
    text = path.read_text()
    if path.name == "pyproject.toml":
        text, n = re.subn(r'(?m)^version = ".*"$', f'version = "{ver}"', text, count=1)
    else:
        text, n = re.subn(r'__version__ = ".*"', f'__version__ = "{ver}"', text, count=1)
    if n != 1:
        raise SystemExit(f"version bump failed in {path}")
    path.write_text(text)
PY
}

wait_checks() {
  local ref="${1:-master}"
  echo "==> Watching CI for ${ref} (up to 12 min)..."
  local deadline=$((SECONDS + 720))
  while (( SECONDS < deadline )); do
    if gh pr checks "$PR" 2>/dev/null | grep -q .; then
      if gh pr checks "$PR" 2>/dev/null | grep -qvE 'pass|skipping'; then
        sleep 30
        continue
      fi
      gh pr checks "$PR" 2>/dev/null || true
      echo "==> PR checks green."
      return 0
    fi
    if gh run list --branch "$ref" --limit 3 --json status,conclusion,name 2>/dev/null \
      | python3 -c "import json,sys; runs=json.load(sys.stdin); pending=[r for r in runs if r.get('status')!='completed']; bad=[r for r in runs if r.get('conclusion') not in (None,'success','skipped') and r.get('status')=='completed']; sys.exit(1 if bad else (2 if pending else 0))" 2>/dev/null; then
      echo "==> Branch CI green."
      return 0
    fi
    sleep 30
  done
  echo "WARN: CI watch timed out — verify manually: gh run list --branch ${ref}" >&2
  return 1
}

preflight_pr() {
  [[ -n "$PR" ]] || { echo "--pr required with --merge" >&2; exit 1; }
  echo "==> PR #${PR} preflight"
  gh pr view "$PR" --json mergeable,state,statusCheckRollup,headRefName \
    --jq '{mergeable,state,head:.headRefName,checks:[.statusCheckRollup[]|{name:.name,conclusion:.conclusion}]}'
  local mergeable state
  mergeable="$(gh pr view "$PR" --json mergeable -q .mergeable)"
  state="$(gh pr view "$PR" --json state -q .state)"
  [[ "$state" == "OPEN" ]] || { echo "PR not open: $state" >&2; exit 1; }
  [[ "$mergeable" == "MERGEABLE" ]] || { echo "PR not mergeable" >&2; exit 1; }
  if gh pr checks "$PR" 2>/dev/null | grep -qvE 'pass|skipping'; then
    echo "PR checks not all green" >&2
    gh pr checks "$PR" 2>/dev/null || true
    exit 1
  fi
  echo "==> CodeRabbit / CI green."
}

merge_pr() {
  preflight_pr
  echo "==> Squash-merging PR #${PR}"
  run gh pr merge "$PR" --squash --delete-branch
}

post_merge_release() {
  local ver tag
  ver="$(pkg_version)"
  tag="v${ver}"
  legacy_tag="open-fdd-v${ver}"
  IMAGE_TAG="${IMAGE_TAG:-$(date -u +%Y.%m.%d)-edge}"

  git fetch origin master
  run git checkout master
  run git pull --ff-only origin master

  echo "==> Release version ${ver} → tag ${tag}, GHCR ${IMAGE_TAG}"

  if git rev-parse "$tag" >/dev/null 2>&1; then
    echo "Tag ${tag} already exists locally."
  else
    run git tag -a "$tag" -m "open-fdd ${ver}"
    run git push origin "$tag"
    echo "==> Pushed ${tag} (triggers PyPI + GHCR publish workflows)"
  fi

  if git rev-parse "$legacy_tag" >/dev/null 2>&1; then
    echo "Legacy tag ${legacy_tag} already exists."
  elif [[ "${PUSH_LEGACY_TAG:-}" == "1" ]]; then
    run git tag -a "$legacy_tag" -m "open-fdd ${ver} (legacy tag)"
    run git push origin "$legacy_tag"
  fi

  if [[ "$SKIP_DOCKER" != true ]]; then
    echo "==> GHCR: tag ${tag} triggers docker-publish.yml (${ver}, ${ver%.*}, latest)"
  fi

  echo ""
  echo "Post-merge automation:"
  echo "  • PyPI + GHCR: tag ${tag} → publish-open-fdd.yml + docker-publish.yml"
  echo "  • Docs site: docs-pages.yml on master push"
  echo "  • PDF: docs-pdf.yml if docs/** changed (opens chore/docs-pdf-refresh PR)"
  echo "  • Edge upgrade: OPENFDD_IMAGE_TAG=${IMAGE_TAG} ./scripts/upgrade_edge_ghcr.sh --limit <host>"
}

prep_next_branch() {
  local ver="$1"
  local branch="fix/${ver}-bugfixes"
  echo "==> Prep next cycle: ${branch} @ ${ver}"
  run git fetch origin --prune
  run git checkout master
  run git pull --ff-only origin master
  if git show-ref --verify --quiet "refs/heads/${branch}"; then
    run git checkout "$branch"
  else
    run git checkout -b "$branch"
  fi
  bump_version "$ver"
  echo "==> Bumped to ${ver} in pyproject.toml + open_fdd/__init__.py"
  if [[ "$DRY_RUN" != true ]]; then
    git diff pyproject.toml open_fdd/__init__.py
    git add pyproject.toml open_fdd/__init__.py
    git commit -m "chore(release): bump open-fdd to ${ver} for next bugfix cycle"
    git push -u origin "$branch"
  fi
}

prune_local_branches() {
  echo "==> Prune merged local branches"
  run git fetch origin --prune
  for b in fix/3.0-bugfixes feature/arrow-native-fdd-runtime; do
    if git show-ref --verify --quiet "refs/heads/${b}"; then
      run git branch -d "$b" 2>/dev/null || run git branch -D "$b" || true
    fi
  done
  echo "Remote branches (review; dependabot/docs bot branches may remain until merged):"
  git branch -r | sed 's/^/  /'
}

if [[ "$MERGE" == true ]]; then
  merge_pr
  POST_MERGE=true
fi

if [[ "$POST_MERGE" == true ]]; then
  post_merge_release
  [[ "$WATCH" == true ]] && wait_checks master || true
  prune_local_branches
fi

if [[ -n "$PREP_NEXT" ]]; then
  prep_next_branch "$PREP_NEXT"
fi

if [[ "$MERGE" != true && "$POST_MERGE" != true && -z "$PREP_NEXT" ]]; then
  usage >&2
  exit 1
fi

echo "==> Done."
