"""
Git manager utility that allows management of git repositories as well as remote
repositories on Github and Gitlab.
"""

import contextvars
import logging
import os
import functools
import uuid
import git
import munge
import pydantic
import urllib
from typing import Callable
from git import GitCommandError
from ogr.services.github import GithubService
from ogr.services.gitlab import GitlabService

__all__ = [
    "GitManager",
    "EphemeralGitContext", 
    "MergeNotPossible", 
    "ephemeral_git_context", 
    "ephemeral_git_context_state"
]

# A context variable to hold the GitManager instance
ephemeral_git_context_state = contextvars.ContextVar("ephemeral_git_context_state")
current_ephemeral_git_context = contextvars.ContextVar("current_ephemeral_git_context")


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
    github_url: str = pydantic.Field(default_factory=lambda: os.getenv("GITHUB_URL"))

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
        url: str,
        directory: str,
        default_branch: str = "main",
        default_service: str = None,
        log: object = None,
        repository_config_filename="config",
        allow_unsafe: bool = False,
    ):
        self.url = url
        self.directory = directory
        self.default_branch = default_branch
        self.origin = None
        self.index = None
        self.repo = None
        self.default_service = default_service
        self.allow_unsafe = allow_unsafe

        self.services = Services()

        self.log = log if log else logging.getLogger(__name__)

        self.repository_config_filename = repository_config_filename
        self.repository_config = RepositoryConfig()

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

    def init_repository(self):
        """
        Clones the repository if it does not exist
        """

        # ensure directory exists
        if not os.path.exists(self.directory):
            os.makedirs(self.directory)

        try:
            self.repo = git.Repo(self.directory)
            self.switch_branch(self.default_branch)
        except git.exc.InvalidGitRepositoryError:
            self.repo = git.Repo.clone_from(
                self.url, self.directory, branch=self.default_branch, progress=None
            )

        self.index = self.repo.index

        self.set_origin()

        self.log.debug(
            f"Repository initialized at {self.directory} from {self.url} - origin set to {self.origin.name if self.origin else None}"
        )

        self.load_repository_config(self.repository_config_filename)

        self.init_services(self.repository_config)

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
        else:
            self.log.warning(f"Could not find repository config file: `{config_filename}`")

    def set_origin(self):
        """
        Sets the origin repository object, which will hold a name
        and url.
        """

        for remote in self.repo.remotes:
            if remote.url == self.url:
                self.origin = remote
                break

    def init_services(self, config: RepositoryConfig):
        """
        Initializes the services for the repository
        """
        if config.gitlab_url and not self.services.gitlab:
            
            # instance_url wants only the scheme and host
            # so we need to parse it out of the full url

            parsed_url = urllib.parse.urlparse(config.gitlab_url)
            base_url = f"{parsed_url.scheme}://{parsed_url.netloc}"
            self.services.gitlab = GitlabService(
                token=config.gitlab_token, instance_url=base_url
            )
        if config.github_url and not self.services.github:
            self.services.github = GithubService(
                token=config.github_token
            )

        if self.default_service and not getattr(self.services, self.default_service):
            raise ValueError(
                f"Could not initialize {self.default_service}, make sure the url and token are correct"
            )

    def service_project(self, service: str = None):
        """
        Returns the service project for the service
        """
        _service = getattr(self.services, service) if service else self.service

        if _service == self.services.gitlab:
            project_url = self.repository_config.gitlab_url
        elif _service == self.services.github:
            project_url = self.repository_config.github_url

        return _service.get_project_from_url(project_url)

    def service_file_url(self, file_path: str, service: str = None):
        """
        Returns the url for a file on the service

        Will account for url, project name and branch
        """

        _service = getattr(self.services, service) if service else self.service
        _project = self.service_project(service)

        return f"{_service.instance_url}/{_project.full_repo_name}/blob/{self.branch}/{file_path}"

    def fetch(self):
        """
        Fetches the origin repository
        """
        self.log.info(f"Fetching from {self.origin.name}")
        self.repo.git.fetch()

    def pull(self):
        """
        Pulls the origin repository
        """
        self.log.info(f"Pulling from {self.origin.name}")
        self.repo.git.pull()

    def push(self):
        """
        Push the current branch to origin
        """
        self.log.info(f"Pushing {self.repo.head.ref.name} to {self.origin.name}")
        self.repo.git.push(self.origin.name, self.repo.head.ref.name)

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
        if not self.remote_branch_reference(self.branch):
            # branch does not exist at origin, push it
            self.log.info(f"Branch {self.branch} does not exist at origin, pushing it")
            self.push()
            return True
        return False

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

    def switch_branch(self, branch_name: str, create: bool = True):
        """
        Switches to the given branch

        Args:
            branch_name (str): The name of the branch to switch to
            create (bool): Whether to create the branch if it does not exist
        """
        try:
            branch_exists_locally = self.repo.heads[branch_name]
        except IndexError:
            branch_exists_locally = False

        branch_exists_remotely = self.remote_branch_reference(branch_name)

        # if branch exists remote but not locally, create from remote
        if branch_exists_remotely and not branch_exists_locally:
            self.fetch()
            self.repo.head.reference = self.repo.create_head(
                branch_name, self.origin.refs[branch_name]
            )
            self.repo.head.reference.checkout()
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

    def reset(self, hard: bool = False, from_origin:bool=True):
        """
        Reset the current branch.

        **Arguments**

        - hard: A boolean indicating whether to perform a hard reset from origin/branch
        """
        if self.allow_unsafe:

            if from_origin and self.origin and self.remote_branch_reference(self.branch):
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

    def create_change_request(self, title: str, description: str = "", target_branch: str = None, source_branch: str = None):
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
            self.log.info(
                f"Merge request already exists for branch {self.branch}, updating it"
            )
            return mr.update_info(title=title, body=description)

        return _project.create_pr(
            title=title,
            body=description,
            target_branch=target_branch,
            source_branch=source_branch,
        )

    def get_open_change_request(self, target_branch:str, source_branch:str):

        """
        Checks if the merge request exists in an open state
        """

        if not self.service:
            raise ValueError("No service configured")

        _project = self.service_project()

        for mr in _project.get_pr_list():

            # skip closed/merged MRs

            if mr.status != "open":
                continue

            if mr.source_branch == source_branch and mr.target_branch == target_branch:
                return mr

        return None


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


class ChangeRequest(pydantic.BaseModel):
    title: str
    description: str = ""
    target_branch: str = None
    source_branch: str = None

class EphemeralGitContextState(pydantic.BaseModel):
    git_manager: GitManager
    branch: str = None
    commit_message: str = "Commit changes"
    dry_run: bool = False
    readonly: bool = False

    context_id: str = pydantic.Field(default_factory=lambda: str(uuid.uuid4())[:8])

    change_request: ChangeRequest = None

    validate_clean: Callable = None

    files_to_add: list[str] = pydantic.Field(default_factory=list)

    model_config = pydantic.ConfigDict(arbitrary_types_allowed=True)

    _initialized: bool = False



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
        - dry_run (bool, optional): Whether to perform a dry run. Defaults to False. WARNING: dry-run here specifically refers to
            commit and push operations, not the entire context manager. It will still reset and pull the repository.
        - change_request (ChangeRequest, optional): A ChangeRequest instance to use. Defaults to None.
        """

        # this should never be set by the user
        kwargs.pop("_initialized", None)

        self.state_token = None
        self.stash_pushed = False
        self.stash_popped = False

        try:
            self.state = ephemeral_git_context_state.get()
        except LookupError:
            self.state = None

        if not self.state and not kwargs:
            raise ValueError("No state provided and no context set")

        if not self.state or kwargs:
            self.state = EphemeralGitContextState(**kwargs)

    def __enter__(self):
        """
        Sets up the repository, fetches and pulls.
        """

        self.context_token = current_ephemeral_git_context.set(self)

        if self.state._initialized:
            # already initialized, can just return
            return self
        
        self.stash_current_context()
        
        self.state_token = ephemeral_git_context_state.set(self.state)
        
        self.git_manager.fetch()

        if self.git_manager.is_dirty:
            self.git_manager.reset(hard=True)

        if self.state.branch:
            self.git_manager.switch_branch(self.state.branch)
            self.git_manager.reset(hard=True)

        # if branch exists remotely
        if self.git_manager.remote_branch_reference(self.git_manager.branch):
            self.git_manager.pull()

        self.state._initialized = True

        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """
        Commits all changes and attempts to push.
        In case of any git failures, hard resets the repository.
        """

        current_ephemeral_git_context.reset(self.context_token)

        if not self.state_token:
            # no state token,  means state was reused, can just
            # return
            return

        if not self.state.dry_run and not self.state.readonly:
            self.finalize(exc_type, exc_val, exc_tb)
        elif self.state.dry_run:
            for changed_file in self.git_manager.changed_files(self.state.files_to_add):
                self.git_manager.log.info(f"[dry-run] commit changes: {changed_file}")
        
        ephemeral_git_context_state.reset(self.state_token)

        # reset to previous branch
        try:
            prev_state = ephemeral_git_context_state.get()

            self.git_manager.switch_branch(prev_state.branch if prev_state.branch else self.git_manager.default_branch)
            self.git_manager.reset(hard=True)

            if not self.stash_pushed:
                return

            # try tro pop stash
            try:
                self.git_manager.repo.git.stash("pop")
                self.stash_popped = True
            except GitCommandError:
                pass

        except LookupError:
            pass

        return False  # re-raise any exception

    @property
    def git_manager(self):
        return self.state.git_manager

    def stash_current_context(self):

        # stash current repo state if we are moving into a nested
        # context

        if not self.git_manager.is_dirty:

            # nothing to stash
            
            return

        # stash

        self.git_manager.repo.git.stash("push")
        self.stash_pushed = True

    def finalize(self, exc_type, exc_val, exc_tb):
        if self.state.dry_run or self.state.readonly:
            return

        if not self.git_manager.changed_files(self.state.files_to_add):
            # no changes, can just return
            return

        if self.state.validate_clean and self.state.validate_clean(self.git_manager):
            # we have a custom validation function and it returned True, indicating
            # that the changes that are there can be ignored, so we can just return
            return

        if exc_type is None:
            try:
                # Commit all changes
                self.git_manager.add(self.git_manager.changed_files(self.state.files_to_add))
                self.git_manager.commit(self.state.commit_message)
                # Attempt to push
                self.git_manager.push()
                # if change request config is specified create a change request
                if self.state.change_request:
                    self.state.change_request.source_branch = self.git_manager.branch
                    self.state.change_request.target_branch = self.git_manager.default_branch
                    self.git_manager.create_change_request(**self.state.change_request.model_dump())

            except GitCommandError:
                # Hard reset the repository in case of git failures
                self.git_manager.reset(hard=True)
                raise
        else:
            # Hard reset the repository in case of other exceptions
            self.git_manager.reset(hard=True)
            raise exc_val

    def add_files(self, file_paths: list[str]):
        """
        Add files to the repository.

        Args:
            file_paths (list[str]): A list of file paths to add to the repository.
        """

        if self.state.readonly:
            raise ValueError("Cannot add files in readonly ephemeral git context")

        self.state.files_to_add.extend(file_paths)



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