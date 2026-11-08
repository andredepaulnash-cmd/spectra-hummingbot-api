"""Refuse to start against an unreviewed Hummingbot core package.

The environment pins the PyPI core package version and this guard checks the
installed distribution metadata before any API services start. The additional
surface list remains available for any future field-level compatibility checks.
"""
from importlib.metadata import PackageNotFoundError, version
from typing import List, Tuple

# (import path, attribute, what it is for) — each one a field this API reads off the
# core and cannot substitute.
PINNED_CORE_VERSION = "20260922"

REQUIRED_CORE_SURFACE: List[Tuple[str, str, str]] = [
    # Empty on purpose. This guard exists for a core field this API reads that a released
    # hummingbot may not carry yet; there is no such field right now. volume_traded_quote
    # was the last one, and it is gone: filled_amount_quote means the volume traded on
    # every executor, including LP, so there is nothing extra to require.
]


def _resolve(path: str):
    module_path, _, name = path.partition(":")
    module = __import__(module_path, fromlist=[name])
    return getattr(module, name)


def require_core_surface() -> None:
    """Require the reviewed Hummingbot package before starting API services."""
    try:
        installed_version = version("hummingbot")
    except PackageNotFoundError as exc:
        raise RuntimeError(
            f"Required Hummingbot core {PINNED_CORE_VERSION} is not installed."
        ) from exc

    if installed_version != PINNED_CORE_VERSION:
        raise RuntimeError(
            "Unsupported Hummingbot core version: "
            f"expected {PINNED_CORE_VERSION}, found {installed_version}. "
            "Rebuild the API image from environment.yml before starting."
        )

    missing = []
    for path, attribute, purpose in REQUIRED_CORE_SURFACE:
        try:
            owner = _resolve(path)
        except (ImportError, AttributeError) as e:
            missing.append(f"  - {path} could not be imported ({e})")
            continue
        fields = getattr(owner, "model_fields", None)
        present = attribute in fields if fields is not None else hasattr(owner, attribute)
        if not present:
            missing.append(f"  - {path}.{attribute} — {purpose}")

    if missing:
        raise RuntimeError(
            "The installed hummingbot core is older than this API requires. Missing:\n"
            + "\n".join(missing)
            + f"\n\nInstalled hummingbot: {installed_version}. "
            "Install a core that carries these fields (see environment.yml) and rebuild. "
            "Starting anyway would record every executor's pnl, fees and volume as zero."
        )
