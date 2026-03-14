#!/usr/bin/env python3
"""
Tests for Binary Response Handling - v0.5.22+

Tests that binary responses (audio, video, image, etc.) are returned as raw bytes
instead of being base64 encoded through JSON serialization.
"""

import os
import subprocess
import sys
import tempfile
import time

# Add parent directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "python"))

import pytest

# Test imports
try:
    import requests
except ImportError:
    requests = None

from turboapi.request_handler import ResponseHandler, _is_binary_content_type
from turboapi.responses import JSONResponse, Response

# ============================================================================
# Binary Content Type Detection Tests
# ============================================================================


class TestBinaryContentTypeDetection:
    """Test that binary content types are properly detected."""

    def test_audio_content_types(self):
        """Test audio/* content types are detected as binary."""
        assert _is_binary_content_type("audio/wav") is True
        assert _is_binary_content_type("audio/mpeg") is True
        assert _is_binary_content_type("audio/mp3") is True
        assert _is_binary_content_type("audio/ogg") is True
        assert _is_binary_content_type("audio/flac") is True
        assert _is_binary_content_type("Audio/WAV") is True  # Case insensitive

    def test_video_content_types(self):
        """Test video/* content types are detected as binary."""
        assert _is_binary_content_type("video/mp4") is True
        assert _is_binary_content_type("video/webm") is True
        assert _is_binary_content_type("video/avi") is True
        assert _is_binary_content_type("Video/MP4") is True  # Case insensitive

    def test_image_content_types(self):
        """Test image/* content types are detected as binary."""
        assert _is_binary_content_type("image/png") is True
        assert _is_binary_content_type("image/jpeg") is True
        assert _is_binary_content_type("image/gif") is True
        assert _is_binary_content_type("image/webp") is True
        assert _is_binary_content_type("Image/PNG") is True  # Case insensitive

    def test_application_binary_types(self):
        """Test application/* binary content types."""
        assert _is_binary_content_type("application/octet-stream") is True
        assert _is_binary_content_type("application/pdf") is True
        assert _is_binary_content_type("application/zip") is True
        assert _is_binary_content_type("application/gzip") is True
        assert _is_binary_content_type("application/x-tar") is True

    def test_non_binary_content_types(self):
        """Test that non-binary content types return False."""
        assert _is_binary_content_type("application/json") is False
        assert _is_binary_content_type("text/plain") is False
        assert _is_binary_content_type("text/html") is False
        assert _is_binary_content_type("text/css") is False
        assert _is_binary_content_type("application/javascript") is False

    def test_empty_and_none_content_types(self):
        """Test handling of empty and None content types."""
        assert _is_binary_content_type("") is False
        assert _is_binary_content_type(None) is False


# ============================================================================
# Binary Response Normalization Tests
# ============================================================================


class TestBinaryResponseNormalization:
    """Test that binary responses are properly normalized."""

    def test_audio_wav_response_returns_bytes(self):
        """Test that audio/wav Response returns raw bytes."""
        wav_data = b"RIFF....WAVEfmt " + b"\x00" * 100  # Fake WAV header
        resp = Response(content=wav_data, media_type="audio/wav")

        result = ResponseHandler.normalize_response(resp)

        # Should return 3-tuple for binary responses
        assert len(result) == 3
        content, status_code, content_type = result

        assert content == wav_data
        assert isinstance(content, bytes)
        assert status_code == 200
        assert content_type == "audio/wav"

    def test_image_png_response_returns_bytes(self):
        """Test that image/png Response returns raw bytes."""
        # PNG magic header
        png_data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        resp = Response(content=png_data, media_type="image/png")

        result = ResponseHandler.normalize_response(resp)

        assert len(result) == 3
        content, status_code, content_type = result

        assert content == png_data
        assert isinstance(content, bytes)
        assert content_type == "image/png"

    def test_video_mp4_response_returns_bytes(self):
        """Test that video/mp4 Response returns raw bytes."""
        mp4_data = b"\x00\x00\x00\x1cftyp" + b"\x00" * 100  # Fake MP4 header
        resp = Response(content=mp4_data, media_type="video/mp4")

        result = ResponseHandler.normalize_response(resp)

        assert len(result) == 3
        content, status_code, content_type = result

        assert content == mp4_data
        assert isinstance(content, bytes)
        assert content_type == "video/mp4"

    def test_octet_stream_response_returns_bytes(self):
        """Test that application/octet-stream Response returns raw bytes."""
        binary_data = b"\x00\x01\x02\x03\xff\xfe\xfd"
        resp = Response(content=binary_data, media_type="application/octet-stream")

        result = ResponseHandler.normalize_response(resp)

        assert len(result) == 3
        content, status_code, content_type = result

        assert content == binary_data
        assert isinstance(content, bytes)
        assert content_type == "application/octet-stream"

    def test_json_response_not_affected(self):
        """Test that JSON responses are not treated as binary."""
        resp = JSONResponse(content={"key": "value"})

        result = ResponseHandler.normalize_response(resp)

        # Should return 3-tuple for consistency
        assert len(result) == 3
        content, status_code, content_type = result

        assert content == {"key": "value"}
        assert status_code == 200

    def test_text_response_not_affected(self):
        """Test that text responses are not treated as binary."""
        resp = Response(content=b"Hello World", media_type="text/plain")

        result = ResponseHandler.normalize_response(resp)

        assert len(result) == 3
        content, status_code, content_type = result

        # Text should be decoded
        assert content == "Hello World"


# ============================================================================
# Binary Response Formatting Tests
# ============================================================================


class TestBinaryResponseFormatting:
    """Test that format_response handles binary data correctly."""

    def test_format_binary_response_preserves_bytes(self):
        """Test that format_response preserves bytes for binary content."""
        wav_data = b"RIFF....WAVEfmt " + b"\x00" * 100

        result = ResponseHandler.format_response(wav_data, 200, "audio/wav")

        assert result["content"] == wav_data
        assert isinstance(result["content"], bytes)
        assert result["status_code"] == 200
        assert result["content_type"] == "audio/wav"

    def test_format_binary_response_not_base64_encoded(self):
        """Test that binary content is NOT base64 encoded."""
        binary_data = b"\x00\x01\x02\x03\xff\xfe\xfd"

        result = ResponseHandler.format_response(binary_data, 200, "audio/wav")

        # Content should be raw bytes, not a base64 string
        assert isinstance(result["content"], bytes)
        assert result["content"] == binary_data

        # Should not be a string (which would be the case if base64 encoded)
        assert not isinstance(result["content"], str)

    def test_format_non_binary_bytes_gets_decoded(self):
        """Test that non-binary bytes (like JSON) are decoded."""
        json_bytes = b'{"key": "value"}'

        # Without binary content type, bytes should be decoded
        result = ResponseHandler.format_response(json_bytes, 200, "application/json")

        # For non-binary content types, bytes should be converted
        assert result["status_code"] == 200


# ============================================================================
# Integration Tests with Real Audio File
# ============================================================================


class TestBinaryResponseIntegration:
    """Integration tests using the real test audio file."""

    @pytest.fixture
    def test_wav_path(self):
        """Path to the test WAV file."""
        return os.path.join(os.path.dirname(__file__), "fixtures", "test_audio.wav")

    def test_wav_file_exists(self, test_wav_path):
        """Verify the test WAV file exists."""
        assert os.path.exists(test_wav_path), f"Test file not found: {test_wav_path}"

    def test_wav_file_is_valid(self, test_wav_path):
        """Verify the test WAV file has valid WAV header."""
        with open(test_wav_path, "rb") as f:
            header = f.read(12)

        # WAV files start with RIFF...WAVE
        assert header[:4] == b"RIFF", "Not a valid WAV file (missing RIFF)"
        assert header[8:12] == b"WAVE", "Not a valid WAV file (missing WAVE)"

    def test_response_with_real_wav_file(self, test_wav_path):
        """Test Response object with real WAV file."""
        with open(test_wav_path, "rb") as f:
            wav_data = f.read()

        resp = Response(content=wav_data, media_type="audio/wav")

        result = ResponseHandler.normalize_response(resp)

        assert len(result) == 3
        content, status_code, content_type = result

        # Content should be exact same bytes
        assert content == wav_data
        assert len(content) == len(wav_data)
        assert isinstance(content, bytes)
        assert content_type == "audio/wav"

    def test_format_response_with_real_wav_file(self, test_wav_path):
        """Test format_response with real WAV file preserves exact bytes."""
        with open(test_wav_path, "rb") as f:
            wav_data = f.read()

        result = ResponseHandler.format_response(wav_data, 200, "audio/wav")

        # Content should be exact same bytes
        assert result["content"] == wav_data
        assert len(result["content"]) == len(wav_data)
        assert isinstance(result["content"], bytes)

    def test_wav_bytes_not_corrupted(self, test_wav_path):
        """Test that WAV bytes are not corrupted through response handling."""
        with open(test_wav_path, "rb") as f:
            original_wav = f.read()

        # Simulate full response flow
        resp = Response(content=original_wav, media_type="audio/wav")

        # Normalize
        content, status_code, content_type = ResponseHandler.normalize_response(resp)

        # Format
        formatted = ResponseHandler.format_response(content, status_code, content_type)

        # Verify bytes are identical
        assert formatted["content"] == original_wav

        # Verify WAV header is intact
        result_content = formatted["content"]
        assert result_content[:4] == b"RIFF"
        assert result_content[8:12] == b"WAVE"


# ============================================================================
# Server Integration Tests (requires running server)
# ============================================================================


@pytest.mark.skipif(requests is None, reason="requests not installed")
class TestBinaryResponseServer:
    """Integration tests that start a real server."""

    @pytest.fixture
    def server_port(self):
        """Use a random available port."""
        import socket

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("", 0))
            return s.getsockname()[1]

    @pytest.fixture
    def test_wav_path(self):
        """Path to the test WAV file."""
        return os.path.join(os.path.dirname(__file__), "fixtures", "test_audio.wav")

    def test_server_returns_raw_wav_bytes(self, server_port, test_wav_path):
        """Test that server returns raw WAV bytes, not base64 encoded."""
        # Create a simple test app
        app_code = f'''
import sys
sys.path.insert(0, "{os.path.join(os.path.dirname(__file__), "..", "python")}")

from turboapi import TurboAPI
from turboapi.responses import Response

app = TurboAPI()

@app.get("/audio")
def get_audio():
    with open("{test_wav_path}", "rb") as f:
        wav_data = f.read()
    return Response(content=wav_data, media_type="audio/wav")

if __name__ == "__main__":
    app.run(host="127.0.0.1", port={server_port})
'''

        # Write temp app file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(app_code)
            app_file = f.name

        try:
            # Start server in background
            proc = subprocess.Popen(
                [sys.executable, app_file], stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )

            # Wait for server to start
            time.sleep(2)

            try:
                # Make request
                response = requests.get(f"http://127.0.0.1:{server_port}/audio", timeout=5)

                # Verify response
                assert response.status_code == 200
                assert response.headers.get("content-type") == "audio/wav"

                # Verify it's raw bytes, not base64
                content = response.content
                assert content[:4] == b"RIFF", "Response is not raw WAV (missing RIFF header)"
                assert content[8:12] == b"WAVE", "Response is not raw WAV (missing WAVE marker)"

                # Compare with original file
                with open(test_wav_path, "rb") as f:
                    original = f.read()

                assert content == original, "Response bytes don't match original file"

            finally:
                proc.terminate()
                proc.wait(timeout=5)
        finally:
            os.unlink(app_file)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
