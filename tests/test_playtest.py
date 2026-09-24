"""The headless playtest: what it decides, and what a real run of the harness shows.

Two layers. :func:`playtest.classify` is pure, so every rule is pinned here without
starting a game. Then the harness itself, run for real under the process sandbox against
small games written in the idioms a first game uses -- including the seven working games
Phase 12.3's grader called frozen (SPIKES.md section 24). Those skip, rather than fail,
where the sandbox cannot be applied, like every other test that runs a project.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from opennest.agent.tools import Toolbox
from opennest.execution import playtest
from opennest.execution.python_runner import RunResult
from opennest.projects.manager import create_project
from opennest.security.process_sandbox import sandbox_available

needs_sandbox = pytest.mark.skipif(
    not sandbox_available(), reason="the process sandbox cannot be applied here"
)


# ------------------------------------------------------------------ classify, pure

def _ran(exit_code=0, stderr="", timed_out=False, seconds=1.0) -> RunResult:
    return RunResult(exit_code, "", stderr, seconds, timed_out)


def _frames(hashes, inputs=None):
    inputs = inputs or ["idle"] * len(hashes)
    return [{"frame": i, "hash": h, "input": a} for i, (h, a) in enumerate(zip(hashes, inputs))]


WINDOW = [{"window": [640, 480]}]


def _end(reason, during="done"):
    return [{"end": reason, "during": during}]


def test_a_game_that_changes_passes() -> None:
    records = WINDOW + _frames(["a", "a", "a", "b", "c"]) + _end("done")
    assert playtest.classify(records, _ran()).verdict == playtest.PASSED


def test_every_frame_the_same_is_frozen() -> None:
    records = WINDOW + _frames(["a"] * 100) + _end("done")
    result = playtest.classify(records, _ran())
    assert result.verdict == playtest.FROZEN and result.failed


def test_a_flip_before_the_loop_is_not_evidence_of_movement() -> None:
    """A title flipped once after ``set_mode`` would otherwise make any game "move"."""
    records = WINDOW + _frames(["splash"] + ["a"] * 99) + _end("done")
    assert playtest.classify(records, _ran()).verdict == playtest.FROZEN


def test_a_game_that_only_redraws_on_input_passes() -> None:
    """Measured as a false failure before the fix: three frames, all different."""
    records = WINDOW + _frames(["a", "b", "c"], ["idle", "right", "hold"]) + _end("done")
    result = playtest.classify(records, _ran())
    assert result.verdict == playtest.PASSED
    assert result.responded_to == ("right", "hold")


def test_moving_by_itself_and_responding_are_diagnostics_not_verdicts() -> None:
    """The starter only moves when a key is held, and that is a pass."""
    still_until_pressed = _frames(["a"] * 20 + ["b", "c"], ["idle"] * 20 + ["right"] * 2)
    result = playtest.classify(WINDOW + still_until_pressed + _end("done"), _ran())
    assert result.verdict == playtest.PASSED
    assert not result.moved_by_itself and result.responded_to == ("right",)


def test_a_traceback_is_a_crash_whenever_it_happens() -> None:
    stderr = (
        "Traceback (most recent call last):\n"
        '  File "/app/opennest/execution/playtest_harness.py", line 300, in <module>\n'
        '    runpy.run_path(ENTRY, run_name="__main__")\n'
        '  File "<frozen runpy>", line 287, in run_path\n'
        '  File "<frozen runpy>", line 98, in _run_module_code\n'
        '  File "src/game.py", line 13, in <module>\n'
        "    bullets.append(p.center)\n"
        "    ^^^^^^^\n"
        "NameError: name 'bullets' is not defined\n"
    )
    records = WINDOW + _frames(["a", "b"] * 20) + _end("error", "space")
    result = playtest.classify(records, _ran(exit_code=1, stderr=stderr), entry="src/game.py")
    assert result.verdict == playtest.CRASHED and result.during == "space"
    assert result.error == (
        "Traceback (most recent call last):\n"
        '  File "src/game.py", line 13, in <module>\n'
        "    bullets.append(p.center)\n"
        "    ^^^^^^^\n"
        "NameError: name 'bullets' is not defined"
    )


def test_a_traceback_the_game_printed_and_survived_is_not_a_crash() -> None:
    stderr = "Traceback (most recent call last):\nValueError: handled\n"
    records = WINDOW + _frames(["a", "b", "c", "d"]) + _end("done")
    assert playtest.classify(records, _ran(stderr=stderr)).verdict == playtest.PASSED


def test_being_killed_by_a_signal_is_a_crash() -> None:
    records = WINDOW + _frames(["a", "b"])
    assert playtest.classify(records, _ran(exit_code=-11)).verdict == playtest.CRASHED


def test_a_window_that_never_draws_is_no_picture() -> None:
    records = WINDOW + _end("no_frames", "idle")
    assert playtest.classify(records, _ran()).verdict == playtest.NO_PICTURE


@pytest.mark.parametrize("frames", [0, 1, 2])
def test_ending_before_it_has_really_started_is_closing_itself(frames) -> None:
    records = WINDOW + _frames(["a", "b"][:frames]) + _end("returned", "idle")
    assert playtest.classify(records, _ran()).verdict == playtest.CLOSED_ITSELF


def test_ending_itself_after_playing_for_a_while_is_not_a_failure() -> None:
    """A rock hits a player nobody moved and the game quits: that game works."""
    records = WINDOW + _frames([str(i) for i in range(31)]) + _end("exit", "up")
    assert playtest.classify(records, _ran()).verdict == playtest.PASSED


def test_still_and_then_quitting_on_a_key_is_inconclusive_not_frozen() -> None:
    records = WINDOW + _frames(["a"] * 40, ["idle"] * 15 + ["right"] * 25) + _end("exit", "q")
    result = playtest.classify(records, _ran())
    assert result.verdict == playtest.INCONCLUSIVE and not result.failed


def test_a_program_with_no_window_gets_no_verdict() -> None:
    result = playtest.classify(_end("returned", "idle"), _ran())
    assert result.verdict == playtest.NO_WINDOW and not result.failed


def test_a_test_that_could_not_start_is_no_verdict() -> None:
    """The sandbox refused, or pygame is missing. The run itself says so loudly."""
    refused = RunResult(None, "", "could not start the safety sandbox", 0.0, False)
    assert playtest.classify([], refused).verdict == playtest.UNAVAILABLE
    no_pygame = [{"end": "no_pygame", "during": ""}]
    assert playtest.classify(no_pygame, _ran()).verdict == playtest.UNAVAILABLE


def test_a_harness_that_never_reached_the_game_is_not_a_crash() -> None:
    """With no record at all the traceback is the harness's own, and a repair aimed at
    the child's code could not fix it."""
    stderr = "Traceback (most recent call last):\nKeyError: 'OPENNEST_PLAYTEST_RECORD'\n"
    result = playtest.classify([], _ran(exit_code=1, stderr=stderr))
    assert result.verdict == playtest.UNAVAILABLE and not result.failed


def test_a_test_that_cannot_be_set_up_never_breaks_the_turn(tmp_path) -> None:
    result = playtest.run(tmp_path / "gone", ("python", "src/game.py"))
    assert result.verdict == playtest.UNAVAILABLE


def test_only_games_asks_for_a_playtest_and_only_one_the_toolbox_knows() -> None:
    from opennest.projects.profiles import load_profiles
    declared = {profile.id: profile.playtest for profile in load_profiles() if profile.playtest}
    assert declared == {"games": "pygame"}


def test_only_the_four_failures_fail() -> None:
    failing = {playtest.CRASHED, playtest.NO_PICTURE, playtest.CLOSED_ITSELF, playtest.FROZEN}
    assert failing == playtest.FAILURES
    for verdict in (playtest.PASSED, playtest.NO_WINDOW, playtest.INCONCLUSIVE,
                    playtest.UNAVAILABLE):
        assert not playtest.Playtest(verdict).failed
        assert playtest.Playtest(verdict).feedback() == ""
        assert playtest.Playtest(verdict).reminder() == ""


@pytest.mark.parametrize("verdict", sorted(playtest.FAILURES))
def test_feedback_says_what_was_tried_and_that_it_will_be_tested_again(verdict) -> None:
    text = playtest.Playtest(verdict, entry="src/game.py", frames=12, during="space",
                             error="NameError: x").feedback()
    assert "Open Nest tested src/game.py without opening a window" in text
    assert playtest.INPUTS_TRIED in text
    assert "Open Nest will test it again" in text
    reminder = playtest.Playtest(verdict).reminder()
    assert reminder.startswith("You did not change any file, so nothing is fixed yet")


def test_crash_feedback_carries_the_error_and_when_it_happened() -> None:
    text = playtest.Playtest(playtest.CRASHED, entry="src/game.py", frames=38,
                             during="space", error="NameError: name 'bullets'").feedback()
    assert "after 38 frames, while it was pressing space" in text
    assert "NameError: name 'bullets'" in text
    first = playtest.Playtest(playtest.CRASHED, frames=0, error="E").feedback()
    assert "before it drew anything" in first


# --------------------------------------------------------------- the harness, for real

STARTER_HEAD = """import pygame, random, sys
pygame.init()
screen = pygame.display.set_mode((640, 480))
clock = pygame.time.Clock()
"""

#: The seven working games Phase 12.3's grader scored as frozen. Each is the smallest
#: honest version of an idiom a first game uses, and each works for a child at a real
#: window.
SPIKE_FALSE_FAILURES = {
    "moves on KEYDOWN, not get_pressed": """
x = 5
while True:
    for event in pygame.event.get():
        if event.type == pygame.KEYDOWN and event.key == pygame.K_RIGHT:
            x += 1
    screen.fill((0, 0, 0))
    pygame.draw.rect(screen, (255, 255, 0), (x * 32, 160, 32, 32))
    pygame.display.flip()
    clock.tick(60)
""",
    "spawns on its own set_timer event": """
SPAWN = pygame.USEREVENT + 1
pygame.time.set_timer(SPAWN, 300)
blocks = []
while True:
    for event in pygame.event.get():
        if event.type == SPAWN:
            blocks.append(random.randint(0, 600))
    screen.fill((0, 0, 0))
    for bx in blocks:
        pygame.draw.rect(screen, (0, 255, 0), (bx, 100, 30, 30))
    pygame.display.flip()
    clock.tick(60)
""",
    "answers a quiz with a number key": """
font = pygame.font.Font(None, 40)
answer = ""
while True:
    for event in pygame.event.get():
        if event.type == pygame.KEYDOWN and event.unicode in "123":
            answer = event.unicode
    screen.fill((20, 20, 60))
    screen.blit(font.render("2 + 2?  1) 3  2) 4  3) 5 " + answer, True, (255, 255, 255)),
                (40, 200))
    pygame.display.flip()
    clock.tick(30)
""",
    "starts on SPACE from a title screen": """
started, y = False, 0
while True:
    for event in pygame.event.get():
        if event.type == pygame.KEYDOWN and event.key == pygame.K_SPACE:
            started = True
    screen.fill((0, 0, 0))
    if started:
        y = (y + 6) % 480
        pygame.draw.circle(screen, (0, 200, 255), (320, y), 15)
    pygame.display.flip()
    clock.tick(60)
""",
    "moves with W A S D": """
p = pygame.Rect(300, 220, 30, 30)
while True:
    pygame.event.get()
    keys = pygame.key.get_pressed()
    if keys[pygame.K_d]:
        p.x += 4
    if keys[pygame.K_s]:
        p.y += 4
    screen.fill((0, 0, 0))
    pygame.draw.rect(screen, (255, 128, 0), p)
    pygame.display.flip()
    clock.tick(60)
""",
    "puts a dot where you click": """
dots = []
while True:
    for event in pygame.event.get():
        if event.type == pygame.MOUSEBUTTONDOWN:
            dots.append(event.pos)
    screen.fill((10, 10, 40))
    for dot in dots:
        pygame.draw.circle(screen, (255, 80, 80), dot, 12)
    pygame.display.flip()
    clock.tick(60)
""",
    "follows the mouse": """
while True:
    pygame.event.get()
    mx, _ = pygame.mouse.get_pos()
    screen.fill((0, 0, 0))
    pygame.draw.rect(screen, (200, 200, 200), (mx - 40, 440, 80, 12))
    pygame.display.flip()
    clock.tick(60)
""",
}


def _game(tmp_path, body: str, *, head: str = STARTER_HEAD, name: str = "Test Game"):
    project = create_project(name, "games", root=tmp_path)
    project.entrypoint_path.write_text(head + body, encoding="utf-8")
    return project


@needs_sandbox
def test_the_untouched_starter_passes_and_leaves_nothing_behind(tmp_path) -> None:
    project = create_project("Starter", "games", root=tmp_path)
    before = sorted(p.relative_to(project.directory) for p in project.directory.rglob("*"))

    result = Toolbox(project).playtest()

    assert result is not None and result.verdict == playtest.PASSED, result
    assert not result.moved_by_itself
    assert {"right", "left", "up", "down"} <= set(result.responded_to)
    after = sorted(p.relative_to(project.directory) for p in project.directory.rglob("*"))
    added = set(after) - set(before)
    # The record's directory may now exist; the record itself never survives the run.
    assert not [p for p in added if p.name == "playtest.jsonl"], added
    assert all(str(p).startswith(".opennest") for p in added), added


@needs_sandbox
def test_the_games_the_spike_called_frozen_all_pass(tmp_path) -> None:
    """Phase 12.3's grader failed seven of these ten idioms. None may fail here.

    Run side by side, because each one is a real two-second run and the point is the
    whole set.
    """
    projects = {
        label: _game(tmp_path / f"g{index}", body, name=f"Game {index}")
        for index, (label, body) in enumerate(SPIKE_FALSE_FAILURES.items())
    }
    with ThreadPoolExecutor(max_workers=len(projects)) as pool:
        results = dict(zip(projects, pool.map(lambda p: Toolbox(p).playtest(),
                                              projects.values())))
    wrong = {label: r.verdict for label, r in results.items() if r.verdict != playtest.PASSED}
    assert not wrong, wrong


@needs_sandbox
def test_a_game_where_nothing_ever_changes_is_frozen(tmp_path) -> None:
    project = _game(tmp_path, """
while True:
    pygame.event.get()
    screen.fill((0, 0, 0))
    pygame.draw.rect(screen, (255, 128, 0), (300, 220, 40, 40))
    pygame.display.flip()
    clock.tick(60)
""")
    result = Toolbox(project).playtest()
    assert result.verdict == playtest.FROZEN and result.frames > 50


@needs_sandbox
def test_a_crash_on_a_key_names_the_real_line_and_the_key(tmp_path) -> None:
    """The spike never pressed space, and dropped any traceback after the first frame."""
    project = _game(tmp_path, """
while True:
    for event in pygame.event.get():
        if event.type == pygame.KEYDOWN and event.key == pygame.K_SPACE:
            bullets.append(1)
    screen.fill((0, 0, 0))
    pygame.display.flip()
    clock.tick(60)
""")
    result = Toolbox(project).playtest()
    assert result.verdict == playtest.CRASHED
    assert result.during == "space"
    assert 'File "src/game.py", line 9, in <module>' in result.error
    assert result.error.endswith("NameError: name 'bullets' is not defined")
    assert "playtest_harness" not in result.error and "runpy" not in result.error


@needs_sandbox
def test_a_game_that_only_redraws_on_input_passes_for_real(tmp_path) -> None:
    project = _game(tmp_path, """
x = 5
def draw():
    screen.fill((0, 0, 0))
    pygame.draw.rect(screen, (0, 255, 255), (x * 20, 200, 20, 20))
    pygame.display.flip()
draw()
while True:
    event = pygame.event.wait()
    if event.type == pygame.KEYDOWN and event.key == pygame.K_RIGHT:
        x += 1
        draw()
""")
    assert Toolbox(project).playtest().verdict == playtest.PASSED


@needs_sandbox
def test_a_game_that_swallows_the_stop_is_not_mistaken_for_a_crash(tmp_path) -> None:
    """A bare ``except:`` round the loop catches the harness's stop as well."""
    project = _game(tmp_path, """
x = 0
while True:
    try:
        pygame.event.get()
        x = (x + 3) % 640
        screen.fill((0, 0, 0))
        pygame.draw.rect(screen, (255, 255, 255), (x, 200, 20, 20))
        pygame.display.flip()
        clock.tick(60)
    except:
        pass
""")
    result = Toolbox(project).playtest()
    assert result.verdict == playtest.PASSED, result
    assert result.seconds < 5, "it waited for the wall clock instead of stopping"


@needs_sandbox
def test_a_game_that_ends_straight_away_closed_itself(tmp_path) -> None:
    project = _game(tmp_path, """
running = False
while running:
    pygame.display.flip()
pygame.quit()
""")
    assert Toolbox(project).playtest().verdict == playtest.CLOSED_ITSELF


@needs_sandbox
def test_a_game_that_never_draws_is_stopped_by_the_watchdog(tmp_path) -> None:
    project = _game(tmp_path, """
while True:
    pygame.event.get()
    screen.fill((0, 0, 0))
    clock.tick(60)
""")
    result = Toolbox(project).playtest()
    assert result.verdict == playtest.NO_PICTURE
    assert result.seconds < playtest.TIMEOUT_SECONDS


@needs_sandbox
def test_a_program_with_no_window_is_not_judged(tmp_path) -> None:
    project = _game(tmp_path, "print('hello')\n", head="")
    assert Toolbox(project).playtest().verdict == playtest.NO_WINDOW


def test_only_a_profile_that_asks_for_it_is_tested(tmp_path) -> None:
    research = create_project("Data", "research", root=tmp_path)
    assert Toolbox(research).playtest() is None


def test_nothing_to_run_yet_is_not_tested(tmp_path) -> None:
    project = create_project("Empty", "games", root=tmp_path)
    project.entrypoint_path.unlink()
    assert Toolbox(project).playtest() is None


def test_the_playtest_is_not_a_tool_the_model_can_reach(tmp_path) -> None:
    """The four-tool rule (SPIKES.md section 4), and a check the model could skip is not one."""
    toolbox = Toolbox(create_project("Game", "games", root=tmp_path))
    assert "playtest" not in toolbox.allowed
    assert toolbox.dispatch("playtest", {}).reason == "not_available"
