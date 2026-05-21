"""Jinja2 helpers for rendering nested template structures."""

from collections.abc import Mapping
from typing import Any

import jinja2

_DROP = object()  # sentinel: rendered placeholder collapsed to empty


def render_node(node: Any, env: jinja2.Environment, ctx: Mapping[str, Any]) -> Any:
    """Recursively render a template node with Jinja2.

    Strings containing ``{{`` are rendered against ``ctx``; an empty
    rendered result causes the surrounding dict key to be dropped or
    the surrounding list element to be skipped. Non-string scalars
    pass through unchanged.
    """
    if isinstance(node, str):
        if "{{" not in node:
            return node
        rendered = env.from_string(node).render(**ctx).strip()
        if rendered == "":
            return _DROP
        return rendered
    if isinstance(node, dict):
        result: dict[Any, Any] = {}
        for k, v in node.items():
            rendered = render_node(v, env, ctx)
            if rendered is _DROP:
                continue
            result[k] = rendered
        return result
    if isinstance(node, list):
        result_list: list[Any] = []
        for item in node:
            rendered = render_node(item, env, ctx)
            if rendered is _DROP:
                continue
            result_list.append(rendered)
        return result_list
    return node
