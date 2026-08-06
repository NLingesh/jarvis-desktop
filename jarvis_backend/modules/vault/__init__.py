"""Markdown vault — an Obsidian-compatible file-based memory system.

Public surface::

    from modules.vault.manager import VaultManager

The package is organized as:

* ``store.py``     — atomic, root-confined filesystem access
* ``codec.py``     — frontmatter parse/serialize, tags, wikilinks
* ``templates.py`` — default folder + body per note type
* ``search.py``    — swappable search backend (FTS5 today)
* ``manager.py``   — the single high-level API used by routes and skills
"""

from modules.vault.manager import VaultManager

__all__ = ["VaultManager"]
