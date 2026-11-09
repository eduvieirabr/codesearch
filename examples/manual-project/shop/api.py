"""Entry point for the fictitious order API."""

from .checkout import checkout


def create_order(prices: list[int]) -> dict:
    """Prepare an order using the checkout module."""
    return checkout(prices)
