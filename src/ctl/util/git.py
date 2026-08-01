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
import time
import urllib
import uuid
from collections.abc import Callable

import git
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

    This is *operator* configuration: it is populated from the environment, from
    command line arguments and by calling code.

    It is deliberately never populated from content inside the repository that ctl
    operates on. A file in the repository must not be able to name the host an
    ambient credential is sent to, nor supply the credentials ctl acts with - that
    is a confused deputy, and repository content is untrusted input. Do not add a
    mechanism that reads any of these values back out of a checkout.
    """

    gitlab_url: str = pydantic.Field(default_factory=lambda: os.getenv("GITLAB_URL"))

    # repr=False: pydantic renders field values in the model repr, so any incidental
    # `f"{config}"` - a log line, an exception message, a debugger - would otherwise
    # write the tokens out in plaintext
    gitlab_token: str = pydantic.Field(
        default_factory=lambda: os.getenv("GITLAB_TOKEN"), repr=False
    )
    github_token: str = pydantic.Field(
        default_factory=lambda: os.getenv("GITHUB_TOKEN"), repr=False
    )


# ogr's GithubService is github.com only - `GithubService.instance_url` is hardcoded
# to `https://github.com` - so an origin on a github host belongs to the github
# service and a gitlab service must never be derived from it
GITHUB_HOST = "github.com"


def is_github_host(host: str) -> bool:
    """
    Returns True if the host belongs to github (`github.com` or any subdomain of it,
    such as `ssh.github.com` or `gist.github.com`).
    """

    if not host:
        return False

    return host == GITHUB_HOST or host.endswith(f".{GITHUB_HOST}")


def _split_repository_url(url: str, allow_scp: bool = True) -> tuple | None:
    """
    Splits a repository url into `(scheme, host, port)`, or returns `None` when it
    does not name a usable host. The host is normalized (lower cased, trailing root
    dot removed) and carries no credentials.

    **Arguments**

    - url: repository url
    - allow_scp: accept scp style remotes (`git@host:path`). Off for operator
      supplied values, where a missing scheme is a mistake rather than a remote form

    **Returns**

    `(scheme, host, port)` (`tuple`) or `None`
    """

    if not url:
        return None

    if "://" in url:
        parsed = urllib.parse.urlparse(url)

        try:
            host, port = parsed.hostname, parsed.port
        except ValueError:
            # malformed authority - an unbracketed ipv6 literal, a port that is not
            # a number or out of range
            return None

        if not host:
            return None

        # http stays http (local instances), everything else - including the ssh
        # and git schemes a remote may use - addresses the api over https. A port is
        # only carried over for http(s): an ssh port says nothing about where the
        # api lives
        if parsed.scheme in ("http", "https"):
            return (parsed.scheme, _normalize_host(host), port)

        return ("https", _normalize_host(host), None)

    if not allow_scp:
        return None

    # scp style remote: [user@]host:path - the host part must not contain a slash,
    # which is what separates it from a plain filesystem path
    host_part, separator, path = url.partition(":")

    if not separator or not path or "/" in host_part:
        return None

    host = host_part.rsplit("@", 1)[-1]

    if not host:
        return None

    return ("https", _normalize_host(host), None)


def _normalize_host(host: str) -> str:
    """
    Returns the host lower cased and without a trailing root dot, so that
    `GitHub.com` and `github.com.` cannot slip past a host comparison.
    """

    return host.lower().rstrip(".")


def sanitize_url(url: str) -> str:
    """
    Returns the url with any embedded credentials removed, so it is safe to log.

    Repository urls routinely carry credentials (`https://oauth2:token@host/path`).
    """

    if not url:
        return url

    parsed = urllib.parse.urlparse(url)

    if parsed.netloc:
        if "@" not in parsed.netloc:
            return url

        return parsed._replace(netloc=parsed.netloc.rsplit("@", 1)[1]).geturl()

    # scheme-less form (scp style remote, or a bare `user:secret@host:path`) - urlparse
    # finds no netloc to clean, so strip the userinfo off the leading segment
    host_part, separator, path = url.partition(":")

    if not separator or "@" not in url:
        return url

    if "@" in host_part:
        return f"{host_part.rsplit('@', 1)[1]}{separator}{path}"

    # `user:secret@host:path` - the credential spans the first separator
    userinfo, _, remainder = url.partition("@")

    return remainder if ":" in userinfo else url


def instance_url_from_repository_url(url: str, allow_scp: bool = True) -> str | None:
    """
    Returns the scheme and host (and port, for http/https) of a repository url, in
    the form a service instance url wants, or `None` if the url does not name a host.

    Handles regular urls (`https://host/path`, `ssh://git@host:22/path`) as well as
    scp style git remotes (`git@host:path`). Any credentials embedded in the url are
    dropped.

    **Arguments**

    - url: repository url
    - allow_scp: accept scp style remotes. Off for operator supplied values

    **Returns**

    instance url (`str`) or `None`
    """

    split = _split_repository_url(url, allow_scp=allow_scp)

    if not split:
        return None

    scheme, host, port = split

    # ipv6 literals have to go back into the url bracketed
    if ":" in host:
        host = f"[{host}]"

    return f"{scheme}://{host}" + (f":{port}" if port else "")


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
    - repository_config_filename: **Deprecated and ignored.** ctl no longer reads
        configuration from the content of the repository it operates on.
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
    - repository_config_filename: **Deprecated and ignored**, retained so existing
        callers keep working.
    - repository_config: The operator supplied repository config
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
        url: str | None,
        directory: str,
        default_branch: str = "main",
        default_service: str = None,
        log: object = None,
        repository_config_filename=None,
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
        self._last_fetch_time = 0

        self.log = log if log else logging.getLogger(__name__)

        # retained so callers passing it keep working, but nothing reads the file:
        # configuration is never taken from repository content (see RepositoryConfig)
        self.repository_config_filename = repository_config_filename

        if repository_config_filename:
            self.log.info(
                f"`repository_config_filename` ({repository_config_filename}) is "
                "deprecated and ignored - ctl no longer reads configuration from the "
                "content of the repository it operates on. Set GITLAB_URL / "
                "GITLAB_TOKEN / GITHUB_TOKEN in the environment, or pass "
                "`repository_config`, instead"
            )

        # copied, never referenced: `init_services` resolves values into this object
        # (including an instance url derived from *this* repository's origin), and a
        # caller that reuses one config across repositories must not have the first
        # repository's host applied to the second
        self.repository_config = (
            repository_config.model_copy() if repository_config else RepositoryConfig()
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
        # repo config will not have been loaded yet, but we might need a service to clone the repo
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
            self.log.debug(
                f"Cloning repository from {sanitize_url(self.url)}: {self.directory}"
            )
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
            f"Repository initialized at {self.directory} from {sanitize_url(self.url)} - "
            f"origin set to {self.origin.name if self.origin else None}"
        )

        # re-init services now that the origin is known: when the operator has not
        # named a gitlab instance, it is derived from the origin (see
        # `derive_gitlab_url`). Nothing is read out of the checkout itself.
        self.init_services(self.repository_config)

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
                f"Could not find origin for repository {sanitize_url(self.url)} "
                f"(first is {sanitize_url(remote.url) if remote else None})"
            )

    def derive_gitlab_url(self) -> str | None:
        """
        Derives the gitlab instance url from the repository's own origin.

        This is the fallback for when the operator has not named an instance: the
        only host ctl may send an ambient credential to is the host the repository
        was cloned from.

        Fails closed - when the origin cannot be determined unambiguously, does not
        name a host, or is a github host, `None` is returned and no gitlab service
        will be created. It never falls back to a default host.

        **Returns**

        instance url (`str`) or `None`
        """

        if self.origin and self.origin.url:
            urls = [self.origin.url]
            source = f"origin remote `{self.origin.name}`"
        elif self.url:
            urls = [self.url]
            source = "repository url"
        elif self.repo is not None and self.repo.remotes:
            urls = [remote.url for remote in self.repo.remotes]
            source = "repository remotes"
        else:
            self.log.warning(
                "No gitlab instance url configured and none could be derived: the "
                "repository has no origin, no url and no remotes - not initializing "
                "a gitlab service. Set GITLAB_URL to name an instance explicitly"
            )
            return None

        splits = {_split_repository_url(url) for url in urls}
        inspected = ", ".join(sorted(sanitize_url(url) for url in urls))

        if len(splits) > 1:
            self.log.warning(
                "No gitlab instance url configured and the repository's remotes do "
                f"not agree on one ({source}: {inspected}) - not initializing a "
                "gitlab service. Set GITLAB_URL to name an instance explicitly"
            )
            return None

        split = splits.pop()

        if not split:
            self.log.warning(
                "No gitlab instance url configured and none could be derived: "
                f"{source} ({inspected}) does not name a host - not initializing a "
                "gitlab service. Set GITLAB_URL to name an instance explicitly"
            )
            return None

        if is_github_host(split[1]):
            self.log.warning(
                f"No gitlab instance url configured and {source} ({inspected}) is a "
                "github host - not initializing a gitlab service"
            )
            return None

        return instance_url_from_repository_url(urls[0])

    def init_services(self, config: RepositoryConfig):
        """
        Initializes the services for the repository

        `config` is operator configuration - environment, command line arguments or
        caller supplied (see `RepositoryConfig`). Nothing that comes out of the
        repository itself may influence which host a credential is sent to.
        """
        # why do we have 2 configs?
        if config.gitlab_url != self.repository_config.gitlab_url:
            raise ValueError("config passed is not repo config")

        # argparse seems to be interfering with the GITLAB_URL var
        env_gitlab_url = os.getenv("GITLAB_URL")
        gitlab_url = env_gitlab_url or config.gitlab_url
        gitlab_token = os.getenv("GITLAB_TOKEN") or config.gitlab_token
        github_token = os.getenv("GITHUB_TOKEN") or config.github_token

        gitlab_url_source = (
            "GITLAB_URL environment variable" if env_gitlab_url else "operator config"
        )

        # `init_repository` calls this once before the repository exists (to set up
        # auth for the clone) and again once the origin is known. Only the second
        # pass can derive anything, and warning from the first would train operators
        # to ignore the warning that means a credential was withheld
        can_derive = self.repo is not None

        if not gitlab_url and gitlab_token and can_derive:
            # the operator has a gitlab credential but named no instance: derive it
            # from the repository's own origin, so the token can only ever go to the
            # host the repository was cloned from
            gitlab_url = self.derive_gitlab_url()
            gitlab_url_source = "the repository's clone origin"

        # update repo config
        self.repository_config.gitlab_token = gitlab_token
        self.repository_config.github_token = github_token
        self.repository_config.gitlab_url = gitlab_url

        if gitlab_url and not self.services.gitlab:
            # instance_url wants only the scheme and host, so we need to parse it out
            # of the full url. `allow_scp` is off: an operator supplied value without
            # a scheme is a mistake, and reading it as an scp style remote would
            # silently drop a port (`gitlab.internal:8443`)
            instance_url = instance_url_from_repository_url(gitlab_url, allow_scp=False)

            if not instance_url:
                # never fall through to a service with no instance url: ogr defaults
                # that to https://gitlab.com, which is exactly the wrong host to send
                # an operator's token to
                raise ValueError(
                    f"Could not determine a gitlab instance url from "
                    f"`{sanitize_url(gitlab_url)}` ({gitlab_url_source}) - it needs "
                    "to be a full url, e.g. https://gitlab.example.com"
                )

            # the operator needs to be able to see which host received their token
            self.log.info(
                f"Using gitlab instance {instance_url} (from {gitlab_url_source})"
            )

            self.services.gitlab = GitlabService(
                token=gitlab_token,
                instance_url=instance_url,
            )
        if github_token and not self.services.github:
            self.services.github = GithubService(token=github_token)

        if self.default_service and not getattr(self.services, self.default_service):
            raise ValueError(
                f"Could not initialize {self.default_service}, make sure the url and token are correct"
            )

    def service_project(self, service: str = None):
        """
        Returns the service project for the service
        """
        _service = getattr(self.services, service) if service else self.service
        if not _service:
            raise ValueError("No service configured, cannot get project")
        return _service.get_project_from_url(self.url)

    def service_file_url(self, file_path: str, service: str = None):
        """
        Returns the url for a file on the service

        Will account for url, project name and branch
        """

        _service = getattr(self.services, service) if service else self.service
        _project = self.service_project(service)

        return f"{_service.instance_url}/{_project.full_repo_name}/blob/{self.branch}/{file_path}"

    def fetch(self, prune: bool = True, force: bool = False):
        """
        Fetches the origin repository.

        Respects a cooldown period to avoid hammering the remote with
        redundant fetches (e.g. multiple fetches within a single
        EphemeralGitContext entry). The cooldown is controlled by the
        GIT_FETCH_COOLDOWN environment variable (seconds, default 30).

        Args:
            prune: Whether to prune deleted remote branches
            force: If True, bypass the cooldown and always fetch
        """

        try:
            cooldown = int(os.environ.get("GIT_FETCH_COOLDOWN", 30))
        except (ValueError, TypeError):
            self.log.error(
                f"Invalid GIT_FETCH_COOLDOWN value: {os.environ.get('GIT_FETCH_COOLDOWN')!r}, using default 30s"
            )
            cooldown = 30

        if not force and cooldown > 0:
            now = time.time()
            elapsed = now - self._last_fetch_time
            if elapsed < cooldown:
                self.log.debug(
                    f"Skipping fetch, last fetch was {elapsed:.1f}s ago "
                    f"(cooldown={cooldown}s)"
                )
                return

        fetch_args = ["--all"]
        if prune:
            fetch_args.append("--prune")

        self.log.info(f"Fetching from {self.origin.name}")
        fetch_info = self.repo.git.fetch(*fetch_args)
        self.log.debug(f"Fetch info: {fetch_info}")
        self._last_fetch_time = time.time()
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

        The fetch bypasses the GIT_FETCH_COOLDOWN throttle: syncing is an
        explicit request to integrate the current remote state, so stale
        refs would defeat its purpose (and can reject the push).
        """

        self.fetch(force=True)
        if self.require_remote_branch() is True:
            # branch did not exist remotely yet
            self.push()

            # fetch again to make sure we have the latest refs
            self.fetch(force=True)
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
            # strip only the remote prefix (`origin/`) so branch names
            # containing slashes (e.g. `feature/x`) still match their ref
            if ref.name.removeprefix(f"{self.origin.name}/") == branch_name:
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
    branch: str | None = None
    commit_message: str = "Commit changes"
    readonly: bool = False
    inactive: bool = False
    force_push: bool = False

    context_id: str = pydantic.Field(default_factory=lambda: str(uuid.uuid4())[:8])

    change_request: ChangeRequest | None = None

    validate_clean: Callable | None = None

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
        try:
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
        except Exception as e:
            # errors during __enter__ dont get caught in __exit__
            # always reset the context state
            ephemeral_git_context_state.reset(self.state_token)
            current_ephemeral_git_context.reset(self.context_token)
            self.reset_context_state()
            self.reset_stash()
            raise e

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
            self.reset_context_state()

        finally:
            # always reset the context state
            ephemeral_git_context_state.reset(self.state_token)
            self.reset_stash()

            # ensure GitPython releases any persistent processes and resources
            try:
                self.git_manager.repo.close()
            except Exception:
                pass

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

    def reset_context_state(self):
        """
        Resets the context state
        """

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

    def reset_stash(self):
        # always pop stash
        if self.state.stash_pushed:
            # can_read implied
            self.log.info("Popping stash")
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

    def stash_current_context(self):
        # stash current repo state if we are moving into a nested
        # context

        if not self.git_manager.is_dirty:
            # nothing to stash

            return

        # stash

        self.git_manager.repo.git.stash("push")
        self.state.stash_pushed = True
        self.log.info("Stashed current context")

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
                # Pull to integrate any remote changes before pushing,
                # avoiding rejection when concurrent processes have
                # pushed to the same branch. Skipped when the branch does
                # not exist remotely yet (nothing to integrate; pulling a
                # nonexistent ref is a fatal git error).
                # If this fails due to conflicts, push would have also failed.
                if (
                    not self.state.force_push
                    and self.git_manager.remote_branch_reference(
                        self.git_manager.branch
                    )
                ):
                    self.git_manager.pull()
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
                "Cannot create change request in readonly ephemeral git context"
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
            allow_unsafe=self._initial_git_manager.allow_unsafe,
            submodules=self._initial_git_manager.submodules,
            # operator config only - carrying this over cannot reintroduce a
            # repository supplied host, because nothing puts one in it
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
