"""Tests for metadata models (InstrumentMetadata, IndexConstituent, FutureContractCode).

This module tests the data structures used for market metadata, which is distinct from
time-series Quote data. These metadata models represent reference data with infrequent
updates.
"""

import pytest
from datetime import date

from plutus.data.model.metadata import InstrumentMetadata, IndexConstituent, FutureContractCode


class TestInstrumentMetadata:
    """Test cases for InstrumentMetadata model."""

    def test_stock_metadata_creation(self):
        """Test creating metadata for a stock instrument."""
        metadata = InstrumentMetadata(
            ticker_symbol="VIC",
            exchange_id="HSX",
            instrument_type="stock",
            last_updated=date(2023, 6, 15)
        )

        assert metadata.ticker_symbol == "VIC"
        assert metadata.exchange_id == "HSX"
        assert metadata.instrument_type == "stock"
        assert metadata.last_updated == date(2023, 6, 15)
        assert metadata.start_date is None
        assert metadata.exp_date is None

    def test_futures_metadata_creation(self):
        """Test creating metadata for a futures instrument with expiration."""
        metadata = InstrumentMetadata(
            ticker_symbol="VN30F2306",
            exchange_id="HSX",
            instrument_type="futures",
            last_updated=date(2023, 6, 15),
            start_date=date(2023, 6, 1),
            exp_date=date(2023, 6, 30)
        )

        assert metadata.ticker_symbol == "VN30F2306"
        assert metadata.exchange_id == "HSX"
        assert metadata.instrument_type == "futures"
        assert metadata.last_updated == date(2023, 6, 15)
        assert metadata.start_date == date(2023, 6, 1)
        assert metadata.exp_date == date(2023, 6, 30)

    def test_metadata_validation_empty_ticker(self):
        """Test that empty ticker_symbol raises ValueError."""
        with pytest.raises(ValueError, match="ticker_symbol cannot be empty"):
            InstrumentMetadata(
                ticker_symbol="",
                exchange_id="HSX",
                instrument_type="stock",
                last_updated=date(2023, 6, 15)
            )

    def test_metadata_validation_empty_exchange(self):
        """Test that empty exchange_id raises ValueError."""
        with pytest.raises(ValueError, match="exchange_id cannot be empty"):
            InstrumentMetadata(
                ticker_symbol="VIC",
                exchange_id="",
                instrument_type="stock",
                last_updated=date(2023, 6, 15)
            )

    def test_metadata_validation_empty_instrument_type(self):
        """Test that empty instrument_type raises ValueError."""
        with pytest.raises(ValueError, match="instrument_type cannot be empty"):
            InstrumentMetadata(
                ticker_symbol="VIC",
                exchange_id="HSX",
                instrument_type="",
                last_updated=date(2023, 6, 15)
            )

    def test_metadata_validation_invalid_date_type(self):
        """Test that non-date last_updated raises TypeError."""
        with pytest.raises(TypeError, match="last_updated must be a date"):
            InstrumentMetadata(
                ticker_symbol="VIC",
                exchange_id="HSX",
                instrument_type="stock",
                last_updated="2023-06-15"  # String instead of date
            )

    def test_metadata_dataclass_equality(self):
        """Test that two identical metadata objects are equal."""
        metadata1 = InstrumentMetadata(
            ticker_symbol="VIC",
            exchange_id="HSX",
            instrument_type="stock",
            last_updated=date(2023, 6, 15)
        )
        metadata2 = InstrumentMetadata(
            ticker_symbol="VIC",
            exchange_id="HSX",
            instrument_type="stock",
            last_updated=date(2023, 6, 15)
        )
        assert metadata1 == metadata2

    def test_metadata_dataclass_inequality(self):
        """Test that different metadata objects are not equal."""
        metadata1 = InstrumentMetadata(
            ticker_symbol="VIC",
            exchange_id="HSX",
            instrument_type="stock",
            last_updated=date(2023, 6, 15)
        )
        metadata2 = InstrumentMetadata(
            ticker_symbol="HPG",
            exchange_id="HSX",
            instrument_type="stock",
            last_updated=date(2023, 6, 15)
        )
        assert metadata1 != metadata2


class TestIndexConstituent:
    """Test cases for IndexConstituent model."""

    def test_constituent_creation(self):
        """Test creating an index constituent."""
        constituent = IndexConstituent(
            index_name="VN30",
            ticker_symbol="VIC",
            effective_date=date(2023, 6, 15)
        )

        assert constituent.index_name == "VN30"
        assert constituent.ticker_symbol == "VIC"
        assert constituent.effective_date == date(2023, 6, 15)

    def test_constituent_validation_empty_index_name(self):
        """Test that empty index_name raises ValueError."""
        with pytest.raises(ValueError, match="index_name cannot be empty"):
            IndexConstituent(
                index_name="",
                ticker_symbol="VIC",
                effective_date=date(2023, 6, 15)
            )

    def test_constituent_validation_empty_ticker(self):
        """Test that empty ticker_symbol raises ValueError."""
        with pytest.raises(ValueError, match="ticker_symbol cannot be empty"):
            IndexConstituent(
                index_name="VN30",
                ticker_symbol="",
                effective_date=date(2023, 6, 15)
            )

    def test_constituent_validation_invalid_date_type(self):
        """Test that non-date effective_date raises TypeError."""
        with pytest.raises(TypeError, match="effective_date must be a date"):
            IndexConstituent(
                index_name="VN30",
                ticker_symbol="VIC",
                effective_date="2023-06-15"  # String instead of date
            )

    def test_constituent_dataclass_equality(self):
        """Test that two identical constituents are equal."""
        constituent1 = IndexConstituent(
            index_name="VN30",
            ticker_symbol="VIC",
            effective_date=date(2023, 6, 15)
        )
        constituent2 = IndexConstituent(
            index_name="VN30",
            ticker_symbol="VIC",
            effective_date=date(2023, 6, 15)
        )
        assert constituent1 == constituent2

    def test_multiple_constituents_same_index(self):
        """Test tracking multiple constituents for the same index."""
        constituents = [
            IndexConstituent("VN30", "VIC", date(2023, 6, 15)),
            IndexConstituent("VN30", "HPG", date(2023, 6, 15)),
            IndexConstituent("VN30", "VJC", date(2023, 6, 15)),
        ]

        assert len(constituents) == 3
        assert all(c.index_name == "VN30" for c in constituents)
        assert {c.ticker_symbol for c in constituents} == {"VIC", "HPG", "VJC"}


class TestFutureContractCode:
    """Test cases for FutureContractCode model."""

    def test_contract_code_creation(self):
        """Test creating a futures contract code mapping."""
        code = FutureContractCode(
            ticker_symbol="VN30F2306",
            contract_code="VN30F1M",
            effective_date=date(2023, 6, 1)
        )

        assert code.ticker_symbol == "VN30F2306"
        assert code.contract_code == "VN30F1M"
        assert code.effective_date == date(2023, 6, 1)

    def test_contract_code_validation_empty_ticker(self):
        """Test that empty ticker_symbol raises ValueError."""
        with pytest.raises(ValueError, match="ticker_symbol cannot be empty"):
            FutureContractCode(
                ticker_symbol="",
                contract_code="VN30F1M",
                effective_date=date(2023, 6, 1)
            )

    def test_contract_code_validation_empty_code(self):
        """Test that empty contract_code raises ValueError."""
        with pytest.raises(ValueError, match="contract_code cannot be empty"):
            FutureContractCode(
                ticker_symbol="VN30F2306",
                contract_code="",
                effective_date=date(2023, 6, 1)
            )

    def test_contract_code_validation_invalid_date_type(self):
        """Test that non-date effective_date raises TypeError."""
        with pytest.raises(TypeError, match="effective_date must be a date"):
            FutureContractCode(
                ticker_symbol="VN30F2306",
                contract_code="VN30F1M",
                effective_date="2023-06-01"  # String instead of date
            )

    def test_contract_code_dataclass_equality(self):
        """Test that two identical contract codes are equal."""
        code1 = FutureContractCode(
            ticker_symbol="VN30F2306",
            contract_code="VN30F1M",
            effective_date=date(2023, 6, 1)
        )
        code2 = FutureContractCode(
            ticker_symbol="VN30F2306",
            contract_code="VN30F1M",
            effective_date=date(2023, 6, 1)
        )
        assert code1 == code2

    def test_contract_code_series(self):
        """Test tracking a series of contract codes (1M, 2M, 1Q, 2Q)."""
        codes = [
            FutureContractCode("VN30F2306", "VN30F1M", date(2023, 6, 1)),
            FutureContractCode("VN30F2309", "VN30F1Q", date(2023, 6, 1)),
            FutureContractCode("VN30F2312", "VN30F2Q", date(2023, 6, 1)),
            FutureContractCode("VN30F2403", "VN30F2M", date(2023, 6, 1)),
        ]

        assert len(codes) == 4
        contract_types = {c.contract_code for c in codes}
        assert contract_types == {"VN30F1M", "VN30F1Q", "VN30F2Q", "VN30F2M"}

    def test_front_month_identification(self):
        """Test identifying front-month contracts."""
        front_month = FutureContractCode("VN30F2306", "VN30F1M", date(2023, 6, 1))
        second_month = FutureContractCode("VN30F2307", "VN30F2M", date(2023, 6, 1))

        assert front_month.contract_code == "VN30F1M"
        assert second_month.contract_code == "VN30F2M"


class TestMetadataIntegration:
    """Integration tests demonstrating usage of multiple metadata types together."""

    def test_futures_metadata_with_contract_code(self):
        """Test combining InstrumentMetadata with FutureContractCode."""
        # Instrument metadata for a futures contract
        metadata = InstrumentMetadata(
            ticker_symbol="VN30F2306",
            exchange_id="HSX",
            instrument_type="futures",
            last_updated=date(2023, 6, 15),
            start_date=date(2023, 6, 1),
            exp_date=date(2023, 6, 30)
        )

        # Contract code for the same contract
        code = FutureContractCode(
            ticker_symbol="VN30F2306",
            contract_code="VN30F1M",
            effective_date=date(2023, 6, 1)
        )

        # Verify they reference the same contract
        assert metadata.ticker_symbol == code.ticker_symbol
        assert metadata.instrument_type == "futures"
        assert code.contract_code == "VN30F1M"

    def test_index_constituents_with_metadata(self):
        """Test combining IndexConstituent with InstrumentMetadata."""
        # Index constituent
        constituent = IndexConstituent(
            index_name="VN30",
            ticker_symbol="VIC",
            effective_date=date(2023, 6, 15)
        )

        # Instrument metadata for the same security
        metadata = InstrumentMetadata(
            ticker_symbol="VIC",
            exchange_id="HSX",
            instrument_type="stock",
            last_updated=date(2023, 6, 15)
        )

        # Verify they reference the same security
        assert constituent.ticker_symbol == metadata.ticker_symbol
        assert constituent.index_name == "VN30"
        assert metadata.exchange_id == "HSX"