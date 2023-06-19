import pytest
import sys

engine=None

@pytest.fixture(autouse=True)
def _setup_default_engine():
	# this is for pytest doctest only
	from .engine import default_engine, ChildProcessEngine

	global engine
	if engine is None: engine=ChildProcessEngine("pdftex")  # this will create 4 engines if pytest get -n4 regardless
	default_engine.set_engine(engine)
