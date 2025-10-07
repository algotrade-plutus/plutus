"""Example: OHLC Bar Generation from Tick Data

This example demonstrates how to use the OHLCQuery class to generate
candlestick bars from high-frequency tick data.
"""

from plutus.datahub import query_historical, OHLCQuery
from pathlib import Path

# Example 1: Generate 1-minute OHLC bars using unified API
print("=" * 60)
print("Example 1: 1-Minute OHLC Bars (Unified API)")
print("=" * 60)

ohlc_1m = query_historical(
    ticker_symbol='FPT',
    begin='2021-01-15',
    end='2021-01-16',
    type='ohlc',
    interval='1m',
    include_volume=True
)

# Iterate through bars
bar_count = 0
for bar in ohlc_1m:
    bar_count += 1
    if bar_count <= 3:  # Show first 3 bars
        print(f"\nBar {bar_count}:")
        print(f"  Time:   {bar['bar_time']}")
        print(f"  Open:   {bar['open']}")
        print(f"  High:   {bar['high']}")
        print(f"  Low:    {bar['low']}")
        print(f"  Close:  {bar['close']}")
        print(f"  Volume: {bar['volume']:,.0f}")

print(f"\nTotal bars: {bar_count}")


# Example 2: Generate 5-minute OHLC bars
print("\n" + "=" * 60)
print("Example 2: 5-Minute OHLC Bars")
print("=" * 60)

ohlc_5m = query_historical(
    ticker_symbol='VIC',
    begin='2021-01-15 09:00:00',
    end='2021-01-15 12:00:00',
    type='ohlc',
    interval='5m'
)

# Convert to DataFrame for analysis
df = ohlc_5m.to_dataframe()
print(f"\nDataFrame shape: {df.shape}")
print(f"Columns: {list(df.columns)}")
print(f"\nFirst 5 bars:")
print(df.head())

# Calculate some statistics
print(f"\nPrice Statistics:")
print(f"  High of highs:  {df['high'].max()}")
print(f"  Low of lows:    {df['low'].min()}")
print(f"  Total volume:   {df['volume'].sum():,.0f}")


# Example 3: Daily OHLC bars for backtesting
print("\n" + "=" * 60)
print("Example 3: Daily OHLC Bars for Backtesting")
print("=" * 60)

ohlc_daily = query_historical(
    ticker_symbol='HPG',
    begin='2021-01-01',
    end='2021-02-01',
    type='ohlc',
    interval='1d'
)

# Save to CSV for backtesting
df_daily = ohlc_daily.to_dataframe()
output_file = 'hpg_daily_ohlc.csv'
df_daily.to_csv(output_file, index=False)
print(f"Saved {len(df_daily)} daily bars to {output_file}")


# Example 4: Using OHLCQuery class directly (advanced)
print("\n" + "=" * 60)
print("Example 4: Direct OHLCQuery Usage (Advanced)")
print("=" * 60)

from plutus.datahub import DataHubConfig

# Configure custom data location
config = DataHubConfig(data_root='/path/to/dataset')
query = OHLCQuery(config)

# Fetch 15-minute bars
ohlc_15m = query.fetch(
    ticker='FPT',
    start_date='2021-01-15 09:00',
    end_date='2021-01-15 16:00',
    interval='15m',
    include_volume=True
)

# Process in batches (memory-efficient)
print("\nProcessing 15-minute bars in batches...")
batch_size = 10
total_processed = 0

for batch in ohlc_15m.batches(size=batch_size):
    # Process each batch
    total_processed += len(batch)
    print(f"  Processed batch of {len(batch)} bars")

print(f"Total bars processed: {total_processed}")


# Example 5: Price-only OHLC (no volume)
print("\n" + "=" * 60)
print("Example 5: OHLC Without Volume")
print("=" * 60)

ohlc_no_vol = query_historical(
    ticker_symbol='VNM',
    begin='2021-01-15',
    end='2021-01-16',
    type='ohlc',
    interval='1h',
    include_volume=False  # Exclude volume
)

# Volume field should not be present
for i, bar in enumerate(ohlc_no_vol):
    if i == 0:
        print(f"\nFirst bar (no volume):")
        for key, value in bar.items():
            print(f"  {key}: {value}")
        assert 'volume' not in bar, "Volume should not be included!"
    break


# Example 6: Error handling
print("\n" + "=" * 60)
print("Example 6: Error Handling")
print("=" * 60)

try:
    # Invalid interval
    bad_query = query_historical(
        ticker_symbol='FPT',
        begin='2021-01-15',
        end='2021-01-16',
        type='ohlc',
        interval='99m'  # Invalid!
    )
except ValueError as e:
    print(f"✓ Caught expected error: {e}")

try:
    # Invalid date range
    bad_query = query_historical(
        ticker_symbol='FPT',
        begin='2021-01-16',  # After end date
        end='2021-01-15',
        type='ohlc',
        interval='1m'
    )
except ValueError as e:
    print(f"✓ Caught expected error: {e}")


print("\n" + "=" * 60)
print("✅ All examples completed successfully!")
print("=" * 60)
