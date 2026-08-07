"""Custom XPath 1.0 extension functions.

lxml lets you extend XPath with Python callables. Every function here is named
``xpath_func_<name>`` and is exposed to expressions as ``<name>``, so a field can
say ``tokenize(title/text(), " - ")`` directly in its xpath.
"""

import re

_PREFIX = "xpath_func_"


def _as_text(value):
    """XPath hands back nodesets, smart strings or None depending on the expression."""
    if isinstance(value, list):
        value = value[0] if value else ""
    if value is None:
        return ""
    if hasattr(value, "text_content"):
        return value.text_content()
    return str(value)


def xpath_func_tokenize(context, value, delimiter):
    return _as_text(value).split(delimiter)


def xpath_func_make_title(context, value):
    return _as_text(value).title()


def xpath_func_findzipcode(context, value):
    return re.findall(r"\d{5}", _as_text(value))


def iter_functions():
    """Yield ``(exposed_name, callable)`` for every extension function in this module."""
    for name, func in sorted(globals().items()):
        if name.startswith(_PREFIX) and callable(func):
            yield name[len(_PREFIX) :], func


def register(namespace=None):
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
