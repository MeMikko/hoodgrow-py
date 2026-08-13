"""Single source of truth for the package version.

Its own module rather than a literal in ``__init__.py`` because ``client``
needs it too, for the ``User-Agent`` it sends on every request. Importing it
from ``__init__`` would be circular: ``__init__`` imports ``client`` on its
first line and only binds ``__version__`` fifty lines later, so ``client``
would import a name that does not exist yet.

A test asserts this matches ``pyproject.toml`` — the sibling MCP package
reported 0.4.0 while shipping 0.7.1 because two copies of a version number
had nothing holding them together.
"""

__version__ = "0.11.0"
