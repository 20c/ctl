import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest
import yaml
from git import Repo

from ctl.util.git import EphemeralGitContext, GitManager, ChangeRequest


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

        repo.index.add(["config.yaml"])
        repo.index.commit("Add config")

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


# Test that the GitManager changed_files method correctly returns a list of changed files
# and unttracked files


def test_git_manager_changed_files(git_repo):
    tmp_dir, repo = git_repo
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
    git_manager.switch_branch("test")

    # Mock the service_project method to return a mock project
    mock_project = MagicMock()
    mock_service_project.return_value = mock_project

    # Call the create_merge_request method
    title = "Test Merge Request"
    git_manager.create_merge_request(title)

    # Check that the service_project and create_pull methods were called with the correct arguments
    mock_service_project.assert_called_once()
    mock_project.create_pr.assert_called_once_with(
        title=title,
        body="",
        target_branch=git_manager.default_branch,
        source_branch=git_manager.branch,
    )



@pytest.mark.parametrize("source_branch, target_branch, status, expected",[
    ("test", "main", "open", True),
    ("test", "main", "closed", False),
    ("test", "main", "merged", False),
    ("test", "test-2", "open", False),
])
@patch("ctl.util.git.GithubService")
@patch("ctl.util.git.GitlabService")
@patch.object(GitManager, "service_project")
def test_git_manager_create_merge_request_existing(
    mock_service_project, 
    mock_gitlab_service, 
    mock_github_service, 
    git_repo_with_config,
    source_branch,
    target_branch,
    status,
    expected
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

    git_manager.switch_branch(source_branch)

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

    # Check that the update_info method of the merge request was called with the correct arguments
    if expected:
        mock_merge_request.update_info.assert_called_once_with(title=title, body="")
    else:
        mock_merge_request.update_info.assert_not_called()


# Test that EphemeralGitContext correctly sets up and tears down the repository
def test_ephemeral_git_context_success(git_repo, clone_dir):
    remote_dir, git_repo = git_repo
    git_manager = GitManager(url=remote_dir, directory=clone_dir)
    with EphemeralGitContext(git_manager=git_manager, branch="test", commit_message="Test commit") as ctx:
        # Create a new file and add it to the index within the context
        with open(os.path.join(clone_dir, "test_context.txt"), "w") as f:
            f.write("Test")
        ctx.add_files(["test_context.txt"])

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
        validate_clean=validate_clean
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
def test_ephemeral_git_context_success_with_change_request(
    mock_service_project, 
    mock_gitlab_service, 
    mock_github_service, 
    git_repo_with_config, 
    clone_dir
):
    remote_dir, git_repo = git_repo_with_config

    # Mock the GithubService and GitlabService instances
    mock_github_service.return_value = MagicMock()
    mock_gitlab_service.return_value = MagicMock()
    # Mock the service_project method to return a mock project
    mock_project = MagicMock()
    mock_service_project.return_value = mock_project

    git_manager = GitManager(url=f"file://{remote_dir}", directory=clone_dir, default_service="gitlab")

    change_request = ChangeRequest(
        title="Test change request",
        description="Test change request body",
    )

    with EphemeralGitContext(git_manager=git_manager, branch="test", commit_message="Test commit", change_request=change_request) as ctx:
        # Create a new file and add it to the index within the context
        with open(os.path.join(clone_dir, "test_context.txt"), "w") as f:
            f.write("Test")
        ctx.add_files(["test_context.txt"])

    mock_project.create_pr.assert_called_once_with(
        title=change_request.title,
        body=change_request.description,
        target_branch=git_manager.default_branch,
        source_branch="test",
    )

    commit_tree = git_manager.repo.head.commit.tree
    file_paths = [blob.path for blob in commit_tree.traverse() if blob.type == "blob"]
    assert "test_context.txt" in file_paths

# Test that EphemeralGitContext correctly handles exceptions and resets the repository
def test_ephemeral_git_context_failure(git_repo, clone_dir):
    remote_dir, git_repo = git_repo
    git_manager = GitManager(url=remote_dir, directory=clone_dir)

    with pytest.raises(DummyException):
        with EphemeralGitContext(git_manager=git_manager, commit_message="Test commit") as ctx:
            # Create a new file and add it to the index within the context
            with open(os.path.join(clone_dir, "test_context.txt"), "w") as f:
                f.write("Test")
            ctx.add_files(["test_context.txt"])
            # Raise an exception to trigger the failure handling
            raise DummyException("Test exception")
        
    commit_tree = git_manager.repo.head.commit.tree
    file_paths = [blob.path for blob in commit_tree.traverse() if blob.type == "blob"]
    assert "test_context.txt" not in file_paths


# Test that EpemeralGitContext correctly handles dry-run mode
def test_ephemeral_git_context_dry_run(git_repo, clone_dir):
    remote_dir, git_repo = git_repo
    git_manager = GitManager(url=remote_dir, directory=clone_dir)

    with EphemeralGitContext(
        git_manager=git_manager, commit_message="Test commit", dry_run=True
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

    with EphemeralGitContext(git_manager=git_manager, branch="outer", commit_message="Test commit") as ctx:
        
        assert git_manager.branch == "outer"

        # Create a new file and add it to the index within the context
        with open(os.path.join(clone_dir, "test_context_outer_1.txt"), "w") as f:
            f.write("Test")
        ctx.add_files(["test_context_outer_1.txt"])
        
        with EphemeralGitContext(git_manager=git_manager, branch="inner", commit_message="Nested Test commit") as ctx2:
            
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

# Test readonly ephemeral git context
def test_readonly_ephemeral_git_context(git_repo, clone_dir):
    remote_dir, git_repo = git_repo
    git_manager = GitManager(url=remote_dir, directory=clone_dir)

    with EphemeralGitContext(
        git_manager=git_manager, commit_message="Test commit", readonly=True
    ) as ctx:
        # Create a new file and add it to the index within the context
        with open(os.path.join(clone_dir, "test_context.txt"), "w") as f:
            f.write("Test")

        with pytest.raises(ValueError):
            ctx.add_files(["test_context.txt"])
    commit_tree = git_manager.repo.head.commit.tree
    file_paths = [blob.path for blob in commit_tree.traverse() if blob.type == "blob"]
    assert "test_context.txt" not in file_paths

# Test nested EphemeralGitContexts where the outer context is readonly
def test_nested_readonly_ephemeral_git_contexts(git_repo, clone_dir):
    remote_dir, git_repo = git_repo
    git_manager = GitManager(url=f"file://{remote_dir}", directory=clone_dir)

    with EphemeralGitContext(git_manager=git_manager, branch="outer", readonly=True, commit_message="Test commit") as ctx:
        
        assert git_manager.branch == "outer"

        # Create a new file and add it to the index within the context
        with open(os.path.join(clone_dir, "test_context_outer_1.txt"), "w") as f:
            f.write("Test")

        with pytest.raises(ValueError):
            ctx.add_files(["test_context_outer_1.txt"])
        
        with EphemeralGitContext(git_manager=git_manager, branch="inner", commit_message="Nested Test commit") as ctx2:
            
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

        with pytest.raises(ValueError):
            ctx.add_files(["test_context_outer_2.txt"])

    # back to default branch
    assert git_manager.branch == git_manager.default_branch

    # "outer" branch should not exist in remote repo

    assert not git_manager.remote_branch_reference("outer")

    # "inner" branch should exist and have the file

    git_repo.git.checkout("inner")

    assert "test_context_inner_1.txt" in os.listdir(remote_dir)