"""
Git manager utility that allows management of git repositories as well as remote
repositories on Github and Gitlab.
"""

import contextvars
import functools
import logging
import os
import shutil
import tempfile
import urllib
import uuid
from typing import Callable, Union

import git
import munge
import pydantic
from git import GitCommandError
from ogr.abstract import MergeCommitStatus, PRStatus
from ogr.services.github import GithubService
from ogr.services.gitlab import GitlabService

__all__ = [
    "GitManager",
    "EphemeralGitContext",
    "MergeNotPossible",
    "ephemeral_git_context",
    "ephemeral_git_context_state",
]

# A context variable to hold the GitManager instance
ephemeral_git_context_state = contextvars.ContextVar("ephemeral_git_context_state")
current_ephemeral_git_context = contextvars.ContextVar("current_ephemeral_git_context")


def ephemeral_git_context(**init_kwargs):
    """
    Decorator for the EphemeralGitContext class.
    This decorator allows the use of EphemeralGitContext as a decorator itself.
    """

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            with EphemeralGitContext(**init_kwargs):
                return func(*args, **kwargs)

        return wrapper

    return decorator


class MergeNotPossible(OSError):
    """
    Raised when merging is not possible
    """

    pass


class RepositoryConfig(pydantic.BaseModel):

    """
    Repository config model
    """

    gitlab_url: str = pydantic.Field(default_factory=lambda: os.getenv("GITLAB_URL"))
    gitlab_token: str = pydantic.Field(
        default_factory=lambda: os.getenv("GITLAB_TOKEN")
    )
    github_token: str = pydantic.Field(
        default_factory=lambda: os.getenv("GITHUB_TOKEN")
    )


class Services:
    gitlab: GitlabService = None
    github: GithubService = None


class GitManager:

    """
    Git manager utility that allows management of git repositories as well as remote repositories on Github and Gitlab.

    **Arguments**

    - url: The url of the repository
    - directory: The directory to clone the repository to
    - default_branch: The default branch to use
    - default_service: The default service to use (github or gitlab)
    - log: The logger to use
    - repository_config_filename: The name of the repository config file to look for
        within the repository once it's checked out.
    - allow_unsafe: Whether to allow unsafe operations such as hard resets
    - submodules: Whether to initialize submodules

    **Attributes**

    - url: The url of the repository
    - directory: The directory to clone the repository to
    - default_branch: The default branch to use
    - origin: The origin remote
    - index: The current index
    - repo: The current repository
    - default_service: The default service to use (github or gitlab)
    - services: The services available for this repository
    - log: The logger to use
    - repository_config_filename: The name of the repository config file to look for
        within the repository once it's checked out.
    - repository_config: The repository config
    - allow_unsafe: Whether to allow unsafe operations such as hard resets
    - submodules: Whether to initialize submodules

    **Properties**

    - service: The default service if set, otherwise will return the only service
    - gitlab: The gitlab service
    - github: The github service
    - is_clean: Returns True if the repository is clean, False otherwise
    - is_dirty: Returns True if the repository is dirty, False otherwise
    - current_commit: Returns the current commit
    - branch: The active branch

    """

    def __init__(
        self,
        url: Union[str, None],
        directory: str,
        default_branch: str = "main",
        default_service: str = None,
        log: object = None,
        repository_config_filename="config",
        allow_unsafe: bool = True,
        submodules: bool = True,
        repository_config: RepositoryConfig = None,
    ):
        self.url = url
        self.directory = directory
        self.default_branch = default_branch
        self.origin = None
        self.index = None
        self.repo = None
        self.default_service = default_service
        self.allow_unsafe = allow_unsafe
        self.submodules = submodules

        self.services = Services()

        self.log = log if log else logging.getLogger(__name__)

        self.repository_config_filename = repository_config_filename
        self.repository_config = (
            repository_config if repository_config else RepositoryConfig()
        )

        self.init_repository()

    @property
    def service(self):
        """
        Returns the default service if set, otherwise will return the only service
        """

        if self.default_service:
            return getattr(self.services, self.default_service)

        if self.services.github and self.services.gitlab:
            raise ValueError(
                "Multiple services available, please specify one as default via default_service"
            )

        return self.services.github if self.services.github else self.services.gitlab

    @property
    def branch(self):
        """
        Returns the current branch
        """
        return self.repo.active_branch.name

    @property
    def gitlab(self):
        return self.services.gitlab

    @property
    def github(self):
        return self.services.github

    @property
    def is_clean(self):
        """
        Returns True if the repository is clean, False otherwise
        """
        return not self.repo.is_dirty()

    @property
    def is_dirty(self):
        """
        Returns True if the repository is dirty, False otherwise
        """
        return self.repo.is_dirty()

    @property
    def current_commit(self):
        """
        Returns the current commit
        """
        return self.repo.head.commit.hexsha

    def get_hash(self, **kwargs):
        """
        Returns the current commit hash
        pass short=True for short
        """
        return self.repo.git.rev_parse("HEAD", **kwargs)

    def init_repository(self):
        """
        Clones the repository if it does not exist
        """

        # ensure directory exists
        if not os.path.exists(self.directory):
            os.makedirs(self.directory)

        # init services first to setup auth
        self.init_services(self.repository_config)

        try:
            self.repo = git.Repo(self.directory)

            # if url is not set we can get a list of remotes
            # and take the first one as origin

            if not self.url and self.repo.remotes:
                self.url = self.repo.remotes[0].url
            elif not self.url:
                # TODO: do we want a flag here? There might be use cases where
                # we want to operate on a local-only repository
                raise ValueError("No url specified and the repository has no remotes")

        except git.exc.InvalidGitRepositoryError:
            # if url is not specified now, we cannot clone
            # so we raise

            if not self.url:
                raise ValueError(
                    "No url specified and specified directory is not a git repository"
                )

            env = os.environ.copy()
            self.log.debug(f"Cloning repository from {self.url}: {self.directory}")
            self.repo = git.Repo.clone_from(
                self.url,
                self.directory,
                branch=self.default_branch,
                progress=None,
                env=env,
            )
            self.init_submodules()

        self.index = self.repo.index

        self.set_origin()

        self.log.debug(
            f"Repository initialized at {self.directory} from {self.url} - origin set to {self.origin.name if self.origin else None}"
        )

        self.load_repository_config(self.repository_config_filename)

    def init_submodules(self):
        """
        Initializes and updates existing submodules
        """

        if not self.submodules:
            return

        self.log.debug("Initializing submodules")
        self.repo.git.submodule("init")
        self.repo.git.submodule("update")

    def update_submodules(self):
        if not self.submodules:
            return

        self.log.debug("Updating submodules")
        self.repo.git.submodule("update")

    def load_repository_config(self, config_filename: str):
        """
        Will look for self.repository_config_filename in the repository and load it
        """

        try:
            config_dict = munge.load_datafile(
                config_filename,
                search_path=self.directory,
            )
        except OSError:
            # no config file found
            config_dict = None

        if config_dict:
            self.repository_config = RepositoryConfig(**config_dict)
            self.log.debug(
                f"Loaded repository config from {config_filename} - {self.repository_config}"
            )
        elif not self.repository_config:
            self.log.warning(
                f"Could not find repository config file: `{config_filename}`"
            )

    def set_origin(self):
        """
        Sets the origin repository object, which will hold a name
        and url.
        """

        for remote in self.repo.remotes:
            if remote.url == self.url:
                self.origin = remote
                break

        if not self.origin:
            remote = next(iter(self.repo.remotes or []), None)
            raise ValueError(
                f"Could not find origin for repository {self.url} (first is {remote.url})"
            )

    def init_services(self, config: RepositoryConfig):
        """
        Initializes the services for the repository
        """
        # why do we have 2 configs?
        if config.gitlab_url != self.repository_config.gitlab_url:
            raise ValueError("config passed is not repo config")

        # argparse seems to be interfering with the GITLAB_URL var
        gitlab_url = os.getenv("GITLAB_URL") or config.gitlab_url
        gitlab_token = os.getenv("GITLAB_TOKEN") or config.gitlab_token
        # update repo config
        self.repository_config.gitlab_token = gitlab_token
        self.repository_config.gitlab_url = gitlab_url

        if gitlab_url and not self.services.gitlab:
            # instance_url wants only the scheme and host
            # so we need to parse it out of the full url
            instance_url = (
                urllib.parse.urlparse(gitlab_url).scheme
                + "://"
                + urllib.parse.urlparse(gitlab_url).netloc
            )

            self.services.gitlab = GitlabService(
                token=config.gitlab_token,
                instance_url=instance_url,
            )
        if config.github_token and not self.services.github:
            self.services.github = GithubService(token=config.github_token)

        if self.default_service and not getattr(self.services, self.default_service):
            raise ValueError(
                f"Could not initialize {self.default_service}, make sure the url and token are correct"
            )

    def service_project(self, service: str = None):
        """
        Returns the service project for the service
        """
        _service = getattr(self.services, service) if service else self.service
        return _service.get_project_from_url(self.url)

    def service_file_url(self, file_path: str, service: str = None):
        """
        Returns the url for a file on the service

        Will account for url, project name and branch
        """

        _service = getattr(self.services, service) if service else self.service
        _project = self.service_project(service)

        return f"{_service.instance_url}/{_project.full_repo_name}/blob/{self.branch}/{file_path}"

    def fetch(self, prune: bool = True):
        """
        Fetches the origin repository
        """

        fetch_args = ["--all"]
        if prune:
            fetch_args.append("--prune")

        self.log.info(f"Fetching from {self.origin.name}")
        fetch_info = self.repo.git.fetch(*fetch_args)
        self.log.debug(f"Fetch info: {fetch_info}")
        return fetch_info

    def pull(self):
        """
        Pulls the origin repository
        """
        self.log.info(f"Pulling from {self.origin.name}")
        fetch_info = self.repo.git.pull(self.origin.name, self.branch)
        self.log.debug(f"Fetch info: {fetch_info}")
        return fetch_info

    def push(self, force: bool = False):
        """
        Push the current branch to origin
        """
        self.log.info(f"Pushing {self.repo.head.ref.name} to {self.origin.name}")
        self.repo.git.push(self.origin.name, self.repo.head.ref.name, force=force)

    def sync(self):
        """
        Fetches the remote repository and will merge with a fast-forward
        strategy if possible and then push back to origin.
        """

        self.fetch()
        if self.require_remote_branch() is True:
            # branch did not exist remotely yet
            self.push()

            # fetch again to make sure we have the latest refs
            self.fetch()
            return

        # fast forward merge from origin
        self.log.info(f"Merging {self.origin.name}/{self.branch} into {self.branch}")

        try:
            self.repo.git.merge(f"{self.origin.name}/{self.branch}")
        except git.exc.GitCommandError as exc:
            if "not possible to fast-forward, aborting" in exc.stderr.lower():
                raise MergeNotPossible(
                    f"Could not fast-forward merge {self.origin.name}/{self.branch} into {self.branch}"
                )
            else:
                raise

        # push
        self.push()

    def require_remote_branch(self) -> bool:
        """
        Makes sure that the branch exists at origin

        Will return True if the branch did not exist at origin and was pushed, False otherwise
        """
        local_branch = self.repo.heads[self.branch]
        if not self.remote_branch_reference(self.branch):
            # branch does not exist at origin, push it
            self.log.info(f"Branch {self.branch} does not exist at origin, pushing it")
            self.push()
            # set tracking branch
            local_branch.set_tracking_branch(self.origin.refs[self.branch])
            return True

        if not local_branch.tracking_branch():
            # set tracking branch
            local_branch.set_tracking_branch(self.origin.refs[self.branch])

        return False

    def set_tracking_branch(self, branch_name: str):
        """
        Sets the tracking branch for the current branch to the given branch name

        Args:
            branch_name (str): The name of the branch to set as tracking branch
        """
        if self.remote_branch_reference(branch_name):
            self.repo.heads[self.branch].set_tracking_branch(
                self.origin.refs[branch_name]
            )

    def create_branch(self, branch_name: str):
        """
        Creates a local branch off the current branch

        Args:
            branch_name (str): The name of the branch to create
        """

        try:
            new_branch = self.repo.create_head(branch_name)
            self.repo.head.reference = new_branch
            self.index = self.repo.index
        except git.exc.GitCommandError:
            self.log.warning(f"Could not create branch {branch_name}")

    def branch_exists(self, branch_name: str):
        """
        Returns True if the branch exists locally, False otherwise

        Args:
            branch_name (str): The name of the branch to check
        """

        try:
            self.repo.heads[branch_name]
            return True
        except IndexError:
            return False

    def switch_branch(self, branch_name: str, create: bool = True):
        """
        Switches to the given branch

        Args:
            branch_name (str): The name of the branch to switch to
            create (bool): Whether to create the branch if it does not exist
        """

        self.log.info(f"Switching to branch {branch_name}")
        # fetch to make sure we have the latest refs
        self.fetch()

        try:
            branch_exists_locally = self.repo.heads[branch_name]
        except IndexError:
            branch_exists_locally = False

        branch_exists_remotely = self.remote_branch_reference(branch_name)

        # if branch exists remote but not locally, create from remote
        if branch_exists_remotely and not branch_exists_locally:
            self.fetch()
            self.repo.git.checkout(branch_name)
            self.index = self.repo.index
            return

        if not branch_exists_locally and not create:
            raise ValueError(
                f"Branch {branch_name} does not exist locally and create=False"
            )

        if not branch_exists_locally:
            self.create_branch(branch_name)
            return

        self.repo.heads[branch_name].checkout()
        self.index = self.repo.index

    def reset(self, hard: bool = False, from_origin: bool = True):
        """
        Reset the current branch.

        **Arguments**

        - hard: A boolean indicating whether to perform a hard reset from origin/branch
        """
        if self.allow_unsafe:
            self.log.info(f"Resetting {self.branch}{' hard' if hard else ''}")

            if (
                from_origin
                and self.origin
                and self.remote_branch_reference(self.branch)
            ):
                if hard:
                    self.repo.git.reset("--hard", f"{self.origin}/{self.branch}")
                else:
                    self.repo.git.reset(f"{self.origin}/{self.branch}")
            else:
                if hard:
                    self.repo.git.reset("--hard")
                else:
                    self.repo.git.reset()

    def add(self, file_paths: list[str]):
        """
        Add files to the index

        **Arguments**

        - file_paths: A list of file paths to add to the index
        """

        if file_paths:
            self.log.info(f"Adding files to index: {file_paths}")
        else:
            self.log.info("No files to add to index")
            return

        self.index.add(file_paths)

    def commit(self, message: str):
        """
        Commit the current index

        **Arguments**

        - message: The commit message
        """

        self.log.info(f"Committing index with message: {message}")

        self.index.commit(message)

    def changed_files(self, file_paths: list[str] = None):
        """
        Returns a list of changed files

        **Arguments**

        - file_paths: A list of file paths to check for changes. If not provided, will check all files.
        """

        # identify new files in file paths that dont exist in index

        if file_paths:
            new_files = [
                path for path in file_paths if path in self.repo.untracked_files
            ]
            changed_files = [
                item.a_path
                for item in self.index.diff(None)
                if item.a_path in file_paths
            ]
        else:
            new_files = []
            changed_files = [item.a_path for item in self.index.diff(None)]

        return list(set(changed_files + new_files))

    def remote_branch_reference(self, branch_name: str):
        """
        Return the ref of remote branch whose name matches branch_name, or None if one does not exist.

        **Arguments**

        - branch_name: The name of the branch to find the remote ref for

        **Returns**

        The ref of the remote branch if it exists, None otherwise
        """

        if not self.origin:
            # no remote
            return None

        for ref in self.origin.refs:
            if ref.name.split("/")[-1] == branch_name:
                # always the same as active_branch?
                self.log.debug(f"found remote branch {ref}")
                return ref
        return None

    def archive_branch(self, new_name: str, branch: str = None):
        """
        Rename the remote branch and delete the local

        This renames remote and doesn't check out to local

        **Arguments**

        - branch_name: The new name of the branch
        """

        if not branch:
            branch = self.branch

        if branch == self.default_branch:
            raise ValueError(f"Cannot rename default branch {self.default_branch}")

        if branch == self.branch:
            # cannot rename current branch
            self.switch_branch(self.default_branch)

        self.log.info(f"Renaming branch {self.branch} to {new_name}")

        # this doesn't rename remote
        # self.repo.heads[self.branch].rename(new_name)

        # Push the archive branch and delete the merge branch both locally and remotely
        repo = self.repo
        remote_name = self.origin.name

        # not sure if pushing the remote ref is actually working
        repo.git.push(remote_name, f"{remote_name}/{branch}:refs/heads/{new_name}")

        # if old remote branch is still there, delete it
        # this can depend on if the merge option to delete branch was checked
        if branch in repo.git.branch("-r").split():
            repo.git.push(remote_name, "--delete", branch)

        # delete local branch if it exists
        repo.delete_head(branch, force=True)

    def create_change_request(
        self,
        title: str,
        description: str = "",
        target_branch: str = None,
        source_branch: str = None,
    ):
        """
        Create new MR/PR in Service from the current branch into default_branch

        **Arguments**

        - title: The title of the merge request
        - description: The description of the merge request
        - target_branch: The target branch of the merge request. Defaults to default_branch
        - source_branch: The source branch of the merge request. Defaults to current branch

        **Returns**

        The created merge request
        """

        self.log.info(f"Creating merge request for branch {self.branch}")

        if not self.service:
            raise ValueError("No service configured")

        _project = self.service_project()

        if not target_branch:
            target_branch = self.default_branch

        if not source_branch:
            source_branch = self.branch

        # check if MR/PR already exists

        mr = self.get_open_change_request(target_branch, source_branch)
        if mr:
            if mr.title == title and mr.description == description:
                self.log.info(
                    f"Merge request already exists for branch {self.branch} with same title and description, skipping"
                )
                return mr

            self.log.info(
                f"Merge request already exists for branch {self.branch}, updating it"
            )
            return mr.update_info(title=title, description=description)

        return _project.create_pr(
            title=title,
            body=description,
            target_branch=target_branch,
            source_branch=source_branch,
        )

    def list_change_requests(self):
        """
        List all open change requests
        """

        if not self.service:
            raise ValueError("No service configured")

        _project = self.service_project()

        return _project.get_pr_list()

    def get_open_change_request(self, target_branch: str, source_branch: str):
        """
        Checks if the merge request exists in an open state
        """

        if not self.service:
            raise ValueError("No service configured")

        _project = self.service_project()

        for mr in _project.get_pr_list():
            if mr.status != PRStatus.open:
                continue

            if mr.source_branch == source_branch and mr.target_branch == target_branch:
                return mr

        return None

    def rename_change_request(self, target_branch: str, source_branch: str, title: str):
        """
        Rename an existing change request

        **Arguments**

        - source_branch (`str`): branch name
        - target_branch (`str`): branch name
        - title (`str`): new title
        """

        change_request = self.get_open_change_request(target_branch, source_branch)

        if not change_request:
            raise ValueError(
                f"Could not find change request for branch {source_branch}"
            )

        change_request.update_info(
            title=title, description=change_request.description or ""
        )

    def create_merge_request(self, title: str):
        """
        Alias for create_change_request
        """

        return self.create_change_request(title)

    def create_pull_request(self, title: str):
        """
        Alias for create_change_request
        """

        return self.create_change_request(title)

    def merge_change_request(
        self, target_branch: str, source_branch: str, squash: bool = True
    ):
        """
        Merge the change request

        **Arguments**

        - target_branch: The target branch of the merge request
        - source_branch: The source branch of the merge request
        - squash: Whether to squash the merge request

        **Token Permissions**

        GitLab:
        - Role: >= Maintainer
        - api
        - read_api
        - read_repository
        - write_repository


        GitHub:
        - Contents: read and write
        - Pull requests: read and write
        - Metadata: read
        """
        self.log.info(f"Merging change request for branch {source_branch} {squash}")

        if not self.service:
            raise ValueError("No service configured")

        _project = self.service_project()

        mr = self.get_open_change_request(target_branch, source_branch)

        if not mr:
            raise ValueError(f"No open merge request found for branch {source_branch}")

        if mr.merge_commit_status != MergeCommitStatus.can_be_merged:
            raise ValueError(
                f"Merge request for branch {source_branch} cannot be merged"
            )

        self.log.info(f"Merging change request for branch {source_branch}")

        if self.service == self.services.github:
            return mr._raw_pr.merge(merge_method="squash" if squash else "merge")
        else:
            return mr._raw_pr.merge(squash=squash)


class ChangeRequest(pydantic.BaseModel):
    title: str
    description: str = ""
    target_branch: str = None
    source_branch: str = None


class EphemeralGitContextState(pydantic.BaseModel):
    git_manager: GitManager
    branch: Union[str, None] = None
    commit_message: str = "Commit changes"
    readonly: bool = False
    inactive: bool = False
    force_push: bool = False

    context_id: str = pydantic.Field(default_factory=lambda: str(uuid.uuid4())[:8])

    change_request: Union[ChangeRequest, None] = None

    validate_clean: Union[Callable, None] = None

    files_to_add: list[str] = pydantic.Field(default_factory=list)

    stash_pushed: bool = False
    stash_popped: bool = False
    original_branch: str = None

    model_config = pydantic.ConfigDict(arbitrary_types_allowed=True)


class EphemeralGitContext:
    """
    A context manager that sets up the repository on open, fetches and pulls.
    At the end commits all changes and attempts to push.
    Supports setting a specific branch.
    Any git failures during the context should result in the repository being hard reset.
    """

    def __init__(self, **kwargs):
        """
        Initializes the context manager with an optional GitManager instance and an optional branch name.

        **Arguments**

        - git_manager (GitManager, optional): The GitManager instance to use. If not provided, will try to get from context.
        - branch (str, optional): The branch to use. Defaults to None.
        - commit_message (str, optional): The commit message to use. Defaults to 'Commit changes'.
        - change_request (ChangeRequest, optional): A ChangeRequest instance to use. Defaults to None.
        - validate_clean (Callable, optional): A callable that will be called with the GitManager instance as argument.
        - readonly (bool, optional): Whether to only allow reading from the repository. Defaults to False.
        - inactive (bool, optional): Whether to deactivate the context. Defaults to False.
        - force_push (bool, optional): Whether to force push. Defaults to False.
        """

        # these should not be set directly
        kwargs.pop("stash_pushed", None)
        kwargs.pop("stash_popped", None)
        kwargs.pop("original_branch", None)

        if not kwargs:
            # can no longer open empty contexts
            raise ValueError("Empty context, needs at least `git_manager` set")

        self.state_token = None
        self.state = EphemeralGitContextState(**kwargs)

    def __enter__(self):
        """
        Sets up the repository, fetches and pulls.
        """

        self.context_token = current_ephemeral_git_context.set(self)
        self.state_token = ephemeral_git_context_state.set(self.state)

        if not self.active:
            # context is deactivated
            return self

        # reset the current branch
        self.stash_current_context()
        self.git_manager.fetch()
        if self.git_manager.is_dirty:
            self.reset()

        # track what branch we were on before switching
        self.state.original_branch = self.git_manager.branch

        if self.state.branch and self.state.branch != self.git_manager.branch:
            # switch to branch

            # delete local branch if it exists
            if self.git_manager.branch_exists(self.state.branch):
                # dont delete default branch
                if self.state.branch != self.git_manager.default_branch:
                    self.git_manager.log.info(
                        f"Deleting local branch {self.state.branch}"
                    )
                    self.git_manager.repo.git.branch("-D", self.state.branch)

            self.git_manager.switch_branch(self.state.branch)
            if self.git_manager.is_dirty:
                self.reset()

        # if branch exists remotely
        if self.git_manager.remote_branch_reference(self.git_manager.branch):
            # set tracking branch
            self.git_manager.set_tracking_branch(self.state.branch)
            # pull
            self.git_manager.pull()
            # update submodules
            self.git_manager.update_submodules()

        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """
        Commits all changes and attempts to push.
        In case of any git failures, hard resets the repository.
        """

        if not self.active:
            # context is deactivated
            return False

        try:
            current_ephemeral_git_context.reset(self.context_token)

            if self.can_write:
                # context is allowed to commit and push, so we can finalize
                self.finalize(exc_type, exc_val, exc_tb)
            elif self.active:
                # context is only allowed to read, but active, so we log
                # what would have been committed / pushed
                for changed_file in self.git_manager.changed_files(
                    self.state.files_to_add
                ):
                    self.git_manager.log.info(
                        f"[readonly] would commit changes: {changed_file}"
                    )

            # reset the context state
            self.log.info(
                f"Resetting context state {self.state.original_branch}, {self.git_manager.branch}"
            )
            if self.state.original_branch != self.git_manager.branch:
                # return to previous branch
                if self.git_manager.is_dirty:
                    self.reset(from_origin=False)
                self.git_manager.switch_branch(self.state.original_branch)
                if self.git_manager.is_dirty:
                    self.reset(from_origin=False)

        finally:
            # always reset the context state
            ephemeral_git_context_state.reset(self.state_token)

            # always pop stash
            if self.state.stash_pushed:
                # can_read implied
                self.log.info(f"Popping stash")
                if self.git_manager.is_dirty:
                    self.reset(from_origin=False)
                try:
                    self.git_manager.repo.git.stash("pop")
                except GitCommandError as e:
                    # ignore "No stash entries found.", raise others
                    # TODO: how does this even happen?
                    if "No stash entries found." not in e.stderr:
                        raise

                self.state.stash_popped = True

        return False  # re-raise any exception

    @property
    def git_manager(self):
        return self.state.git_manager

    @property
    def can_read(self):
        return self.active

    @property
    def can_write(self):
        return not self.state.readonly and self.active

    @property
    def active(self):
        return not self.state.inactive

    @property
    def log(self):
        return self.git_manager.log

    def reset(self, from_origin: bool = True):
        """
        Resets the repository
        """
        self.git_manager.log.info(f"Resetting repository, {self.can_read}")
        if not self.can_read:
            return

        self.git_manager.reset(hard=True, from_origin=from_origin)

    def stash_current_context(self):
        # stash current repo state if we are moving into a nested
        # context

        if not self.git_manager.is_dirty:
            # nothing to stash

            return

        # stash

        self.git_manager.repo.git.stash("push")
        self.state.stash_pushed = True
        self.log.info(f"Stashed current context")

    def finalize(self, exc_type, exc_val, exc_tb):
        if not self.can_write:
            # we are not allowed to commit/push so we can just return
            return

        if self.state.validate_clean and self.state.validate_clean(self.git_manager):
            # we have a custom validation function and it returned True, indicating
            # that the changes that are there can be ignored, so we can just return
            return

        if not self.git_manager.changed_files(self.state.files_to_add):
            # nothing to commit/push so we can just return
            return

        if exc_type is None:
            try:
                # Commit all changes
                self.git_manager.add(
                    self.git_manager.changed_files(self.state.files_to_add)
                )
                self.git_manager.commit(self.state.commit_message)
                # Attempt to push
                self.git_manager.push(force=self.state.force_push)

                self.create_change_request()

            except GitCommandError:
                # Hard reset the repository in case of git failures
                self.reset()
                raise
        else:
            # Hard reset the repository in case of other exceptions
            self.reset()
            raise exc_val

    def create_change_request(self):
        """
        Create a change request if one is set in the state
        """

        if not self.active:
            return

        if not self.state.change_request:
            return

        if not self.can_write:
            self.log.debug(
                f"Cannot create change request in readonly ephemeral git context"
            )
            return

        # are there any differences between the current branch and the default branch?
        # to check this we diff the current branch against the default branch
        diff = self.git_manager.repo.git.diff(
            f"{self.git_manager.default_branch}..HEAD"
        )

        if not diff:
            # no differences, nothing to do
            return

        # make sure current branch exists remotely
        self.git_manager.require_remote_branch()

        # create change request
        self.state.change_request.source_branch = self.git_manager.branch
        self.state.change_request.target_branch = self.git_manager.default_branch
        self.git_manager.create_change_request(**self.state.change_request.model_dump())

    def add_files(self, file_paths: list[str]):
        """
        Add files to the repository.

        Args:
            file_paths (list[str]): A list of file paths to add to the repository.
        """

        if not self.active:
            return

        self.state.files_to_add.extend(file_paths)


class TemporaryGitContext:
    """
    Will re-clone the repository into a temporary directory and run the context manager in that directory.

    This is mostly useful when you want to ensure a clean state for read operations without
    affecting the original repository via a hard reset or deleting of local branchesoh. (as EphmeralGitContext does)
    """

    def __init__(self, git_manager: GitManager, **kwargs):
        """
        Initializes the context manager with a GitManager instance.

        **Arguments**

        - git_manager (GitManager): The GitManager instance to use.
        """

        self._initial_git_manager = git_manager

    def __enter__(self):
        self.git_manager = GitManager(
            self._initial_git_manager.url,
            tempfile.mkdtemp(),
            default_branch=self._initial_git_manager.default_branch,
            default_service=self._initial_git_manager.default_service,
            log=self._initial_git_manager.log,
            repository_config_filename=self._initial_git_manager.repository_config_filename,
            allow_unsafe=self._initial_git_manager.allow_unsafe,
            submodules=self._initial_git_manager.submodules,
            repository_config=self._initial_git_manager.repository_config,
        )

        self.git_manager.log.debug(
            f"Temporary repository cloned to {self.git_manager.directory}"
        )

        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.git_manager.log.debug(
            f"Removing temporary repository {self.git_manager.directory}"
        )
        shutil.rmtree(self.git_manager.directory)
        return False
