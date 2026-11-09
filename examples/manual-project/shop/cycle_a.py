"""Intentional import cycle for static inspection; do not execute."""

from .cycle_b import label_b


def label_a() -> str:
    return label_b()
