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
            "cd {path}; git config user.name pytest; git config user.email pytest@localhost; git add *; git commit -am initial;".format(
                path=repo_path_clone
            )
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

    subprocess.call(
        [
            "cd {path}; git config user.name pytest; git config user.email pytest@localhost".format(
                path=plugin.checkout_path
            )
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
            "echo changed > {path}/README.md; cd {path}; "
            "git commit -am 'update'; git push -u origin main".format(path=repo_path)
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
