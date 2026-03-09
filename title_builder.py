from __future__ import annotations


def build_title(seed: str = "", **kwargs: str) -> str:
    exact = kwargs.get("exact_title")
    if exact:
        return exact
    return seed or "Crafted Occasion Personalized Product"
