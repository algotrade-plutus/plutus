import time
from decimal import Decimal

import pytest

from plutus.data.model.enums import QuoteType
from plutus.data.model.quote import Quote


@pytest.fixture
def basic_quote_data():
    """Provides a dictionary of basic, valid quote data."""
    return {
        "ticker_symbol": "FPT",
        "timestamp": time.time(),
        "source": "test_source",
        "exchange_code": "HSX",
    }


class TestQuoteModel:
    def test_successful_creation_and_type_coercion(self, basic_quote_data):
        """
        Tests that a Quote can be created with valid data and that type
        conversion works correctly (e.g., string to Decimal).
        """
        full_data = {
            **basic_quote_data,
            "ref_price": "101.5",  # Should be converted to Decimal
            "bid_qty_1": 1500,
        }
        quote = Quote(**full_data)

        assert quote.ticker_symbol == "FPT"
        assert quote.exchange_code == "HSX"
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
        quote = Quote(**full_data)

        assert quote.ticker_symbol == "FPT"
        assert quote.exchange_code == "HSX"
        assert quote.source == "test_source"
        assert isinstance(quote.ref_price, Decimal)
        assert quote.ref_price == Decimal("101.5")
        assert quote.bid_qty_1 == 1500
        assert quote.floor_price is None  # Unset optional field should be None

    def test_creation_fails_with_missing_required_fields(self):
        """
        Tests that TypeError is raised if required fields are missing.
        """
        with pytest.raises(TypeError):
            Quote(timestamp=time.time(), source="test")

        with pytest.raises(TypeError):
            Quote(ticker_symbol="FPT", source="test")

        with pytest.raises(TypeError):
            Quote(ticker_symbol="FPT", timestamp=time.time())

    def test_creation_fails_with_invalid_data_type(self, basic_quote_data):
        """
        Tests that ValueError is raised for incorrect data types that
        cannot be coerced.
        """
        invalid_data = {**basic_quote_data, "ref_price": "not-a-decimal"}
        with pytest.raises(ValueError):
            Quote(**invalid_data)

    def test_attribute_access_dot_notation(self, basic_quote_data):
        """
        Tests standard attribute access using dot notation.
        """
        quote = Quote(**basic_quote_data, ref_price=Decimal("99.9"))
        assert quote.ref_price == Decimal("99.9")
        assert quote.ceiling_price is None

    def test_attribute_access_getitem(self, basic_quote_data):
        """
        Tests dictionary-style access using QuoteType enums.
        """
        quote = Quote(
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
        quote = Quote(**basic_quote_data)
        with pytest.raises(TypeError, match="Index must be a QuoteType enum member"):
            _ = quote["ref_price"]  # Using a string instead of enum

    def test_available_quote_types(self, basic_quote_data):
        """
        Tests the available_quote_types method to ensure it lists only
        populated, aliased fields.
        """
        # Test on a lean quote
        lean_quote = Quote(
            **basic_quote_data,
            ref_price=Decimal("100.0"),
            bid_qty_1=5000,
        )
        available = lean_quote.available_quote_types()
        assert isinstance(available, list)
        assert set(available) == {"ref_price", "bid_qty_1"}

        # Test on a quote with only required fields
        minimal_quote = Quote(**basic_quote_data)
        assert minimal_quote.available_quote_types() == []

    def test_serialization_to_dict(self, basic_quote_data):
        """
        Tests the to_dict method for correct serialization format.
        """
        quote = Quote(
            **basic_quote_data,
            ref_price=Decimal("105.5"),
            bid_qty_1=2000,
        )
        quote_dict = quote.to_dict()

        # Check core fields
        assert quote_dict["ticker_symbol"] == "FPT"
        assert quote_dict["exchange_code"] == "HSX"
        assert quote_dict["source"] == "test_source"

        # Check serialized market data
        assert quote_dict["ref_price"] == "105.5"  # Decimal -> str
        assert quote_dict["bid_qty_1"] == 2000

        # Check that unset fields are not included
        assert "floor_price" not in quote_dict

    def test_deserialization_from_dict_and_round_trip(self):
        """
        Tests the from_dict method and ensures a perfect round trip.
        """
        original_data = {
            "ticker_symbol": "FPT",
            "exchange_code": "HSX",
            "timestamp": time.time(),
            "source": "round_trip_test",
            "ref_price": "110.0",
            "latest_price": "111.5",
            "total_matched_qty": 500000,
        }

        # 1. Deserialize from dictionary
        quote1 = Quote.from_dict(original_data)

        assert isinstance(quote1, Quote)
        assert quote1.ticker_symbol == "FPT"
        assert quote1.exchange_code == "HSX"
        assert quote1.ref_price == Decimal("110.0")
        assert quote1.latest_price == Decimal("111.5")
        assert quote1.total_matched_qty == 500000

        # 2. Serialize it back
        re_serialized_data = quote1.to_dict()

        # 3. Deserialize again and check for equality
        quote2 = Quote.from_dict(re_serialized_data)
        assert quote1 == quote2

    def test_from_dict_has_side_effects(self):
        """
        Tests that from_dict does not mutate its input dict.
        """
        data_dict = {
            "ticker_symbol": "FPT",
            "exchange_code": "HSX",
            "timestamp": time.time(),
            "source": "side_effect_test",
        }

        # The first call succeeds
        Quote.from_dict(data_dict)

        # The second call should also succeed (no mutation)
        Quote.from_dict(data_dict)

    def test_exchange_code_none_handling(self):
        """
        Tests that Quote properly handles exchange_code=None.
        """
        # Test 1: Create Quote without exchange_code (defaults to None)
        quote1 = Quote(
            ticker_symbol="FPT",
            timestamp=time.time(),
            source="test_source",
            ref_price=Decimal("100.0")
        )
        assert quote1.exchange_code is None

        # Test 2: Create Quote with explicit exchange_code=None
        quote2 = Quote(
            ticker_symbol="FPT",
            timestamp=time.time(),
            source="test_source",
            exchange_code=None,
            ref_price=Decimal("100.0")
        )
        assert quote2.exchange_code is None

        # Test 3: Serialization with None exchange_code
        quote_dict = quote1.to_dict()
        assert 'exchange_code' not in quote_dict  # None should not be serialized

        # Test 4: Deserialization without exchange_code field
        data = {
            "ticker_symbol": "FPT",
            "timestamp": time.time(),
            "source": "test",
            "ref_price": "100.0"
        }
        quote3 = Quote.from_dict(data)
        assert quote3.exchange_code is None

        # Test 5: Repr with None exchange_code should not show exchange_code
        repr_str = repr(quote1)
        assert "exchange_code=" not in repr_str

    def test_settlement_price_and_open_interest(self):
        """
        Tests that Quote properly handles futures-specific fields: settlement_price and open_interest.
        """
        # Test 1: Create Quote with settlement_price (Decimal)
        quote1 = Quote(
            ticker_symbol="VN30F2306",
            timestamp=time.time(),
            source="test_source",
            exchange_code="HNX",
            settlement_price=Decimal("1025.50")
        )
        assert quote1.settlement_price == Decimal("1025.50")
        assert isinstance(quote1.settlement_price, Decimal)

        # Test 2: Create Quote with open_interest (int)
        quote2 = Quote(
            ticker_symbol="VN30F2306",
            timestamp=time.time(),
            source="test_source",
            exchange_code="HNX",
            open_interest=50000
        )
        assert quote2.open_interest == 50000
        assert isinstance(quote2.open_interest, int)

        # Test 3: Type conversion - settlement_price from string
        quote3 = Quote(
            ticker_symbol="VN30F2306",
            timestamp=time.time(),
            source="test_source",
            exchange_code="HNX",
            settlement_price="1030.75"
        )
        assert quote3.settlement_price == Decimal("1030.75")

        # Test 4: Type conversion - open_interest from string
        quote4 = Quote(
            ticker_symbol="VN30F2306",
            timestamp=time.time(),
            source="test_source",
            exchange_code="HNX",
            open_interest="75000"
        )
        assert quote4.open_interest == 75000

        # Test 5: Serialization includes both fields
        quote5 = Quote(
            ticker_symbol="VN30F2306",
            timestamp=time.time(),
            source="test_source",
            exchange_code="HNX",
            settlement_price=Decimal("1025.50"),
            open_interest=50000
        )
        quote_dict = quote5.to_dict()
        assert quote_dict['settlement_price'] == '1025.50'
        assert quote_dict['open_interest'] == 50000

        # Test 6: Deserialization from dict
        data = {
            "ticker_symbol": "VN30F2306",
            "exchange_code": "HNX",
            "timestamp": time.time(),
            "source": "test",
            "settlement_price": "1025.50",
            "open_interest": 50000
        }
        quote6 = Quote.from_dict(data)
        assert quote6.settlement_price == Decimal("1025.50")
        assert quote6.open_interest == 50000
