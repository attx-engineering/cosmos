#!/usr/bin/env bash
# warplink_release.sh
# Release a tagged snapshot of this COSMOS fork (attx-engineering/cosmos)
# to distribution (warpware-distribution/warplink) as a clean tree.

set -Eeuo pipefail

# ===== CONFIG DEFAULTS =====
DIST_URL_DEFAULT="git@github.com:warpware-distribution/warplink.git"
DIST_BRANCH_DEFAULT="main"
SOURCE_BRANCH_DEFAULT="main"

# ===== UTILS =====
err()  { printf "\e[31mERROR:\e[0m %s\n" "$*" >&2; }
warn() { printf "\e[33mWARN:\e[0m %s\n" "$*" >&2; }
info() { printf "\e[34mINFO:\e[0m %s\n" "$*"; }
ok()   { printf "\e[32mOK:\e[0m %s\n" "$*"; }

KEEP_TMPDIR="false"
cleanup() {
  if [[ "${KEEP_TMPDIR}" != "true" && -n "${TMPDIR_RELEASE:-}" && -d "$TMPDIR_RELEASE" ]]; then
    rm -rf "$TMPDIR_RELEASE"
  fi
}
trap cleanup EXIT

usage() {
  cat <<EOF
Usage:
  $0 --tag <tag> [--dist-url <git@...>] [--dist-branch <branch>] [--source-branch <branch>] [--dry-run]

Options:
  --tag            REQUIRED. Tag name to release, e.g. 26.09 (created on origin/<source-branch> if missing).
  --dist-url       Distribution repo URL (default: ${DIST_URL_DEFAULT})
  --dist-branch    Distribution branch to update (default: ${DIST_BRANCH_DEFAULT})
  --source-branch  Branch to tag when the tag doesn't exist yet (default: ${SOURCE_BRANCH_DEFAULT})
  --dry-run        Build the release commit but don't create/push tags or push to distribution.
                   The staged distribution checkout is kept for inspection.

Notes:
  - Only committed content is released (git archive of the tag). Uncommitted and
    untracked files are NOT included.
  - .releaseignore at the repo root lists root-relative glob patterns to remove
    from the exported tree (bash globstar syntax).
  - The distribution branch is replaced with the exported tree: files that no
    longer exist in the release are deleted from distribution.
EOF
}

# ===== ARG PARSE =====
TAG=""
DIST_URL="${DIST_URL_DEFAULT}"
DIST_BRANCH="${DIST_BRANCH_DEFAULT}"
SOURCE_BRANCH="${SOURCE_BRANCH_DEFAULT}"
DRY_RUN="false"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --tag) TAG="${2:-}"; shift 2;;
    --dist-url) DIST_URL="${2:-}"; shift 2;;
    --dist-branch) DIST_BRANCH="${2:-}"; shift 2;;
    --source-branch) SOURCE_BRANCH="${2:-}"; shift 2;;
    --dry-run) DRY_RUN="true"; shift;;
    -h|--help) usage; exit 0;;
    *) err "Unknown argument: $1"; usage; exit 1;;
  esac
done

[[ -n "$TAG" ]] || { err "--tag is required"; usage; exit 1; }

# ===== PRE-FLIGHT =====
# Make sure no weird env vars break git
unset GIT_DIR GIT_WORK_TREE

command -v git >/dev/null 2>&1 || { err "git not found"; exit 1; }
command -v tar >/dev/null 2>&1 || { err "tar not found"; exit 1; }

# Ensure we're in the source repo and work from its root regardless of cwd
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || { err "Run this inside the source Git repo (attx-engineering/cosmos)"; exit 1; }
cd "${REPO_ROOT}"
RELEASEIGNORE_FILE="${REPO_ROOT}/.releaseignore"
SOURCE_URL="$(git remote get-url origin 2>/dev/null || echo unknown)"

# Make sure we can see the distribution repo
if ! git ls-remote --heads "${DIST_URL}" >/dev/null 2>&1; then
  err "Cannot access distribution repository: ${DIST_URL}
- Check your SSH agent/key and write permissions."
  exit 1
fi
ok "Distribution repo reachable"

if [[ -n "$(git status --porcelain)" ]]; then
  warn "Working tree has uncommitted or untracked changes. They will NOT be part of this release."
fi

# ===== VERIFY OR CREATE TAG IN SOURCE REPO =====
if git ls-remote --exit-code --tags "${DIST_URL}" "refs/tags/${TAG}" >/dev/null 2>&1; then
  err "Tag '${TAG}' already exists in ${DIST_URL}. Pick a new tag."
  exit 1
fi

if git rev-parse --verify --quiet "refs/tags/${TAG}" >/dev/null; then
  SOURCE_REF="refs/tags/${TAG}"
  SOURCE_SHA="$(git rev-list -n1 "${SOURCE_REF}")"
  info "Found existing tag '${TAG}' @ ${SOURCE_SHA}"
else
  git fetch --quiet origin "${SOURCE_BRANCH}"
  SOURCE_REF="refs/remotes/origin/${SOURCE_BRANCH}"
  SOURCE_SHA="$(git rev-parse "${SOURCE_REF}")"
  if [[ "${DRY_RUN}" == "true" ]]; then
    info "[DRY-RUN] Tag '${TAG}' not found — would create it on origin/${SOURCE_BRANCH} @ ${SOURCE_SHA}"
  else
    info "Tag '${TAG}' not found — creating on origin/${SOURCE_BRANCH}."
    git tag -a "${TAG}" -m "Release ${TAG}" "${SOURCE_SHA}"
    git push origin "refs/tags/${TAG}"
    SOURCE_REF="refs/tags/${TAG}"
    ok "Created tag '${TAG}' @ ${SOURCE_SHA}"
  fi
fi

info "Preparing release '${TAG}' from ${SOURCE_SHA}"

# ===== CREATE CLEAN EXPORT =====
TMPDIR_RELEASE="$(mktemp -d -t warplink_release_XXXXXX)"
EXPORT_DIR="${TMPDIR_RELEASE}/export"
mkdir -p "${EXPORT_DIR}"

info "Exporting clean tree via git archive..."
git archive --format=tar "${SOURCE_SHA}" | tar -x -C "${EXPORT_DIR}"
ok "Archive extracted to ${EXPORT_DIR}"

# ===== SANITIZE WITH .releaseignore =====
if [[ -f "${RELEASEIGNORE_FILE}" ]]; then
  info "Applying patterns from ${RELEASEIGNORE_FILE}"
  shopt -s dotglob globstar nullglob
  while IFS= read -r pattern || [[ -n "$pattern" ]]; do
    [[ -z "${pattern// }" || "${pattern}" =~ ^# ]] && continue
    matches=( "${EXPORT_DIR}"/${pattern} )
    for m in "${matches[@]}"; do
      # Literal (non-wildcard) patterns expand to themselves even when absent
      [[ -e "$m" || -L "$m" ]] || continue
      rm -rf -- "$m"
      info "Removed: ${m#"${EXPORT_DIR}"/}"
    done
  done < "${RELEASEIGNORE_FILE}"
  shopt -u dotglob globstar nullglob
else
  info "No ${RELEASEIGNORE_FILE} found; skipping sanitize step"
fi

# ===== ADD RELEASE METADATA =====
DATE_ISO="$(date -u +'%Y-%m-%dT%H:%M:%SZ')"
cat > "${EXPORT_DIR}/RELEASE_METADATA.json" <<META
{
  "product": "warplink",
  "source_repo": "${SOURCE_URL}",
  "source_tag": "${TAG}",
  "source_commit": "${SOURCE_SHA}",
  "dist_repo": "${DIST_URL}",
  "dist_branch": "${DIST_BRANCH}",
  "released_at_utc": "${DATE_ISO}"
}
META
ok "Wrote RELEASE_METADATA.json"

# ===== STAGE DISTRIBUTION CHECKOUT =====
PUSH_DIR="${TMPDIR_RELEASE}/dist"
if ! git clone --quiet --branch "${DIST_BRANCH}" "${DIST_URL}" "${PUSH_DIR}" 2>/dev/null; then
  info "Branch '${DIST_BRANCH}' not found in distribution; starting it fresh"
  git clone --quiet "${DIST_URL}" "${PUSH_DIR}"
  git -C "${PUSH_DIR}" checkout --quiet --orphan "${DIST_BRANCH}"
fi
cd "${PUSH_DIR}"

# Replace the whole tree so files removed from the source are removed from distribution
find . -mindepth 1 -maxdepth 1 ! -name .git -exec rm -rf -- {} +
cp -a "${EXPORT_DIR}/." .

# --force: this tree is exactly the git archive export, so every file in it is
# release content. Without it, files force-added in the source repo that match a
# .gitignore (e.g. the openc3-ruby/*.tar.gz build inputs) are silently dropped.
git add -A --force
git commit --quiet --allow-empty -m "Release ${TAG} from ${SOURCE_SHA}"

# Guard: the release commit must contain every file that was exported.
MISSING="$(LC_ALL=C comm -23 \
  <(cd "${EXPORT_DIR}" && find . \( -type f -o -type l \) | sed "s|^\./||" | LC_ALL=C sort) \
  <(git -c core.quotepath=off ls-files | LC_ALL=C sort))"
if [[ -n "${MISSING}" ]]; then
  err "Release commit is missing files from the export:"
  printf "%s\n" "${MISSING}" | sed "s/^/  /" >&2
  exit 1
fi
ok "Release commit contains all exported files"
git tag -a "${TAG}" -m "Release ${TAG}"
ok "Created release commit $(git rev-parse --short HEAD)"
git --no-pager show --stat --format='%s' HEAD | tail -n 1

info "About to push to ${DIST_URL} (branch: ${DIST_BRANCH}, tag: ${TAG})"
if [[ "${DRY_RUN}" == "true" ]]; then
  KEEP_TMPDIR="true"
  info "[DRY-RUN] Skipping push. Inspect the release at: ${PUSH_DIR}"
  info "[DRY-RUN] e.g. git -C ${PUSH_DIR} show --stat HEAD"
else
  git push origin "HEAD:refs/heads/${DIST_BRANCH}"
  git push origin "refs/tags/${TAG}"
  ok "Pushed branch '${DIST_BRANCH}' and tag '${TAG}' to distribution"
fi

ok "Release process completed"
