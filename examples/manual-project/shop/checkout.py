"""Checkout orchestration."""

from .pricing import calculate_total


def checkout(prices: list[int], discount: int = 0) -> dict:
    """Create a checkout summary in cents."""
    return {"total": calculate_total(prices, discount), "currency": "BRL"}
