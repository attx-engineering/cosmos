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

# The version of a tool's gem: COSMOS's release, then a number made from the files the gem holds.
#
# COSMOS's init (init.sh) loads each tool's gem at every start, and upgrades a tool already installed only when the
# gem's version differs from the installed one's. A version made from the gem's own files changes exactly when the
# tool does, so an installation whose volumes came from an earlier build takes each changed tool at its next start,
# and leaves an unchanged one alone. The files are the gemspec's (targets/, lib/, tools/, microservices/, Rakefile,
# LICENSE.txt, README.md, plugin.txt) and the gemspec itself, each by its path in the package and its content.
#
#   gem-version.sh <package folder, built> <COSMOS's release version, such as 6.10.6>
#
# Prints, for example, 6.10.6.2846571022: the number is the first 32 bits of a SHA-256, in decimal, which
# RubyGems reads as one more segment of the version.
set -eu
FOLDER=${1:?the folder of a tool package, once built}
BASE=${2:?the COSMOS release version, such as 6.10.6}
cd "$FOLDER"
DIGEST=$(
  {
    for d in targets lib tools microservices; do
      if [ -d "$d" ]; then find "$d" -type f; fi
    done
    for f in Rakefile LICENSE.txt README.md plugin.txt *.gemspec; do
      if [ -f "$f" ]; then echo "$f"; fi
    done
  } | LC_ALL=C sort | while IFS= read -r f; do
    printf '%s\n' "$f"
    sha256sum < "$f"
  done | sha256sum | cut -c1-8
)
printf '%s.%s\n' "$BASE" "$((0x$DIGEST))"
