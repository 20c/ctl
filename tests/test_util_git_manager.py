import logging
import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest
import yaml
from git import GitCommandError, Repo
from ogr.abstract import PRStatus

from ctl.util.git import (
    ChangeRequest,
    EphemeralGitContext,
    GitManager,
    RepositoryConfig,
    TemporaryGitContext,
    current_ephemeral_git_context,
    ephemeral_git_context_state,
    instance_url_from_repository_url,
    is_github_host,
    sanitize_url,
)


class DummyException(Exception):
    pass


# RepositoryConfig defaults pull tokens straight from the environment
# (env-over-config precedence), so ambient CI/developer credentials would
# otherwise leak into every GitManager these tests construct.
@pytest.fixture(autouse=True)
def isolate_ambient_tokens(monkeypatch):
    for var in ("GITHUB_TOKEN", "GITLAB_TOKEN", "GITLAB_URL"):
        monkeypatch.delenv(var, raising=False)


# Fixture to create a temporary directory and initialize a git repository
@pytest.fixture
def git_repo():
    with tempfile.TemporaryDirectory() as tmp_dir:
        repo = Repo.init(tmp_dir, initial_branch="main")
        repo.git.config("user.email", "test@example.com")
        repo.git.config("user.name", "Test User")

        assert repo.active_branch.name == "main"

        # create an empty README file and commit it

        open(os.path.join(tmp_dir, "README.md"), "w").close()
        repo.index.add(["README.md"])
        repo.index.commit("Initial commit")

        yield tmp_dir, repo


# Fixture to create a temporary directory, initialize a git repository, and add a config yaml file
@pytest.fixture
def git_repo_with_config():
    with tempfile.TemporaryDirectory() as tmp_dir:
        repo = Repo.init(tmp_dir, initial_branch="main")
        repo.git.config("user.email", "test@example.com")
        repo.git.config("user.name", "Test User")
        assert repo.active_branch.name == "main"

        # create an empty README file and commit it
        open(os.path.join(tmp_dir, "README.md"), "w").close()
        repo.index.add(["README.md"])
        repo.index.commit("Initial commit")

        # create a config yaml file
        config = {
            "gitlab_url": "https://gitlab.com",
            "github_token": "test_token",
        }
        with open(os.path.join(tmp_dir, "config.yaml"), "w") as f:
            yaml.dump(config, f)

        repo.index.add(["config.yaml"])
        repo.index.commit("Add config")

        yield tmp_dir, repo


# fixture to create two git repostirories and make one the submodule of the other
@pytest.fixture
def git_repo_with_submodule():
    with tempfile.TemporaryDirectory() as tmp_dir:
        # create two directories one for each repo
        main_dir = os.path.join(tmp_dir, "main_repo")
        os.mkdir(main_dir)

        submodule_dir = os.path.join(tmp_dir, "submodule_repo")
        os.mkdir(submodule_dir)

        # init submodule repository and add a README file
        submodule_repo = Repo.init(submodule_dir, initial_branch="main")
        assert submodule_repo.active_branch.name == "main"
        open(os.path.join(submodule_dir, "README.md"), "w").close()
        submodule_repo.index.add(["README.md"])
        submodule_repo.index.commit("Initial commit")

        # init main repository and add a README file
        main_repo = Repo.init(main_dir, initial_branch="main")
        assert main_repo.active_branch.name == "main"
        open(os.path.join(main_dir, "README.md"), "w").close()
        main_repo.git.config("user.email", "test@example.com")
        main_repo.git.config("user.name", "Test User")
        main_repo.index.add(["README.md"])
        main_repo.index.commit("Initial commit")

        os.environ["GIT_ALLOW_PROTOCOL"] = "file"
        # add submodule to main repo
        main_repo.git.submodule("add", f"file://{submodule_dir}", "test_submodule")
        main_repo.git.commit("-am", "submodules")

        assert main_repo.is_dirty() is False

        assert os.path.exists(os.path.join(main_dir, "test_submodule", "README.md"))

        yield main_dir, main_repo, submodule_dir


# Fixture to create a temporary directory to be later used to clone
# a repository into
@pytest.fixture
def clone_dir():
    with tempfile.TemporaryDirectory() as tmp_dir:
        yield tmp_dir


# Test that a GitManager instance can be created
def test_git_manager_init(git_repo):
    tmp_dir, repo = git_repo
    repo.create_remote("origin", url="http://localhost")
    git_manager = GitManager(url="http://localhost", directory=tmp_dir)
    assert git_manager is not None
    assert git_manager.url == "http://localhost"
    assert git_manager.directory == tmp_dir


# Test that a GitManager instance correctly identifies a clean repository
def test_git_manager_is_clean(git_repo):
    tmp_dir, repo = git_repo
    repo.create_remote("origin", url="http://localhost")
    git_manager = GitManager(url="http://localhost", directory=tmp_dir)
    assert git_manager.is_clean


# Test that a GitManager instance correctly identifies a dirty repository
def test_git_manager_is_dirty(git_repo):
    tmp_dir, repo = git_repo
    repo.create_remote("origin", url="http://localhost")
    git_manager = GitManager(url="http://localhost", directory=tmp_dir)
    # Make a change to the repository
    with open(os.path.join(tmp_dir, "test.txt"), "w") as f:
        f.write("Test")
    repo.index.add(["test.txt"])
    assert git_manager.is_dirty


# Test that a GitManager instance can correctly switch branches
def test_git_manager_switch_branch(git_repo):
    tmp_dir, repo = git_repo
    repo.create_remote("origin", url="file://" + tmp_dir)
    git_manager = GitManager(url="file://" + tmp_dir, directory=tmp_dir)
    git_manager.switch_branch("test", create=True)
    assert git_manager.repo.active_branch.name == "test"


# Test that a GitManager instance can pull from a "remote" repository
def test_git_manager_pull(git_repo, clone_dir):
    remote_dir, git_repo = git_repo
    git_manager = GitManager(url=f"file://{remote_dir}", directory=clone_dir)
    # Make a change to the "remote" repository
    with open(os.path.join(remote_dir, "test.txt"), "w") as f:
        f.write("Test")
    git_repo.index.add(["test.txt"])
    git_repo.index.commit("Test commit")
    # Pull the change into the local repository
    git_manager.pull()
    assert "test.txt" in os.listdir(clone_dir)


# Test that a GitManager instance can push to a "remote" repository
def test_git_manager_push(git_repo, clone_dir):
    remote_dir, git_repo = git_repo
    git_manager = GitManager(url=remote_dir, directory=clone_dir)
    # Create a new branch for this test
    branch_name = "test_branch"
    git_manager.switch_branch(branch_name, create=True)
    # Make a change to the local repository
    with open(os.path.join(clone_dir, "test.txt"), "w") as f:
        f.write("Test")
    git_manager.repo.index.add(["test.txt"])
    git_manager.repo.index.commit("Test commit")
    # Push the change to the "remote" repository
    git_manager.push()
    # Switch to the new branch on the remote repository and check that the change was pushed
    git_repo.git.checkout(branch_name)
    assert "test.txt" in os.listdir(remote_dir)


# Test that a GitManger instance can --force push to a "remote" repository
def test_git_manager_force_push(git_repo, clone_dir):
    remote_dir, git_repo = git_repo
    git_manager = GitManager(url=f"file://{remote_dir}", directory=clone_dir)
    # Create a new branch for this test
    branch_name = "test_branch"
    git_manager.switch_branch(branch_name, create=True)
    git_manager.require_remote_branch()
    # Make a change to the local repository
    with open(os.path.join(clone_dir, "test.txt"), "w") as f:
        f.write("Test")
    git_manager.repo.index.add(["test.txt"])
    git_manager.repo.index.commit("Test commit")

    # make a change to the remote repository
    git_repo.git.checkout(branch_name)
    with open(os.path.join(remote_dir, "test.txt"), "w") as f:
        f.write("Test in remote")
    git_repo.git.add("test.txt")
    git_repo.git.commit("-m", "Test commit")  #
    git_repo.git.checkout("main")

    # Push the change to the "remote" repository
    git_manager.push(force=True)
    # Switch to the new branch on the remote repository and check that the change was pushed
    git_repo.git.checkout(branch_name)
    assert "test.txt" in os.listdir(remote_dir)


# Test that the GitManager changed_files method correctly returns a list of changed files
# and unttracked files


def test_git_manager_changed_files(git_repo):
    tmp_dir, repo = git_repo
    repo.create_remote("origin", url="http://localhost")
    git_manager = GitManager(url="http://localhost", directory=tmp_dir)

    # Create a new file and add it to the index
    with open(os.path.join(tmp_dir, "test.txt"), "w") as f:
        f.write("Test")
    git_manager.repo.index.add(["test.txt"])
    git_manager.repo.index.commit("Test commit")

    # Create a new file and do not add it to the index
    with open(os.path.join(tmp_dir, "test2.txt"), "w") as f:
        f.write("Test")

    # Change the contents of the first file
    with open(os.path.join(tmp_dir, "test.txt"), "w") as f:
        f.write("Test2")

    changed_files_no_untracked = git_manager.changed_files()

    assert changed_files_no_untracked == ["test.txt"]

    changed_files_with_untracked = git_manager.changed_files(["test.txt", "test2.txt"])

    assert sorted(changed_files_with_untracked) == sorted(["test.txt", "test2.txt"])

    changed_files_discard_unchanged = git_manager.changed_files(["readme.md"])

    assert changed_files_discard_unchanged == []

    changed_files_discard_unchanged = git_manager.changed_files(
        ["test.txt", "readme.md"]
    )

    assert changed_files_discard_unchanged == ["test.txt"]


# Test that a GitManager instance can reset a repository
@pytest.mark.parametrize("allow_unsafe, expected", [(True, True), (False, False)])
def test_git_manager_reset(git_repo, clone_dir, allow_unsafe, expected):
    remote_dir, git_repo = git_repo
    git_manager = GitManager(
        url=remote_dir, directory=clone_dir, allow_unsafe=allow_unsafe
    )
    # Make a change to the local repository
    with open(os.path.join(clone_dir, "test.txt"), "w") as f:
        f.write("Test")
    git_manager.repo.index.add(["test.txt"])
    assert git_manager.is_dirty

    git_manager.reset(hard=True)
    assert git_manager.is_clean == expected


def test_git_manager_add_and_commit(git_repo):
    tmp_dir, repo = git_repo
    repo.create_remote("origin", url="http://localhost")
    git_manager = GitManager(url="http://localhost", directory=tmp_dir)
    # Create a new file and add it to the index
    with open(os.path.join(tmp_dir, "test_commit.txt"), "w") as f:
        f.write("Test")
    git_manager.add(["test_commit.txt"])
    git_manager.commit("Test commit")
    commit_tree = git_manager.repo.head.commit.tree
    file_paths = [blob.path for blob in commit_tree.traverse() if blob.type == "blob"]
    assert "test_commit.txt" in file_paths


# Repository content is untrusted input: a config file committed to the repository
# must never name the host that the operator's ambient token is sent to, and must
# never supply the credentials ctl acts with (issue #30). `git_repo_with_config`
# commits a config.yaml naming `https://gitlab.com` and a `github_token`, while the
# repository's own origin is `http://localhost`.
@patch("ctl.util.git.GithubService")
@patch("ctl.util.git.GitlabService")
def test_git_manager_ignores_repository_content_config(
    mock_gitlab_service, mock_github_service, git_repo_with_config, monkeypatch
):
    monkeypatch.setenv("GITLAB_TOKEN", "env_gitlab_token")

    tmp_dir, repo = git_repo_with_config
    repo.create_remote("origin", url="http://localhost")

    mock_github_service.return_value = MagicMock()
    mock_gitlab_service.return_value = MagicMock()

    git_manager = GitManager(url="http://localhost", directory=tmp_dir)

    # the host named by the repository is never used, for anything
    assert git_manager.repository_config.gitlab_url == "http://localhost"
    mock_gitlab_service.assert_called_once_with(
        token="env_gitlab_token", instance_url="http://localhost"
    )

    # and the credential committed to the repository is not used either
    mock_github_service.assert_not_called()


# Companion to the above: with no ambient credential at all, a repository that names
# a host and ships a token gets no services whatsoever
@patch("ctl.util.git.GithubService")
@patch("ctl.util.git.GitlabService")
def test_git_manager_repository_content_cannot_create_services(
    mock_gitlab_service, mock_github_service, git_repo_with_config
):
    tmp_dir, repo = git_repo_with_config
    repo.create_remote("origin", url="http://localhost")

    mock_github_service.return_value = MagicMock()
    mock_gitlab_service.return_value = MagicMock()

    git_manager = GitManager(url="http://localhost", directory=tmp_dir)

    mock_gitlab_service.assert_not_called()
    mock_github_service.assert_not_called()
    assert git_manager.services.gitlab is None
    assert git_manager.services.github is None


# The environment github token is the only one that can be used - the repository's
# `github_token` was previously taken verbatim, with no environment precedence at all
@patch("ctl.util.git.GithubService")
@patch("ctl.util.git.GitlabService")
def test_git_manager_github_token_comes_from_environment_only(
    mock_gitlab_service, mock_github_service, git_repo_with_config, monkeypatch
):
    monkeypatch.setenv("GITHUB_TOKEN", "env_github_token")

    tmp_dir, repo = git_repo_with_config
    repo.create_remote("origin", url="http://localhost")

    mock_github_service.return_value = MagicMock()
    mock_gitlab_service.return_value = MagicMock()

    # a config side token loses to the environment - the precedence #35 is about
    git_manager = GitManager(
        url="http://localhost",
        directory=tmp_dir,
        repository_config=RepositoryConfig(github_token="config_github_token"),
    )

    mock_github_service.assert_called_once_with(token="env_github_token")
    assert git_manager.repository_config.github_token == "env_github_token"


# `repository_config_filename` is accepted but ignored, so downstream callers that
# still pass it keep working without a config file ever being read
@patch("ctl.util.git.GithubService")
@patch("ctl.util.git.GitlabService")
def test_git_manager_repository_config_filename_is_ignored(
    mock_gitlab_service, mock_github_service, git_repo_with_config, monkeypatch
):
    monkeypatch.setenv("GITLAB_TOKEN", "env_gitlab_token")

    tmp_dir, repo = git_repo_with_config
    repo.create_remote("origin", url="http://localhost")

    mock_gitlab_service.return_value = MagicMock()

    git_manager = GitManager(
        url="http://localhost", directory=tmp_dir, repository_config_filename="config"
    )

    assert git_manager.repository_config.gitlab_url == "http://localhost"
    mock_gitlab_service.assert_called_once_with(
        token="env_gitlab_token", instance_url="http://localhost"
    )


# Companion to the ambient-token isolation fixture: environment tokens take
# precedence over repository config values, and that behavior must stay pinned.
@patch("ctl.util.git.GithubService")
@patch("ctl.util.git.GitlabService")
def test_git_manager_env_token_precedence(
    mock_gitlab_service, mock_github_service, git_repo_with_config, monkeypatch
):
    monkeypatch.setenv("GITHUB_TOKEN", "env_github_token")
    monkeypatch.setenv("GITLAB_TOKEN", "env_gitlab_token")

    tmp_dir, repo = git_repo_with_config
    repo.create_remote("origin", url="http://localhost")

    mock_github_service.return_value = MagicMock()
    mock_gitlab_service.return_value = MagicMock()

    git_manager = GitManager(url="http://localhost", directory=tmp_dir)

    # env wins over the config.yaml github_token ("test_token"): the service is
    # initialized from RepositoryConfig's env-derived defaults before the
    # repository config file is loaded
    mock_github_service.assert_called_once_with(token="env_github_token")
    # and the env token is folded back into the repository config
    assert git_manager.repository_config.gitlab_token == "env_gitlab_token"


# Test that a GitManager instance correctly sets the default_service property
@patch("ctl.util.git.GithubService")
@patch("ctl.util.git.GitlabService")
@patch("ctl.util.git.RepositoryConfig")
def test_git_manager_default_service(
    mock_repo_config, mock_gitlab_service, mock_github_service, git_repo_with_config
):
    mock_config = MagicMock()
    mock_config.gitlab_url = None
    mock_config.gitlab_token = None
    mock_config.github_token = "fake-github-token"
    mock_repo_config.return_value = mock_config

    tmp_dir, repo = git_repo_with_config
    repo.create_remote("origin", url="http://localhost")
    git_manager = GitManager(
        url="http://localhost", directory=tmp_dir, default_service="github"
    )

    # Mock the GithubService and GitlabService instances
    mock_github_service.return_value = MagicMock()
    mock_gitlab_service.return_value = MagicMock()

    assert git_manager.default_service == "github"
    assert mock_github_service.call_count == 1
    mock_github_service.assert_called_once_with(token="fake-github-token")


# Test that a GitManager instance correctly returns the default service or the only available service
@patch("ctl.util.git.GithubService")
@patch("ctl.util.git.GitlabService")
@patch("ctl.util.git.RepositoryConfig")
def test_git_manager_service(
    mock_repo_config, mock_gitlab_service, mock_github_service, git_repo_with_config
):
    mock_config = MagicMock()
    mock_config.gitlab_url = None
    mock_config.gitlab_token = None
    mock_config.github_token = "fake-github-token"
    mock_repo_config.return_value = mock_config

    tmp_dir, repo = git_repo_with_config
    repo.create_remote("origin", url="http://localhost")
    git_manager = GitManager(
        url="http://localhost", directory=tmp_dir, default_service="github"
    )

    # Mock the GithubService and GitlabService instances
    mock_github_service.return_value = MagicMock()
    mock_gitlab_service.return_value = MagicMock()

    assert git_manager.service == git_manager.services.github
    assert mock_github_service.call_count == 1
    mock_github_service.assert_called_once_with(token="fake-github-token")

    # Remove the default service and check that a value error is raised since both services
    # are setup and its not possible to determine which one to use
    git_manager.default_service = None
    git_manager.services.gitlab = MagicMock()
    with pytest.raises(ValueError):
        assert git_manager.service == git_manager.services.github

    # finally unset the github service and check that the gitlab service is returned

    git_manager.services.github = None
    assert git_manager.service == git_manager.services.gitlab


# --- gitlab instance url derivation (issue #30) ------------------------------


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://gitlab.example.com/group/repo.git", "https://gitlab.example.com"),
        (
            "https://user:token@gitlab.example.com/group/repo",
            "https://gitlab.example.com",
        ),
        (
            "https://gitlab.example.com:8443/group/repo",
            "https://gitlab.example.com:8443",
        ),
        ("http://localhost", "http://localhost"),
        ("http://localhost:8080/group/repo", "http://localhost:8080"),
        # scp style remotes are the common form for ssh clones
        ("git@gitlab.example.com:group/repo.git", "https://gitlab.example.com"),
        ("gitlab.example.com:group/repo.git", "https://gitlab.example.com"),
        # an ssh port says nothing about where the api lives
        (
            "ssh://git@gitlab.example.com:2222/group/repo.git",
            "https://gitlab.example.com",
        ),
        # hosts are normalized, so a comparison against them cannot be dodged
        ("https://GitLab.Example.COM/g/r", "https://gitlab.example.com"),
        ("git@gitlab.example.com.:group/repo.git", "https://gitlab.example.com"),
        # ipv6 literals have to come back out bracketed
        ("https://[2001:db8::1]/g/r.git", "https://[2001:db8::1]"),
        ("https://[2001:db8::1]:8443/g/r.git", "https://[2001:db8::1]:8443"),
        # nothing that does not name a host
        ("/srv/repos/repo.git", None),
        ("../repo", None),
        ("file:///srv/repos/repo.git", None),
        ("", None),
        (None, None),
        # malformed authorities fail closed rather than raising
        ("https://gitlab.example.com:99999/x", None),
        ("https://2001:db8::1/g/r.git", None),
        ("https://gitlab.example.com:notaport/x", None),
    ],
)
def test_instance_url_from_repository_url(url, expected):
    assert instance_url_from_repository_url(url) == expected


# Operator supplied values are parsed strictly: a missing scheme is a mistake, and
# reading it as an scp style remote would silently drop the port the operator named
@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://gitlab.internal:8443/g/r", "https://gitlab.internal:8443"),
        ("gitlab.internal:8443", None),
        ("gitlab.internal", None),
        ("git@gitlab.internal:group/repo.git", None),
    ],
)
def test_instance_url_from_repository_url_without_scp(url, expected):
    assert instance_url_from_repository_url(url, allow_scp=False) == expected


@pytest.mark.parametrize(
    "url,expected",
    [
        (
            "https://oauth2:glpat-secret@git.example.com/g/r",
            "https://git.example.com/g/r",
        ),
        ("https://git.example.com/g/r", "https://git.example.com/g/r"),
        # scheme-less forms: urlparse finds no netloc to clean, so these are handled
        # separately - a credential in one of them still must not reach a log line
        ("git@git.example.com:g/r.git", "git.example.com:g/r.git"),
        ("oauth2:glpat-secret@git.example.com:g/r.git", "git.example.com:g/r.git"),
        ("/srv/repos/repo.git", "/srv/repos/repo.git"),
        ("", ""),
    ],
)
def test_sanitize_url(url, expected):
    assert sanitize_url(url) == expected


@pytest.mark.parametrize(
    "host,expected",
    [
        ("github.com", True),
        ("ssh.github.com", True),
        ("gist.github.com", True),
        ("gitlab.example.com", False),
        # a host that merely ends in the string is not a github host
        ("notgithub.com", False),
        ("", False),
    ],
)
def test_is_github_host(host, expected):
    assert is_github_host(host) is expected


# Fixture for a repository whose origin is an arbitrary (non cloneable) url - the
# directory already holds a repository, so GitManager never tries to clone it
@pytest.fixture
def git_repo_with_origin():
    def _make(origin_url):
        tmp_dir = tempfile.mkdtemp()
        repo = Repo.init(tmp_dir, initial_branch="main")
        repo.git.config("user.email", "test@example.com")
        repo.git.config("user.name", "Test User")
        open(os.path.join(tmp_dir, "README.md"), "w").close()
        repo.index.add(["README.md"])
        repo.index.commit("Initial commit")
        repo.create_remote("origin", url=origin_url)
        return tmp_dir, repo

    return _make


# With no instance named by the operator, the instance is derived from the host the
# repository was actually cloned from - so the token can only ever reach that host
@patch("ctl.util.git.GithubService")
@patch("ctl.util.git.GitlabService")
def test_git_manager_derives_gitlab_url_from_origin(
    mock_gitlab_service, mock_github_service, git_repo_with_origin, monkeypatch, caplog
):
    monkeypatch.setenv("GITLAB_TOKEN", "env_gitlab_token")
    tmp_dir, repo = git_repo_with_origin("git@gitlab.example.com:group/repo.git")

    mock_gitlab_service.return_value = MagicMock()

    with caplog.at_level(logging.INFO, logger="ctl.util.git"):
        git_manager = GitManager(
            url="git@gitlab.example.com:group/repo.git", directory=tmp_dir
        )

    mock_gitlab_service.assert_called_once_with(
        token="env_gitlab_token", instance_url="https://gitlab.example.com"
    )
    assert git_manager.repository_config.gitlab_url == "https://gitlab.example.com"

    # the operator has to be able to read which host received their token
    assert (
        "Using gitlab instance https://gitlab.example.com (from the repository's "
        "clone origin)" in caplog.text
    )


# An explicitly configured instance always wins over the derived one, and is
# reported as such
@patch("ctl.util.git.GithubService")
@patch("ctl.util.git.GitlabService")
def test_git_manager_env_gitlab_url_wins_over_derivation(
    mock_gitlab_service, mock_github_service, git_repo_with_origin, monkeypatch, caplog
):
    monkeypatch.setenv("GITLAB_TOKEN", "env_gitlab_token")
    monkeypatch.setenv("GITLAB_URL", "https://gitlab.operator.example/group/repo")
    tmp_dir, repo = git_repo_with_origin("git@gitlab.example.com:group/repo.git")

    mock_gitlab_service.return_value = MagicMock()

    with caplog.at_level(logging.INFO, logger="ctl.util.git"):
        GitManager(url="git@gitlab.example.com:group/repo.git", directory=tmp_dir)

    mock_gitlab_service.assert_called_once_with(
        token="env_gitlab_token", instance_url="https://gitlab.operator.example"
    )
    assert (
        "Using gitlab instance https://gitlab.operator.example (from GITLAB_URL "
        "environment variable)" in caplog.text
    )


# Derivation fails closed: an origin that does not name a host we can use gets no
# service at all, and says what it looked at
@pytest.mark.parametrize(
    "origin_url,expected_in_log",
    [
        # github is the github service's territory, never a gitlab instance
        ("git@github.com:group/repo.git", "is a github host"),
        # ... and the check is not dodged by a trailing root dot, a case change or
        # one of github's other hosts
        ("git@GitHub.com.:group/repo.git", "is a github host"),
        ("ssh://git@ssh.github.com:443/group/repo.git", "is a github host"),
        # a local path names no host
        ("/srv/repos/repo.git", "does not name a host"),
        # neither does a malformed authority - it fails closed instead of raising
        # (an unbracketed ipv6 literal is covered in
        # test_instance_url_from_repository_url; git itself refuses it as a remote)
        ("https://gitlab.example.com:99999/group/repo.git", "does not name a host"),
    ],
)
@patch("ctl.util.git.GithubService")
@patch("ctl.util.git.GitlabService")
def test_git_manager_derivation_fails_closed(
    mock_gitlab_service,
    mock_github_service,
    git_repo_with_origin,
    monkeypatch,
    caplog,
    origin_url,
    expected_in_log,
):
    monkeypatch.setenv("GITLAB_TOKEN", "env_gitlab_token")
    tmp_dir, repo = git_repo_with_origin(origin_url)

    with caplog.at_level(logging.WARNING, logger="ctl.util.git"):
        git_manager = GitManager(url=origin_url, directory=tmp_dir)

    mock_gitlab_service.assert_not_called()
    assert git_manager.services.gitlab is None
    assert expected_in_log in caplog.text
    assert "not initializing a gitlab service" in caplog.text


# The remaining fail-closed cases are states the manager can be in before an origin
# has been established
@patch("ctl.util.git.GithubService")
@patch("ctl.util.git.GitlabService")
def test_git_manager_derivation_without_origin_fails_closed(
    mock_gitlab_service, mock_github_service, git_repo_with_origin, monkeypatch, caplog
):
    monkeypatch.setenv("GITLAB_TOKEN", "env_gitlab_token")
    tmp_dir, repo = git_repo_with_origin("https://gitlab.example.com/group/repo.git")
    git_manager = GitManager(
        url="https://gitlab.example.com/group/repo.git", directory=tmp_dir
    )

    # nothing at all to go on
    git_manager.origin = None
    git_manager.url = None
    git_manager.repo = None
    with caplog.at_level(logging.WARNING, logger="ctl.util.git"):
        assert git_manager.derive_gitlab_url() is None
    assert "no origin, no url and no remotes" in caplog.text

    # remotes that do not agree on a host
    caplog.clear()
    repo.create_remote("other", url="https://gitlab.other.example/group/repo.git")
    git_manager.repo = repo
    with caplog.at_level(logging.WARNING, logger="ctl.util.git"):
        assert git_manager.derive_gitlab_url() is None
    assert "do not agree on one" in caplog.text


# No gitlab credential means there is nothing to protect and nothing to derive
@patch("ctl.util.git.GithubService")
@patch("ctl.util.git.GitlabService")
def test_git_manager_no_derivation_without_token(
    mock_gitlab_service, mock_github_service, git_repo_with_origin, caplog
):
    tmp_dir, repo = git_repo_with_origin("git@gitlab.example.com:group/repo.git")

    with caplog.at_level(logging.WARNING, logger="ctl.util.git"):
        git_manager = GitManager(
            url="git@gitlab.example.com:group/repo.git", directory=tmp_dir
        )

    mock_gitlab_service.assert_not_called()
    assert git_manager.services.gitlab is None
    assert "gitlab service" not in caplog.text


# The temporary context re-clones and builds a second GitManager - it must not be a
# way back in for a host named by repository content
@patch("ctl.util.git.GithubService")
@patch("ctl.util.git.GitlabService")
def test_temporary_git_context_carries_only_operator_config(
    mock_gitlab_service, mock_github_service, git_repo_with_config, monkeypatch
):
    tmp_dir, repo = git_repo_with_config
    repo.create_remote("origin", url=f"file://{tmp_dir}")
    mock_gitlab_service.return_value = MagicMock()

    # supplied by the caller only - nothing in the environment stands in for it, so
    # the inner manager can only have it by way of the context carrying it over
    git_manager = GitManager(
        url=f"file://{tmp_dir}",
        directory=tmp_dir,
        repository_config=RepositoryConfig(
            gitlab_url="https://gitlab.operator.example",
            gitlab_token="operator_gitlab_token",
        ),
    )

    with TemporaryGitContext(git_manager) as ctx:
        # the config.yaml committed in the repository travels with the clone, and
        # still does not get to name a host: the operator's instance is what the
        # inner manager uses
        assert os.path.exists(os.path.join(ctx.git_manager.directory, "config.yaml"))
        assert (
            ctx.git_manager.repository_config.gitlab_url
            == "https://gitlab.operator.example"
        )
        assert ctx.git_manager.services.gitlab is not None

    assert mock_gitlab_service.call_args_list
    for call in mock_gitlab_service.call_args_list:
        assert call.kwargs["instance_url"] == "https://gitlab.operator.example"


# The derived instance url is resolved into the manager's own config. A caller that
# builds one RepositoryConfig and reuses it across repositories must not have the
# first repository's host applied to the second
@patch("ctl.util.git.GithubService")
@patch("ctl.util.git.GitlabService")
def test_repository_config_is_not_shared_between_managers(
    mock_gitlab_service, mock_github_service, git_repo_with_origin, monkeypatch
):
    monkeypatch.setenv("GITLAB_TOKEN", "env_gitlab_token")
    mock_gitlab_service.return_value = MagicMock()

    config = RepositoryConfig()

    first_dir, _ = git_repo_with_origin("https://gitlab-a.example/group/repo.git")
    GitManager(
        url="https://gitlab-a.example/group/repo.git",
        directory=first_dir,
        repository_config=config,
    )

    # the caller's object is untouched by the first repository's derivation
    assert config.gitlab_url is None

    second_dir, _ = git_repo_with_origin("https://gitlab-b.example/group/repo.git")
    GitManager(
        url="https://gitlab-b.example/group/repo.git",
        directory=second_dir,
        repository_config=config,
    )

    instance_urls = [
        call.kwargs["instance_url"] for call in mock_gitlab_service.call_args_list
    ]
    assert instance_urls == ["https://gitlab-a.example", "https://gitlab-b.example"]


# An operator supplied value that is not a full url must never fall through to
# GitlabService with no instance url - ogr defaults that to https://gitlab.com
@patch("ctl.util.git.GithubService")
@patch("ctl.util.git.GitlabService")
def test_git_manager_rejects_unusable_operator_gitlab_url(
    mock_gitlab_service, mock_github_service, git_repo_with_origin, monkeypatch
):
    monkeypatch.setenv("GITLAB_TOKEN", "env_gitlab_token")
    monkeypatch.setenv("GITLAB_URL", "gitlab.internal:8443")

    tmp_dir, _ = git_repo_with_origin("https://gitlab.example.com/group/repo.git")

    with pytest.raises(ValueError, match="Could not determine a gitlab instance url"):
        GitManager(url="https://gitlab.example.com/group/repo.git", directory=tmp_dir)

    mock_gitlab_service.assert_not_called()


# Credentials embedded in an origin must not reach a log line
@patch("ctl.util.git.GithubService")
@patch("ctl.util.git.GitlabService")
def test_git_manager_does_not_log_origin_credentials(
    mock_gitlab_service, mock_github_service, git_repo_with_origin, monkeypatch, caplog
):
    monkeypatch.setenv("GITLAB_TOKEN", "env_gitlab_token")
    origin_url = "https://oauth2:glpat-SUPERSECRET@github.com/group/repo.git"
    tmp_dir, _ = git_repo_with_origin(origin_url)

    with caplog.at_level(logging.DEBUG, logger="ctl.util.git"):
        GitManager(url=origin_url, directory=tmp_dir)

    # the refusal names what it inspected, but not the credential in it
    assert "is a github host" in caplog.text
    assert "glpat-SUPERSECRET" not in caplog.text


# The pre-clone pass cannot derive anything - warning from it would train operators
# to ignore the warning that means a credential was withheld
@patch("ctl.util.git.GithubService")
@patch("ctl.util.git.GitlabService")
def test_git_manager_does_not_warn_before_the_origin_is_known(
    mock_gitlab_service, mock_github_service, git_repo_with_origin, monkeypatch, caplog
):
    monkeypatch.setenv("GITLAB_TOKEN", "env_gitlab_token")
    tmp_dir, _ = git_repo_with_origin("https://gitlab.example.com/group/repo.git")

    mock_gitlab_service.return_value = MagicMock()

    # this is the `--checkout-path` shape: no url passed, it comes off the checkout
    with caplog.at_level(logging.WARNING, logger="ctl.util.git"):
        git_manager = GitManager(url=None, directory=tmp_dir)

    assert caplog.text == ""
    assert git_manager.services.gitlab is not None
    mock_gitlab_service.assert_called_once_with(
        token="env_gitlab_token", instance_url="https://gitlab.example.com"
    )


# Tokens must not be rendered by an incidental repr - the manager logs the config
# object at debug level
def test_repository_config_repr_hides_tokens():
    config = RepositoryConfig(
        gitlab_url="https://gitlab.example.com",
        gitlab_token="secret-gitlab-token",
        github_token="secret-github-token",
    )

    assert "secret-gitlab-token" not in repr(config)
    assert "secret-github-token" not in repr(config)
    assert "https://gitlab.example.com" in repr(config)


# Test that a GitManager instance can sync with a "remote" repository
def test_git_manager_sync(git_repo, clone_dir):
    remote_dir, git_repo = git_repo
    git_manager = GitManager(url=f"file://{remote_dir}", directory=clone_dir)
    # Make a change to the "remote" repository
    with open(os.path.join(remote_dir, "test_sync.txt"), "w") as f:
        f.write("Test sync")
    git_repo.index.add(["test_sync.txt"])
    git_repo.index.commit("Test sync commit")
    # Sync the local repository with the "remote" repository
    git_manager.sync()
    assert "test_sync.txt" in os.listdir(clone_dir)


# Test that a GitManager instance can sync with a "remote" repository and create a new branch if it does not exist
def test_git_manager_sync_with_new_branch(git_repo, clone_dir):
    remote_dir, git_repo = git_repo
    git_manager = GitManager(url=f"file://{remote_dir}", directory=clone_dir)
    # Switch to a new branch on the local repository
    new_branch = "test_sync_branch"
    git_manager.switch_branch(new_branch, create=True)
    # Make a change to the local repository
    with open(os.path.join(clone_dir, "test_sync.txt"), "w") as f:
        f.write("Test sync")
    git_manager.repo.index.add(["test_sync.txt"])
    git_manager.repo.index.commit("Test sync commit")
    # Sync the local repository with the "remote" repository
    git_manager.sync()
    # Switch to the new branch on the remote repository and check that the change was pushed
    git_repo.git.checkout(new_branch)
    assert "test_sync.txt" in os.listdir(remote_dir)


# Test that a GitManager instance can sync with a "remote" repository and merge changes
def test_git_manager_sync_with_merge(git_repo, clone_dir):
    remote_dir, git_repo = git_repo
    git_manager = GitManager(url=f"file://{remote_dir}", directory=clone_dir)
    git_manager.repo.git.config("user.email", "test@example.com")
    git_manager.repo.git.config("user.name", "Test User")
    git_manager.switch_branch("test", create=True)
    git_manager.require_remote_branch()

    # Make a change to the "remote" repository
    with open(os.path.join(remote_dir, "test_sync_remote.txt"), "w") as f:
        f.write("Test sync remote")

    git_repo.git.fetch()
    git_repo.git.checkout("test")
    git_repo.index.add(["test_sync_remote.txt"])
    git_repo.index.commit("Test sync remote commit")
    git_repo.git.checkout("main")

    # Make a different change to the local repository
    with open(os.path.join(clone_dir, "test_sync_local.txt"), "w") as f:
        f.write("Test sync local")
    git_manager.repo.index.add(["test_sync_local.txt"])
    git_manager.repo.index.commit("Test sync local commit")
    # Sync the local repository with the "remote" repository
    git_manager.sync()
    assert "test_sync_remote.txt" in os.listdir(clone_dir)
    assert "test_sync_local.txt" in os.listdir(clone_dir)


def test_submodule_init(git_repo_with_submodule, clone_dir):
    """
    Test that the GitManager correctly initializes submodules
    """
    remote_dir, git_repo, submodule_dir = git_repo_with_submodule
    GitManager(url=f"file://{remote_dir}", directory=clone_dir)
    assert os.path.exists(os.path.join(clone_dir, "test_submodule", "README.md"))


def test_submodule_init_disabled(git_repo_with_submodule, clone_dir):
    """
    Test that the GitManager does not initialize submodules if submodules=False
    """
    remote_dir, git_repo, submodule_dir = git_repo_with_submodule
    GitManager(url=f"file://{remote_dir}", directory=clone_dir, submodules=False)
    assert not os.path.exists(os.path.join(clone_dir, "test_submodule", "README.md"))


@patch("ctl.util.git.GithubService")
@patch("ctl.util.git.GitlabService")
@patch.object(GitManager, "service_project")
@patch("ctl.util.git.RepositoryConfig")
def test_git_manager_create_merge_request(
    mock_repo_config,
    mock_service_project,
    mock_gitlab_service,
    mock_github_service,
    git_repo_with_config,
):
    """
    Test that the GitManager.create_merge_request method correctly creates a merge request
    """
    tmp_dir, repo = git_repo_with_config

    mock_config = MagicMock()
    mock_config.github_url = None
    mock_config.github_token = None
    mock_config.gitlab_url = "http://localhost"
    mock_config.gitlab_token = "fake-gitlab-token"
    mock_repo_config.return_value = mock_config

    # Mock the GithubService and GitlabService instances
    mock_github_service.return_value = MagicMock()
    mock_gitlab_instance = MagicMock()
    mock_gitlab_service.return_value = mock_gitlab_instance

    repo.create_remote("origin", url="http://localhost")
    git_manager = GitManager(
        url="http://localhost", directory=tmp_dir, default_service="gitlab"
    )
    try:
        repo.git.checkout("test")
    except GitCommandError:
        repo.git.checkout("-b", "test")

    # Mock the service_project method to return a mock project
    mock_project = MagicMock()
    mock_service_project.return_value = mock_project

    # Call the create_merge_request method
    title = "Test Merge Request"
    git_manager.create_merge_request(title)

    # Check that the service_project and create_pull methods were called with the correct arguments
    mock_service_project.assert_called()
    mock_project.create_pr.assert_called_once_with(
        title=title,
        body="",
        target_branch=git_manager.default_branch,
        source_branch=git_manager.branch,
    )

    assert mock_gitlab_service.call_count == 1
    mock_gitlab_service.assert_called_once_with(
        token="fake-gitlab-token", instance_url="http://localhost"
    )


@pytest.mark.parametrize(
    "source_branch, target_branch, status, expected",
    [
        ("test", "main", PRStatus.open, True),
        ("test", "main", PRStatus.closed, False),
        ("test", "main", PRStatus.merged, False),
        ("test", "test-2", PRStatus.open, False),
    ],
)
@patch("ctl.util.git.GithubService")
@patch("ctl.util.git.GitlabService")
@patch.object(GitManager, "service_project")
@patch("ctl.util.git.RepositoryConfig")
def test_git_manager_create_merge_request_existing(
    mock_repo_config,
    mock_service_project,
    mock_gitlab_service,
    mock_github_service,
    git_repo_with_config,
    source_branch,
    target_branch,
    status,
    expected,
):
    """
    Test that the GitManager.create_merge_request method correctly updates an existing merge request
    """
    tmp_dir, repo = git_repo_with_config

    mock_config = MagicMock()
    mock_config.github_url = None
    mock_config.github_token = None
    mock_config.gitlab_url = "http://localhost"
    mock_config.gitlab_token = "fake-gitlab-token"
    mock_repo_config.return_value = mock_config

    # Mock the GithubService and GitlabService instances
    mock_github_service.return_value = MagicMock()
    mock_gitlab_instance = MagicMock()
    mock_gitlab_service.return_value = mock_gitlab_instance

    repo.create_remote("origin", url="http://localhost")
    git_manager = GitManager(
        url="http://localhost", directory=tmp_dir, default_service="gitlab"
    )
    try:
        repo.git.checkout(source_branch)
    except GitCommandError:
        repo.git.checkout("-b", source_branch)

    # Mock the service_project method to return a mock project
    mock_project = MagicMock()
    mock_service_project.return_value = mock_project

    # Mock the get_pr_list method to return a list containing a mock merge request with the same source branch
    mock_merge_request = MagicMock()
    mock_merge_request.source_branch = source_branch
    mock_merge_request.target_branch = target_branch
    mock_merge_request.status = status
    mock_project.get_pr_list.return_value = [mock_merge_request]

    # Call the create_merge_request method
    title = "Test Merge Request"
    git_manager.create_merge_request(title)

    assert mock_gitlab_service.call_count == 1
    mock_gitlab_service.assert_called_once_with(
        token="fake-gitlab-token", instance_url="http://localhost"
    )

    # Check that the update_info method of the merge request was called with the correct arguments
    if expected:
        mock_merge_request.update_info.assert_called_once_with(
            title=title, description=""
        )
    else:
        mock_merge_request.update_info.assert_not_called()


# Test that EphemeralGitContext correctly sets up and tears down the repository
def test_ephemeral_git_context_success(git_repo, clone_dir):
    remote_dir, git_repo = git_repo
    git_manager = GitManager(url=f"file://{remote_dir}", directory=clone_dir)

    # outside of context, currently in branch `main`

    assert git_manager.branch == git_manager.default_branch

    with EphemeralGitContext(
        git_manager=git_manager, branch="test", commit_message="Test commit"
    ) as ctx:
        # inside context, currently in branch `test`

        assert git_manager.branch == "test"

        # Create a new file and add it to the index within the context
        with open(os.path.join(clone_dir, "test_context.txt"), "w") as f:
            f.write("Test")
        ctx.add_files(["test_context.txt"])

    # outside of context, currently in branch `main`

    assert git_manager.branch == git_manager.default_branch

    # assert new file not in main branch

    commit_tree = git_manager.repo.head.commit.tree
    file_paths = [blob.path for blob in commit_tree.traverse() if blob.type == "blob"]
    assert "test_context.txt" not in file_paths

    # switch to test branch

    git_manager.switch_branch("test")

    # asset files were committed

    commit_tree = git_manager.repo.head.commit.tree
    file_paths = [blob.path for blob in commit_tree.traverse() if blob.type == "blob"]
    assert "test_context.txt" in file_paths

    # assert test branch now exists remotely

    assert git_manager.remote_branch_reference("test") is not None


# Test that EphemeralGitContext uses force push if force_push is set to True
def test_ephemeral_git_context_success_with_force_push(git_repo, clone_dir):
    remote_dir, git_repo = git_repo
    git_manager = GitManager(url=f"file://{remote_dir}", directory=clone_dir)

    # outside of context, currently in branch `main`

    assert git_manager.branch == git_manager.default_branch

    with EphemeralGitContext(
        git_manager=git_manager,
        branch="test",
        force_push=True,
        commit_message="Test commit",
    ) as ctx:
        # make changes to remote branch to cause a conflict

        with open(os.path.join(remote_dir, "test_context.txt"), "w") as f:
            f.write("Test")
        git_repo.git.checkout("-b", "test")
        git_repo.git.add("test_context.txt")
        git_repo.git.commit("-m", "Test commit")
        git_repo.git.checkout("main")

        # inside context, currently in branch `test`

        assert git_manager.branch == "test"

        # Create a new file and add it to the index within the context
        with open(os.path.join(clone_dir, "test_context.txt"), "w") as f:
            f.write("Test")
        ctx.add_files(["test_context.txt"])

    # outside of context, currently in branch `main`

    assert git_manager.branch == git_manager.default_branch

    # assert new file not in main branch

    commit_tree = git_manager.repo.head.commit.tree
    file_paths = [blob.path for blob in commit_tree.traverse() if blob.type == "blob"]
    assert "test_context.txt" not in file_paths

    # switch to test branch

    git_manager.switch_branch("test")

    # asset files were committed

    commit_tree = git_manager.repo.head.commit.tree
    file_paths = [blob.path for blob in commit_tree.traverse() if blob.type == "blob"]
    assert "test_context.txt" in file_paths

    # assert test branch now exists remotely

    assert git_manager.remote_branch_reference("test") is not None


# Test that EphemeralGitContext correctly sets up and tears down the repository and also
# honors validate_clean if set
def test_ephemeral_git_context_success_with_validate_clean(git_repo, clone_dir):
    remote_dir, git_repo = git_repo
    git_manager = GitManager(url=remote_dir, directory=clone_dir)

    def validate_clean(git_manager):
        # return True indicating we consider the repository clean
        # regardless of the actual state
        return True

    with EphemeralGitContext(
        git_manager=git_manager,
        branch="test",
        commit_message="Test commit",
        validate_clean=validate_clean,
    ) as ctx:
        # Create a new file and add it to the index within the context
        with open(os.path.join(clone_dir, "test_context.txt"), "w") as f:
            f.write("Test")
        ctx.add_files(["test_context.txt"])

    # asset files were NOT committed

    commit_tree = git_manager.repo.head.commit.tree
    file_paths = [blob.path for blob in commit_tree.traverse() if blob.type == "blob"]
    assert "test_context.txt" not in file_paths

    # assert test branch is still missing from remote

    assert git_manager.remote_branch_reference("test") is None


# Test that EphemeralGitContext correctly sets up and tears down the repository and also
# creates a change request if change_request is set
@patch("ctl.util.git.GithubService")
@patch("ctl.util.git.GitlabService")
@patch.object(GitManager, "service_project")
@patch("ctl.util.git.RepositoryConfig")
def test_ephemeral_git_context_success_with_change_request(
    mock_repo_config,
    mock_service_project,
    mock_gitlab_service,
    mock_github_service,
    git_repo_with_config,
    clone_dir,
):
    remote_dir, git_repo = git_repo_with_config

    mock_config = MagicMock()
    mock_config.github_url = None
    mock_config.github_token = None
    mock_config.gitlab_url = "http://localhost"
    mock_config.gitlab_token = "fake-gitlab-token"
    mock_repo_config.return_value = mock_config

    # Mock the GithubService and GitlabService instances
    mock_github_service.return_value = MagicMock()
    mock_gitlab_service.return_value = MagicMock()
    # Mock the service_project method to return a mock project
    mock_project = MagicMock()
    mock_service_project.return_value = mock_project
    git_repo.create_remote("origin", url=f"file://{remote_dir}")
    git_manager = GitManager(
        url=f"file://{remote_dir}", directory=clone_dir, default_service="gitlab"
    )

    change_request = ChangeRequest(
        title="Test change request",
        description="Test change request body",
    )

    # outside of context, currently in branch `main`

    assert git_manager.branch == git_manager.default_branch

    with EphemeralGitContext(
        git_manager=git_manager,
        branch="test",
        commit_message="Test commit",
        change_request=change_request,
    ) as ctx:
        # inside context, currently in branch `test`

        assert git_manager.branch == "test"

        # Create a new file and add it to the index within the context
        with open(os.path.join(clone_dir, "test_context.txt"), "w") as f:
            f.write("Test")
        ctx.add_files(["test_context.txt"])

    # assert change request was created

    mock_project.create_pr.assert_called_once_with(
        title=change_request.title,
        body=change_request.description,
        target_branch=git_manager.default_branch,
        source_branch="test",
    )

    # outside of context, currently in branch `main`

    assert git_manager.branch == git_manager.default_branch

    # switch to test branch

    git_manager.switch_branch("test")

    commit_tree = git_manager.repo.head.commit.tree
    file_paths = [blob.path for blob in commit_tree.traverse() if blob.type == "blob"]
    assert "test_context.txt" in file_paths
    assert mock_gitlab_service.call_count == 1
    mock_gitlab_service.assert_called_once_with(
        token="fake-gitlab-token", instance_url="http://localhost"
    )


# Test that EphemeralGitContext correctly handles exceptions and resets the repository
def test_ephemeral_git_context_failure(git_repo, clone_dir):
    remote_dir, git_repo = git_repo
    git_manager = GitManager(url=remote_dir, directory=clone_dir)

    with pytest.raises(DummyException):
        with EphemeralGitContext(
            git_manager=git_manager, commit_message="Test commit"
        ) as ctx:
            # Create a new file and add it to the index within the context
            with open(os.path.join(clone_dir, "test_context.txt"), "w") as f:
                f.write("Test")
            ctx.add_files(["test_context.txt"])
            # Raise an exception to trigger the failure handling
            raise DummyException("Test exception")

    commit_tree = git_manager.repo.head.commit.tree
    file_paths = [blob.path for blob in commit_tree.traverse() if blob.type == "blob"]
    assert "test_context.txt" not in file_paths


# Test that EpemeralGitContext correctly handles readonly mode
def test_ephemeral_git_context_readonly(git_repo, clone_dir):
    remote_dir, git_repo = git_repo
    git_manager = GitManager(url=remote_dir, directory=clone_dir)

    with EphemeralGitContext(
        git_manager=git_manager, commit_message="Test commit", readonly=True
    ) as ctx:
        # Create a new file and add it to the index within the context
        with open(os.path.join(clone_dir, "test_context.txt"), "w") as f:
            f.write("Test")
        ctx.add_files(["test_context.txt"])
    commit_tree = git_manager.repo.head.commit.tree
    file_paths = [blob.path for blob in commit_tree.traverse() if blob.type == "blob"]
    assert "test_context.txt" not in file_paths


# Test nested EphemeralGitContexts
def test_nested_ephemeral_git_contexts(git_repo, clone_dir):
    remote_dir, git_repo = git_repo
    git_manager = GitManager(url=f"file://{remote_dir}", directory=clone_dir)

    with EphemeralGitContext(
        git_manager=git_manager, branch="outer", commit_message="Test commit"
    ) as ctx:
        assert git_manager.branch == "outer"

        # Create a new file and add it to the index within the context
        with open(os.path.join(clone_dir, "test_context_outer_1.txt"), "w") as f:
            f.write("Test")
        ctx.add_files(["test_context_outer_1.txt"])

        with EphemeralGitContext(
            git_manager=git_manager, branch="inner", commit_message="Nested Test commit"
        ) as ctx2:
            assert git_manager.branch == "inner"

            # Create a new file and add it to the index within the context
            with open(os.path.join(clone_dir, "test_context_inner_1.txt"), "w") as f:
                f.write("Test")
            ctx2.add_files(["test_context_inner_1.txt"])

        # test that branch is "outer"
        assert git_manager.branch == "outer"

        # Create a new file and add it to the index within the context
        with open(os.path.join(clone_dir, "test_context_outer_2.txt"), "w") as f:
            f.write("Test")
        ctx.add_files(["test_context_outer_2.txt"])

    # back to default branch
    assert git_manager.branch == git_manager.default_branch

    # checkout outer branch in remote repo

    git_repo.git.checkout("outer")

    # check that the files exist at their remote branches
    assert "test_context_outer_1.txt" in os.listdir(remote_dir)
    assert "test_context_outer_2.txt" in os.listdir(remote_dir)

    git_repo.git.checkout("inner")

    assert "test_context_inner_1.txt" in os.listdir(remote_dir)


# Test inactive ephemeral git context
def test_inactive_ephemeral_git_context(git_repo, clone_dir):
    remote_dir, git_repo = git_repo
    git_manager = GitManager(url=remote_dir, directory=clone_dir)

    with open(os.path.join(clone_dir, "README.md"), "w") as f:
        f.write("Test")

    with EphemeralGitContext(
        git_manager=git_manager, commit_message="Test commit", inactive=True
    ) as ctx:
        # branch should still be dirty
        assert git_manager.is_dirty

        # no stashing
        assert not ctx.state.stash_pushed

        # Create a new file and add it to the index within the context
        with open(os.path.join(clone_dir, "test_context.txt"), "w") as f:
            f.write("Test")

        ctx.add_files(["test_context.txt"])
        assert not ctx.state.files_to_add

        # README.md changes should still be there
        with open(os.path.join(clone_dir, "README.md")) as f:
            assert f.read() == "Test"

    commit_tree = git_manager.repo.head.commit.tree
    file_paths = [blob.path for blob in commit_tree.traverse() if blob.type == "blob"]
    assert "test_context.txt" not in file_paths


# Test nested EphemeralGitContexts where the outer context is inactive
def test_nested_inactive_ephemeral_git_contexts(git_repo, clone_dir):
    remote_dir, git_repo = git_repo
    git_manager = GitManager(url=f"file://{remote_dir}", directory=clone_dir)

    with EphemeralGitContext(
        git_manager=git_manager,
        branch="outer",
        inactive=True,
        commit_message="Test commit",
    ) as ctx:
        # context is inactive, so branch should still be default

        assert git_manager.branch == git_manager.default_branch

        # Create a new file and add it to the index within the context
        with open(os.path.join(clone_dir, "test_context_outer_1.txt"), "w") as f:
            f.write("Test")

        ctx.add_files(["test_context_outer_1.txt"])

        # context is inactive, so files should not be added

        assert not ctx.state.files_to_add

        with EphemeralGitContext(
            git_manager=git_manager, branch="inner", commit_message="Nested Test commit"
        ) as ctx2:
            # nested context is active, so branch should be "inner"

            assert git_manager.branch == "inner"

            # Create a new file and add it to the index within the context
            with open(os.path.join(clone_dir, "test_context_inner_1.txt"), "w") as f:
                f.write("Test")
            ctx2.add_files(["test_context_inner_1.txt"])

        # test that branch is back to default
        assert git_manager.branch == git_manager.default_branch

        # Create a new file and add it to the index within the context
        with open(os.path.join(clone_dir, "test_context_outer_2.txt"), "w") as f:
            f.write("Test")

        ctx.add_files(["test_context_outer_2.txt"])

        # context is inactive, so files should not be added

        assert not ctx.state.files_to_add

    # back to default branch
    assert git_manager.branch == git_manager.default_branch

    # "outer" branch should not exist in remote repo

    assert not git_manager.remote_branch_reference("outer")

    # "inner" branch should exist and have the file

    git_repo.git.checkout("inner")

    assert "test_context_inner_1.txt" in os.listdir(remote_dir)


# Test nested readonly context, where outer context is read-only
def test_nested_readonly_ephemeral_git_contexts(git_repo, clone_dir):
    remote_dir, git_repo = git_repo
    git_manager = GitManager(url=f"file://{remote_dir}", directory=clone_dir)

    with EphemeralGitContext(
        git_manager=git_manager,
        branch="outer",
        readonly=True,
        commit_message="Test commit",
    ) as ctx:
        # context is readonly, which allows us to switch branches

        assert git_manager.branch == "outer"

        # Create a new file and add it to the index within the context
        with open(os.path.join(clone_dir, "test_context_outer_1.txt"), "w") as f:
            f.write("Test")

        ctx.add_files(["test_context_outer_1.txt"])

        # also change existing "README.md" file

        with open(os.path.join(clone_dir, "README.md"), "w") as f:
            f.write("Test outer")

        ctx.add_files(["README.md"])

        # context is readonly, files can be added to the context, but in the end
        # should not be committed or pushed

        assert len(ctx.state.files_to_add) == 2

        with EphemeralGitContext(
            git_manager=git_manager, branch="inner", commit_message="Nested Test commit"
        ) as ctx2:
            # nested context is writable, so branch should be "inner"

            assert git_manager.branch == "inner"

            # Create a new file and add it to the index within the context
            with open(os.path.join(clone_dir, "test_context_inner_1.txt"), "w") as f:
                f.write("Test")

            ctx2.add_files(["test_context_inner_1.txt"])

        # test that branch is back to "outer"
        assert git_manager.branch == "outer"

        # Create a new file and add it to the index within the context
        with open(os.path.join(clone_dir, "test_context_outer_2.txt"), "w") as f:
            f.write("Test")

        ctx.add_files(["test_context_outer_2.txt"])

        # context is readonly, files can be added to the context, but in the end
        # should not be committed or pushed

        assert len(ctx.state.files_to_add) == 3

    # back to default branch
    assert git_manager.branch == git_manager.default_branch

    # "outer" branch should not exist in remote repo

    assert not git_manager.remote_branch_reference("outer")

    # "inner" branch should exist and have the file

    git_repo.git.checkout("inner")

    assert "test_context_inner_1.txt" in os.listdir(remote_dir)

    # finally we we open another local context to outer, and it should be reset from main
    # since it was never committed

    with EphemeralGitContext(
        git_manager=git_manager,
        branch="outer",
        commit_message="Test commit",
        readonly=True,
    ) as ctx:
        # check that test_context_outer_1.txt are not tracked
        # since they were never committed but still exist in the working tree

        assert "test_context_outer_1.txt" in git_manager.repo.untracked_files
        assert "test_context_outer_2.txt" in git_manager.repo.untracked_files

        # check that README.md has been reset

        assert open(os.path.join(clone_dir, "README.md")).read() == ""


# Test that ephemeral context deletes local branch before switching to it
def test_ephemeral_git_context_delete_local_branch(git_repo, clone_dir):
    remote_dir, git_repo = git_repo

    # needs to allow_unsafe=False so git reset doesnt reset our branch
    # branch should be reset through deletion
    git_manager = GitManager(
        url=f"file://{remote_dir}", directory=clone_dir, allow_unsafe=False
    )

    git_manager.switch_branch("test", create=True)

    orig_readme_content = open(os.path.join(clone_dir, "README.md")).read()

    # change README.md

    with open(os.path.join(clone_dir, "README.md"), "w") as f:
        f.write("Testing")
    git_manager.repo.index.add(["README.md"])
    git_manager.repo.index.commit("Test commit")

    git_manager.switch_branch("main")

    with EphemeralGitContext(
        git_manager=git_manager, branch="test", commit_message="Test commit"
    ) as ctx:
        # check that README.md has been reset

        assert open(os.path.join(clone_dir, "README.md")).read() == orig_readme_content


# Test that ephemeral context deletes local branch before switching to it
def test_ephemeral_git_context_delete_local_branch_inactive(git_repo, clone_dir):
    remote_dir, git_repo = git_repo

    # needs to allow_unsafe=False so git reset doesnt reset our branch
    # branch should be reset through deletion
    git_manager = GitManager(
        url=f"file://{remote_dir}", directory=clone_dir, allow_unsafe=False
    )

    git_manager.switch_branch("test", create=True)

    orig_readme_content = open(os.path.join(clone_dir, "README.md")).read()

    # change README.md

    with open(os.path.join(clone_dir, "README.md"), "w") as f:
        f.write("Testing")
    git_manager.repo.index.add(["README.md"])
    git_manager.repo.index.commit("Test commit")

    git_manager.switch_branch("main")

    with EphemeralGitContext(
        git_manager=git_manager,
        branch="test",
        commit_message="Test commit",
        inactive=True,
    ) as ctx:
        # check that README.md has NOT been reset

        assert open(os.path.join(clone_dir, "README.md")).read() == orig_readme_content


# Test that ephemeral context deletes local branch before switching to it
def test_ephemeral_git_context_delete_local_branch_remake_from_remote(
    git_repo, clone_dir
):
    remote_dir, git_repo = git_repo

    # create remote "test" branch and change README.md and commit

    git_repo.git.checkout("main")
    git_repo.git.checkout("-b", "test")
    with open(os.path.join(remote_dir, "README.md"), "w") as f:
        f.write("Testing initial")
    git_repo.git.commit("-am", "Test commit")
    git_repo.git.checkout("main")

    assert open(os.path.join(remote_dir, "README.md")).read() == ""

    git_repo.git.checkout("test")

    assert open(os.path.join(remote_dir, "README.md")).read() == "Testing initial"

    git_repo.git.checkout("main")

    # needs to allow_unsafe=False so git reset doesnt reset our branch
    # branch should be reset through deletion
    git_manager = GitManager(
        url=f"file://{remote_dir}", directory=clone_dir, allow_unsafe=False
    )

    git_manager.switch_branch("test")
    # git_manager.pull()

    with open(os.path.join(clone_dir, "README.md")) as f:
        orig_readme_content = f.read()

    assert orig_readme_content == "Testing initial"

    # change README.md

    with open(os.path.join(clone_dir, "README.md"), "w") as f:
        f.write("Testing new")
    git_manager.repo.index.add(["README.md"])
    git_manager.repo.index.commit("Test commit")

    git_manager.switch_branch("main")
    assert open(os.path.join(clone_dir, "README.md")).read() == ""

    with EphemeralGitContext(
        git_manager=git_manager, branch="test", commit_message="Test commit"
    ) as ctx:
        # check that README.md has been reset

        assert open(os.path.join(clone_dir, "README.md")).read() == orig_readme_content

    with EphemeralGitContext(
        git_manager=git_manager, branch="main", commit_message="Test commit"
    ) as ctx:
        # check that README.md has been reset

        assert open(os.path.join(clone_dir, "README.md")).read() == ""


# Test current_ephemeral_git_context holds the current ctx
def test_context_vars(git_repo, clone_dir):
    remote_dir, git_repo = git_repo
    git_manager = GitManager(url=remote_dir, directory=clone_dir)
    with EphemeralGitContext(
        git_manager=git_manager, branch="test", commit_message="Test commit"
    ) as ctx:
        assert current_ephemeral_git_context.get() == ctx
        assert ephemeral_git_context_state.get() == ctx.state
        with EphemeralGitContext(
            git_manager=git_manager, branch="inner", commit_message="Nested Test commit"
        ) as ctx2:
            assert current_ephemeral_git_context.get() == ctx2
            assert ephemeral_git_context_state.get() == ctx2.state
            assert ctx2.state != ctx.state
        assert current_ephemeral_git_context.get() == ctx
        assert ephemeral_git_context_state.get() == ctx.state


# Test stashing between contexts
def test_stash_between_contexts(git_repo, clone_dir):
    remote_dir, git_repo = git_repo
    git_manager = GitManager(url=f"file://{remote_dir}", directory=clone_dir)

    # Create a new file and add it to the index within the context

    with open(os.path.join(clone_dir, "README.md"), "w") as f:
        f.write("Testing initial")

    with EphemeralGitContext(
        git_manager=git_manager, branch="outer", commit_message="Test commit"
    ) as ctx:
        # assert stashes
        assert ctx.state.stash_pushed
        assert git_manager.repo.git.stash("list")

        assert git_manager.branch == "outer"

        # Create a new file and add it to the index within the context
        with open(os.path.join(clone_dir, "README.md"), "w") as f:
            f.write("Test")

        assert git_manager.is_dirty

        with EphemeralGitContext(
            git_manager=git_manager, branch="inner", commit_message="Nested Test commit"
        ) as ctx2:
            assert ctx2.state.stash_pushed
            assert git_manager.branch == "inner"

            # Create a new file and add it to the index within the context
            with open(os.path.join(clone_dir, "test_context_inner_1.txt"), "w") as f:
                f.write("Test")
            ctx2.add_files(["test_context_inner_1.txt"])

        assert ctx2.state.stash_popped

        # test that branch is "outer"
        assert git_manager.branch == "outer"

        # Create a new file and add it to the index within the context
        with open(os.path.join(clone_dir, "test_context_outer_2.txt"), "w") as f:
            f.write("Test")
        ctx.add_files(["test_context_outer_2.txt", "README.md"])

    # back to default branch
    assert git_manager.branch == git_manager.default_branch

    # checkout outer branch in remote repo

    git_repo.git.checkout("outer")

    # check that the files exist at their remote branches
    assert "test_context_outer_2.txt" in os.listdir(remote_dir)

    git_repo.git.checkout("inner")

    assert "test_context_inner_1.txt" in os.listdir(remote_dir)

    # assert that README.md was stashed and popped

    assert "README.md" in os.listdir(clone_dir)
    with open(os.path.join(clone_dir, "README.md")) as f:
        assert f.read() == "Testing initial"

    # assert all stashes have been popped

    assert not git_manager.repo.git.stash("list")


def test_remote_branch_reference_slashed_branch(git_repo, clone_dir):
    # branch names containing "/" must match their own remote ref -
    # naive splitting on "/" only compared the last segment
    remote_dir, repo = git_repo
    git_manager = GitManager(url=f"file://{remote_dir}", directory=clone_dir)
    git_manager.switch_branch("feature/nested-name", create=True)
    git_manager.require_remote_branch()

    ref = git_manager.remote_branch_reference("feature/nested-name")
    assert ref is not None
    assert ref.name == "origin/feature/nested-name"

    assert git_manager.remote_branch_reference("nested-name") is None
