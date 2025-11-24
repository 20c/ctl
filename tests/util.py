import ctl
from ctl.plugins.repository import RepositoryPlugin


def instantiate_version(tmpdir, ctlr=None):
    """
    shortcut to instantiate a version plugin as well as a dummy repository
    """
    dummy_repo = ctl.plugin._instance["dummy_repo"] = DummyRepositoryPlugin(
        {"config": {"checkout_path": str(tmpdir.mkdir("repo"))}}, ctlr
    )
    config = {"config": {"branch_dev": "main", "branch_release": "release"}}
    plugin = instantiate_test_plugin("version", "test_version", _ctl=ctlr, **config)
    plugin.init_version = True
    plugin.no_auto_dev = True
    return (plugin, dummy_repo)


def instantiate_semver2(tmpdir, ctlr=None):
    """
    shortcut to instantiate a version plugin as well as a dummy repository
    """
    dummy_repo = ctl.plugin._instance["dummy_repo"] = DummyRepositoryPlugin(
        {"config": {"checkout_path": str(tmpdir.mkdir("repo"))}}, ctlr
    )
    plugin = instantiate_test_plugin("semver2", "test_semver2", _ctl=ctlr)
    plugin.init_version = True

    return (plugin, dummy_repo)


def instantiate_test_plugin(typ, name, _ctl=None, **extra):
    config = {"type": typ, "name": name}
    config.update(**extra)
    ctl.plugin.instantiate([config], _ctl)
    return ctl.plugin.get_instance(name)


class DummyRepositoryPlugin(RepositoryPlugin):
    """
    In order to test the versioning plugin we need a dummy
    repository plugin - so we can test that actions are properly
    propagated to a repository managed by the version plugin.

    This plugin serves that purpose
    """

    def init(self):
        self._repo_url = self.config.get("repo_url")
        self._checkout_path = self.config.get("checkout_path")
        self._clean = True
        self._cloned = False
        self._committed = False
        self._pulled = False
        self._pushed = False
        self._merged = None
        self._tag = None
        self._branch = "main"
        self._tags = set()

    @property
    def uuid(self):
        return "deadbeef"

    @property
    def is_cloned(self):
        return self._cloned

    @property
    def is_clean(self):
        return self._clean

    @property
    def branch(self):
        return self._branch

    def commit(self, **kwargs):
        self._committed = True

    def clone(self, **kwargs):
        self._is_cloned = True

    def pull(self, **kwargs):
        self._pulled = True

    def push(self, **kwargs):
        self._committed = False
        self._pushed = True

    def tag(self, version, **kwargs):
        self._tag = version
        nogit = kwargs.get("nogit", False)

        if not nogit:
            self._tags.add(version)

    def checkout(self, branch, **kwargs):
        print(("SETTING BRANCH", branch))
        self._branch = branch

    def merge(self, a, b, **kwargs):
        self.checkout(b)
        self._merged = b

    def has_tag(self, tag):
        return tag in self._tags
