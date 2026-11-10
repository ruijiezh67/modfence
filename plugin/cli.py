"""Entry point for the Claude Code plugin's hooks and commands: runs modfence from the plugin's own folder, so the
plugin needs no pip install (golden rule 7)."""
import os, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from modfence.__main__ import main  # noqa: E402

sys.exit(main())
