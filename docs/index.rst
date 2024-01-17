.. pythonimmediate documentation master file, created by
   sphinx-quickstart on Thu Jan  5 11:13:47 2023.
   You can adapt this file completely to your liking, but it should at least
   contain the root `toctree` directive.

Welcome to pythonimmediate's documentation!
===========================================

This package is a Python-TeX binding. It requires the ``pythonimmediate`` TeX package to be installed.

The package works both ways -- you can run Python code from TeX, or TeX code from Python.

There are different sections of the documentation:

- :mod:`pythonimmediate.texcmds` -- list of all TeX commands/environments, such as ``\py``, ``pycode`` etc.
  These are also (mostly) available in the documentation of the `TeX package <https://www.ctan.org/pkg/pythonimmediate>`_.

  **For getting started, it's recommended to read the documentation of the TeX package linked above first.**

- :mod:`pythonimmediate.simple` -- interface that "just works" for typical users of the
  ``pythonimmediate`` TeX package, to use Python coding from TeX,
  who does not know TeX inner details such as category codes.

  Note that this should be read in conjunction with the ``pythonimmediate`` TeX package documentation.

- Some properties of the parent TeX engine (e.g. whether Unicode is supported)
  can be accessed from :const:`~pythonimmediate.engine.default_engine`.

- The rest: contain functions that controls TeX in a more "low-level" way.
  Start with reading the module documentation :mod:`pythonimmediate`.

- See the documentation of :class:`pythonimmediate.engine.ChildProcessEngine` for ways to create a TeX engine from inside Python,
  and see :const:`~pythonimmediate.engine.default_engine` for how to set which engine functions are run on.

- The command-line arguments that the Python component accepts
  (can be specified through the ``args=`` TeX module option)
  are documented in :mod:`pythonimmediate.pytotex`.

- Debugging functionalities should be available:

  - Error messages should be as descriptive as possible.
  - TeX errors results in Python traceback, and Python error results in TeX traceback.
  - Errors in code executed with the ``pycode`` environment gives the correct traceback point to the Python line of code in the TeX file.
  - There are some command-line flags to enable debugging functionalities, which can be passed in follows the documentation in :mod:`pythonimmediate.pytotex`.

.. note::
  Disclaimer: the sole purpose of this package is to let me do some programming in TeX in a sane programming language.

  Its design is not necessarily good, usually with lots of abstraction layers piled over legacy code.

.. toctree::
   :maxdepth: 4
   :caption: Contents:

   pythonimmediate

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
