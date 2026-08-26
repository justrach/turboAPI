"""Regression tests for release wheel platform tagging."""

import pytest

from scripts.wheel_platform import (
    normalize_machine,
    release_platform_tag,
    required_macos_architectures,
)


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
