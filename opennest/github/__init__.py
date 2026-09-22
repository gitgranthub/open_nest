"""GitHub backup -- WORKORDER_01 section 29A, Phase 9.

Four modules, and the split follows the two things that must not get mixed up:

- :mod:`opennest.github.auth` -- how the *parent's* account is connected, and where the
  token lives (the Keychain, and nowhere else).
- :mod:`opennest.github.api` -- the REST calls: create a private repository, open a pull
  request. Transport is injectable, so the test suite opens no socket.
- :mod:`opennest.github.push_queue` -- pushes waiting for the internet. Section 34: a
  temporary loss of connectivity must never block local development.
- :mod:`opennest.github.backup` -- the orchestration, and the PR policy.

**Whose account this is.** The parent's. Section 35A's connection flow says "Sign in to
the parent's GitHub account" in as many words, the connection lives behind the parent
PIN, and GitHub's own terms put an age floor under a child having one at all. The commit
*identity* is a separate thing and may be the child's -- section 29A permits their
GitHub noreply address -- and that half was already plumbed in Phase 8.
"""
