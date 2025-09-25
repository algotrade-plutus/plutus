import time
from decimal import Decimal

import pytest

from plutus.core.instrument import Instrument
from plutus.data.model.enums import QuoteType
from plutus.data.model.quote import QuoteNamedTuple


@pytest.fixture
def sample_instrument():
    """Provides a sample Instrument object for tests."""
    return Instrument(ticker_symbol="FPT", exchange_code_str="HSX")


@pytest.fixture
def basic_quote_data(sample_instrument):
    """Provides a dictionary of basic, valid quote data."""
    return {
        "instrument": sample_instrument,
        "timestamp": time.time(),
        "source": "test_source",
    }


class TestQuoteModel:
    def test_successful_creation_and_type_coercion(self, basic_quote_data):
        """
        Tests that a Quote can be created with valid data and that Pydantic
        correctly coerces types (e.g., string to Decimal).
        """
        full_data = {
            **basic_quote_data,
            "ref_price": "101.5",  # Should be coerced to Decimal
            "bid_qty_1": 1500,
        }
        quote = QuoteNamedTuple(**full_data)

        assert quote.instrument == basic_quote_data["instrument"]
        assert quote.source == "test_source"
        assert isinstance(quote.ref_price, Decimal)
        assert quote.ref_price == Decimal("101.5")
        assert quote.bid_qty_1 == 1500
        assert quote.floor_price is None  # Unset optional field should be None

    def test_creation_with_input_price_as_float(self, basic_quote_data):
        """
        Tests that a Quote can be created with valid data but the price value is float not string
        """
        full_data = {
            **basic_quote_data,
            "ref_price": 101.5,  # Should be converted to Decimal
            "bid_qty_1": 1500,
        }
        quote = QuoteNamedTuple(**full_data)

        assert quote.instrument == basic_quote_data["instrument"]
        assert quote.source == "test_source"
        assert isinstance(quote.ref_price, Decimal)
        assert quote.ref_price == Decimal("101.5")
        assert quote.bid_qty_1 == 1500
        assert quote.floor_price is None  # Unset optional field should be None

    def test_creation_fails_with_missing_required_fields(self, sample_instrument):
        """
        Tests that TypeError is raised if required fields are missing.
        """
        with pytest.raises(TypeError):
            QuoteNamedTuple(timestamp=time.time(), source="test")

        with pytest.raises(TypeError):
            QuoteNamedTuple(instrument=sample_instrument, source="test")

        with pytest.raises(TypeError):
            QuoteNamedTuple(instrument=sample_instrument, timestamp=time.time())

    def test_creation_fails_with_invalid_data_type(self, basic_quote_data):
        """
        Tests that ValueError is raised for incorrect data types that
        cannot be coerced.
        """
        invalid_data = {**basic_quote_data, "ref_price": "not-a-decimal"}
        with pytest.raises(ValueError):
            QuoteNamedTuple(**invalid_data)

    def test_attribute_access_dot_notation(self, basic_quote_data):
        """
        Tests standard attribute access using dot notation.
        """
        quote = QuoteNamedTuple(**basic_quote_data, ref_price=Decimal("99.9"))
        assert quote.ref_price == Decimal("99.9")
        assert quote.ceiling_price is None

    def test_attribute_access_getitem(self, basic_quote_data):
        """
        Tests dictionary-style access using QuoteType enums.
        """
        quote = QuoteNamedTuple(
            **basic_quote_data,
            ref_price=Decimal("100.0"),
            latest_price=Decimal("101.2"),
        )
        assert quote[QuoteType.REFERENCE] == Decimal("100.0")
        assert quote[QuoteType.LATEST_PRICE] == Decimal("101.2")

    def test_getitem_raises_error_for_invalid_key(self, basic_quote_data):
        """
        Tests that __getitem__ raises a TypeError for non-QuoteType keys.
        """
        quote = QuoteNamedTuple(**basic_quote_data)
        with pytest.raises(TypeError, match="Index must be a QuoteType enum member"):
            _ = quote["ref_price"]  # Using a string instead of enum

    def test_available_quote_types(self, basic_quote_data):
        """
        Tests the available_quote_types method to ensure it lists only
        populated, aliased fields.
        """
        # Test on a lean quote
        lean_quote = QuoteNamedTuple(
            **basic_quote_data,
            ref_price=Decimal("100.0"),
            bid_qty_1=5000,
        )
        available = lean_quote.available_quote_types()
        assert isinstance(available, list)
        assert set(available) == {"ref_price", "bid_qty_1"}

        # Test on a quote with only required fields
        minimal_quote = QuoteNamedTuple(**basic_quote_data)
        assert minimal_quote.available_quote_types() == []

    def test_serialization_to_dict(self, basic_quote_data):
        """
        Tests the to_dict method for correct serialization format.
        """
        quote = QuoteNamedTuple(
            **basic_quote_data,
            ref_price=Decimal("105.5"),
            bid_qty_1=2000,
        )
        quote_dict = quote.to_dict()

        # Check core types
        assert quote_dict["instrument"] == basic_quote_data["instrument"].id
        assert quote_dict["source"] == "test_source"

        # Check serialized market data
        assert quote_dict["ref_price"] == "105.5"  # Decimal -> str
        assert quote_dict["bid_qty_1"] == 2000

        # Check that unset fields are not included
        assert "floor_price" not in quote_dict

    def test_deserialization_from_dict_and_round_trip(self, sample_instrument):
        """
        Tests the from_dict method and ensures a perfect round trip.
        """
        original_data = {
            "instrument": sample_instrument.id,
            "timestamp": time.time(),
            "source": "round_trip_test",
            "ref_price": "110.0",
            "latest_price": "111.5",
            "total_matched_qty": 500000,
        }

        # 1. Deserialize from dictionary
        quote1 = QuoteNamedTuple.from_dict(original_data)

        assert isinstance(quote1, QuoteNamedTuple)
        assert quote1.instrument == sample_instrument
        assert quote1.ref_price == Decimal("110.0")
        assert quote1.latest_price == Decimal("111.5")
        assert quote1.total_matched_qty == 500000

        # 2. Serialize it back
        re_serialized_data = quote1.to_dict()

        # 3. Deserialize again and check for equality
        quote2 = QuoteNamedTuple.from_dict(re_serialized_data)
        assert quote1 == quote2

    def test_from_dict_has_side_effects(self, sample_instrument):
        """
        This test demonstrates the bug where from_dict mutates its input dict.
        This test is EXPECTED TO FAIL before the fix is applied.
        The bug is that the second call to from_dict will raise an error
        because the dictionary was modified by the first call.
        """
        data_dict = {
            "instrument": sample_instrument.id,
            "timestamp": time.time(),
            "source": "side_effect_test",
        }

        # The first call succeeds but mutates data_dict
        QuoteNamedTuple.from_dict(data_dict)

        # The second call should also succeed, but will fail due to the mutation
        QuoteNamedTuple.from_dict(data_dict)
