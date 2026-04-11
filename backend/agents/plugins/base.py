"""
agents/plugins/base.py — Plugin base class.

Plugins describe themselves in natural language.
The router agent reads all descriptions and decides which plugin to call.

To add a new plugin:
  1. Create a file in agents/plugins/
  2. Inherit WhisprPlugin
  3. Set name, description, examples
  4. Implement run(text, context) -> str
  5. Export plugin = MyPlugin()
"""
from __future__ import annotations

import sys
from pathlib import Path
_backend_root = str(Path(__file__).resolve().parents[2])
if _backend_root not in sys.path:
    sys.path.insert(0, _backend_root)

from abc import ABC, abstractmethod


class WhisprPlugin(ABC):
    """Base class for all Whispr plugins."""

    name       : str       = ""    # unique id e.g. "knowledge"
    description: str       = ""    # what this plugin does — used by router agent
    examples   : list[str] = []    # example inputs that trigger this plugin
    priority   : int       = 50    # fallback order if agent is unsure (lower = first)

    @abstractmethod
    def run(self, text: str, context: dict) -> str:
        """Execute the plugin and return the output string."""
        ...

    def can_handle(self, text: str, context: dict) -> bool:
        """Optional fast regex pre-check — return True to skip agent routing.
        Leave as False to always go through the agent router.
        """
        return False

    def to_prompt_entry(self) -> str:
        """Return a description string for the router agent prompt."""
        lines = [f'- {self.name}: {self.description}']
        if self.examples:
            lines.append(f'  Examples: {", ".join(repr(e) for e in self.examples[:3])}')
        return "\n".join(lines)

    def __repr__(self) -> str:
        return f"<Plugin:{self.name} priority={self.priority}>"