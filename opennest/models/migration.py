"""Carrying an existing installation into the Phase 11B model registry.

Section 55 of the Phase 11 work order, and it matters more than most migrations: Phase
12 is the owner's first hands-on test, and it depends on the Qwen model already on their
Mac still being the one Open Nest uses, without a redownload.

**Nothing here downloads, deletes or rewrites a model.** It reconciles a record with what
is actually on disk. The worst outcome of getting it wrong should be a stale line in a
JSON file, never a missing model or a second copy of one.

Three things it fixes, each of which is a real state an installation can already be in:

- **A preferred model that is still perfectly good.** The common case. Before Phase 11B
  the id in ``installation.json`` was compared against a hard-coded list; it is now a
  key into a catalogue that a remote update can change. A valid id is left alone.
- **A preferred model the catalogue no longer offers.** A withdrawn or renamed entry.
  The preference is cleared rather than silently repointed at something else -- section
  38 forbids substituting a model behind a person's back, and that applies just as much
  when the substitution would be convenient.
- **An ``installed_models`` list that disagrees with the disk.** It was only ever written
  by the wizard, so a model downloaded some other way was missing from it, and a model
  removed by hand stayed in it. Both are now answered by looking.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MigrationResult:
    """What changed, in terms that can be shown to a parent or written to a log."""

    changed: bool = False
    #: Plain-language notes, one per thing that moved. Empty when nothing did.
    notes: tuple[str, ...] = ()
    #: The model that ended up preferred, after reconciliation.
    preferred_model: str = ""


def migrate(state, catalog=None, *, installed_ids=None) -> MigrationResult:
    """Reconcile an installation record with the catalogue and the disk.

    ``installed_ids`` is injectable so this can be tested without a model on the
    machine running the tests -- which is the whole point, since the machine running
    the tests is not the machine being migrated.
    """
    from opennest.ai import router
    from opennest.models import discovery

    entries = catalog if catalog is not None else router.load_catalogue()
    known = {entry.info.id for entry in entries}

    if installed_ids is None:
        try:
            installed_ids = list(discovery.installed_ids(entries))
        except Exception:
            # A cache that cannot be read is not a reason to rewrite a record. Leaving
            # the list alone is the conservative answer: it may be stale, and stale is
            # better than empty, because empty reads as "nothing is installed" and
            # that is what triggers a download.
            installed_ids = list(state.installed_models)

    notes: list[str] = []
    changed = False

    preferred = state.preferred_model
    if preferred and preferred not in known:
        notes.append(
            f"The model this Mac was set up with ({preferred}) is no longer one Open "
            f"Nest offers. Choose another in Settings."
        )
        state.preferred_model = ""
        changed = True

    # Discovery is the authority, because it asks the same question the provider asks
    # when it loads. A record saying a model is installed does not make it loadable.
    reconciled = [model_id for model_id in installed_ids if model_id in known]
    if sorted(reconciled) != sorted(state.installed_models):
        gained = sorted(set(reconciled) - set(state.installed_models))
        lost = sorted(set(state.installed_models) - set(reconciled))
        if gained:
            notes.append(f"Found {len(gained)} model(s) already on this Mac.")
        if lost:
            notes.append(f"{len(lost)} model(s) in the record are no longer on this Mac.")
        state.installed_models = reconciled
        changed = True

    # A Mac with a working model and no stated preference should use it rather than be
    # asked. This is the case that matters for the owner's first run: the model is
    # there, setup predates the registry, and nothing should offer to fetch it again.
    if not state.preferred_model and reconciled:
        preferred_default = router.default_model_id()
        pick = preferred_default if preferred_default in reconciled else reconciled[0]
        state.preferred_model = pick
        notes.append(f"Using the model already installed on this Mac ({pick}).")
        changed = True

    return MigrationResult(
        changed=changed, notes=tuple(notes), preferred_model=state.preferred_model
    )
