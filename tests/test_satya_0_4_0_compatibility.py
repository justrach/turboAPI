"""
Test Satya 0.4.0 compatibility with TurboAPI.

This test suite identifies breaking changes in Satya 0.4.0 and ensures
TurboAPI continues to work correctly.
"""

import pytest
from satya import Model, Field
from turboapi.models import TurboRequest, TurboResponse


class TestSatyaFieldAccess:
    """Test field access behavior in Satya 0.4.0."""
    
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
    
    def test_field_with_constraints_no_description(self):
        """Fields with Field() but no description."""
        class ConstrainedModel(Model):
            age: int = Field(ge=0, le=150)
        
        obj = ConstrainedModel(age=30)
        # BUG: This returns Field object instead of value!
        result = obj.age
        print(f"obj.age type: {type(result)}, value: {result}")
        
        # Workaround: access via __dict__
        assert obj.__dict__["age"] == 30
    
    def test_field_with_description(self):
        """Fields with Field(description=...) - the problematic case."""
        class DescribedModel(Model):
            name: str = Field(description="User name")
            age: int = Field(ge=0, description="User age")
        
        obj = DescribedModel(name="Alice", age=30)
        
        # BUG: Both return Field objects!
        name_result = obj.name
        age_result = obj.age
        print(f"obj.name type: {type(name_result)}")
        print(f"obj.age type: {type(age_result)}")
        
        # Workaround: access via __dict__
        assert obj.__dict__["name"] == "Alice"
        assert obj.__dict__["age"] == 30
    
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


class TestTurboRequestCompatibility:
    """Test TurboRequest with Satya 0.4.0."""
    
    def test_turbo_request_creation(self):
        """TurboRequest should create successfully."""
        req = TurboRequest(
            method="GET",
            path="/test",
            query_string="foo=bar",
            headers={"content-type": "application/json"},
            path_params={"id": "123"},
            query_params={"foo": "bar"},
            body=b'{"test": "data"}'
        )
        
        # Access via __dict__ (workaround)
        assert req.__dict__["method"] == "GET"
        assert req.__dict__["path"] == "/test"
        assert req.__dict__["query_string"] == "foo=bar"
    
    def test_turbo_request_get_header(self):
        """get_header() method should work."""
        req = TurboRequest(
            method="GET",
            path="/test",
            headers={"Content-Type": "application/json", "X-API-Key": "secret"}
        )
        
        # This method accesses self.headers which might be broken
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
        """Properties should work."""
        req = TurboRequest(
            method="POST",
            path="/test",
            headers={"content-type": "application/json"},
            body=b'{"test": "data"}'
        )
        
        assert req.content_type == "application/json"
        assert req.content_length == len(b'{"test": "data"}')


class TestTurboResponseCompatibility:
    """Test TurboResponse with Satya 0.4.0."""
    
    def test_turbo_response_creation(self):
        """TurboResponse should create successfully."""
        resp = TurboResponse(
            content="Hello, World!",
            status_code=200,
            headers={"content-type": "text/plain"}
        )
        
        # Access via __dict__ (workaround)
        assert resp.__dict__["status_code"] == 200
        assert resp.__dict__["content"] == "Hello, World!"
    
    def test_turbo_response_json_method(self):
        """TurboResponse.json() should work."""
        resp = TurboResponse.json(
            {"message": "Success", "data": [1, 2, 3]},
            status_code=200
        )
        
        # Check via model_dump()
        dumped = resp.model_dump()
        assert dumped["status_code"] == 200
        assert "application/json" in dumped["headers"]["content-type"]
    
    def test_turbo_response_body_property(self):
        """body property should work."""
        resp = TurboResponse(content="Hello")
        body = resp.body
        assert body == b"Hello"
    
    def test_turbo_response_dict_content(self):
        """Dict content should be serialized to JSON."""
        resp = TurboResponse(content={"key": "value"})
        
        # Check via __dict__
        content = resp.__dict__["content"]
        assert '"key"' in content  # Should be JSON string
        assert '"value"' in content


class TestSatyaNewFeatures:
    """Test new features in Satya 0.4.0."""
    
    def test_model_validate_fast(self):
        """Test new model_validate_fast() method."""
        class User(Model):
            name: str
            age: int = Field(ge=0, le=150)
        
        # New in 0.4.0: model_validate_fast()
        user = User.model_validate_fast({"name": "Alice", "age": 30})
        
        # Access via __dict__ or model_dump()
        dumped = user.model_dump()
        assert dumped["name"] == "Alice"
        assert dumped["age"] == 30
    
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
        
        # Check first user via model_dump()
        first = users[0].model_dump()
        assert first["name"] == "Alice"
        assert first["age"] == 30


def test_workaround_property_access():
    """
    Demonstrate workaround for Field descriptor issue.
    
    Until Satya fixes the Field descriptor bug, use one of these approaches:
    1. Access via __dict__: obj.__dict__["field_name"]
    2. Use model_dump(): obj.model_dump()["field_name"]
    3. Use getattr with __dict__: getattr(obj.__dict__, "field_name", default)
    """
    class TestModel(Model):
        name: str = Field(description="Name")
        age: int = Field(ge=0, description="Age")
    
    obj = TestModel(name="Alice", age=30)
    
    # Workaround 1: Direct __dict__ access
    assert obj.__dict__["name"] == "Alice"
    assert obj.__dict__["age"] == 30
    
    # Workaround 2: model_dump()
    dumped = obj.model_dump()
    assert dumped["name"] == "Alice"
    assert dumped["age"] == 30
    
    # Workaround 3: Helper function
    def get_field_value(model_instance, field_name, default=None):
        """Get field value, working around Satya 0.4.0 descriptor bug."""
        return model_instance.__dict__.get(field_name, default)
    
    assert get_field_value(obj, "name") == "Alice"
    assert get_field_value(obj, "age") == 30


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
