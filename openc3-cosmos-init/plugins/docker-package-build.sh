#!/bin/sh
set -e

HERE=$(cd "$(dirname "$0")" && pwd)
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
echo "--- packageBuild $1 pnpm run build"
pnpm run build
echo "=== packageBuild $1 pnpm run build complete"
echo "--- packageBuild $1 rake build"
# COSMOS's release, then a number made from the files the gem holds, so an installation upgrades the tool exactly when
# it has changed (see gem-version.sh).
GEM_VERSION=$("${HERE}/gem-version.sh" . "${OPENC3_RELEASE_VERSION}")
echo "--- packageBuild $1 version ${GEM_VERSION}"
rake build VERSION=${GEM_VERSION}
echo "=== packageBuild $1 rake build complete"
ls *.gem
echo "--- packageInstall $1 mv gem file"
mv ${1}-*.gem ${GEMS}
echo "=== packageInstall $1 mv gem complete"
