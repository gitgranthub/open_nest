"""Installation lifecycle: the setup wizard, and what it records.

WORKORDER_01 section 35A. This package is deliberately separate from ``opennest/ui``
because it answers a different question -- not "what is the child doing" but "is this
Mac set up, and is it still set up". The wizard is the visible part; most of what is
here is UI-free so it can be tested without a display and reused by Repair Installation.

Why it lives under ``opennest/`` rather than ``bootstrap/``: section 35A requires the
installer to run one real inference *through the same provider code the app uses*, and
forbids a separate installer-only implementation. That means importing
``opennest.ai.mlx_provider``, which ``bootstrap/`` may not do -- it must stay Python
3.9-compatible and free of application imports, because it runs before either exists.
The bootstrap therefore *launches* this package as a subprocess once the environment is
ready, which keeps the two decoupled by process boundary rather than by duplication.
"""
