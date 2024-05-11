import pytest
import sys
from typing import Any

engines=None

@pytest.fixture(autouse=True)
def _setup_default_engine(doctest_namespace: Any)->None:
	# this is for pytest doctest only
	from pythonimmediate.engine import default_engine, ChildProcessEngine

	global engines
	if engines is None:
		# this will be run for each process if pytest get -n4 regardless
		engines=[
				ChildProcessEngine("pdftex", autorestart=True),
				ChildProcessEngine("luatex", autorestart=True)
				]
	default_engine.set_engine(engines[0])
	doctest_namespace["luatex_engine"]=engines[1]
