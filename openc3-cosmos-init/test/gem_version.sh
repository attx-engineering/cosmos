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

# plugins/gem-version.sh, under each shell given (by default whichever of BusyBox's sh, dash and bash this machine
# has; the init image builds under Alpine's BusyBox): a tool gem's version is COSMOS's release and one number, a
# version RubyGems reads, the same for the same files wherever the package is, and different when any file the gem
# holds changes, is added or is renamed -- and the same when only a file the gem leaves out changes.
#
#   openc3-cosmos-init/test/gem_version.sh [<shell command>]...
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
SCRIPT=$HERE/../plugins/gem-version.sh
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
FAILED=0

if [ $# -eq 0 ]; then
  command -v busybox >/dev/null 2>&1 && set -- "$@" "busybox sh"
  command -v dash >/dev/null 2>&1 && set -- "$@" dash
  command -v bash >/dev/null 2>&1 && set -- "$@" bash
fi

fail() {
  echo "FAIL ($SH): $1"
  FAILED=1
  SHELL_FAILED=1
}

# A built tool package: what its gem holds, and what it leaves out.
package() {
  rm -rf "$1"
  mkdir -p "$1/tools/simcontrol" "$1/lib" "$1/src" "$1/node_modules/x"
  printf 'TOOL Sim Control\n' > "$1/plugin.txt"
  printf 'task :build\n' > "$1/Rakefile"
  printf 'AGPL\n' > "$1/LICENSE.txt"
  printf '# Sim Control\n' > "$1/README.md"
  printf 'Gem::Specification.new\n' > "$1/openc3-cosmos-tool-simcontrol.gemspec"
  printf 'console.log(1)\n' > "$1/tools/simcontrol/SimControl-abc.js"
  printf 'body {}\n' > "$1/tools/simcontrol/a file with spaces.css"
  printf 'module X; end\n' > "$1/lib/x.rb"
  printf 'source\n' > "$1/src/SimControl.vue"
  printf '{}\n' > "$1/package.json"
  printf 'dependency\n' > "$1/node_modules/x/index.js"
}

# BusyBox's sh is run with BusyBox's own find, sort, sha256sum and cut alone on its path, as under Alpine.
BUSYBOX=$(command -v busybox || true)
if [ -n "$BUSYBOX" ]; then
  mkdir -p "$WORK/busybox"
  for tool in find sort sha256sum cut; do ln -s "$BUSYBOX" "$WORK/busybox/$tool"; done
fi

for SH in "$@"; do
  SHELL_FAILED=0
  if [ "$SH" = "busybox sh" ]; then
    version() { PATH="$WORK/busybox" "$BUSYBOX" sh "$SCRIPT" "$1" "${2:-6.10.6}"; }
  else
    version() { $SH "$SCRIPT" "$1" "${2:-6.10.6}"; }
  fi
  package "$WORK/a"
  base=$(version "$WORK/a") || { fail "it refused a built package"; continue; }

  case "$base" in
    6.10.6.*) ;;
    *) fail "the version $base does not begin with COSMOS's release" ;;
  esac
  echo "$base" | grep -Eq '^6\.10\.6\.[0-9]+$' || fail "the version $base is not COSMOS's release and one number"
  if command -v ruby >/dev/null 2>&1; then
    ruby -e 'v = ARGV[0]; exit(Gem::Version.correct?(v) && Gem::Version.new(v).segments.length == 4 && !Gem::Version.new(v).prerelease? ? 0 : 1)' "$base" \
      || fail "RubyGems does not read $base as a released version of four segments"
  fi
  [ "$(version "$WORK/a" 7.0.0)" = "7.0.0.${base#6.10.6.}" ] || fail "COSMOS's release is not passed through"

  package "$WORK/elsewhere/b"
  [ "$(version "$WORK/elsewhere/b")" = "$base" ] || fail "the same files in another folder give another version"
  [ "$(version "$WORK/a")" = "$base" ] || fail "the same package gives another version a second time"

  printf 'console.log(2)\n' > "$WORK/a/tools/simcontrol/SimControl-abc.js"
  [ "$(version "$WORK/a")" != "$base" ] || fail "a changed tool file leaves the version as it was"

  package "$WORK/a"; printf 'x\n' > "$WORK/a/lib/new.rb"
  [ "$(version "$WORK/a")" != "$base" ] || fail "a file added to lib/ leaves the version as it was"

  package "$WORK/a"; mv "$WORK/a/tools/simcontrol/SimControl-abc.js" "$WORK/a/tools/simcontrol/SimControl-def.js"
  [ "$(version "$WORK/a")" != "$base" ] || fail "a renamed tool file leaves the version as it was"

  package "$WORK/a"; printf 'body { color: red }\n' > "$WORK/a/tools/simcontrol/a file with spaces.css"
  [ "$(version "$WORK/a")" != "$base" ] || fail "a changed file whose name has spaces leaves the version as it was"

  for held in plugin.txt Rakefile LICENSE.txt README.md openc3-cosmos-tool-simcontrol.gemspec; do
    package "$WORK/a"; printf 'changed\n' >> "$WORK/a/$held"
    [ "$(version "$WORK/a")" != "$base" ] || fail "a changed $held leaves the version as it was"
  done

  package "$WORK/a"; mkdir -p "$WORK/a/targets/SIM" "$WORK/a/microservices/M"
  printf 'x\n' > "$WORK/a/targets/SIM/target.txt"
  with_targets=$(version "$WORK/a")
  [ "$with_targets" != "$base" ] || fail "a file in targets/ leaves the version as it was"
  printf 'y\n' > "$WORK/a/microservices/M/m.rb"
  [ "$(version "$WORK/a")" != "$with_targets" ] || fail "a file in microservices/ leaves the version as it was"

  package "$WORK/a"
  printf 'changed\n' > "$WORK/a/src/SimControl.vue"
  printf '{"changed": true}\n' > "$WORK/a/package.json"
  printf 'changed\n' > "$WORK/a/node_modules/x/index.js"
  [ "$(version "$WORK/a")" = "$base" ] || fail "a file the gem leaves out changed the version"

  rm -rf "$WORK/bare"; mkdir -p "$WORK/bare"; printf 'TOOL\n' > "$WORK/bare/plugin.txt"
  echo "$(version "$WORK/bare")" | grep -Eq '^6\.10\.6\.[0-9]+$' || fail "a package with only plugin.txt has no version"

  $SH "$SCRIPT" "$WORK/a" >/dev/null 2>&1 && fail "it gave a version with no release named"
  $SH "$SCRIPT" "$WORK/missing" 6.10.6 >/dev/null 2>&1 && fail "it gave a version for a folder that is not there"

  [ $SHELL_FAILED -eq 0 ] && echo "ok ($SH): $base"
done

[ $# -gt 0 ] || { echo "FAIL: no shell to run it under"; exit 1; }
exit $FAILED
