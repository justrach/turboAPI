import json

from dhi import BaseModel, Field
from turboapi.request_handler import create_fast_model_handler


def test_dhi_model_with_constraints_and_untyped_list_dumps_all_fields():
    class BacktestRequest(BaseModel):
        symbol: str = Field(min_length=1)
        candles: list
        initial_capital: float = Field(gt=0)
        position_size: float = Field(gt=0, le=1)

    seen = []

    def handler(request):
        seen.append(request)
        return request.model_dump()

    fast = create_fast_model_handler(handler, BacktestRequest, "request")
    _, _, body = fast(
        body_dict={
            "symbol": "BTCUSDT",
            "candles": [{"close": 100.0}],
            "initial_capital": 10_000.0,
            "position_size": 0.1,
        }
    )

    assert json.loads(body) == {
        "symbol": "BTCUSDT",
        "candles": [{"close": 100.0}],
        "initial_capital": 10_000.0,
        "position_size": 0.1,
    }
    assert isinstance(seen[0], BacktestRequest)
    assert type(seen[0]) is not BacktestRequest
    assert "model_dump" not in seen[0].__dict__


def test_custom_model_dump_is_never_wrapped_or_expanded():
    class RedactedModel(BaseModel):
        name: str
        secrets: list

        def model_dump(self, *args, **kwargs):
            return {"name": self.name}

    seen = []

    def handler(model):
        seen.append(model)
        return model.model_dump()

    fast = create_fast_model_handler(handler, RedactedModel, "model")
    _, _, body = fast(body_dict={"name": "safe", "secrets": ["hidden"]})

    assert type(seen[0]) is RedactedModel
    assert json.loads(body) == {"name": "safe"}


def test_typed_list_fields_are_compatible_across_dhi_versions():
    class TypedModel(BaseModel):
        name: str
        values: list[int]

    seen = []

    def handler(model):
        seen.append(model)
        return model.model_dump()

    fast = create_fast_model_handler(handler, TypedModel, "model")
    _, _, body = fast(body_dict={"name": "test", "values": [1, 2]})

    assert isinstance(seen[0], TypedModel)
    assert type(seen[0]) is not TypedModel
    assert json.loads(body) == {"name": "test", "values": [1, 2]}


def test_scalar_benchmark_shape_has_no_compatibility_wrapper():
    class Item(BaseModel):
        name: str
        price: float
        description: str | None = None

    seen = []

    def handler(item):
        seen.append(item)
        return item.model_dump()

    fast = create_fast_model_handler(handler, Item, "item")
    _, _, body = fast(body_dict={"name": "Widget", "price": 9.99})

    dumped = json.loads(body)
    assert type(seen[0]) is Item
    assert dumped["name"] == "Widget"
    assert dumped["price"] == 9.99
