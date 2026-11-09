"""Declared inheritance for the manual examples."""


class Order:
    """Base order."""

    def status(self) -> str:
        return "pending"


class DiscountedOrder(Order):
    """Order with a discount policy."""

    def discount_percent(self) -> int:
        return 10
