.. pythonimmediate documentation master file, created by
   sphinx-quickstart on Thu Jan  5 11:13:47 2023.
   You can adapt this file completely to your liking, but it should at least
   contain the root `toctree` directive.

Welcome to pythonimmediate's documentation!
===========================================

This package is a Python-TeX binding. It requires the ``pythonimmediate`` TeX package to be installed.

The package works both ways -- you can run Python code from TeX, or TeX code from Python.

There are different sections of the documentation:


- :mod:`pythonimmediate.simple` -- interface that "just works" for typical users of the
  ``pythonimmediate`` TeX package, to use Python coding from TeX,
  who does not know TeX inner details such as category codes.
- Some properties of the parent TeX interpreter can be accessed from :const:`~pythonimmediate.engine.default_engine`.
- The rest: contain functions to control the precise category codes of the tokens.

  Read :func:`~pythonimmediate.textopy.expand_once`
  and :class:`~pythonimmediate.textopy.NTokenList` for some examples.

- See the documentation of :class:`pythonimmediate.engine.ChildProcessEngine` for ways to create a TeX engine from inside Python,
  and explanation of the ``engine=`` optional argument for most functions.

.. toctree::
   :maxdepth: 4
   :caption: Contents:

   pythonimmediate


Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
