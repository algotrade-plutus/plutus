"""Plutus — zero-setup market data analytics for the Vietnamese market.

Plutus provides a market-faithful data and instrument layer: daily and tick
market data queried directly from CSV/Parquet with no database to install, and
the market's own structural rules (price-limit bands, price-dependent tick
grids, round lots, trading sessions) as first-class objects.

Plutus does **not** ship a backtesting or live-execution engine. An earlier
attempt at one was removed from the package; see ``archive/legacy-trader-stack``.

Example:
    >>> from plutus.datahub import OHLCQuery
    >>> bars = OHLCQuery().fetch('FPT', '2021-01-15', '2021-02-15', interval='1d')
    >>> df = bars.to_dataframe()
"""

from importlib import metadata as _metadata

#: Distribution name on PyPI. The bare name `plutus` belongs to an unrelated
#: project, so anything resolving this package by name must use this one.
DISTRIBUTION_NAME = "algotrade-plutus"


def _resolve_version() -> str:
    """Resolve the version from installed metadata, falling back to pyproject.

    `pyproject.toml` is the single source of truth. Installed metadata is
    derived from it, so it is preferred at runtime; the fallback exists for a
    source checkout run straight off `src/` with nothing installed, which is
    how the test suite runs.

    Note that the two can differ in spelling: packaging normalises a version
    like `0.2.5.202510rc` to `0.2.5.202510rc0`. Both denote the same release.
    """
    try:
        return _metadata.version(DISTRIBUTION_NAME)
    except _metadata.PackageNotFoundError:
        pass

    try:  # source checkout: read pyproject.toml directly
        import tomllib
        from pathlib import Path

        pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
        if pyproject.is_file():
            with pyproject.open("rb") as handle:
                return tomllib.load(handle)["project"]["version"]
    except Exception:  # pragma: no cover - never let version lookup break import
        pass

    return "0.0.0+unknown"


__version__ = _resolve_version()

__all__ = [
    "__version__",
    "DISTRIBUTION_NAME",
]
