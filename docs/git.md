## GitHub / GitLab

### `ctl` commands for pr management

```sh
export REPO_PATH=/path/to/checked-out-repo

# list all open pull / merge requests
ctl git list_change_requests  --checkout-path $REPO_PATH

# rename pull / merge requests
# ctl git rename_change_request <source> <target> <title>
ctl git rename_change_request prep-release main "Updated PR title" --checkout-path $REPO_PATH

# merge release
# ctl git merge_release <source> <target> 
ctl git merge_release prep-release main --checkout-path $REPO_PATH
```

#### GitHub token permission requirements

- Contents: read and write
- Pull requests: read and write
- Metadata: read

#### GitLab token permission requirements

- Role: >= Maintainer
- api
- read_api
- read_repository
- write_repository