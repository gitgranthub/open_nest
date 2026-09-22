"""GitHub backup -- WORKORDER_01 section 29A, DoD 46-50.

Two stand-ins keep this hermetic, and they are different in kind:

- :class:`FakeTransport` replaces the GitHub API the way ``ScriptedProvider`` replaces
  the model. Nothing here opens a socket.
- A **real bare repository** in a temporary directory replaces github.com for the git
  half. Pushing to it exercises real ``git push``, real branches and a real fast-forward
  merge, which a mock could not -- the whole point of section 29A's Git layer is what
  git actually does.

What is deliberately *not* tested here: the device flow against the real service, and a
real private repository. Those are measurements, and they live in SPIKES.md section 17.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from opennest.github import api, auth, backup
from opennest.github.push_queue import PushQueue, QueuedPush
from opennest.github.transport import GitHubError, OfflineError, Response
from opennest.projects.manager import create_project
from opennest.security import keychain, permissions
from opennest.versioning import git_manager
from opennest.versioning.checkpoint import VersionHistory
from tests.conftest import FakeKeyring

TOKEN = "gho_TestOnlyNotARealToken0123456789"


class FakeTransport:
    """Answers GitHub API calls from a script. Records everything it was asked."""

    def __init__(self, answers: dict | None = None) -> None:
        #: (method, url-suffix) -> Response, matched by suffix so tests stay readable.
        self.answers = dict(answers or {})
        self.requests: list[tuple[str, str, dict, dict]] = []

    def request(self, method, url, *, headers=None, body=None) -> Response:
        self.requests.append((method, url, dict(headers or {}), dict(body or {})))
        for (want_method, suffix), response in self.answers.items():
            if method == want_method and url.endswith(suffix):
                return response
        return Response(404, {"message": "Not Found"})

    def sent_bodies(self) -> list[dict]:
        return [body for _, _, _, body in self.requests]

    def authorisation_headers(self) -> list[str]:
        return [headers.get("Authorization", "") for _, _, headers, _ in self.requests]


@pytest.fixture
def github_credentials():
    store = keychain.Credentials(backend=FakeKeyring())
    store.save_github_token(TOKEN)
    return store


@pytest.fixture
def client_id(monkeypatch):
    """A build that has an OAuth App. Most tests need one to get past ``configured()``."""
    monkeypatch.setattr(auth, "CLIENT_ID", "Iv1.test0client0id")


@pytest.fixture
def remote(tmp_path: Path) -> Path:
    """A real bare repository standing in for the private repo on GitHub."""
    bare = tmp_path / "remote.git"
    subprocess.run(
        ["git", "init", "--bare", "--initial-branch=main", str(bare)],
        capture_output=True, check=True,
    )
    return bare


@pytest.fixture
def backed_up_project(tmp_path: Path, remote: Path):
    """A project that is a repo, has one commit, and points at the bare remote."""
    project = create_project("Asteroid Game", "games", root=tmp_path / "projects")
    history = VersionHistory(project)
    history.start()
    git_manager.set_remote(project.directory, str(remote))
    return project


# --------------------------------------------------------------- naming (section 29A)

def test_a_repository_name_is_legal_and_recognisable():
    assert api.repository_name("Asteroid Game") == "OpenNest-Asteroid-Game"
    assert api.repository_name("My Game!!! 🚀") == "OpenNest-My-Game"
    assert api.repository_name("") == "OpenNest-Project"
    assert len(api.repository_name("x" * 400)) <= api.MAX_NAME


def test_a_repository_name_never_ends_in_punctuation_github_rejects():
    for awful in ("Game...", "Game---", "Game.", "Game-"):
        name = api.repository_name(awful)
        assert not name.endswith((".", "-", "_")), name


# --------------------------------------------------------------- private (section 29A)

def test_a_created_repository_is_always_private(github_credentials):
    transport = FakeTransport({
        ("POST", "/user/repos"): Response(201, {
            "full_name": "parent/OpenNest-Asteroid-Game",
            "clone_url": "https://github.com/parent/OpenNest-Asteroid-Game.git",
            "private": True,
        }),
    })
    repository = api.create_repository(TOKEN, "Asteroid Game", transport)

    assert repository.private
    assert transport.sent_bodies()[0]["private"] is True


def test_nothing_can_ask_for_a_public_repository():
    """Section 29A: "Do not automatically make repositories public."

    ``private`` is a constant in the request body, not a parameter, so there is no
    argument a caller could pass to change it. This checks the signature rather than the
    behaviour, because the behaviour has no way to vary.
    """
    import inspect

    parameters = inspect.signature(api.create_repository).parameters
    assert "private" not in parameters
    assert "public" not in parameters
    assert "visibility" not in parameters


def test_an_existing_repository_is_adopted_rather_than_failing(github_credentials):
    """A parent who runs setup twice should get a working backup, not an error."""
    transport = FakeTransport({
        ("POST", "/user/repos"): Response(422, {
            "errors": [{"message": "name already exists on this account"}],
        }),
        ("GET", "/user"): Response(200, {"login": "parent"}),
        ("GET", "/repos/parent/OpenNest-Asteroid-Game"): Response(200, {
            "full_name": "parent/OpenNest-Asteroid-Game",
            "clone_url": "https://github.com/parent/OpenNest-Asteroid-Game.git",
            "private": True,
        }),
    })
    repository = api.create_repository(TOKEN, "Asteroid Game", transport)
    assert repository.full_name == "parent/OpenNest-Asteroid-Game"


# --------------------------------------------------------------- the token (section 22)

def test_the_token_lives_only_in_the_keychain(github_credentials, tmp_path):
    """Section 22's list, checked against every file Open Nest writes."""
    controls = permissions.ParentControls(path=tmp_path / "settings.json")
    controls.github_pr_policy = backup.POLICY_PULL_REQUEST
    controls.save()

    from opennest.setup import state as state_module

    installation = state_module.InstallationState(
        setup_complete=True, github_enabled=True, github_account="parent"
    )
    installation.save(tmp_path / "installation.json")

    queue = PushQueue(path=tmp_path / "push_queue.json")
    queue.enqueue(tmp_path / "project", "main", "parent/OpenNest-Thing")
    queue.save()

    for name in ("settings.json", "installation.json", "push_queue.json"):
        assert TOKEN not in (tmp_path / name).read_text(encoding="utf-8")


def test_a_remote_url_carrying_a_credential_is_refused(backed_up_project):
    with pytest.raises(git_manager.GitError):
        git_manager.set_remote(
            backed_up_project.directory,
            f"https://x-access-token:{TOKEN}@github.com/parent/thing.git",
        )


def test_a_real_push_leaves_no_token_in_the_repository(backed_up_project, remote):
    """The measured rule from SPIKES.md section 17, enforced as a test.

    The bare remote needs no authentication, so ``GIT_ASKPASS`` is never consulted here
    -- what this pins is that nothing on the push path *writes* the token down.
    """
    git_manager.push(backed_up_project.directory, TOKEN, branch="main")

    git_dir = backed_up_project.directory / ".git"
    for path in git_dir.rglob("*"):
        if path.is_file():
            assert TOKEN.encode() not in path.read_bytes(), path


def test_the_queue_refuses_to_save_anything_credential_shaped(tmp_path):
    queue = PushQueue(path=tmp_path / "push_queue.json")
    queue.entries.append(
        QueuedPush(project_dir="/p", branch="main", last_error=f"token={TOKEN!r}")
    )
    with pytest.raises(ValueError):
        queue.save()


# --------------------------------------------------------------- secret scanning

def test_a_secret_committed_and_then_deleted_still_blocks_the_push(backed_up_project):
    """The reason a push scan is not the same as a commit scan.

    ``commit()`` scans the working tree, so a credential that was committed and then
    removed is invisible to it -- the file is gone. The blob is not, and a push sends
    the blob.
    """
    project_dir = backed_up_project.directory
    leaky = project_dir / "src" / "config.py"
    leaky.write_text('OPENAI_KEY = "sk-' + "a" * 40 + '"\n', encoding="utf-8")

    # Committed the way something bypassing the scan would do it.
    subprocess.run(["git", "-C", str(project_dir), "add", "-A"], capture_output=True)
    subprocess.run(
        ["git", "-C", str(project_dir), "commit", "-m", "Open Nest: oops"],
        capture_output=True,
    )
    leaky.unlink()
    git_manager.commit(project_dir, "Removed it again")

    # The working tree is clean now, so a commit-time scan finds nothing.
    assert not git_manager.scan_paths(project_dir, git_manager.changed_files(project_dir))

    with pytest.raises(git_manager.SecretsFound):
        git_manager.push(project_dir, TOKEN, branch="main")


def test_a_blocked_push_never_quotes_the_credential(backed_up_project):
    project_dir = backed_up_project.directory
    secret = "sk-" + "z" * 40
    (project_dir / "src" / "keys.py").write_text(
        f'KEY = "{secret}"\n', encoding="utf-8"
    )
    subprocess.run(["git", "-C", str(project_dir), "add", "-A"], capture_output=True)
    subprocess.run(
        ["git", "-C", str(project_dir), "commit", "-m", "Open Nest: keys"],
        capture_output=True,
    )

    with pytest.raises(git_manager.SecretsFound) as caught:
        git_manager.push(project_dir, TOKEN, branch="main")
    assert secret not in str(caught.value)
    assert "keys.py" in str(caught.value)


# --------------------------------------------------------------- the queue (DoD 48-50)

def test_being_offline_queues_the_push_and_never_raises(tmp_path):
    queue = PushQueue(path=tmp_path / "queue.json", clock=lambda: 1000.0)
    project = tmp_path / "Asteroid Game"
    project.mkdir()
    queue.enqueue(project, "main")

    def refuse(*args, **kwargs):
        raise git_manager.Offline("no internet")

    outcome = queue.drain(TOKEN, pusher=refuse)

    assert outcome.pushed == ()
    assert outcome.waiting == ("Asteroid Game",)
    assert outcome.problems == ()
    assert len(queue) == 1, "an offline push must stay queued"


def test_a_queued_push_resumes_when_connectivity_returns(tmp_path):
    """DoD 50, as close as a hermetic test gets to it."""
    now = [1000.0]
    queue = PushQueue(path=tmp_path / "queue.json", clock=lambda: now[0])
    project = tmp_path / "Asteroid Game"
    project.mkdir()
    queue.enqueue(project, "main")

    def refuse(*args, **kwargs):
        raise git_manager.Offline("no internet")

    queue.drain(TOKEN, pusher=refuse)
    assert len(queue) == 1

    # Still inside the backoff: nothing is attempted.
    attempts: list = []
    queue.drain(TOKEN, pusher=lambda *a, **k: attempts.append(1))
    assert attempts == [], "the backoff must actually hold an attempt back"

    now[0] += 3600  # the internet comes back, and the backoff has expired
    outcome = queue.drain(TOKEN, pusher=lambda *a, **k: None)
    assert outcome.pushed == ("Asteroid Game",)
    assert len(queue) == 0


def test_one_entry_per_branch_no_matter_how_many_checkpoints(tmp_path):
    queue = PushQueue(path=tmp_path / "queue.json", clock=lambda: 1000.0)
    project = tmp_path / "Asteroid Game"
    project.mkdir()
    for _ in range(40):
        queue.enqueue(project, "main")
    assert len(queue) == 1, "a push sends the branch, so forty are one"


def test_new_work_resets_a_backoff_earned_while_offline(tmp_path):
    now = [1000.0]
    queue = PushQueue(path=tmp_path / "queue.json", clock=lambda: now[0])
    project = tmp_path / "Asteroid Game"
    project.mkdir()
    queue.enqueue(project, "main")

    def refuse(*args, **kwargs):
        raise git_manager.Offline("no internet")

    for _ in range(4):
        queue.drain(TOKEN, pusher=refuse)
        now[0] += 3600
    assert queue.pending()[0].attempts == 4

    queue.enqueue(project, "main")
    entry = queue.pending()[0]
    assert entry.attempts == 0
    assert entry.ready(now[0]), "a child working now should not wait out an old backoff"


def test_a_blocked_credential_leaves_the_queue_and_is_reported(tmp_path):
    """Section 29A: block the push, notify the parent. Retrying forever would not."""
    queue = PushQueue(path=tmp_path / "queue.json", clock=lambda: 1000.0)
    project = tmp_path / "Asteroid Game"
    project.mkdir()
    queue.enqueue(project, "main")

    findings = [git_manager.Finding("src/keys.py", 1, "an OpenAI API key")]

    def blocked(*args, **kwargs):
        raise git_manager.SecretsFound(findings)

    outcome = queue.drain(TOKEN, pusher=blocked)
    assert outcome.pushed == ()
    assert len(outcome.problems) == 1
    assert "keys.py" in outcome.problems[0][1]
    assert len(queue) == 0


def test_a_deleted_project_is_dropped_rather_than_retried_forever(tmp_path):
    queue = PushQueue(path=tmp_path / "queue.json", clock=lambda: 1000.0)
    queue.enqueue(tmp_path / "gone", "main")
    outcome = queue.drain(TOKEN, pusher=lambda *a, **k: pytest.fail("should not push"))
    assert outcome.quiet
    assert len(queue) == 0


def test_the_queue_survives_a_quit(tmp_path):
    path = tmp_path / "queue.json"
    project = tmp_path / "Asteroid Game"
    project.mkdir()
    first = PushQueue(path=path, clock=lambda: 1000.0)
    first.enqueue(project, "main", "parent/OpenNest-Asteroid-Game")
    first.save()

    second = PushQueue.load(path, clock=lambda: 1000.0)
    assert len(second) == 1
    assert second.pending()[0].repository == "parent/OpenNest-Asteroid-Game"


def test_a_damaged_queue_file_costs_a_delay_and_never_a_project(tmp_path):
    path = tmp_path / "queue.json"
    path.write_text("{not json", encoding="utf-8")
    assert len(PushQueue.load(path)) == 0


def test_a_stale_entry_is_eventually_given_up_on(tmp_path):
    path = tmp_path / "queue.json"
    payload = {"pushes": [{"project_dir": "/p", "branch": "main", "queued_at": 1.0}]}
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert len(PushQueue.load(path, clock=lambda: 1.0 + 15 * 24 * 3600)) == 0


# --------------------------------------------------------------- PR policy (DoD 47)

def test_the_default_policy_creates_no_branch(backed_up_project):
    controls = permissions.ParentControls()
    assert controls.github_pr_policy == backup.POLICY_NORMAL
    assert backup.begin_change(backed_up_project.directory, controls) == ""


def test_a_review_branch_is_created_before_the_change(backed_up_project):
    controls = permissions.ParentControls(github_pr_policy=backup.POLICY_BRANCH)
    branch = backup.begin_change(backed_up_project.directory, controls)
    assert branch == "opennest/change-1"
    assert git_manager.current_branch(backed_up_project.directory) == branch


def test_a_small_change_becomes_an_ordinary_local_commit(
    backed_up_project, github_credentials
):
    """Section 29A: "Small successful modifications can remain ordinary local commits.""" ""
    project = backed_up_project
    controls = permissions.ParentControls(github_pr_policy=backup.POLICY_BRANCH)
    branch = backup.begin_change(project.directory, controls)

    (project.directory / "src" / "main.py").write_text(
        "print('one small change')\n", encoding="utf-8"
    )
    git_manager.commit(project.directory, "Assistant made changes")

    result = backup.finish_change(project, branch, controls, github_credentials)

    assert not result.large
    assert result.branch == "main"
    assert git_manager.current_branch(project.directory) == "main"
    assert branch not in git_manager.branches(project.directory)


def test_a_large_change_stays_on_its_review_branch(backed_up_project, github_credentials):
    project = backed_up_project
    controls = permissions.ParentControls(github_pr_policy=backup.POLICY_BRANCH)
    branch = backup.begin_change(project.directory, controls)

    for index in range(4):
        (project.directory / "src" / f"part{index}.py").write_text(
            "\n".join(f"line {n}" for n in range(60)), encoding="utf-8"
        )
    git_manager.commit(project.directory, "Assistant made changes")

    queue = PushQueue(path=project.directory / "queue.json")
    result = backup.finish_change(
        project, branch, controls, github_credentials, queue=queue
    )

    assert result.large
    assert result.branch == branch
    assert git_manager.current_branch(project.directory) == branch
    assert len(queue) == 2, "both the branch and main are queued"


def test_a_large_change_opens_a_pull_request_when_the_policy_says_so(
    backed_up_project, remote, github_credentials
):
    project = backed_up_project
    controls = permissions.ParentControls(github_pr_policy=backup.POLICY_PULL_REQUEST)
    branch = backup.begin_change(project.directory, controls)

    for index in range(4):
        (project.directory / "src" / f"part{index}.py").write_text(
            "\n".join(f"line {n}" for n in range(60)), encoding="utf-8"
        )
    git_manager.commit(project.directory, "Assistant made changes")

    transport = FakeTransport({
        ("POST", "/user/repos"): Response(201, {
            "full_name": "parent/OpenNest-Asteroid-Game",
            # The bare repo on disk, so the real push in finish_change works.
            "clone_url": str(remote),
            "private": True,
        }),
        ("POST", "/repos/parent/OpenNest-Asteroid-Game/pulls"): Response(201, {
            "number": 7,
            "html_url": "https://github.com/parent/OpenNest-Asteroid-Game/pull/7",
            "title": "Open Nest: changes to Asteroid Game",
        }),
    })
    result = backup.finish_change(
        project, branch, controls, github_credentials, transport=transport
    )

    assert result.problem == "", result.problem
    assert result.pull_request is not None
    assert result.pull_request.number == 7
    bodies = [b for b in transport.sent_bodies() if "head" in b]
    assert bodies[0]["head"] == branch
    assert bodies[0]["base"] == "main"


def test_a_failed_pull_request_still_leaves_the_work_saved(
    backed_up_project, github_credentials
):
    project = backed_up_project
    controls = permissions.ParentControls(github_pr_policy=backup.POLICY_PULL_REQUEST)
    branch = backup.begin_change(project.directory, controls)
    for index in range(4):
        (project.directory / "src" / f"part{index}.py").write_text(
            "\n".join(f"line {n}" for n in range(60)), encoding="utf-8"
        )
    ref = git_manager.commit(project.directory, "Assistant made changes")

    queue = PushQueue(path=project.directory / "queue.json")
    result = backup.finish_change(
        project, branch, controls, github_credentials,
        queue=queue, transport=FakeTransport(),  # every call 404s
    )

    assert result.problem
    assert result.large
    # The commit is still there, on the branch, and queued for a later attempt.
    assert git_manager.history(project.directory)[0].ref == ref
    assert len(queue) >= 1


# --------------------------------------------------------------- section 38

def test_conversation_archives_are_excluded_by_default(project):
    controls = permissions.ParentControls()
    assert controls.github_include_conversations is False
    assert backup.CONVERSATIONS_IGNORE in git_manager.GITIGNORE


def test_a_parent_can_include_conversation_history(backed_up_project):
    project_dir = backed_up_project.directory
    assert backup.apply_conversation_policy(project_dir, include=True)
    text = (project_dir / ".gitignore").read_text(encoding="utf-8")
    assert backup.CONVERSATIONS_IGNORE not in text

    assert backup.apply_conversation_policy(project_dir, include=False)
    text = (project_dir / ".gitignore").read_text(encoding="utf-8")
    assert backup.CONVERSATIONS_IGNORE in text


def test_applying_the_same_policy_twice_changes_nothing(backed_up_project):
    project_dir = backed_up_project.directory
    assert backup.apply_conversation_policy(project_dir, include=False) is False


# --------------------------------------------------------------- readiness

def test_backup_says_which_thing_is_missing(credentials, client_id):
    controls = permissions.ParentControls()
    assert "No GitHub account" in backup.readiness(controls, credentials).reason

    controls.github_private_backup = False
    assert "turned off" in backup.readiness(controls, credentials).reason


def test_a_build_with_no_oauth_app_says_so_rather_than_offering_a_button(credentials):
    """Phase 8's precedent: nothing fakes a connection."""
    assert auth.CLIENT_ID == "", "an unset client id is the shipped state until D1 lands"
    assert not auth.configured()
    controls = permissions.ParentControls()
    assert "not built with GitHub backup" in backup.readiness(controls, credentials).reason


def test_backup_is_ready_when_everything_is_configured(github_credentials, client_id):
    controls = permissions.ParentControls()
    readiness = backup.readiness(controls, github_credentials)
    assert readiness.ready, readiness.reason


# --------------------------------------------------------------- device flow

def test_the_device_flow_asks_for_only_the_repo_scope(client_id):
    transport = FakeTransport({
        ("POST", "/login/device/code"): Response(200, {
            "device_code": "dc", "user_code": "ABCD-1234",
            "verification_uri": "https://github.com/login/device",
            "interval": 5, "expires_in": 900,
        }),
    })
    code = auth.begin(transport)

    assert code.user_code == "ABCD-1234"
    assert transport.sent_bodies()[0]["scope"] == "repo"
    assert "delete_repo" not in transport.sent_bodies()[0]["scope"]


def test_the_parent_never_sees_the_device_code_half(client_id):
    code = auth.DeviceCode(
        user_code="ABCD-1234", verification_uri="https://github.com/login/device",
        device_code="secret-half",
    )
    assert "ABCD-1234" in code.instructions
    assert "secret-half" not in code.instructions


def test_waiting_is_not_an_error(client_id, credentials):
    transport = FakeTransport({
        ("POST", "/login/oauth/access_token"): Response(
            200, {"error": "authorization_pending"}
        ),
    })
    code = auth.DeviceCode("ABCD", "https://github.com/login/device", "dc")
    assert isinstance(auth.poll(code, transport, credentials), auth.Pending)


def test_slow_down_actually_slows_down(client_id, credentials):
    transport = FakeTransport({
        ("POST", "/login/oauth/access_token"): Response(200, {"error": "slow_down"}),
    })
    code = auth.DeviceCode("ABCD", "https://github.com/login/device", "dc", interval=5)
    outcome = auth.poll(code, transport, credentials)
    assert isinstance(outcome, auth.Pending)
    assert outcome.interval >= 10


def test_an_unknown_device_flow_error_is_not_reported_as_a_missing_token(
    client_id, credentials
):
    """The token endpoint answers HTTP 200 with the error in the body.

    So a response-status check sees success and falls through. Without an explicit
    branch, a parent whose sign-in failed for a real reason is told "GitHub approved the
    sign-in but sent no token", which is both wrong and unactionable.
    """
    transport = FakeTransport({
        ("POST", "/login/oauth/access_token"): Response(200, {
            "error": "device_flow_disabled",
            "error_description": "Device flow is not enabled for this app.",
        }),
    })
    code = auth.DeviceCode("ABCD", "https://github.com/login/device", "dc")
    with pytest.raises(GitHubError) as caught:
        auth.poll(code, transport, credentials)
    assert "not enabled" in str(caught.value)
    assert "sent no token" not in str(caught.value)


def test_a_declined_sign_in_says_it_was_declined(client_id, credentials):
    transport = FakeTransport({
        ("POST", "/login/oauth/access_token"): Response(200, {"error": "access_denied"}),
    })
    code = auth.DeviceCode("ABCD", "https://github.com/login/device", "dc")
    with pytest.raises(GitHubError) as caught:
        auth.poll(code, transport, credentials)
    assert "declined" in str(caught.value)
    assert not credentials.has_github_token()


def test_approval_stores_the_token_and_reports_the_account(client_id, credentials):
    transport = FakeTransport({
        ("POST", "/login/oauth/access_token"): Response(200, {"access_token": TOKEN}),
        ("GET", "/user"): Response(200, {"login": "parent-example"}),
    })
    code = auth.DeviceCode("ABCD", "https://github.com/login/device", "dc")
    outcome = auth.poll(code, transport, credentials)

    assert isinstance(outcome, auth.Connected)
    assert outcome.login == "parent-example"
    assert credentials.get_github_token() == TOKEN


def test_a_connection_result_does_not_carry_the_token(client_id, credentials):
    connected = auth.Connected(login="parent-example")
    assert TOKEN not in repr(connected)


def test_the_account_is_asked_of_github_not_remembered(github_credentials):
    """A token revoked on github.com must stop answering."""
    transport = FakeTransport({("GET", "/user"): Response(401, {"message": "Bad"})})
    assert auth.account(github_credentials, transport) is None


def test_being_offline_does_not_look_like_a_broken_connection(github_credentials):
    class Dead:
        def request(self, *args, **kwargs):
            raise OfflineError("no internet")

    assert auth.account(github_credentials, Dead()) is None
    assert auth.connected(github_credentials), "the token is still there"


def test_disconnect_removes_the_token(github_credentials):
    assert auth.disconnect(github_credentials)
    assert not auth.connected(github_credentials)
    assert not auth.disconnect(github_credentials)


def test_a_server_error_never_echoes_the_token(github_credentials):
    transport = FakeTransport({
        ("GET", "/user"): Response(500, {"message": f"failed for {TOKEN}"}),
    })
    with pytest.raises(GitHubError) as caught:
        auth.account(github_credentials, transport)
    assert TOKEN not in str(caught.value)


def test_a_permission_problem_is_not_reported_as_a_bad_credential(github_credentials):
    """Phase 6's lesson in ai/cloud.py, applied here before it could bite again."""
    transport = FakeTransport({
        ("GET", "/user"): Response(403, {"message": "Resource not accessible"}),
    })
    with pytest.raises(GitHubError) as caught:
        auth.account(github_credentials, transport)
    assert "reconnect" not in str(caught.value).lower()


def test_every_api_call_sends_the_token_as_a_bearer_header_only(github_credentials):
    transport = FakeTransport({("GET", "/user"): Response(200, {"login": "parent"})})
    auth.account(github_credentials, transport)
    method, url, headers, body = transport.requests[0]
    assert headers["Authorization"] == f"Bearer {TOKEN}"
    assert TOKEN not in url
    assert TOKEN not in json.dumps(body)
