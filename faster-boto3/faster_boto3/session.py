"""boto3-compatible session wrapper with optional native S3 clients."""

from __future__ import annotations

import os

import boto3 as _boto3

from .native_s3 import NativeS3Client


def _native_mode(service_name: str) -> str:
    raw = os.getenv("FASTER_BOTO3_NATIVE", "").strip().lower()
    if raw in {"", "0", "false", "off", "legacy"}:
        return "legacy"
    if raw in {"1", "true", "on", "all", "native"}:
        return "native"
    if raw in {"shadow", "native_shadow"}:
        return "native_shadow"
    enabled = {part.strip() for part in raw.split(",") if part.strip()}
    if service_name in enabled:
        return "native"
    if f"{service_name}:shadow" in enabled:
        return "native_shadow"
    return "legacy"


def _parse_mode_list(raw: str, *, default_mode: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in raw.split(","):
        item = part.strip().lower()
        if not item:
            continue
        if ":" in item:
            name, mode = item.split(":", 1)
            if mode in {"legacy", "native", "native_shadow", "shadow"}:
                out[name] = "native_shadow" if mode == "shadow" else mode
            continue
        out[item] = default_mode
    return out


def _native_operation_modes(service_name: str) -> dict[str, str]:
    prefix = f"FASTER_BOTO3_NATIVE_{service_name.upper()}_OPS"
    ops = {}
    ops.update(_parse_mode_list(os.getenv(prefix, ""), default_mode="native"))
    ops.update(
        _parse_mode_list(
            os.getenv(f"{prefix}_SHADOW", ""),
            default_mode="native_shadow",
        )
    )
    ops.update(
        _parse_mode_list(
            os.getenv(f"{prefix}_LEGACY", ""),
            default_mode="legacy",
        )
    )
    return ops


class Session:
    """Thin wrapper around boto3.Session that can return native clients."""

    def __init__(self, *args, **kwargs):
        self._session = _boto3.session.Session(*args, **kwargs)

    def client(
        self,
        service_name,
        region_name=None,
        api_version=None,
        use_ssl=True,
        verify=None,
        endpoint_url=None,
        aws_access_key_id=None,
        aws_secret_access_key=None,
        aws_session_token=None,
        config=None,
        aws_account_id=None,
    ):
        create_client_kwargs = {
            "region_name": region_name,
            "api_version": api_version,
            "use_ssl": use_ssl,
            "verify": verify,
            "endpoint_url": endpoint_url,
            "aws_access_key_id": aws_access_key_id,
            "aws_secret_access_key": aws_secret_access_key,
            "aws_session_token": aws_session_token,
            "config": config,
            "aws_account_id": aws_account_id,
        }
        if aws_account_id is None:
            del create_client_kwargs["aws_account_id"]

        fallback = self._session.client(service_name, **create_client_kwargs)
        mode = _native_mode(service_name)
        operation_modes = _native_operation_modes(service_name)
        if service_name != "s3" or (mode == "legacy" and not operation_modes):
            return fallback

        return NativeS3Client.from_botocore_client(
            fallback,
            mode=mode,
            operation_modes=operation_modes,
        )

    def resource(self, *args, **kwargs):
        return self._session.resource(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._session, name)
