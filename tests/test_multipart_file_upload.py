import pytest
from turboapi import File, Form, TurboAPI, UploadFile
from turboapi.testclient import TestClient


@pytest.fixture
def app():
    return TurboAPI()


@pytest.fixture
def client(app):
    return TestClient(app)


class TestFormParsing:
    def test_form_field_urlencoded(self, app, client):
        @app.post("/login")
        def login(username: str = Form(), password: str = Form()):
            return {"username": username, "password": password}

        resp = client.post("/login", data={"username": "alice", "password": "secret"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["username"] == "alice"
        assert body["password"] == "secret"

    def test_form_field_with_default(self, app, client):
        @app.post("/search")
        def search(q: str = Form(), limit: int = Form(default=10)):
            return {"q": q, "limit": limit}

        resp = client.post("/search", data={"q": "hello"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["q"] == "hello"

    def test_form_field_with_alias(self, app, client):
        @app.post("/items")
        def create_item(item_name: str = Form(alias="item-name")):
            return {"item_name": item_name}

        resp = client.post("/items", data={"item-name": "Widget"})
        assert resp.status_code == 200
        assert resp.json()["item_name"] == "Widget"


class TestFileUpload:
    def test_file_upload_basic(self, app, client):
        @app.post("/upload")
        def upload(file: UploadFile = File()):
            return {"filename": file.filename, "size": file.size}

        content = b"hello world from turboapi"
        resp = client.post("/upload", files={"file": ("test.txt", content, "text/plain")})
        assert resp.status_code == 200
        body = resp.json()
        assert body["filename"] == "test.txt"
        assert body["size"] == len(content)

    def test_file_upload_byte_identical(self, app, client):
        @app.post("/upload")
        def upload(file: UploadFile = File()):
            return file.file.read()

        raw_bytes = bytes(range(256))
        resp = client.post(
            "/upload", files={"file": ("binary.bin", raw_bytes, "application/octet-stream")}
        )
        assert resp.status_code == 200
        assert resp.content == raw_bytes

    def test_file_upload_with_form_field(self, app, client):
        @app.post("/upload")
        def upload(file: UploadFile = File(), description: str = Form()):
            return {"filename": file.filename, "description": description}

        content = b"file content here"
        resp = client.post(
            "/upload",
            files={"file": ("doc.txt", content, "text/plain")},
            data={"description": "My document"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["filename"] == "doc.txt"
        assert body["description"] == "My document"

    def test_multiple_file_uploads(self, app, client):
        @app.post("/upload")
        def upload(file1: UploadFile = File(), file2: UploadFile = File()):
            return {
                "file1": file1.filename,
                "file2": file2.filename,
            }

        resp = client.post(
            "/upload",
            files={
                "file1": ("a.txt", b"aaa", "text/plain"),
                "file2": ("b.txt", b"bbb", "text/plain"),
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["file1"] == "a.txt"
        assert body["file2"] == "b.txt"

    def test_file_upload_binary_content(self, app, client):
        @app.post("/upload")
        def upload(file: UploadFile = File()):
            return file.file.read()

        png_header = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        resp = client.post("/upload", files={"file": ("image.png", png_header, "image/png")})
        assert resp.status_code == 200
        assert resp.content == png_header

    def test_upload_file_type_annotation(self, app, client):
        @app.post("/upload")
        def upload(file: UploadFile):
            return {"filename": file.filename, "size": file.size}

        content = b"typed upload"
        resp = client.post("/upload", files={"file": ("data.bin", content)})
        assert resp.status_code == 200
        body = resp.json()
        assert body["filename"] == "data.bin"
        assert body["size"] == len(content)


class TestByteLevelParity:
    def test_text_file_round_trip(self, app, client):
        @app.post("/echo")
        def echo(file: UploadFile = File()):
            return file.file.read()

        text = "Hello, World! \u00e9\u00e8\u00ea\nLine 2\tTabbed"
        encoded = text.encode("utf-8")
        resp = client.post("/echo", files={"file": ("hello.txt", encoded, "text/plain")})
        assert resp.status_code == 200
        assert resp.content == encoded

    def test_large_file_round_trip(self, app, client):
        @app.post("/echo")
        def echo(file: UploadFile = File()):
            return file.file.read()

        large = b"A" * 100_000
        resp = client.post("/echo", files={"file": ("large.bin", large)})
        assert resp.status_code == 200
        assert resp.content == large

    def test_empty_file_upload(self, app, client):
        @app.post("/upload")
        def upload(file: UploadFile = File()):
            return {"filename": file.filename, "size": file.size}

        resp = client.post("/upload", files={"file": ("empty.txt", b"", "text/plain")})
        assert resp.status_code == 200
        body = resp.json()
        assert body["filename"] == "empty.txt"
        assert body["size"] == 0

    def test_null_bytes_in_file(self, app, client):
        @app.post("/echo")
        def echo(file: UploadFile = File()):
            return file.file.read()

        content = b"\x00\x01\x02\x00\xff\xfe"
        resp = client.post("/echo", files={"file": ("nulls.bin", content)})
        assert resp.status_code == 200
        assert resp.content == content


class TestUrlencodedParsing:
    def test_special_characters(self, app, client):
        @app.post("/form")
        def form_handler(q: str = Form()):
            return {"q": q}

        resp = client.post("/form", data={"q": "hello world & more=yes"})
        assert resp.status_code == 200
        assert resp.json()["q"] == "hello world & more=yes"

    def test_percent_encoded(self, app, client):
        @app.post("/form")
        def form_handler(email: str = Form()):
            return {"email": email}

        resp = client.post("/form", data={"email": "test@example.com"})
        assert resp.status_code == 200
        assert resp.json()["email"] == "test@example.com"
