"""Installing and verifying a local model, and the setup health check.

WORKORDER_01 section 35A, "Model installation" / "Model verification" / step 7. These
are hermetic: no network, no real model, no Keychain. The behaviours that *cannot* be
tested that way -- that a real download resumes, that a real cancel stops the transfer,
that a real model answers -- were measured instead, and are recorded in SPIKES.md
section 15.

The recurring rule is the one section 35A states outright: an optional service nobody
configured shows "Not configured", not an error. A health check that cries wolf about
Anthropic on a machine with no Anthropic key is a health check a parent learns to skip.
"""

from __future__ import annotations

from opennest.ai.provider import ProviderError, Reply
from opennest.ai.router import ModelEntry
from opennest.security import keychain, permissions
from opennest.setup import checks, downloader
from tests.conftest import FakeKeyring, ScriptedProvider


def _entry(model_id="mlx-community/thing", download_gb=2.28, name="Test Model"):
    from opennest.ai.provider import ModelInfo

    return ModelEntry(
        info=ModelInfo(id="test-model", name=name, provider="mlx"),
        model_id=model_id,
        revision="a" * 40,
        download_gb=download_gb,
    )


# --------------------------------------------------------------------- progress

def test_progress_reads_the_way_the_work_order_shows_it() -> None:
    """Section 35A's example: "3.1 GB of 4.0 GB" under a bar at 78%."""
    progress = downloader.Progress(3_100_000_000, 4_000_000_000)
    assert progress.percent == 77
    assert progress.describe() == "3.1 GB of 4.0 GB"


def test_progress_with_no_announced_total_does_not_invent_one() -> None:
    progress = downloader.Progress(500_000_000, 0)
    assert progress.fraction == 0.0
    assert "of" not in progress.describe()


def test_progress_cannot_exceed_its_total() -> None:
    """A bar that reads 140% is worse than one that sits at 100%."""
    assert downloader.Progress(5_000_000_000, 4_000_000_000).percent == 100


def test_the_stated_download_size_never_grows(monkeypatch) -> None:
    """The acceptance pass watched a 2.28 GB model report "4.2 GB of 4.2 GB".

    huggingface_hub's byte counts are summed across its own progress bars and can
    overshoot; an earlier version let the *denominator* chase them upward, so the
    wizard overstated how large the download was while it ran. The catalogue is the
    source of truth for a size (section 35A), and the count is clamped to it.
    """
    entry = _entry(download_gb=2.28)
    reported: list = []
    monkeypatch.setattr(downloader, "is_installed", lambda e: False)
    monkeypatch.setattr(
        downloader, "_pump",
        lambda child, sink: [
            sink.put('{"bytes": 1000000000}\n'),
            sink.put('{"bytes": 3000000000}\n'),   # overshoots the real size
            sink.put('{"bytes": 4200000000}\n'),   # overshoots badly
            sink.put('{"done": true, "path": "/x"}\n'),
            sink.put(None),
        ],
    )
    downloader.download(entry, on_progress=reported.append)

    assert reported, "progress should have been reported"
    totals = {p.total_bytes for p in reported}
    assert totals == {2_280_000_000}, f"the stated total moved: {totals}"
    assert all(p.downloaded_bytes <= p.total_bytes for p in reported)
    assert all(p.percent <= 100 for p in reported)
    assert reported[-1].describe() == "2.3 GB of 2.3 GB"


def test_small_downloads_are_reported_in_megabytes() -> None:
    assert downloader.Progress(120_000_000, 300_000_000).describe() == "120 MB of 300 MB"


# --------------------------------------------------------------------- what is installed

def test_expected_size_comes_from_the_catalogue() -> None:
    """Section 35A: sizes come from the model config, not from wizard logic."""
    assert downloader.expected_bytes(_entry(download_gb=2.28)) == 2_280_000_000


def test_a_model_with_nothing_configured_is_not_installed() -> None:
    assert downloader.is_installed(_entry(model_id=None)) is False


def test_availability_is_decided_by_the_call_the_app_itself_makes(monkeypatch) -> None:
    """``resolve_local_model`` is what MLXProvider.load uses, so True means loadable."""
    seen: list[tuple] = []

    def resolve(model_id, revision=None):
        seen.append((model_id, revision))
        return "/somewhere"

    monkeypatch.setattr("opennest.ai.mlx_provider.resolve_local_model", resolve)
    assert downloader.is_installed(_entry()) is True
    assert seen == [("mlx-community/thing", "a" * 40)]


def test_an_unresolvable_model_is_simply_not_available(monkeypatch) -> None:
    def resolve(model_id, revision=None):
        raise ProviderError("not installed")

    monkeypatch.setattr("opennest.ai.mlx_provider.resolve_local_model", resolve)
    assert downloader.is_installed(_entry()) is False


# --------------------------------------------------------------------- downloading

def test_a_model_already_on_disk_is_not_downloaded_again(monkeypatch) -> None:
    """Section 35A: "avoid downloading duplicate copies unnecessarily"."""
    monkeypatch.setattr(downloader, "is_installed", lambda entry: True)
    result = downloader.download(_entry())
    assert result.ok is True
    assert result.outcome == "already-installed"


def test_a_model_with_no_repository_fails_without_starting_anything(monkeypatch) -> None:
    result = downloader.download(_entry(model_id=None))
    assert result.ok is False
    assert result.outcome == "failed"


def test_cancelling_does_not_promise_a_resume_that_cannot_happen(monkeypatch) -> None:
    """SPIKES.md section 15B: hf_hub 1.32 re-transfers from the start every time.

    An earlier version of this message said "starting again will carry on from where it
    stopped", which was measured to be false.
    """
    monkeypatch.setattr(downloader, "is_installed", lambda entry: False)
    result = downloader.download(_entry(), should_cancel=lambda: True)
    assert result.outcome == "cancelled"
    assert "carry on from where it stopped" not in result.message


def test_cancelling_throws_away_the_partial_download(tmp_path, monkeypatch) -> None:
    """Three cancels once left 102 MB of files nothing would ever read again."""
    entry = _entry()
    folder = tmp_path / "models--mlx-community--thing" / "blobs"
    folder.mkdir(parents=True)
    orphan = folder / "abc.deadbeef.incomplete"
    orphan.write_bytes(b"x" * 4096)
    keeper = folder / "abc"
    keeper.write_bytes(b"y" * 16)

    monkeypatch.setattr(downloader, "is_installed", lambda e: False)
    result = downloader.download(entry, should_cancel=lambda: True, store=tmp_path)

    assert result.outcome == "cancelled"
    assert not orphan.exists(), "the abandoned partial should have been removed"
    assert keeper.exists(), "a completed blob must never be touched"


def test_discarding_a_partial_leaves_other_models_alone(tmp_path) -> None:
    other = tmp_path / "models--mlx-community--something-else" / "blobs"
    other.mkdir(parents=True)
    theirs = other / "zzz.cafebabe.incomplete"
    theirs.write_bytes(b"z" * 128)

    downloader._discard_partial_files(_entry(), tmp_path)
    assert theirs.exists(), "another model's download must not be disturbed"


def test_a_completed_download_is_not_reported_as_failed(monkeypatch) -> None:
    """The final line can arrive after the child has already exited.

    The loop waits for ``_pump``'s sentinel rather than breaking as soon as the child
    process is gone, because the last line it wrote can still be in flight.
    """
    import time

    monkeypatch.setattr(downloader, "is_installed", lambda e: False)

    def slow_pump(child, sink):
        child.wait()          # the child is gone before anything is delivered
        time.sleep(0.5)       # and the final line is late
        sink.put('{"done": true, "path": "/models/thing"}\n')
        sink.put(None)

    monkeypatch.setattr(downloader, "_pump", slow_pump)
    result = downloader.download(_entry())

    assert result.ok is True, result.message
    assert result.outcome == "completed"


def test_the_success_line_is_built_outside_the_try(monkeypatch) -> None:
    """A fault in *reporting* success must not be reported as a failed download.

    The Phase 8 acceptance pass hit exactly this: a stale ``Reporting.seen`` raised
    AttributeError after a 2.3 GB download had finished, the child's blanket except
    caught it, and the wizard said the model "could not be downloaded" -- for a model
    that was on disk and passed its inference test moments later.
    """
    child = downloader._CHILD
    body = child.split("try:", 1)[1]
    success, _, failure = body.partition("except BaseException")
    assert '"done": True' not in success, (
        "the success line is inside the try; an error while composing it will be "
        "reported as a download failure"
    )
    assert "else:" in failure and '"done": True' in failure


def test_a_child_that_says_nothing_at_all_is_still_a_failure(monkeypatch) -> None:
    """The sentinel is what ends the loop, so a silent child must not hang it."""
    monkeypatch.setattr(downloader, "is_installed", lambda e: False)
    monkeypatch.setattr(downloader, "_pump", lambda child, sink: sink.put(None))

    result = downloader.download(_entry())
    assert result.ok is False
    assert result.outcome == "failed"


def test_cancelling_leaves_no_child_process_behind(monkeypatch) -> None:
    """Cancel must stop the transfer, not just stop the window waiting for it."""
    started: list = []
    real_popen = downloader.subprocess.Popen

    def watched(*args, **kwargs):
        child = real_popen(*args, **kwargs)
        started.append(child)
        return child

    monkeypatch.setattr(downloader, "is_installed", lambda entry: False)
    monkeypatch.setattr(downloader.subprocess, "Popen", watched)
    downloader.download(_entry(), should_cancel=lambda: True)

    assert started, "a download subprocess should have been started"
    for child in started:
        assert child.poll() is not None, "the download process is still running"


def test_the_download_never_uses_the_backend_that_cannot_be_cancelled(monkeypatch) -> None:
    """SPIKES.md section 15: with Xet on, a cancel at 127 MB still fetched 1,598 MB."""
    captured: dict = {}
    real_popen = downloader.subprocess.Popen

    def watched(*args, **kwargs):
        captured.update(kwargs.get("env") or {})
        return real_popen(*args, **kwargs)

    monkeypatch.setattr(downloader, "is_installed", lambda entry: False)
    monkeypatch.setattr(downloader.subprocess, "Popen", watched)
    downloader.download(_entry(), should_cancel=lambda: True)

    assert captured.get("HF_HUB_DISABLE_XET") == "1"


# --------------------------------------------------------------------- verification

def test_verification_needs_a_real_answer_from_the_provider() -> None:
    """Section 35A: one real request "through the same provider code" the app uses."""
    provider = ScriptedProvider([Reply(text="OPEN NEST READY")])
    result = downloader.verify(_entry(), provider=provider)
    assert result.ok is True
    assert result.reply == "OPEN NEST READY"
    assert provider.calls, "the provider should actually have been asked something"


def test_verification_does_not_demand_the_exact_words() -> None:
    """The checklist is about the machinery. A chatty model has still proved it works."""
    provider = ScriptedProvider([Reply(text="Sure! OPEN NEST READY")])
    assert downloader.verify(_entry(), provider=provider).ok is True


def test_a_model_that_answers_nothing_has_not_been_verified() -> None:
    """SPIKES.md section 13 has a real case: a success by every mechanical measure,
    and silence on screen."""
    provider = ScriptedProvider([Reply(text="")])
    result = downloader.verify(_entry(), provider=provider)
    assert result.ok is False
    assert "nothing" in result.message


def test_a_model_that_will_not_load_is_reported_as_such() -> None:
    class Broken(ScriptedProvider):
        def load(self):
            raise ProviderError("The local AI model could not be loaded.")

    result = downloader.verify(_entry(), provider=Broken([]))
    assert result.ok is False
    assert result.model_loaded is False


def test_a_missing_engine_is_told_apart_from_a_bad_download() -> None:
    """Three ticks, three different failures -- and three different remedies."""
    class NoEngine(ScriptedProvider):
        def load(self):
            raise ProviderError("The local AI engine is not installed.")

    result = downloader.verify(_entry(), provider=NoEngine([]))
    assert result.engine_loaded is False


def test_verification_reports_the_three_ticks_the_work_order_shows() -> None:
    provider = ScriptedProvider([Reply(text="OPEN NEST READY")])
    lines = downloader.verify(_entry(), provider=provider).lines()
    assert lines == ("✓ Installed", "✓ Loaded successfully", "✓ Test response received")


def test_a_model_that_never_answers_does_not_hang_the_wizard() -> None:
    import time

    class Slow(ScriptedProvider):
        def chat(self, messages, *, tools=None, settings=None):
            time.sleep(5)
            yield from ()

    result = downloader.verify(_entry(), provider=Slow([]), timeout_seconds=0.2)
    assert result.ok is False
    assert "did not answer" in result.message


# --------------------------------------------------------------------- health check

def _controls(**kwargs):
    return permissions.ParentControls(**kwargs)


def _store(items=None):
    return keychain.Credentials(backend=FakeKeyring(items or {}))


def test_an_unconfigured_optional_service_is_not_an_error() -> None:
    """Section 35A says this in as many words, and it is the module's whole shape."""
    results = checks.run(_controls(), _store())
    by_name = {check.name: check for check in results}
    assert by_name["OpenAI"].state == checks.NOT_CONFIGURED
    assert by_name["OpenAI"].ok is True
    assert "○" in by_name["OpenAI"].line()
    assert checks.blocking(results) == () or all(
        check.name not in ("OpenAI", "Anthropic") for check in checks.blocking(results)
    )


def test_every_check_the_work_order_lists_is_present() -> None:
    names = {check.name for check in checks.run(_controls(), _store())}
    for expected in (
        "Python environment", "PySide6", "MLX", "MLX-LM", "Local model",
        "Project folder", "Project sandbox", "macOS Keychain", "Version history",
        "GitHub backup", "OpenAI", "Anthropic",
    ):
        assert expected in names, f"section 35A step 7 lists {expected}"


def test_a_saved_key_with_cloud_off_is_reported_as_two_different_facts() -> None:
    """The switch and the key have different remedies, so they read differently."""
    store = _store({(keychain.SERVICE, "openai"): "sk-test-000"})
    off = {check.name: check for check in checks.run(_controls(allow_cloud_ai=False), store)}
    on = {check.name: check for check in checks.run(_controls(allow_cloud_ai=True), store)}
    assert off["OpenAI"].state == checks.NOT_CONFIGURED
    assert "cloud AI is off" in off["OpenAI"].detail
    assert on["OpenAI"].state == checks.OK


def test_a_failed_check_blocks_and_an_unconfigured_one_does_not() -> None:
    failed = checks.Check("Thing", checks.FAILED, "broken")
    absent = checks.Check("Other", checks.NOT_CONFIGURED)
    assert failed.ok is False
    assert absent.ok is True
    assert checks.blocking([failed, absent]) == (failed,)


def test_the_summary_counts_only_real_problems() -> None:
    assert "working" in checks.summary(
        [checks.Check("A", checks.OK), checks.Check("B", checks.NOT_CONFIGURED)]
    )
    assert "One thing" in checks.summary(
        [checks.Check("A", checks.FAILED), checks.Check("B", checks.NOT_CONFIGURED)]
    )


def test_a_line_shows_not_configured_even_with_no_detail() -> None:
    assert checks.Check("GitHub backup", checks.NOT_CONFIGURED).line().endswith("Not configured")


# --------------------------------------------------------------------- repair

def test_repair_reinstalls_dependencies_when_an_import_is_broken() -> None:
    plan = checks.plan_repair([
        checks.Check("PySide6", checks.FAILED, "could not be loaded"),
        checks.Check("MLX", checks.OK),
    ])
    assert plan.reinstall_dependencies is True
    assert plan.anything_to_do is True


def test_repair_redownloads_only_a_model_that_is_missing() -> None:
    plan = checks.plan_repair(
        [checks.Check("Local model", checks.NOT_CONFIGURED)],
        preferred_model="qwen3-4b-instruct",
    )
    assert plan.missing_models == ("qwen3-4b-instruct",)


def test_repair_reports_what_it_cannot_fix_instead_of_attempting_it() -> None:
    """A missing Git is a job for the parent. Section 35A's repair list is not magic."""
    plan = checks.plan_repair([
        checks.Check("Version history", checks.FAILED, "Git is not installed"),
    ])
    assert plan.reinstall_dependencies is False
    assert plan.notes == ("Git is not installed",)


def test_a_healthy_installation_needs_no_repair() -> None:
    plan = checks.plan_repair([
        checks.Check("PySide6", checks.OK),
        checks.Check("Local model", checks.OK),
    ])
    assert plan.anything_to_do is False


# --------------------------------------------------------------------- arduino toolchain

def test_the_toolchain_is_pinned_to_a_release_never_latest() -> None:
    """The same rule models.json follows for model weights."""
    from opennest.setup import toolchain

    assert toolchain.VERSION == "1.5.1"
    assert "latest" not in toolchain._BASE
    assert toolchain.VERSION in toolchain._BASE


def test_the_toolchain_asset_matches_this_kind_of_mac() -> None:
    from opennest.setup import toolchain

    assert toolchain.archive_name("arm64") == "arduino-cli_1.5.1_macOS_ARM64.tar.gz"
    assert toolchain.archive_name("x86_64") == "arduino-cli_1.5.1_macOS_64bit.tar.gz"
    assert toolchain.archive_name("riscv") is None


def test_a_mac_with_no_published_build_is_told_so(monkeypatch) -> None:
    from opennest.setup import toolchain

    monkeypatch.setattr(toolchain, "archive_name", lambda machine=None: None)
    result = toolchain.install(tools_dir=_scratch())
    assert result.ok is False
    assert "does not publish" in result.message


def test_a_checksum_mismatch_refuses_to_install(monkeypatch, tmp_path) -> None:
    """Refuse, never warn. The artifact came from outside, so it is checked."""
    from opennest.setup import toolchain

    monkeypatch.setattr(toolchain, "_published_checksum", lambda asset: "0" * 64)
    monkeypatch.setattr(toolchain, "_fetch", lambda url: b"not the real tarball")
    installed: list = []
    monkeypatch.setattr(toolchain, "_install_core",
                        lambda *a, **k: installed.append(True))

    result = toolchain.install(tools_dir=tmp_path)
    assert result.ok is False
    assert "checksum" in result.message
    assert not installed, "nothing should be installed after a mismatch"


def test_an_unreachable_download_says_it_needs_the_internet(monkeypatch, tmp_path) -> None:
    import urllib.error

    from opennest.setup import toolchain

    def offline(url):
        raise urllib.error.URLError("no route to host")

    monkeypatch.setattr(toolchain, "_fetch", offline)
    result = toolchain.install(tools_dir=tmp_path)
    assert result.ok is False
    assert "internet" in result.message


def test_the_extractor_refuses_a_member_that_escapes_its_directory(tmp_path) -> None:
    """Belt and braces behind the checksum, and four lines well spent."""
    import io
    import tarfile

    import pytest

    from opennest.setup import toolchain

    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        payload = b"x"
        info = tarfile.TarInfo("../escaped.txt")
        info.size = len(payload)
        archive.addfile(info, io.BytesIO(payload))

    target = tmp_path / "tools"
    target.mkdir()
    with tarfile.open(fileobj=io.BytesIO(buffer.getvalue()), mode="r:gz") as archive, \
            pytest.raises(tarfile.TarError, match="outside"):
        toolchain._safe_extract(archive, target)
    assert not (tmp_path / "escaped.txt").exists()


def _scratch():
    import tempfile
    from pathlib import Path

    return Path(tempfile.mkdtemp())
