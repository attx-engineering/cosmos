#!/bin/sh
set -e

PLUGINS="/openc3/plugins"
GEMS="/openc3/plugins/gems/"
PACKAGES="packages"
OPENC3_RELEASE_VERSION=6.10.6

# 2nd argument provides an override for the build folder
FOLDER_NAME=$2
if [ -z "${FOLDER_NAME}" ]; then # if WORKSPACE_NAME is unset or empty string
  # "openc3-cosmos-tool-admin" -> "@openc3/cosmos-tool-admin"
  FOLDER_NAME=${PLUGINS}/${PACKAGES}/${1}/
fi

mkdir -p ${GEMS}

echo "<<< packageBuild $1"
cd ${FOLDER_NAME}

# WarpLink: a tool whose code is installed by a WarpLink feature names its main
# file in package.json ("warplink": {"requires": ...}). Until that feature is
# installed the package is only a skeleton, so skip it rather than fail.
WARPLINK_REQUIRES=$(node -p "(require('./package.json').warplink || {}).requires || ''")
if [ -n "${WARPLINK_REQUIRES}" ] && [ ! -e "${WARPLINK_REQUIRES}" ]; then
  echo "=== packageBuild $1 skipped: ${WARPLINK_REQUIRES} is not installed"
  exit 0
fi
echo "--- packageBuild $1 pnpm run build"
pnpm run build
echo "=== packageBuild $1 pnpm run build complete"
echo "--- packageBuild $1 rake build"
# WarpLink: suffix the version with a checksum of everything the gem packages
# (see the gemspec's s.files), so it changes exactly when the tool does.
# Otherwise the init container sees an unchanged version, logs "No version
# change detected", and keeps serving the previously installed tool.
BUILD_SUM=$(find targets lib tools microservices Rakefile LICENSE.txt README.md plugin.txt -type f 2>/dev/null |
  LC_ALL=C sort | while IFS= read -r f; do cksum "$f"; done | cksum | cut -d' ' -f1)
rake build VERSION=${OPENC3_RELEASE_VERSION}.${BUILD_SUM}
echo "=== packageBuild $1 rake build complete"
ls *.gem
echo "--- packageInstall $1 mv gem file"
mv ${1}-*.gem ${GEMS}
echo "=== packageInstall $1 mv gem complete"
