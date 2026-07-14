"""Auto-discovers and imports every converter module in this package.

Import ``fileconverter.converters`` once (the CLI/GUI entry points do this)
and every ``*_converter.py`` module here registers itself with the global
registry as a side effect of being imported. To add a brand-new format,
just drop a new ``my_format_converter.py`` file in this folder that
subclasses ``BaseConverter`` and calls ``register(...)`` at module scope —
nothing else needs to change.
"""

from __future__ import annotations

import importlib
import pkgutil

_package_name = __name__

for module_info in pkgutil.iter_modules(__path__):
    if module_info.name.endswith("_converter"):
        importlib.import_module(f"{_package_name}.{module_info.name}")
