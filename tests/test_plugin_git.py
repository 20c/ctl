import os
import subprocess

from util import instantiate_test_plugin


def init_tmp_repo(tmpdir):
    repo_path = str(tmpdir.mkdir("git_repo_src.git"))
    repo_path_clone = str(tmpdir.mkdir("git_repo_clone"))

    subprocess.call(
        [
            f"cd {repo_path}; git config --global init.defaultBranch main; git init --bare;"
        ],
        shell=True,
    )
    subprocess.call(
        [f"git clone {repo_path} {repo_path_clone}"],
        shell=True,
    )

    subprocess.call([f"echo empty > {repo_path_clone}/README.md"], shell=True)
    subprocess.call(
        [
            f"cd {repo_path_clone}; git config user.name pytest; git config user.email pytest@localhost; git add *; git commit -am initial;"
        ],
        shell=True,
    )
    subprocess.call(
        [f"cd {repo_path_clone}; git push -u origin main;"],
        shell=True,
    )

    subprocess.call([f"cd {repo_path_clone}; git branch test;"], shell=True)

    return repo_path, repo_path_clone


def instantiate(tmpdir, ctlr=None, **kwargs):
    repo_path, repo_path_clone = init_tmp_repo(tmpdir)
    print((repo_path, repo_path_clone))
    config = {
        "config": {
            "repo_url": repo_path,
            "checkout_path": str(tmpdir.mkdir("git_repo_co")),
        }
    }
    config["config"].update(**kwargs)
    plugin = instantiate_test_plugin("git", "test_git", _ctl=ctlr, **config)
    plugin.init_repo()

    subprocess.call(
        [
            f"cd {plugin.checkout_path}; git config user.name pytest; git config user.email pytest@localhost"
        ],
        shell=True,
    )

    return plugin, repo_path_clone


def test_init_and_clone(tmpdir, ctlr):
    plugin, repo_path = instantiate(tmpdir, ctlr)
    assert plugin.is_cloned
    assert plugin.is_clean
    assert plugin.branch == "main"
    assert len(plugin.uuid) > 0


def test_pull(tmpdir, ctlr):
    plugin, repo_path = instantiate(tmpdir, ctlr)
    subprocess.call(
        [
            f"echo changed > {repo_path}/README.md; cd {repo_path}; "
            "git commit -am 'update'; git push -u origin main"
        ],
        shell=True,
    )
    plugin.execute(op="pull")
    with open(f"{plugin.checkout_path}/README.md") as fh:
        assert fh.read() == "changed\n"


def test_commit_and_push(tmpdir, ctlr):
    plugin, repo_path = instantiate(tmpdir, ctlr)
    subprocess.call([f"echo abcdef > {plugin.checkout_path}/README.md"], shell=True)
    plugin.commit(files=["README.md"], message="updated", push=True)

    subprocess.call([f"cd {repo_path}; git pull;"], shell=True)

    with open(f"{repo_path}/README.md") as fh:
        assert fh.read() == "abcdef\n"


def test_tag(tmpdir, ctlr):
    plugin, repo_path = instantiate(tmpdir, ctlr)
    plugin.tag("0.0.1", "0.0.1", push=True)

    subprocess.call([f"cd {repo_path}; git pull;"], shell=True)

    out = subprocess.check_output([f"cd {repo_path}; git tag;"], shell=True)

    assert f"{out}".find("0.0.1") > -1


def test_branch_and_merge(tmpdir, ctlr):
    plugin, repo_path = instantiate(tmpdir, ctlr, branch="test")

    # confirm we are starting on `test` branch
    assert plugin.branch == "test"

    # update README.md on test brach and commit
    subprocess.call(
        [f"echo abcdeftest > {plugin.checkout_path}/README.md"],
        shell=True,
    )
    plugin.commit(files=["README.md"], message="test")

    # switch back to main and check file was reverted
    plugin.checkout("main")
    with open(f"{plugin.checkout_path}/README.md") as fh:
        assert fh.read() == "empty\n"

    # merge test
    plugin.merge("test", "main")
    assert plugin.branch == "main"

    # check that main is now on the new file
    with open(f"{plugin.checkout_path}/README.md") as fh:
        assert fh.read() == "abcdeftest\n"


def test_find_git_root(tmpdir, ctlr):
    plugin, repo_path = instantiate(tmpdir, ctlr)

    # checkout_path itself is a repo root
    assert os.path.abspath(plugin.find_git_root()) == os.path.abspath(
        plugin.checkout_path
    )

    # from a subdirectory the enclosing repository root is found
    subdir = os.path.join(plugin.checkout_path, "sub", "dir")
    os.makedirs(subdir)
    assert os.path.abspath(plugin.find_git_root(subdir)) == os.path.abspath(
        plugin.checkout_path
    )

    # outside any repository resolution terminates and returns None
    outside = str(tmpdir.mkdir("no_repo_here"))
    assert plugin.find_git_root(outside) is None

    # is_cloned uses the same resolution as git command targeting
    assert plugin.is_cloned


def test_clone_nested_in_enclosing_repo(tmpdir, ctlr):
    # a not-yet-cloned checkout_path nested inside another repository
    # must still be cloned (is_cloned must not report the enclosing repo)
    outer, repo_path = instantiate(tmpdir, ctlr)

    nested_path = os.path.join(outer.checkout_path, "nested", "repo")
    config = {"config": {"repo_url": outer.repo_url, "checkout_path": nested_path}}
    nested = instantiate_test_plugin("git", "test_git_nested", _ctl=ctlr, **config)

    # checkout_path is missing - resolution finds the enclosing repo but
    # the plugin must not consider itself cloned
    assert nested.find_git_root() == os.path.abspath(outer.checkout_path)
    assert not nested.is_cloned

    nested.clone()

    # a proper nested repository now exists and resolution targets it
    assert os.path.isdir(os.path.join(nested_path, ".git"))
    assert nested.find_git_root() == os.path.abspath(nested_path)
    assert nested.is_cloned


def test_clone_skips_content_bearing_subdir(tmpdir, ctlr):
    # a content-bearing subdirectory of an enclosing repository is
    # treated as cloned (monorepo intent) and clone() skips
    outer, repo_path = instantiate(tmpdir, ctlr)

    subdir = os.path.join(outer.checkout_path, "sub")
    os.makedirs(subdir)
    with open(os.path.join(subdir, "content.txt"), "w") as fh:
        fh.write("content\n")

    config = {"config": {"repo_url": outer.repo_url, "checkout_path": subdir}}
    plugin = instantiate_test_plugin("git", "test_git_subdir", _ctl=ctlr, **config)

    assert plugin.is_cloned
    plugin.clone()

    # no nested repo was created, operations target the enclosing repo
    assert not os.path.isdir(os.path.join(subdir, ".git"))
    assert plugin.find_git_root() == os.path.abspath(outer.checkout_path)
