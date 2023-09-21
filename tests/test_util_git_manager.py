import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest
import yaml
from git import Repo

from ctl.util.git import EphemeralGitContext, GitManager


class DummyException(Exception):
    pass


# Fixture to create a temporary directory and initialize a git repository
@pytest.fixture
def git_repo():
    with tempfile.TemporaryDirectory() as tmp_dir:
        repo = Repo.init(tmp_dir, initial_branch="main")

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
        assert repo.active_branch.name == "main"

        # create an empty README file and commit it
        open(os.path.join(tmp_dir, "README.md"), "w").close()
        repo.index.add(["README.md"])
        repo.index.commit("Initial commit")

        # create a config yaml file
        config = {
            "gitlab_url": "https://gitlab.com",
            "github_url": "https://github.com",
        }
        with open(os.path.join(tmp_dir, "config.yaml"), "w") as f:
            yaml.dump(config, f)

        yield tmp_dir, repo


# Fixture to create a temporary directory to be later used to clone
# a repository into
@pytest.fixture
def clone_dir():
    with tempfile.TemporaryDirectory() as tmp_dir:
        yield tmp_dir


# Test that a GitManager instance can be created
def test_git_manager_init(git_repo):
    tmp_dir, repo = git_repo
    git_manager = GitManager(url="http://localhost", directory=tmp_dir)
    assert git_manager is not None
    assert git_manager.url == "http://localhost"
    assert git_manager.directory == tmp_dir


# Test that a GitManager instance correctly identifies a clean repository
def test_git_manager_is_clean(git_repo):
    tmp_dir, repo = git_repo
    git_manager = GitManager(url="http://localhost", directory=tmp_dir)
    assert git_manager.is_clean


# Test that a GitManager instance correctly identifies a dirty repository
def test_git_manager_is_dirty(git_repo):
    tmp_dir, repo = git_repo
    git_manager = GitManager(url="http://localhost", directory=tmp_dir)
    # Make a change to the repository
    with open(os.path.join(tmp_dir, "test.txt"), "w") as f:
        f.write("Test")
    repo.index.add(["test.txt"])
    assert git_manager.is_dirty


# Test that a GitManager instance can correctly switch branches
def test_git_manager_switch_branch(git_repo):
    tmp_dir, repo = git_repo
    git_manager = GitManager(url="http://localhost", directory=tmp_dir)
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
    git_manager = GitManager(url="http://localhost", directory=tmp_dir)
    # Create a new file and add it to the index
    with open(os.path.join(tmp_dir, "test_commit.txt"), "w") as f:
        f.write("Test")
    git_manager.add(["test_commit.txt"])
    git_manager.commit("Test commit")
    commit_tree = git_manager.repo.head.commit.tree
    file_paths = [blob.path for blob in commit_tree.traverse() if blob.type == "blob"]
    assert "test_commit.txt" in file_paths


# Test that a GitManager instance can correctly load repository config
@patch("ctl.util.git.GithubService")
@patch("ctl.util.git.GitlabService")
def test_git_manager_load_repository_config(
    mock_gitlab_service, mock_github_service, git_repo_with_config
):
    tmp_dir, repo = git_repo_with_config
    git_manager = GitManager(url="http://localhost", directory=tmp_dir)

    # Mock the GithubService and GitlabService instances
    mock_github_service.return_value = MagicMock()
    mock_gitlab_service.return_value = MagicMock()

    assert git_manager.repository_config.gitlab_url == "https://gitlab.com"
    assert git_manager.repository_config.github_url == "https://github.com"

    # Check that the GithubService and GitlabService were called with the correct arguments
    mock_github_service.assert_called_once_with(
        token=None, instance_url="https://github.com"
    )
    mock_gitlab_service.assert_called_once_with(
        token=None, instance_url="https://gitlab.com"
    )


# Test that a GitManager instance correctly sets the default_service property
@patch("ctl.util.git.GithubService")
@patch("ctl.util.git.GitlabService")
def test_git_manager_default_service(
    mock_gitlab_service, mock_github_service, git_repo_with_config
):
    tmp_dir, repo = git_repo_with_config
    git_manager = GitManager(
        url="http://localhost", directory=tmp_dir, default_service="github"
    )

    # Mock the GithubService and GitlabService instances
    mock_github_service.return_value = MagicMock()
    mock_gitlab_service.return_value = MagicMock()

    git_manager.load_repository_config("config.yaml")
    assert git_manager.default_service == "github"


# Test that a GitManager instance correctly returns the default service or the only available service
@patch("ctl.util.git.GithubService")
@patch("ctl.util.git.GitlabService")
def test_git_manager_service(
    mock_gitlab_service, mock_github_service, git_repo_with_config
):
    tmp_dir, repo = git_repo_with_config
    git_manager = GitManager(
        url="http://localhost", directory=tmp_dir, default_service="github"
    )

    # Mock the GithubService and GitlabService instances
    mock_github_service.return_value = MagicMock()
    mock_gitlab_service.return_value = MagicMock()

    git_manager.load_repository_config("config.yaml")
    assert git_manager.service == git_manager.services.github

    # Remove the default service and check that a value error is raised since both services
    # are setup and its not possible to determine which one to use
    git_manager.default_service = None
    with pytest.raises(ValueError):
        assert git_manager.service == git_manager.services.github

    # finally unset the github service and check that the gitlab service is returned

    git_manager.services.github = None
    assert git_manager.service == git_manager.services.gitlab


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


@patch("ctl.util.git.GithubService")
@patch("ctl.util.git.GitlabService")
@patch.object(GitManager, "service_project")
def test_git_manager_create_merge_request(
    mock_service_project, mock_gitlab_service, mock_github_service, git_repo_with_config
):
    """
    Test that the GitManager.create_merge_request method correctly creates a merge request
    """
    tmp_dir, repo = git_repo_with_config

    # Mock the GithubService and GitlabService instances
    mock_github_service.return_value = MagicMock()
    mock_gitlab_service.return_value = MagicMock()

    git_manager = GitManager(
        url="http://localhost", directory=tmp_dir, default_service="gitlab"
    )

    # Mock the service_project method to return a mock project
    mock_project = MagicMock()
    mock_service_project.return_value = mock_project

    # Call the create_merge_request method
    title = "Test Merge Request"
    git_manager.create_merge_request(title)

    # Check that the service_project and create_pull methods were called with the correct arguments
    mock_service_project.assert_called_once()
    mock_project.create_pull.assert_called_once_with(
        title=title,
        description="",
        target_branch=git_manager.default_branch,
        source_branch=git_manager.branch,
    )


@patch("ctl.util.git.GithubService")
@patch("ctl.util.git.GitlabService")
@patch.object(GitManager, "service_project")
def test_git_manager_create_merge_request_existing(
    mock_service_project, mock_gitlab_service, mock_github_service, git_repo_with_config
):
    """
    Test that the GitManager.create_merge_request method correctly updates an existing merge request
    """
    tmp_dir, repo = git_repo_with_config

    # Mock the GithubService and GitlabService instances
    mock_github_service.return_value = MagicMock()
    mock_gitlab_service.return_value = MagicMock()

    git_manager = GitManager(
        url="http://localhost", directory=tmp_dir, default_service="gitlab"
    )

    # Mock the service_project method to return a mock project
    mock_project = MagicMock()
    mock_service_project.return_value = mock_project

    # Mock the get_pr_list method to return a list containing a mock merge request with the same source branch
    mock_merge_request = MagicMock()
    mock_merge_request.source_branch = git_manager.branch
    mock_project.get_pr_list.return_value = [mock_merge_request]

    # Call the create_merge_request method
    title = "Test Merge Request"
    git_manager.create_merge_request(title)

    # Check that the update_info method of the merge request was called with the correct arguments
    mock_merge_request.update_info.assert_called_once_with(title=title)


# Test that EphemeralGitContext correctly sets up and tears down the repository
def test_ephemeral_git_context_success(git_repo, clone_dir):
    remote_dir, git_repo = git_repo
    git_manager = GitManager(url=remote_dir, directory=clone_dir)
    with EphemeralGitContext(git_manager=git_manager, commit_message="Test commit"):
        # Create a new file and add it to the index within the context
        with open(os.path.join(clone_dir, "test_context.txt"), "w") as f:
            f.write("Test")
        git_manager.add(["test_context.txt"])
    commit_tree = git_manager.repo.head.commit.tree
    file_paths = [blob.path for blob in commit_tree.traverse() if blob.type == "blob"]
    assert "test_context.txt" in file_paths


# Test that EphemeralGitContext correctly handles exceptions and resets the repository
def test_ephemeral_git_context_failure(git_repo, clone_dir):
    remote_dir, git_repo = git_repo
    git_manager = GitManager(url=remote_dir, directory=clone_dir)

    with pytest.raises(DummyException):
        with EphemeralGitContext(git_manager=git_manager, commit_message="Test commit"):
            # Create a new file and add it to the index within the context
            with open(os.path.join(clone_dir, "test_context.txt"), "w") as f:
                f.write("Test")
            git_manager.add(["test_context.txt"])
            # Raise an exception to trigger the failure handling
            raise DummyException("Test exception")
    commit_tree = git_manager.repo.head.commit.tree
    file_paths = [blob.path for blob in commit_tree.traverse() if blob.type == "blob"]
    assert "test_context.txt" not in file_paths
