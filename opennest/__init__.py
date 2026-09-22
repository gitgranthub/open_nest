"""Open Nest — a local-first project workspace for kids."""

__version__ = "0.1.0"

#: Child-facing product name. See DESIGN_DOC.md section 1.
APP_NAME = "Open Nest"

#: The visible conversational helper (brand_design_guide.md section 3), adopted in Phase
#: 10B. Gary is a *voice*, not a character: he has no illustrated face, and section 47
#: keeps him separate from the pixel-art symbols -- the eagle, the nest and the
#: sunglasses belong to Open Nest, and Gary never names them out loud.
ASSISTANT_NAME = "Gary"

#: Who a message is attributed to when Gary did not say it. The split is settled in
#: PHASE_10_HANDOFF.md section 1: installation, security, account, recovery and status
#: stay Open Nest rather than pretending Gary said them. A transport failure is the
#: case that makes this matter -- see ``Workbench._turn_failed``.
SYSTEM_NAME = APP_NAME
