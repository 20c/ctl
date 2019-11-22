import os
import pytest

import pytest_filedata

import ctl


@pytest.fixture
def this_dir():
    return os.path.dirname(__file__)


@pytest.fixture
def config_dir(this_dir):
    return os.path.join(this_dir, "data", "config")


@pytest.fixture(params=["standard"])
def ctlr(config_dir):
    return ctl.Ctl(config_dir=os.path.join(config_dir, "standard"))


@pytest.fixture(params=["permission_denied"])
def ctldeny(config_dir):
    return ctl.Ctl(config_dir=os.path.join(config_dir, "permission_denied"))


pytest_filedata.setup(os.path.dirname(__file__))

def pytest_generate_tests(metafunc):
    for fixture in metafunc.fixturenames:
        if fixture.startswith('data_'):
            data = pytest_filedata.get_data(fixture)
            metafunc.parametrize(fixture, list(data.values()), ids=list(data.keys()))
