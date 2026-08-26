"""Regression tests for release wheel platform tagging."""

import subprocess
import zipfile

import pytest

from scripts.wheel_platform import (
    macos_platform_floor,
    normalize_machine,
    parse_macho_deployment_targets,
    release_platform_tag,
    release_platform_tag_for_wheel,
    required_macos_architectures,
    validate_macos_deployment_contract,
    verify_macos_wheel,
)
from zig.build_turbonet import macos_zig_target


def _write_macos_wheel(tmp_path, platform_tag):
    wheel = tmp_path / f"turboapi-1.0.0-cp314-cp314t-{platform_tag}.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr(
            "turboapi-1.0.0.dist-info/WHEEL",
            f"Wheel-Version: 1.0\nRoot-Is-Purelib: false\nTag: cp314-cp314t-{platform_tag}\n",
        )
        archive.writestr("turboapi/turbonet.cpython-314t-darwin.so", b"Mach-O fixture")
    return wheel


def _mock_macho_tools(monkeypatch, deployment_target="26.0"):
    def check_output(command, *, text):
        assert text is True
        if command[0] == "lipo":
            return "arm64\n"
        if command[:4] == ["otool", "-l", "-arch", "arm64"]:
            return f"""
Load command 10
      cmd LC_BUILD_VERSION
  cmdsize 32
 platform 1
    minos {deployment_target}
      sdk 26.5
"""
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr("scripts.wheel_platform.subprocess.check_output", check_output)


def test_arm64_macos_does_not_inherit_universal2_from_python():
    assert (
        release_platform_tag(
            system="Darwin",
            machine="arm64",
            configured_platform="macosx-10.15-universal2",
        )
        == "macosx_10_15_arm64"
    )


def test_macos_tag_preserves_built_wheel_deployment_target():
    assert (
        release_platform_tag(
            system="Darwin",
            machine="arm64",
            configured_platform="macosx-26.0-universal2",
        )
        == "macosx_26_0_arm64"
    )


def test_x86_64_macos_does_not_inherit_universal2_from_python():
    assert (
        release_platform_tag(
            system="Darwin",
            machine="x86_64",
            configured_platform="macosx-10.15-universal2",
        )
        == "macosx_10_15_x86_64"
    )


def test_linux_release_tag_is_unchanged():
    assert (
        release_platform_tag(
            system="Linux",
            machine="x86_64",
            configured_platform="linux-x86_64",
        )
        == "manylinux_2_17_x86_64.manylinux2014_x86_64"
    )


def test_machine_aliases_match_wheel_architecture_names():
    assert normalize_machine("aarch64") == "arm64"
    assert normalize_machine("AMD64") == "x86_64"


def test_macos_platform_tag_architecture_contract():
    assert required_macos_architectures("macosx_10_15_arm64") == {"arm64"}
    assert required_macos_architectures("macosx_10_15_x86_64") == {"x86_64"}
    assert required_macos_architectures("macosx_10_15_universal2") == {
        "arm64",
        "x86_64",
    }


def test_unknown_macos_architecture_fails_closed():
    with pytest.raises(ValueError, match="unsupported macOS wheel architecture"):
        release_platform_tag(
            system="Darwin",
            machine="powerpc",
            configured_platform="macosx-10.15-universal2",
        )


def test_macos_zig_target_pins_requested_deployment_floor():
    assert macos_zig_target("arm64", "26.0") == "aarch64-macos.26.0"
    assert macos_zig_target("x86_64", "14.0") == "x86_64-macos.14.0"


def test_macos_zig_target_rejects_invalid_input():
    with pytest.raises(ValueError, match="invalid macOS deployment target"):
        macos_zig_target("arm64", "latest")
    with pytest.raises(ValueError, match="unsupported macOS architecture"):
        macos_zig_target("powerpc", "26.0")


def test_parse_macho_deployment_targets_supports_current_and_legacy_commands():
    output = """
Load command 9
      cmd LC_BUILD_VERSION
  cmdsize 32
 platform 1
    minos 26.0
      sdk 26.5
Load command 10
      cmd LC_VERSION_MIN_MACOSX
  cmdsize 16
  version 10.15
      sdk 11.3
"""
    assert parse_macho_deployment_targets(output) == ((26, 0, 0), (10, 15, 0))


def test_macos_platform_floor_parses_wheel_tag():
    assert macos_platform_floor("macosx_26_0_arm64") == (26, 0, 0)


def test_macos_deployment_contract_rejects_understated_wheel_floor():
    with pytest.raises(ValueError, match="does not match Mach-O deployment target"):
        validate_macos_deployment_contract("macosx_26_0_arm64", {"arm64": (26, 5, 2)})


def test_release_tag_is_derived_from_native_macho(monkeypatch, tmp_path):
    wheel = _write_macos_wheel(tmp_path, "macosx_26_0_universal2")
    _mock_macho_tools(monkeypatch, "26.0")
    assert release_platform_tag_for_wheel(wheel) == "macosx_26_0_arm64"


def test_artifact_verifier_accepts_exact_macho_floor(monkeypatch, tmp_path):
    wheel = _write_macos_wheel(tmp_path, "macosx_26_0_arm64")
    _mock_macho_tools(monkeypatch, "26.0")
    verify_macos_wheel(wheel)


def test_artifact_verifier_rejects_published_v1034_mismatch(monkeypatch, tmp_path):
    wheel = _write_macos_wheel(tmp_path, "macosx_26_0_arm64")
    _mock_macho_tools(monkeypatch, "26.5.2")
    with pytest.raises(ValueError, match="does not match Mach-O deployment target"):
        verify_macos_wheel(wheel)
