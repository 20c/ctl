# Git Manager Utility Quickstart Guide

This Python utility provides functionalities for managing Git repositories, including operations on Github and Gitlab.

## Basic Usage

1. **Import the utility**

```python
from git_manager import GitManager, EphemeralGitContext
```

2. **Initialize a GitManager instance**

```python
git_manager = GitManager(
  url="https://github.com/username/repo.git",
  directory="/path/to/local/repo",
  default_branch="main"
)
```

3. **Fetch and pull from the repository**

```python
git_manager.fetch()
git_manager.pull()
```

4. **Create a new branch and switch to it**

```python
git_manager.create_branch("new-branch")
git_manager.switch_branch("new-branch")
```

5. **Add files to the index and commit changes**

```python
git_manager.add(["file1.py", "file2.py"])
git_manager.commit("Commit message")
```

6. **Push changes to the repository**

```python
git_manager.push()
```

## Using EphemeralGitContext

The `EphemeralGitContext` class provides a context manager for Git operations. It sets up the repository on open, fetches and pulls. At the end, it commits all changes and attempts to push.

```python
with EphemeralGitContext(git_manager=git_manager, branch="new-branch", commit_message="Commit changes"):
  # Perform operations within the context
  pass
```

## Creating a Merge Request

```python
git_manager.create_change_request(
  title="Merge Request Title",
  description="Merge Request Description",
  target_branch="main",
  source_branch="new-branch"
)
```

Please refer to the source code for more detailed usage and additional functionalities.
Please note that this is a basic guide and the actual usage may vary depending on the specific requirements of your project.
