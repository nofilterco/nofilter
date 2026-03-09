from __future__ import annotations


def build_description(title: str, **kwargs: str) -> str:
    exact = kwargs.get("exact_html_description")
    if exact:
        return exact
    return f"<p>{title} from Crafted Occasion. Add personalization details at checkout.</p>"
