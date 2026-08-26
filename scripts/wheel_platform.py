#!/usr/bin/env python3
"""Select release wheel tags and verify macOS native wheel architecture."""

from __future__ import annotations

import argparse
import pathlib
import platform
import re
import subprocess
import sysconfig
import tempfile
import zipfile

_MACOS_ARCH_SUFFIX = re.compile(r"_(?:arm64|x86_64|universal2)$")
_MACOS_PLATFORM = re.compile(
    r"^macosx_(?P<major>[0-9]+)_(?P<minor>[0-9]+)"
    r"(?:_(?P<patch>[0-9]+))?_(?P<architecture>arm64|x86_64|universal2)$"
)


def normalize_machine(machine: str) -> str:
    """Return the wheel architecture spelling for a host machine."""
    normalized = machine.strip().lower()
    aliases = {
        "aarch64": "arm64",
        "amd64": "x86_64",
    }
    return aliases.get(normalized, normalized)


def release_platform_tag(
    system: str | None = None,
    machine: str | None = None,
    configured_platform: str | None = None,
) -> str:
    """Return the platform tag for a wheel containing a host-native extension.

    Free-threaded CPython on the GitHub arm64 macOS runner reports a universal2
    sysconfig platform even though Zig builds a host-native arm64 extension. A
    universal2 tag would therefore overstate the wheel compatibility. Keep the
    deployment target inferred while building the wheel, but use the
    architecture actually built.
    """
    host_system = system or platform.system()
    host_machine = normalize_machine(machine or platform.machine())
    configured = configured_platform or sysconfig.get_platform()
    tag = configured.replace("-", "_").replace(".", "_")

    if host_system == "Linux":
        return f"manylinux_2_17_{host_machine}.manylinux2014_{host_machine}"

    if host_system == "Darwin":
        if host_machine not in {"arm64", "x86_64"}:
            raise ValueError(f"unsupported macOS wheel architecture: {host_machine}")
        if not _MACOS_ARCH_SUFFIX.search(tag):
            raise ValueError(f"unrecognized macOS sysconfig platform: {tag}")
        return _MACOS_ARCH_SUFFIX.sub(f"_{host_machine}", tag)

    return tag


def required_macos_architectures(platform_tag: str) -> frozenset[str]:
    """Return the native slices a macOS wheel platform tag promises."""
    if platform_tag.endswith("_universal2"):
        return frozenset({"arm64", "x86_64"})
    if platform_tag.endswith("_arm64"):
        return frozenset({"arm64"})
    if platform_tag.endswith("_x86_64"):
        return frozenset({"x86_64"})
    raise ValueError(f"unsupported macOS wheel platform tag: {platform_tag}")


def macos_platform_floor(platform_tag: str) -> tuple[int, int, int]:
    """Return the deployment floor encoded by a macOS wheel platform tag."""
    match = _MACOS_PLATFORM.fullmatch(platform_tag)
    if match is None:
        raise ValueError(f"unsupported macOS wheel platform tag: {platform_tag}")
    return (
        int(match.group("major")),
        int(match.group("minor")),
        int(match.group("patch") or 0),
    )


def parse_macho_deployment_targets(output: str) -> tuple[tuple[int, int, int], ...]:
    """Parse deployment targets from ``otool -l`` output."""
    targets: list[tuple[int, int, int]] = []
    expected_field: str | None = None

    for raw_line in output.splitlines():
        line = raw_line.strip()
        if line == "cmd LC_BUILD_VERSION":
            expected_field = "minos"
            continue
        if line == "cmd LC_VERSION_MIN_MACOSX":
            expected_field = "version"
            continue
        if expected_field is None:
            continue
        if line.startswith("cmd "):
            raise ValueError(f"missing {expected_field} in Mach-O version load command")
        prefix = f"{expected_field} "
        if line.startswith(prefix):
            value = line.removeprefix(prefix).split()[0]
            parts = value.split(".")
            if not 2 <= len(parts) <= 3 or not all(part.isdigit() for part in parts):
                raise ValueError(f"invalid Mach-O deployment target: {value}")
            targets.append(tuple(int(part) for part in (*parts, "0")[:3]))
            expected_field = None

    if expected_field is not None:
        raise ValueError(f"missing {expected_field} in Mach-O version load command")
    if not targets:
        raise ValueError("Mach-O has no macOS deployment target load command")
    return tuple(targets)


def macos_platform_tag(
    deployment_target: tuple[int, int, int], architectures: frozenset[str]
) -> str:
    """Return a wheel tag that exactly represents a Mach-O compatibility floor."""
    major, minor, patch = deployment_target
    if patch:
        raise ValueError(
            f"Mach-O deployment target {major}.{minor}.{patch} cannot be represented "
            "exactly by a macOS wheel platform tag"
        )
    if architectures == {"arm64", "x86_64"}:
        architecture = "universal2"
    elif len(architectures) == 1:
        architecture = next(iter(architectures))
    else:
        raise ValueError(f"unsupported Mach-O architecture set: {sorted(architectures)}")
    required_macos_architectures(f"macosx_{major}_{minor}_{architecture}")
    return f"macosx_{major}_{minor}_{architecture}"


def inspect_macos_extension(
    extension: pathlib.Path,
) -> tuple[frozenset[str], dict[str, tuple[int, int, int]]]:
    """Return the native slices and deployment target of each Mach-O slice."""
    output = subprocess.check_output(["lipo", "-archs", extension], text=True)
    architectures = frozenset(normalize_machine(value) for value in output.split())
    if not architectures:
        raise ValueError(f"no Mach-O architectures found in {extension.name}")

    deployment_targets: dict[str, tuple[int, int, int]] = {}
    for architecture in sorted(architectures):
        load_commands = subprocess.check_output(
            ["otool", "-l", "-arch", architecture, extension], text=True
        )
        targets = set(parse_macho_deployment_targets(load_commands))
        if len(targets) != 1:
            raise ValueError(
                f"expected one macOS deployment target for {architecture}, found {sorted(targets)}"
            )
        deployment_targets[architecture] = next(iter(targets))
    return architectures, deployment_targets


def validate_macos_deployment_contract(
    platform_tag: str, deployment_targets: dict[str, tuple[int, int, int]]
) -> None:
    """Fail unless every Mach-O slice exactly matches the wheel platform floor."""
    platform_floor = macos_platform_floor(platform_tag)
    mismatches = {
        architecture: target
        for architecture, target in deployment_targets.items()
        if target != platform_floor
    }
    if mismatches:
        formatted = ", ".join(
            f"{architecture}={'.'.join(map(str, target))}"
            for architecture, target in sorted(mismatches.items())
        )
        raise ValueError(
            f"wheel platform floor {'.'.join(map(str, platform_floor))} does not "
            f"match Mach-O deployment target(s): {formatted}"
        )


def _wheel_platform_tags(wheel: pathlib.Path, archive: zipfile.ZipFile) -> set[str]:
    wheel_metadata = [name for name in archive.namelist() if name.endswith(".dist-info/WHEEL")]
    if len(wheel_metadata) != 1:
        raise ValueError(f"expected one WHEEL metadata file, found {wheel_metadata}")

    tags = set()
    for line in archive.read(wheel_metadata[0]).decode("utf-8").splitlines():
        if line.startswith("Tag: "):
            parts = line.removeprefix("Tag: ").split("-", 2)
            if len(parts) == 3:
                tags.add(parts[2])

    filename_platforms = set(wheel.name.removesuffix(".whl").rsplit("-", 1)[-1].split("."))
    if tags != filename_platforms:
        raise ValueError(
            f"wheel filename platforms {sorted(filename_platforms)} do not match "
            f"WHEEL metadata {sorted(tags)}"
        )
    return tags


def release_platform_tag_for_wheel(wheel: pathlib.Path) -> str:
    """Return a release tag using the native extension's real compatibility floor."""
    with zipfile.ZipFile(wheel) as archive:
        platform_tags = _wheel_platform_tags(wheel, archive)
        macos_tags = {tag for tag in platform_tags if tag.startswith("macosx_")}
        if not macos_tags:
            if len(platform_tags) != 1:
                raise ValueError(
                    f"expected one built-wheel platform tag, found {sorted(platform_tags)}"
                )
            return release_platform_tag(configured_platform=next(iter(platform_tags)))
        if len(macos_tags) != 1:
            raise ValueError(f"expected one macOS platform tag, found {sorted(macos_tags)}")

        extensions = [
            name
            for name in archive.namelist()
            if name.startswith("turboapi/turbonet") and name.endswith(".so")
        ]
        if len(extensions) != 1:
            raise ValueError(f"expected one turbonet extension, found {extensions}")
        with tempfile.TemporaryDirectory(prefix="turboapi-wheel-tag-") as tmp:
            extension = pathlib.Path(tmp) / pathlib.Path(extensions[0]).name
            extension.write_bytes(archive.read(extensions[0]))
            architectures, deployment_targets = inspect_macos_extension(extension)

    targets = set(deployment_targets.values())
    if len(targets) != 1:
        raise ValueError(f"Mach-O slices have different deployment targets: {deployment_targets}")
    return macos_platform_tag(next(iter(targets)), architectures)


def verify_macos_wheel(wheel: pathlib.Path) -> None:
    """Fail unless the wheel tag exactly matches every embedded Mach-O slice."""
    with zipfile.ZipFile(wheel) as archive:
        platform_tags = _wheel_platform_tags(wheel, archive)
        macos_tags = {tag for tag in platform_tags if tag.startswith("macosx_")}
        if not macos_tags:
            raise ValueError(f"wheel has no macOS platform tag: {sorted(platform_tags)}")
        if len(macos_tags) != 1:
            raise ValueError(f"expected one macOS platform tag, found {sorted(macos_tags)}")
        required = required_macos_architectures(next(iter(macos_tags)))

        extensions = [
            name
            for name in archive.namelist()
            if name.startswith("turboapi/turbonet") and name.endswith(".so")
        ]
        if len(extensions) != 1:
            raise ValueError(f"expected one turbonet extension, found {extensions}")

        with tempfile.TemporaryDirectory(prefix="turboapi-wheel-arch-") as tmp:
            extension = pathlib.Path(tmp) / pathlib.Path(extensions[0]).name
            extension.write_bytes(archive.read(extensions[0]))
            actual, deployment_targets = inspect_macos_extension(extension)

    if actual != required:
        raise ValueError(
            f"wheel platform promises {sorted(required)}, but {extensions[0]} contains "
            f"{sorted(actual)}"
        )
    platform_tag = next(iter(macos_tags))
    validate_macos_deployment_contract(platform_tag, deployment_targets)
    deployment_target = next(iter(set(deployment_targets.values())))
    print(
        f"macOS wheel verified: {wheel.name} -> {','.join(sorted(actual))}, "
        f"deployment={'.'.join(map(str, deployment_target))}"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    tag = subparsers.add_parser("tag", help="print the release platform tag")
    tag.add_argument("wheel", nargs="?", type=pathlib.Path)
    verify = subparsers.add_parser("verify", help="verify a built macOS wheel")
    verify.add_argument("wheel", type=pathlib.Path)
    args = parser.parse_args()

    if args.command in {None, "tag"}:
        if args.command == "tag" and args.wheel:
            print(release_platform_tag_for_wheel(args.wheel))
        else:
            print(release_platform_tag())
        return
    verify_macos_wheel(args.wheel)


if __name__ == "__main__":
    main()
