import time
from decimal import Decimal

import pytest

from plutus.data.model.enums import QuoteType
from plutus.data.model.quote_named_tuple import QuoteNamedTuple as QuoteNT, create_quote_nt


@pytest.fixture
def basic_quote_data():
    """Provides a dictionary of basic, valid quote data."""
    return {
        "ticker_symbol": "FPT",
        "timestamp": time.time(),
        "source": "test_source",
        "exchange_code": "HSX",
    }


class TestQuoteNTModel:
    def test_successful_creation_and_type_coercion(self, basic_quote_data):
        """
        Tests that a QuoteNT can be created with valid data and that
        correctly coerces types (e.g., string to Decimal).
        """
        full_data = {
            **basic_quote_data,
            "ref_price": "101.5",  # Should be coerced to Decimal
            "bid_qty_1": 1500,
        }
        quote = create_quote_nt(**full_data)

        assert quote.ticker_symbol == "FPT"
        assert quote.exchange_code == "HSX"
        assert quote.source == "test_source"
        assert isinstance(quote.ref_price, Decimal)
        assert quote.ref_price == Decimal("101.5")
        assert quote.bid_qty_1 == 1500
        assert quote.floor_price is None  # Unset optional field should be None

    def test_creation_with_input_price_as_float(self, basic_quote_data):
        """
        Tests that a QuoteNT can be created with valid data but the price value is float not string
        """
        full_data = {
            **basic_quote_data,
            "ref_price": 101.5,  # Should be converted to Decimal
            "bid_qty_1": 1500,
        }
        quote = create_quote_nt(**full_data)

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
            QuoteNT(timestamp=time.time(), source="test")

        with pytest.raises(TypeError):
            QuoteNT(ticker_symbol="FPT", source="test")

        with pytest.raises(TypeError):
            QuoteNT(ticker_symbol="FPT", timestamp=time.time())

    def test_creation_fails_with_invalid_data_type(self, basic_quote_data):
        """
        Tests that ValueError is raised for incorrect data types that
        cannot be coerced.
        """
        invalid_data = {**basic_quote_data, "ref_price": "not-a-decimal"}
        with pytest.raises(ValueError):
            create_quote_nt(**invalid_data)

    def test_attribute_access_dot_notation(self, basic_quote_data):
        """
        Tests standard attribute access using dot notation.
        """
        quote = QuoteNT(**basic_quote_data, ref_price=Decimal("99.9"))
        assert quote.ref_price == Decimal("99.9")
        assert quote.ceiling_price is None

    def test_attribute_access_getitem(self, basic_quote_data):
        """
        Tests dictionary-style access using QuoteType enums.
        """
        quote = QuoteNT(
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
        quote = QuoteNT(**basic_quote_data)
        with pytest.raises(TypeError, match="Index must be a QuoteType enum member"):
            _ = quote["ref_price"]  # Using a string instead of enum

    def test_available_quote_types(self, basic_quote_data):
        """
        Tests the available_quote_types method to ensure it lists only
        populated fields.
        """
        # Test on a lean quote
        lean_quote = QuoteNT(
            **basic_quote_data,
            ref_price=Decimal("100.0"),
            bid_qty_1=5000,
        )
        available = lean_quote.available_quote_types()
        assert isinstance(available, list)
        assert set(available) == {"ref_price", "bid_qty_1"}

        # Test on a quote with only required fields
        minimal_quote = QuoteNT(**basic_quote_data)
        assert minimal_quote.available_quote_types() == []

    def test_serialization_to_dict(self, basic_quote_data):
        """
        Tests the to_dict method for correct serialization format.
        """
        quote = QuoteNT(
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
        quote1 = QuoteNT.from_dict(original_data)

        assert isinstance(quote1, QuoteNT)
        assert quote1.ticker_symbol == "FPT"
        assert quote1.exchange_code == "HSX"
        assert quote1.ref_price == Decimal("110.0")
        assert quote1.latest_price == Decimal("111.5")
        assert quote1.total_matched_qty == 500000

        # 2. Serialize it back
        re_serialized_data = quote1.to_dict()

        # 3. Deserialize again and check for equality
        quote2 = QuoteNT.from_dict(re_serialized_data)
        assert quote1 == quote2

    def test_from_dict_no_side_effects(self):
        """
        Tests that from_dict does NOT mutate its input dict (fixing the original bug).
        This should pass for QuoteNT implementation.
        """
        data_dict = {
            "ticker_symbol": "FPT",
            "exchange_code": "HSX",
            "timestamp": time.time(),
            "source": "side_effect_test",
        }

        original_dict = data_dict.copy()

        # The first call succeeds and should NOT mutate data_dict
        QuoteNT.from_dict(data_dict)

        # Verify the dictionary wasn't mutated
        assert data_dict == original_dict

        # The second call should also succeed
        QuoteNT.from_dict(data_dict)

        # Dictionary should still be unchanged
        assert data_dict == original_dict

    def test_immutability(self, basic_quote_data):
        """
        Tests that QuoteNT instances are immutable (NamedTuple property).
        """
        quote = QuoteNT(**basic_quote_data, ref_price=Decimal("100.0"))

        # Attempt to modify should raise AttributeError
        with pytest.raises(AttributeError):
            quote.ref_price = Decimal("200.0")

        with pytest.raises(AttributeError):
            quote.source = "modified_source"

    def test_factory_function(self):
        """
        Tests the create_quote_nt factory function.
        """
        quote = create_quote_nt(
            ticker_symbol="FPT",
            timestamp=time.time(),
            source="factory_test",
            exchange_code="HSX",
            ref_price=Decimal("99.99"),
            latest_qty=1000
        )

        assert isinstance(quote, QuoteNT)
        assert quote.ticker_symbol == "FPT"
        assert quote.exchange_code == "HSX"
        assert quote.ref_price == Decimal("99.99")
        assert quote.latest_qty == 1000

    def test_repr_string(self, basic_quote_data):
        """
        Tests the __repr__ method shows useful information.
        """
        quote = QuoteNT(
            **basic_quote_data,
            ref_price=Decimal("100.0"),
            bid_qty_1=1000,
            ask_price_1=Decimal("100.5")
        )

        repr_str = repr(quote)
        assert "QuoteNT" in repr_str
        assert quote.ticker_symbol in repr_str
        assert "market_data_fields=3" in repr_str

    def test_equality_comparison(self, basic_quote_data):
        """
        Tests that two QuoteNT instances with same data are equal.
        """
        data = {**basic_quote_data, "ref_price": Decimal("100.0")}

        quote1 = QuoteNT(**data)
        quote2 = QuoteNT(**data)

        assert quote1 == quote2
        assert hash(quote1) == hash(quote2)  # NamedTuple is hashable

    def test_performance_characteristics(self, basic_quote_data):
        """
        Tests that demonstrate the performance characteristics we expect.
        This is more of a smoke test to ensure the implementation works.
        """
        # Test fast creation
        start_time = time.perf_counter()
        quotes = []
        for i in range(1000):
            quote = QuoteNT(
                **basic_quote_data,
                ref_price=Decimal(f"{100 + i % 10}.50"),
                latest_qty=1000 + i
            )
            quotes.append(quote)
        creation_time = time.perf_counter() - start_time

        # Should be very fast (much less than 1 second for 1000 instances)
        assert creation_time < 0.1

        # Test fast access
        start_time = time.perf_counter()
        for quote in quotes:
            _ = quote.ref_price
            _ = quote.latest_qty
            _ = quote.ticker_symbol
        access_time = time.perf_counter() - start_time

        # Should be extremely fast
        assert access_time < 0.01

    def test_large_data_scenario(self):
        """
        Tests QuoteNT with a large amount of market data fields.
        """
        large_data = {
            "ticker_symbol": "FPT",
            "exchange_code": "HSX",
            "timestamp": time.time(),
            "source": "large_test",
            # Add many fields
            "ref_price": Decimal("100.00"),
            "ceiling_price": Decimal("110.00"),
            "floor_price": Decimal("90.00"),
            "latest_price": Decimal("100.50"),
            "bid_price_1": Decimal("100.25"), "bid_qty_1": 1000,
            "bid_price_2": Decimal("100.00"), "bid_qty_2": 1500,
            "bid_price_3": Decimal("99.75"), "bid_qty_3": 2000,
            "ask_price_1": Decimal("100.75"), "ask_qty_1": 800,
            "ask_price_2": Decimal("101.00"), "ask_qty_2": 1200,
            "ask_price_3": Decimal("101.25"), "ask_qty_3": 1600,
            "latest_qty": 5000,
            "total_matched_qty": 100000,
            "highest_price": Decimal("101.50"),
            "lowest_price": Decimal("99.50"),
            "avg_price": Decimal("100.25"),
            "foreign_buy_qty": 50000,
            "foreign_sell_qty": 45000,
        }

        quote = create_quote_nt(**large_data)

        # All fields should be accessible
        assert quote.ref_price == Decimal("100.00")
        assert quote.bid_price_3 == Decimal("99.75")
        assert quote.ask_qty_2 == 1200
        assert quote.foreign_buy_qty == 50000

        # Available quote types should include all non-None fields (excluding core 3)
        available = quote.available_quote_types()
        # Count the market data fields we actually set (excluding instrument, timestamp, source)
        expected_fields = len([k for k in large_data.keys() if k not in ['ticker_symbol', 'timestamp', 'source', 'exchange_code']])
        assert len(available) == expected_fields  # All the market data fields we set

        # Serialization should work correctly
        quote_dict = quote.to_dict()
        assert len(quote_dict) == len(large_data)  # Should match input data

    def test_exchange_code_none_handling(self):
        """
        Tests that QuoteNT properly handles exchange_code=None.
        """
        # Test 1: Create QuoteNT without exchange_code (defaults to None)
        quote1 = create_quote_nt(
            ticker_symbol="FPT",
            timestamp=time.time(),
            source="test_source",
            ref_price=Decimal("100.0")
        )
        assert quote1.exchange_code is None

        # Test 2: Create QuoteNT with explicit exchange_code=None
        quote2 = create_quote_nt(
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
        quote3 = QuoteNT.from_dict(data)
        assert quote3.exchange_code is None

        # Test 5: Repr with None exchange_code should not show exchange_code
        repr_str = repr(quote1)
        assert "exchange_code=" not in repr_str

        # Test 6: Direct QuoteNT construction (bypassing factory)
        quote4 = QuoteNT(
            ticker_symbol="FPT",
            timestamp=time.time(),
            source="test_source"
        )
        assert quote4.exchange_code is None

    def test_settlement_price_and_open_interest(self):
        """
        Tests that QuoteNT properly handles futures-specific fields: settlement_price and open_interest.
        """
        # Test 1: Create QuoteNT with settlement_price (Decimal)
        quote1 = create_quote_nt(
            ticker_symbol="VN30F2306",
            exchange_code="HNX",
            timestamp=time.time(),
            source="test_source",
            settlement_price=Decimal("1025.50")
        )
        assert quote1.settlement_price == Decimal("1025.50")
        assert isinstance(quote1.settlement_price, Decimal)

        # Test 2: Create QuoteNT with open_interest (int)
        quote2 = create_quote_nt(
            ticker_symbol="VN30F2306",
            exchange_code="HNX",
            timestamp=time.time(),
            source="test_source",
            open_interest=50000
        )
        assert quote2.open_interest == 50000
        assert isinstance(quote2.open_interest, int)

        # Test 3: Type conversion - settlement_price from string
        quote3 = create_quote_nt(
            ticker_symbol="VN30F2306",
            exchange_code="HNX",
            timestamp=time.time(),
            source="test_source",
            settlement_price="1030.75"
        )
        assert quote3.settlement_price == Decimal("1030.75")

        # Test 4: Type conversion - open_interest from string
        quote4 = create_quote_nt(
            ticker_symbol="VN30F2306",
            exchange_code="HNX",
            timestamp=time.time(),
            source="test_source",
            open_interest="75000"
        )
        assert quote4.open_interest == 75000

        # Test 5: Serialization includes both fields
        quote5 = create_quote_nt(
            ticker_symbol="VN30F2306",
            exchange_code="HNX",
            timestamp=time.time(),
            source="test_source",
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
        quote6 = QuoteNT.from_dict(data)
        assert quote6.settlement_price == Decimal("1025.50")
        assert quote6.open_interest == 50000

        # Test 7: Direct construction with new fields
        quote7 = QuoteNT(
            ticker_symbol="VN30F2306",
            exchange_code="HNX",
            timestamp=time.time(),
            source="test_source",
            settlement_price=Decimal("1025.50"),
            open_interest=50000
        )
        assert quote7.settlement_price == Decimal("1025.50")
        assert quote7.open_interest == 50000