"""Intentional import cycle for static inspection; do not execute."""

from .cycle_a import label_a


def label_b() -> str:
    return label_a()
