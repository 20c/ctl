import os
import tempfile
from unittest.mock import MagicMock, patch
from ogr.abstract import PRStatus
import pytest
import yaml
from git import Repo

from ctl.util.git import (
    EphemeralGitContext, 
    GitManager, 
    ChangeRequest,
    current_ephemeral_git_context,
    ephemeral_git_context_state,
)

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
        main_repo.index.add(["README.md"])
        main_repo.index.commit("Initial commit")

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
    git_repo.git.commit("-m", "Test commit")#
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

    # Check that the GithubService and GitlabService were called with the correct arguments
    mock_github_service.assert_called_once_with(
        token="test_token"
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
    mock_service_project.assert_called()
    mock_project.create_pr.assert_called_once_with(
        title=title,
        body="",
        target_branch=git_manager.default_branch,
        source_branch=git_manager.branch,
    )



@pytest.mark.parametrize("source_branch, target_branch, status, expected",[
    ("test", "main", PRStatus.open, True),
    ("test", "main", PRStatus.closed, False),
    ("test", "main", PRStatus.merged, False),
    ("test", "test-2", PRStatus.open, False),
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
        mock_merge_request.update_info.assert_called_once_with(title=title, description="")
    else:
        mock_merge_request.update_info.assert_not_called()

# Test that EphemeralGitContext correctly sets up and tears down the repository
def test_ephemeral_git_context_success(git_repo, clone_dir):
    remote_dir, git_repo = git_repo
    git_manager = GitManager(url=f"file://{remote_dir}", directory=clone_dir)

    # outside of context, currently in branch `main`
    
    assert git_manager.branch == git_manager.default_branch

    with EphemeralGitContext(git_manager=git_manager, branch="test", commit_message="Test commit") as ctx:
        
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

    with EphemeralGitContext(git_manager=git_manager, branch="test", force_push=True, commit_message="Test commit") as ctx:

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

    # outside of context, currently in branch `main`

    assert git_manager.branch == git_manager.default_branch

    with EphemeralGitContext(git_manager=git_manager, branch="test", commit_message="Test commit", change_request=change_request) as ctx:

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
        with open(os.path.join(clone_dir, "README.md"), "r") as f:
            assert f.read() == "Test"

    commit_tree = git_manager.repo.head.commit.tree
    file_paths = [blob.path for blob in commit_tree.traverse() if blob.type == "blob"]
    assert "test_context.txt" not in file_paths

# Test nested EphemeralGitContexts where the outer context is inactive
def test_nested_inactive_ephemeral_git_contexts(git_repo, clone_dir):
    remote_dir, git_repo = git_repo
    git_manager = GitManager(url=f"file://{remote_dir}", directory=clone_dir)

    with EphemeralGitContext(git_manager=git_manager, branch="outer", inactive=True, commit_message="Test commit") as ctx:
        
        # context is inactive, so branch should still be default
        
        assert git_manager.branch == git_manager.default_branch

        # Create a new file and add it to the index within the context
        with open(os.path.join(clone_dir, "test_context_outer_1.txt"), "w") as f:
            f.write("Test")

        ctx.add_files(["test_context_outer_1.txt"])

        # context is inactive, so files should not be added

        assert not ctx.state.files_to_add
        
        with EphemeralGitContext(git_manager=git_manager, branch="inner", commit_message="Nested Test commit") as ctx2:

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

    with EphemeralGitContext(git_manager=git_manager, branch="outer", readonly=True, commit_message="Test commit") as ctx:
        
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
        
        with EphemeralGitContext(git_manager=git_manager, branch="inner", commit_message="Nested Test commit") as ctx2:

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

    with EphemeralGitContext(git_manager=git_manager, branch="outer", commit_message="Test commit", readonly=True) as ctx:

        # check that test_context_outer_1.txt are not tracked
        # since they were never committed but still exist in the working tree

        assert "test_context_outer_1.txt" in git_manager.repo.untracked_files
        assert "test_context_outer_2.txt" in git_manager.repo.untracked_files

        # check that README.md has been reset

        assert open(os.path.join(clone_dir, "README.md"), "r").read() == ""





# Test that ephemeral context deletes local branch before switching to it
def test_ephemeral_git_context_delete_local_branch(git_repo, clone_dir):

    remote_dir, git_repo = git_repo

    # needs to allow_unsafe=False so git reset doesnt reset our branch
    # branch should be reset through deletion
    git_manager = GitManager(url=f"file://{remote_dir}", directory=clone_dir, allow_unsafe=False)

    git_manager.switch_branch("test", create=True)

    orig_readme_content = open(os.path.join(clone_dir, "README.md"), "r").read()

    # change README.md

    with open(os.path.join(clone_dir, "README.md"), "w") as f:
        f.write("Testing")
    git_manager.repo.index.add(["README.md"])
    git_manager.repo.index.commit("Test commit")

    git_manager.switch_branch("main")
   
    with EphemeralGitContext(git_manager=git_manager, branch="test", commit_message="Test commit") as ctx:

        # check that README.md has been reset

        assert open(os.path.join(clone_dir, "README.md"), "r").read() == orig_readme_content

# Test that ephemeral context deletes local branch before switching to it
def test_ephemeral_git_context_delete_local_branch_inactive(git_repo, clone_dir):

    remote_dir, git_repo = git_repo

    # needs to allow_unsafe=False so git reset doesnt reset our branch
    # branch should be reset through deletion
    git_manager = GitManager(url=f"file://{remote_dir}", directory=clone_dir, allow_unsafe=False)

    git_manager.switch_branch("test", create=True)

    orig_readme_content = open(os.path.join(clone_dir, "README.md"), "r").read()

    # change README.md

    with open(os.path.join(clone_dir, "README.md"), "w") as f:
        f.write("Testing")
    git_manager.repo.index.add(["README.md"])
    git_manager.repo.index.commit("Test commit")

    git_manager.switch_branch("main")
   
    with EphemeralGitContext(git_manager=git_manager, branch="test", commit_message="Test commit", inactive=True) as ctx:

        # check that README.md has NOT been reset

        assert open(os.path.join(clone_dir, "README.md"), "r").read() == orig_readme_content


# Test that ephemeral context deletes local branch before switching to it
def test_ephemeral_git_context_delete_local_branch_remake_from_remote(git_repo, clone_dir):

    remote_dir, git_repo = git_repo

    # create remote "test" branch and change README.md and commit

    git_repo.git.checkout("main")
    git_repo.git.checkout("-b", "test")
    with open(os.path.join(remote_dir, "README.md"), "w") as f:
        f.write("Testing initial")
    git_repo.git.commit("-am", "Test commit")
    git_repo.git.checkout("main")

    assert open(os.path.join(remote_dir, "README.md"), "r").read() == ""

    git_repo.git.checkout("test")

    assert open(os.path.join(remote_dir, "README.md"), "r").read() == "Testing initial"

    git_repo.git.checkout("main")

    # needs to allow_unsafe=False so git reset doesnt reset our branch
    # branch should be reset through deletion
    git_manager = GitManager(url=f"file://{remote_dir}", directory=clone_dir, allow_unsafe=False)

    git_manager.switch_branch("test")
    #git_manager.pull()
    
    with open(os.path.join(clone_dir, "README.md"), "r") as f:
        orig_readme_content = f.read()

    assert orig_readme_content == "Testing initial"

    # change README.md

    with open(os.path.join(clone_dir, "README.md"), "w") as f:
        f.write("Testing new")
    git_manager.repo.index.add(["README.md"])
    git_manager.repo.index.commit("Test commit")

    git_manager.switch_branch("main")
    assert open(os.path.join(clone_dir, "README.md"), "r").read() == ""
   
    with EphemeralGitContext(git_manager=git_manager, branch="test", commit_message="Test commit") as ctx:

        # check that README.md has been reset

        assert open(os.path.join(clone_dir, "README.md"), "r").read() == orig_readme_content


    with EphemeralGitContext(git_manager=git_manager, branch="main", commit_message="Test commit") as ctx:

        # check that README.md has been reset

        assert open(os.path.join(clone_dir, "README.md"), "r").read() == ""


# Test current_ephemeral_git_context holds the current ctx
def test_context_vars(git_repo, clone_dir):
    remote_dir, git_repo = git_repo
    git_manager = GitManager(url=remote_dir, directory=clone_dir)
    with EphemeralGitContext(git_manager=git_manager, branch="test", commit_message="Test commit") as ctx:
        assert current_ephemeral_git_context.get() == ctx
        assert ephemeral_git_context_state.get() == ctx.state
        with EphemeralGitContext(git_manager=git_manager, branch="inner", commit_message="Nested Test commit") as ctx2:
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

    with EphemeralGitContext(git_manager=git_manager, branch="outer", commit_message="Test commit") as ctx:
        
        # assert stashes
        assert ctx.state.stash_pushed
        assert git_manager.repo.git.stash("list")

        assert git_manager.branch == "outer"

        # Create a new file and add it to the index within the context
        with open(os.path.join(clone_dir, "README.md"), "w") as f:
            f.write("Test")

        assert git_manager.is_dirty
        
        with EphemeralGitContext(git_manager=git_manager, branch="inner", commit_message="Nested Test commit") as ctx2:
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
    with open(os.path.join(clone_dir, "README.md"), "r") as f:
        assert f.read() == "Testing initial"

    # assert all stashes have been popped

    assert not git_manager.repo.git.stash("list")
