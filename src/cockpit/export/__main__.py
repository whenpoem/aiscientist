"""Allow ``python -m cockpit.export`` to dispatch through cli.main."""

from __future__ import annotations

from cockpit.export.cli import main

raise SystemExit(main())
