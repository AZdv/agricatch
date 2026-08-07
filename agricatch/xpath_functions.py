"""Custom XPath 1.0 extension functions.

lxml lets you extend XPath with Python callables. Every function here is named
``xpath_func_<name>`` and is exposed to expressions as ``<name>``, so a field can
say ``tokenize(title/text(), " - ")`` directly in its xpath.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from typing import Any

_PREFIX = "xpath_func_"

# lxml passes an evaluation context as the first argument and hands values back
# as nodesets, smart strings or None, none of which have useful public types.
XPathContext = Any
XPathValue = Any


def _as_text(value: XPathValue) -> str:
    """XPath hands back nodesets, smart strings or None depending on the expression."""
    if isinstance(value, list):
        value = value[0] if value else ""
    if value is None:
        return ""
    if hasattr(value, "text_content"):
        return str(value.text_content())
    return str(value)


def xpath_func_tokenize(context: XPathContext, value: XPathValue, delimiter: str) -> list[str]:
    return _as_text(value).split(delimiter)


def xpath_func_make_title(context: XPathContext, value: XPathValue) -> str:
    return _as_text(value).title()


def xpath_func_findzipcode(context: XPathContext, value: XPathValue) -> list[str]:
    return re.findall(r"\d{5}", _as_text(value))


def iter_functions() -> Iterator[tuple[str, Callable[..., Any]]]:
    """Yield ``(exposed_name, callable)`` for every extension function in this module."""
    for name, func in sorted(globals().items()):
        if name.startswith(_PREFIX) and callable(func):
            yield name[len(_PREFIX) :], func


def register(namespace: Any | None = None) -> Any:
    """Install the extension functions into an lxml FunctionNamespace.

    Defaults to the unprefixed namespace, which is what plain ``tokenize(...)``
    in an xpath string resolves against.
    """
    if namespace is None:
        from lxml import etree

        namespace = etree.FunctionNamespace(None)
    for name, func in iter_functions():
        namespace[name] = func
    return namespace
