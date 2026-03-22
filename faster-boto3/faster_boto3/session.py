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
        if service_name != "s3" or mode == "legacy":
            return fallback

        return NativeS3Client.from_botocore_client(fallback, mode=mode)

    def resource(self, *args, **kwargs):
        return self._session.resource(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._session, name)
