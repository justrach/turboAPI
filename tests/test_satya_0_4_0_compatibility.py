"""
Test Satya 0.5.1 compatibility with TurboAPI.

Satya 0.5.1 includes the TurboValidator architecture (1.17× faster than Pydantic v2)
and fixes the Field descriptor bug from 0.4.0 (field access now returns values directly).
"""

import pytest
from satya import Model, Field
from turboapi.models import TurboRequest, TurboResponse


class TestSatyaFieldAccess:
    """Test field access behavior in Satya 0.5.1 (descriptor bug fixed)."""

    def test_field_without_constraints(self):
        """Fields without Field() should work normally."""
        class SimpleModel(Model):
            name: str
            age: int

        obj = SimpleModel(name="Alice", age=30)
        assert obj.name == "Alice"
        assert obj.age == 30
        assert isinstance(obj.name, str)
        assert isinstance(obj.age, int)

    def test_field_with_constraints(self):
        """Fields with Field() constraints return values directly (fixed in 0.4.12+)."""
        class ConstrainedModel(Model):
            age: int = Field(ge=0, le=150)

        obj = ConstrainedModel(age=30)
        # Direct access works correctly in 0.5.1
        assert obj.age == 30
        assert isinstance(obj.age, int)
        assert obj.age + 5 == 35

    def test_field_with_description(self):
        """Fields with Field(description=...) return values directly."""
        class DescribedModel(Model):
            name: str = Field(description="User name")
            age: int = Field(ge=0, description="User age")

        obj = DescribedModel(name="Alice", age=30)

        # Direct field access works in 0.5.1 (no __dict__ workaround needed)
        assert obj.name == "Alice"
        assert obj.age == 30
        assert isinstance(obj.name, str)
        assert isinstance(obj.age, int)

    def test_field_arithmetic(self):
        """Field values support arithmetic operations directly."""
        class NumericModel(Model):
            x: int = Field(ge=0, description="X coordinate")
            y: float = Field(description="Y coordinate")

        obj = NumericModel(x=10, y=3.14)
        assert obj.x * 2 == 20
        assert obj.y > 3.0

    def test_model_dump_works(self):
        """model_dump() should work correctly."""
        class TestModel(Model):
            name: str = Field(description="Name")
            age: int = Field(ge=0, description="Age")

        obj = TestModel(name="Alice", age=30)
        dumped = obj.model_dump()

        assert dumped == {"name": "Alice", "age": 30}
        assert isinstance(dumped["name"], str)
        assert isinstance(dumped["age"], int)

    def test_model_dump_json(self):
        """model_dump_json() provides fast Rust-powered JSON serialization."""
        class TestModel(Model):
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
    """Test TurboRequest with Satya 0.5.1."""

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

        # Direct access works in 0.5.1
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
    """Test TurboResponse with Satya 0.5.1."""

    def test_turbo_response_creation(self):
        """TurboResponse should create successfully with direct field access."""
        resp = TurboResponse(
            content="Hello, World!",
            status_code=200,
            headers={"content-type": "text/plain"}
        )

        # Direct access works in 0.5.1
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

        # content stores the raw value
        assert resp.content == {"key": "value"}
        # body property serializes to JSON bytes
        body = resp.body
        assert b'"key"' in body
        assert b'"value"' in body


class TestSatya051Features:
    """Test Satya 0.5.1 features including TurboValidator performance."""

    def test_model_validate(self):
        """Test standard model_validate()."""
        class User(Model):
            name: str
            age: int = Field(ge=0, le=150)

        user = User.model_validate({"name": "Alice", "age": 30})
        assert user.name == "Alice"
        assert user.age == 30

    def test_model_validate_fast(self):
        """Test model_validate_fast() (optimized validation path)."""
        class User(Model):
            name: str
            age: int = Field(ge=0, le=150)

        user = User.model_validate_fast({"name": "Alice", "age": 30})
        assert user.name == "Alice"
        assert user.age == 30

    def test_validate_many(self):
        """Test batch validation with validate_many()."""
        class User(Model):
            name: str
            age: int = Field(ge=0, le=150)

        users_data = [
            {"name": "Alice", "age": 30},
            {"name": "Bob", "age": 25},
            {"name": "Charlie", "age": 35}
        ]

        users = User.validate_many(users_data)
        assert len(users) == 3
        assert users[0].name == "Alice"
        assert users[1].name == "Bob"
        assert users[2].age == 35

    def test_model_dump_json_fast(self):
        """Test model_dump_json() uses Rust fast path for serialization."""
        class User(Model):
            name: str
            age: int = Field(ge=0)
            email: str = Field(description="Email address")

        user = User(name="Alice", age=30, email="alice@example.com")
        json_str = user.model_dump_json()

        assert isinstance(json_str, str)
        assert "Alice" in json_str
        assert "30" in json_str
        assert "alice@example.com" in json_str

    def test_model_validate_json_bytes(self):
        """Test streaming JSON bytes validation."""
        class User(Model):
            name: str
            age: int

        user = User.model_validate_json_bytes(
            b'{"name": "Alice", "age": 30}',
            streaming=True
        )
        assert user.name == "Alice"
        assert user.age == 30

    def test_nested_model_validation(self):
        """Test nested model validation works correctly."""
        class Address(Model):
            street: str
            city: str

        class User(Model):
            name: str
            address: Address

        user = User.model_validate({
            "name": "Alice",
            "address": {"street": "123 Main St", "city": "Portland"}
        })

        assert user.name == "Alice"
        assert user.address.street == "123 Main St"
        assert user.address.city == "Portland"

    def test_nested_model_dump(self):
        """Test nested model_dump() serializes recursively."""
        class Address(Model):
            street: str
            city: str

        class User(Model):
            name: str
            address: Address

        user = User(name="Alice", address=Address(street="123 Main St", city="Portland"))
        dumped = user.model_dump()

        assert dumped == {
            "name": "Alice",
            "address": {"street": "123 Main St", "city": "Portland"}
        }

    def test_default_factory(self):
        """Test default_factory support (added in 0.4.12)."""
        class Config(Model):
            tags: list = Field(default_factory=list)
            metadata: dict = Field(default_factory=dict)

        c1 = Config()
        c2 = Config()

        c1.tags.append("admin")
        # Each instance gets its own list
        assert c1.tags == ["admin"]
        assert c2.tags == []

    def test_constraint_validation(self):
        """Test field constraints are properly enforced."""
        class Bounded(Model):
            value: int = Field(ge=0, le=100)
            name: str = Field(min_length=2, max_length=50)

        obj = Bounded(value=50, name="test")
        assert obj.value == 50
        assert obj.name == "test"

        # Test constraint violations
        with pytest.raises(Exception):
            Bounded(value=-1, name="test")

        with pytest.raises(Exception):
            Bounded(value=50, name="x")  # too short


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
