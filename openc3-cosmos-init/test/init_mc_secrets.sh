#!/bin/sh
# Copyright 2026 ATTX, Inc.
# All Rights Reserved.
#
# This program is free software; you can modify and/or redistribute it
# under the terms of the GNU Affero General Public License
# as published by the Free Software Foundation; version 3 with
# attribution addendums as found in the LICENSE.txt
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.

# init.sh's MinIO setup with secrets that begin with "-", which mc would read as flags: the lines of the init.sh
# given (this folder's, by default) from "mc alias set" to "mc admin policy attach", run in a COSMOS init image
# against a MinIO started from a COSMOS MinIO image, on a Docker network of their own with no way out. Passes when
# the script runner's user is made, with the script policy. Everything it starts is removed at the end.
#
#   openc3-cosmos-init/test/init_mc_secrets.sh <init image> <minio image> [<init.sh>]
set -u
INIT_IMAGE=${1:?a COSMOS init image, such as docker.io/openc3inc/openc3-cosmos-init:latest}
MINIO_IMAGE=${2:?a COSMOS MinIO image}
HERE=$(cd "$(dirname "$0")" && pwd)
INIT_SH=$(cd "$(dirname "${3:-$HERE/../init.sh}")" && pwd)/$(basename "${3:-$HERE/../init.sh}")
N=init-mc-secrets-$$
ROOT_PASSWORD=-3N-Mpe_rootSecret0
SR_PASSWORD=-Kd_runnerSecret12
cleanup() {
  docker rm -f "$N-minio" >/dev/null 2>&1
  docker network rm "$N" >/dev/null 2>&1
}
trap cleanup EXIT INT TERM
fail() { echo "FAILED: $*"; exit 1; }

docker network create --internal "$N" >/dev/null || fail "docker network create"
docker run -d --name "$N-minio" --network "$N" -e MINIO_ROOT_USER=openc3minio -e "MINIO_ROOT_PASSWORD=$ROOT_PASSWORD" \
  "$MINIO_IMAGE" server --address ":9000" /data >/dev/null || fail "starting MinIO"

docker run --rm --network "$N" -v "$INIT_SH:/tmp/init.sh:ro" --entrypoint sh \
  -e "OPENC3_BUCKET_URL=http://$N-minio:9000" -e OPENC3_BUCKET_USERNAME=openc3minio -e "OPENC3_BUCKET_PASSWORD=$ROOT_PASSWORD" \
  -e OPENC3_SR_BUCKET_USERNAME=scriptrunnerminio -e "OPENC3_SR_BUCKET_PASSWORD=$SR_PASSWORD" "$INIT_IMAGE" -c '
    for i in $(seq 1 30); do curl -sf "$OPENC3_BUCKET_URL/minio/health/live" >/dev/null && break; sleep 1; done
    sed -n "/^ *mc alias set/,/^ *mc admin policy attach/p" /tmp/init.sh > /tmp/mc-lines.sh
    echo "== the lines run:"; sed "s/^ */  /" /tmp/mc-lines.sh
    . /tmp/mc-lines.sh
    echo "== the script runner as MinIO has it:"
    mc admin user info openc3minio scriptrunnerminio' > "/tmp/$N.log" 2>&1
status=$?
cat "/tmp/$N.log"
grep -q "flag provided but not defined" "/tmp/$N.log" && fail "mc read a secret as a flag"
[ $status -eq 0 ] || fail "init.sh's MinIO setup exited $status"
grep -qE "Status: *enabled" "/tmp/$N.log" || fail "no script runner user"
grep -qE "PolicyName: *script|Policy: *script" "/tmp/$N.log" || fail "the script runner holds no script policy"
rm -f "/tmp/$N.log"
echo "PASSED: init.sh's MinIO setup takes secrets that begin with -"
