"""Calculate order totals in integer cents."""


def apply_discount(subtotal: int, percent: int) -> int:
    """Apply an integer discount percentage."""
    if not 0 <= percent <= 100:
        raise ValueError("Invalid discount percentage")
    return subtotal * (100 - percent) // 100


def calculate_total(prices: list[int], discount: int = 0) -> int:
    """Calculate the discounted total for a checkout."""
    subtotal = sum(prices)
    return apply_discount(subtotal, discount)
