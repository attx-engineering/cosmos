#!/usr/bin/env python3
###############################################################################
# Emit WarpLink's component descriptor, as specified by warpware_hub
# docs/contracts/component-descriptor.md.
#
# Standalone rather than sharing WarpTwin and WarpOS's engine
# (warpos/utils/descriptor.py), and that is a choice rather than an oversight.
# WarpLink is a separate repository with its own remote and no code dependency
# on either -- it reads a cmd_tlm.json those produce, which is a data
# dependency. Importing their tooling would create a coupling that does not
# otherwise exist, and would mean a WarpLink checkout could not describe itself
# without a WarpOS beside it.
#
# The cost is duplicated reading logic, and it is a real cost: a bug fixed in
# one engine has to be fixed in the other. It was one, once already -- git
# describe parsed by splitting on the first hyphen reports the CalVer tag
# "26.04-0" as "26.04", a release that does not exist. The mitigation is that
# the hub's conformance suite checks every emitted descriptor the same way, so
# a divergence shows up as a failing test rather than a wrong descriptor.
#
# The shared thing is the contract, not the code. That is what constraint 1
# asks for anyway: a format a non-WarpWare product could implement.
###############################################################################
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

SCHEMA_VERSION = 1
ROOT = Path(__file__).resolve().parent
#: Where a descriptor is found, from component-descriptor.md section 10. One
#: name for every product, which is what lets the hub identify a tree without
#: knowing anything about the product in it.
WELL_KNOWN_NAME = "warpware-component.json"

# The declared half, named so it cannot be mistaken for the emitted descriptor.
# They collided at first -- the scanner found the manifest, failed to parse it as
# a descriptor, and silently fell back to probing, which is exactly the quiet
# wrong answer a fallback is supposed to prevent from being loud.
MANIFEST = ROOT / "descriptor.manifest.json"


class DescriptorError(Exception):
    """A descriptor could not be produced from the tree it describes."""


def git_version(root):
    """Derive a version from the repository, as section 4 requires."""
    try:
        described = subprocess.run(
            ["git", "describe", "--tags", "--always", "--dirty"],
            cwd=str(root), capture_output=True, text=True, check=True,
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return {"id": "unknown", "source": "declared"}

    version = {"id": described, "source": "git-describe"}
    # "<tag>-<commits>-g<hash>[-dirty]". The tag is not the part before the
    # first hyphen: WarpWare's CalVer tags contain one.
    match = re.match(r"^(?P<tag>.+)-(?P<ahead>\d+)-g(?P<hash>[0-9a-f]+)(-dirty)?$", described)
    if match:
        version["tag"] = match.group("tag")
        version["commit"] = match.group("hash")
        return version
    if re.fullmatch(r"[0-9a-f]{7,40}(-dirty)?", described):
        version["commit"] = described.removesuffix("-dirty")
        return version
    version["tag"] = described.removesuffix("-dirty")
    return version


def read_version(root, site, what):
    """Read a contract version out of the source that implements it."""
    path = Path(root) / site["file"]
    if not path.is_file():
        raise DescriptorError(
            f"{what}: {site['file']} does not exist. The manifest names it as where "
            "this contract's version lives.")
    match = re.search(site["pattern"], path.read_text(encoding="utf-8"), re.MULTILINE)
    if match is None:
        raise DescriptorError(
            f"{what}: no match for {site['pattern']!r} in {site['file']}. The constant "
            "moved or was renamed. Fix the manifest rather than writing the number "
            "here -- a declaration not read from the implementation is one that can "
            "disagree with it.")
    value = int(match.group(1))
    if value < 1:
        raise DescriptorError(f"{what}: read version {value}, which is not a version.")
    return value


def capability(name, version, role=None):
    return f"contract:{name}@{version}" + (f":{role}" if role else "")


def build(root, manifest):
    provides = list(manifest.get("provides", {}).get("services", []))
    for name in sorted(manifest.get("provides", {}).get("contracts", {})):
        site = manifest["provides"]["contracts"][name]
        provides.insert(0, capability(name, read_version(root, site, f"provides.{name}"),
                                      site.get("role")))

    requires = []
    for entry in manifest.get("requires", []):
        site = entry.get("versionFrom")
        if site is None:
            raise DescriptorError(
                f"requires entry for {entry.get('contract')!r} has no versionFrom.")
        version = read_version(root, site, f"requires.{entry['contract']}")
        requires.append({
            "capability": capability(entry["contract"], version, entry.get("role")),
            "optional": bool(entry.get("optional", False)),
        })

    descriptor = {
        "schemaVersion": SCHEMA_VERSION,
        "component": manifest["component"],
        "displayName": manifest["displayName"],
        "version": git_version(root),
        "provides": provides,
        "requires": requires,
        "artifacts": manifest.get("artifacts", {}),
        "dependencies": manifest.get("dependencies", []),
        "bundles": manifest.get("bundles", []),
        "launch": manifest.get("launch", {}),
    }
    if "tools" in manifest:
        descriptor["tools"] = manifest["tools"]
    return descriptor


def check_launch(descriptor):
    """Section 6 rules a descriptor can be checked against as it is written."""
    problems = []
    for name, mode in descriptor.get("launch", {}).items():
        ports = mode.get("ports", [])
        if mode.get("kind") == "python" and ports:
            problems.append(
                f"launch.{name}: kind 'python' is a module imported in-process but "
                f"declares {len(ports)} port(s). Nothing that starts no process can listen.")
        for i, port in enumerate(ports):
            if port.get("scope") not in ("local", "published"):
                problems.append(
                    f"launch.{name}.ports[{i}]: scope must be 'local' or 'published'. "
                    "It has no default -- publishing puts mission data on a network, "
                    "and a default that did it silently would make that an accident.")
    return problems


def main():
    parser = argparse.ArgumentParser(description="Emit WarpLink's component descriptor.")
    parser.add_argument(
        "--out",
        help="Write here instead of the component root's "
             "warpware-component.json. Use - for stdout.")
    args = parser.parse_args()

    try:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        descriptor = build(ROOT, manifest)
        problems = check_launch(descriptor)
        if problems:
            raise DescriptorError("\n  ".join(["launch modes are not conforming:"] + problems))
    except DescriptorError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    text = json.dumps(descriptor, indent=2) + "\n"
    # Section 10 is where the hub looks. An emitter whose default lands
    # somewhere else means every caller has to know the convention separately,
    # and one of them will not.
    out = ROOT / WELL_KNOWN_NAME if args.out is None else (
        None if args.out == "-" else Path(args.out))
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        print(f"wrote {out}")
        print(f"  warplink {descriptor['version']['id']}")
        print(f"  provides: {', '.join(descriptor['provides']) or 'nothing'}")
        print(f"  requires: {', '.join(r['capability'] for r in descriptor['requires'])}")
        published = [p['service'] for m in descriptor['launch'].values()
                     for p in m.get('ports', []) if p['scope'] == 'published']
        print(f"  published: {', '.join(published) or 'nothing'}")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
