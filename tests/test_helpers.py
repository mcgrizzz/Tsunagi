import pytest
from pydantic import BaseModel, Field

from tsunagi.shared.errors import ValidationError as TsunagiValidationError
from tsunagi.shared.helpers import (
    copy_if_present,
    find_in_subresource,
    normalize_field_names,
    validate_nonempty_list,
    validate_required_keys,
    validate_subresource_order,
)


class _PatchSchema(BaseModel):
    name: str = None
    sort_field: int = Field(default=None, alias="sortf")

    class Config:
        allow_population_by_field_name = True
        extra = "ignore"


class TestNormalizeFieldNames:
    def test_clean_names_become_aliases(self):
        assert normalize_field_names({"sort_field": 1, "name": "Basic"}, _PatchSchema) == {
            "sortf": 1,
            "name": "Basic",
        }

    def test_alias_names_pass_through(self):
        assert normalize_field_names({"sortf": 1, "name": "Basic"}, _PatchSchema) == {
            "sortf": 1,
            "name": "Basic",
        }

    def test_none_fields_excluded(self):
        assert normalize_field_names({"name": "Basic"}, _PatchSchema) == {"name": "Basic"}


class TestValidators:
    def test_required_keys_ok(self):
        validate_required_keys({"a": 1, "b": 2}, ["a", "b"])

    @pytest.mark.parametrize("data", [{}, {"a": None}, {"b": 1}])
    def test_required_keys_missing(self, data):
        with pytest.raises(TsunagiValidationError):
            validate_required_keys(data, ["a"])

    def test_copy_if_present(self):
        target = {}
        copy_if_present({"a": 1, "b": None}, target, ["a", "b", "c"])
        assert target == {"a": 1, "b": None}

    def test_nonempty_list(self):
        assert validate_nonempty_list({"flds": [1]}, "flds") == [1]
        for bad in ({}, {"flds": []}, {"flds": "nope"}):
            with pytest.raises(TsunagiValidationError):
                validate_nonempty_list(bad, "flds")


class TestSubresourceHelpers:
    PARENT = {"flds": [{"name": "Front", "ord": 0}, {"name": "Back", "ord": 1}]}

    def test_find_by_name(self):
        assert find_in_subresource(self.PARENT, "flds", "Back")["ord"] == 1

    def test_find_missing_raises_with_available(self):
        with pytest.raises(TsunagiValidationError, match="Front"):
            find_in_subresource(self.PARENT, "flds", "Middle")

    def test_order_valid(self):
        validate_subresource_order(self.PARENT, "flds", ["Back", "Front"])

    @pytest.mark.parametrize(
        "order", [["Front"], ["Front", "Back", "Extra"], ["Front", "Front"]]
    )
    def test_order_invalid(self, order):
        with pytest.raises(TsunagiValidationError):
            validate_subresource_order(self.PARENT, "flds", order)
