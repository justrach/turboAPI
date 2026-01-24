"""
Test Dhi 1.1.0 compatibility with TurboAPI.

Dhi provides a Pydantic v2 compatible BaseModel with high-performance
validation powered by Zig/C native extensions.
"""

import pytest
from dhi import BaseModel, Field, ValidationError, field_validator
from turboapi.models import TurboRequest, TurboResponse


class TestDhiFieldAccess:
    """Test field access behavior in Dhi BaseModel."""

    def test_field_without_constraints(self):
        """Fields without Field() should work normally."""
        class SimpleModel(BaseModel):
            name: str
            age: int

        obj = SimpleModel(name="Alice", age=30)
        assert obj.name == "Alice"
        assert obj.age == 30
        assert isinstance(obj.name, str)
        assert isinstance(obj.age, int)

    def test_field_with_constraints(self):
        """Fields with Field() constraints return values directly."""
        class ConstrainedModel(BaseModel):
            age: int = Field(ge=0, le=150)

        obj = ConstrainedModel(age=30)
        assert obj.age == 30
        assert isinstance(obj.age, int)
        assert obj.age + 5 == 35

    def test_field_with_description(self):
        """Fields with Field(description=...) return values directly."""
        class DescribedModel(BaseModel):
            name: str = Field(description="User name")
            age: int = Field(ge=0, description="User age")

        obj = DescribedModel(name="Alice", age=30)
        assert obj.name == "Alice"
        assert obj.age == 30
        assert isinstance(obj.name, str)
        assert isinstance(obj.age, int)

    def test_field_arithmetic(self):
        """Field values support arithmetic operations directly."""
        class NumericModel(BaseModel):
            x: int = Field(ge=0, description="X coordinate")
            y: float = Field(description="Y coordinate")

        obj = NumericModel(x=10, y=3.14)
        assert obj.x * 2 == 20
        assert obj.y > 3.0

    def test_model_dump_works(self):
        """model_dump() should work correctly."""
        class TestModel(BaseModel):
            name: str = Field(description="Name")
            age: int = Field(ge=0, description="Age")

        obj = TestModel(name="Alice", age=30)
        dumped = obj.model_dump()

        assert dumped == {"name": "Alice", "age": 30}
        assert isinstance(dumped["name"], str)
        assert isinstance(dumped["age"], int)

    def test_model_dump_json(self):
        """model_dump_json() provides JSON serialization."""
        class TestModel(BaseModel):
            name: str = Field(description="Name")
            age: int = Field(ge=0, description="Age")

        obj = TestModel(name="Alice", age=30)
        json_str = obj.model_dump_json()

        assert isinstance(json_str, str)
        assert '"name"' in json_str
        assert '"Alice"' in json_str
        assert '"age"' in json_str
        assert "30" in json_str


class TestTurboRequestCompatibility:
    """Test TurboRequest with Dhi BaseModel."""

    def test_turbo_request_creation(self):
        """TurboRequest should create successfully with direct field access."""
        req = TurboRequest(
            method="GET",
            path="/test",
            query_string="foo=bar",
            headers={"content-type": "application/json"},
            path_params={"id": "123"},
            query_params={"foo": "bar"},
            body=b'{"test": "data"}'
        )

        assert req.method == "GET"
        assert req.path == "/test"
        assert req.query_string == "foo=bar"

    def test_turbo_request_get_header(self):
        """get_header() method should work."""
        req = TurboRequest(
            method="GET",
            path="/test",
            headers={"Content-Type": "application/json", "X-API-Key": "secret"}
        )

        content_type = req.get_header("content-type")
        assert content_type == "application/json"

        api_key = req.get_header("x-api-key")
        assert api_key == "secret"

    def test_turbo_request_json_parsing(self):
        """JSON parsing should work."""
        req = TurboRequest(
            method="POST",
            path="/api/users",
            body=b'{"name": "Alice", "age": 30}'
        )

        data = req.json()
        assert data == {"name": "Alice", "age": 30}

    def test_turbo_request_properties(self):
        """Properties should work with direct field access."""
        req = TurboRequest(
            method="POST",
            path="/test",
            headers={"content-type": "application/json"},
            body=b'{"test": "data"}'
        )

        assert req.content_type == "application/json"
        assert req.content_length == len(b'{"test": "data"}')

    def test_turbo_request_model_dump(self):
        """model_dump() on TurboRequest should serialize correctly."""
        req = TurboRequest(
            method="POST",
            path="/api/data",
            headers={"x-custom": "value"},
            body=b"hello"
        )

        dumped = req.model_dump()
        assert dumped["method"] == "POST"
        assert dumped["path"] == "/api/data"
        assert dumped["headers"] == {"x-custom": "value"}


class TestTurboResponseCompatibility:
    """Test TurboResponse with Dhi BaseModel."""

    def test_turbo_response_creation(self):
        """TurboResponse should create successfully with direct field access."""
        resp = TurboResponse(
            content="Hello, World!",
            status_code=200,
            headers={"content-type": "text/plain"}
        )

        assert resp.status_code == 200
        assert resp.content == "Hello, World!"

    def test_turbo_response_json_method(self):
        """TurboResponse.json() should work."""
        resp = TurboResponse.json(
            {"message": "Success", "data": [1, 2, 3]},
            status_code=200
        )

        dumped = resp.model_dump()
        assert dumped["status_code"] == 200
        assert "application/json" in dumped["headers"]["content-type"]

    def test_turbo_response_body_property(self):
        """body property should work."""
        resp = TurboResponse(content="Hello")
        body = resp.body
        assert body == b"Hello"

    def test_turbo_response_dict_content(self):
        """Dict content should serialize to JSON via body property."""
        resp = TurboResponse(content={"key": "value"})

        assert resp.content == {"key": "value"}
        body = resp.body
        assert b'"key"' in body
        assert b'"value"' in body


class TestDhiFeatures:
    """Test Dhi features including Pydantic v2 compatible API."""

    def test_model_validate(self):
        """Test model_validate() classmethod."""
        class User(BaseModel):
            name: str
            age: int = Field(ge=0, le=150)

        user = User.model_validate({"name": "Alice", "age": 30})
        assert user.name == "Alice"
        assert user.age == 30

    def test_model_json_schema(self):
        """Test model_json_schema() for OpenAPI compatibility."""
        class User(BaseModel):
            name: str = Field(description="User name", min_length=1)
            age: int = Field(ge=0, le=150, description="User age")

        schema = User.model_json_schema()
        assert schema["title"] == "User"
        assert schema["type"] == "object"
        assert "name" in schema["properties"]
        assert "age" in schema["properties"]

    def test_model_copy(self):
        """Test model_copy() with updates."""
        class User(BaseModel):
            name: str
            age: int

        user = User(name="Alice", age=30)
        updated = user.model_copy(update={"age": 31})
        assert updated.name == "Alice"
        assert updated.age == 31
        assert user.age == 30  # Original unchanged

    def test_model_dump_json(self):
        """Test model_dump_json() serialization."""
        class User(BaseModel):
            name: str
            age: int = Field(ge=0)
            email: str = Field(description="Email address")

        user = User(name="Alice", age=30, email="alice@example.com")
        json_str = user.model_dump_json()

        assert isinstance(json_str, str)
        assert "Alice" in json_str
        assert "30" in json_str
        assert "alice@example.com" in json_str

    def test_field_validator(self):
        """Test field_validator decorator."""
        class User(BaseModel):
            name: str
            email: str

            @field_validator('name')
            @classmethod
            def name_must_not_be_empty(cls, v):
                if not v.strip():
                    raise ValueError('name cannot be empty')
                return v.strip()

        user = User(name="  Alice  ", email="a@b.com")
        assert user.name == "Alice"

    def test_default_factory(self):
        """Test default_factory support (requires Annotated pattern)."""
        from typing import Annotated

        class Config(BaseModel):
            tags: Annotated[list, Field(default_factory=list)]
            metadata: Annotated[dict, Field(default_factory=dict)]

        c1 = Config()
        c2 = Config()

        c1.tags.append("admin")
        assert c1.tags == ["admin"]
        assert c2.tags == []

    def test_constraint_validation(self):
        """Test field constraints are properly enforced (Annotated pattern)."""
        from typing import Annotated

        class Bounded(BaseModel):
            value: Annotated[int, Field(ge=0, le=100)]
            name: Annotated[str, Field(min_length=2, max_length=50)]

        obj = Bounded(value=50, name="test")
        assert obj.value == 50
        assert obj.name == "test"

        with pytest.raises(Exception):
            Bounded(value=-1, name="test")

        with pytest.raises(Exception):
            Bounded(value=50, name="x")  # too short

    def test_model_dump_exclude_include(self):
        """Test model_dump with exclude/include parameters."""
        class User(BaseModel):
            name: str
            age: int
            email: str

        user = User(name="Alice", age=30, email="a@b.com")

        partial = user.model_dump(include={"name", "age"})
        assert partial == {"name": "Alice", "age": 30}

        without_email = user.model_dump(exclude={"email"})
        assert without_email == {"name": "Alice", "age": 30}

    def test_annotated_field_pattern(self):
        """Test Annotated[type, Field(...)] pattern (Pydantic v2 style)."""
        from typing import Annotated

        class User(BaseModel):
            name: Annotated[str, Field(min_length=1, max_length=100)]
            age: Annotated[int, Field(ge=0, le=150)]

        user = User(name="Alice", age=30)
        assert user.name == "Alice"
        assert user.age == 30


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
