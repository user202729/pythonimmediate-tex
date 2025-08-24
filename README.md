# pythonimmediate-tex

[![PyPI](https://img.shields.io/pypi/v/pythonimmediate-tex?style=flat)](https://pypi.python.org/pypi/pythonimmediate-tex/)
[![Read the Docs](https://img.shields.io/readthedocs/pythonimmediate)](https://pythonimmediate.readthedocs.io)
[![CTAN](https://img.shields.io/ctan/l/pythonimmediate)](https://ctan.org/pkg/pythonimmediate)

A library to facilitate bidirectional communication between Python and TeX,
with support of manipulating TeX tokens as Python objects.

Background: this library started as...
* I get annoyed at programming in TeX and want to use a proper programming language, and
* Almost all the current packages that allow programming in Python runs a separate Python pass from TeX,
which requires using temporary file and
* `pythontex` does not work on Overleaf.

Thus, the library name is named after the second point -- the `python` and `tex` process are run in parallel,
bidirectional communications are supported.

Since then, the library has grown considerably, although not in a particular direction, as I add features when I need it.
Occasionally (but rarely), refactors are done.

As such, I don't guarantee any particular use case for this library -- except for my own use cases.
Along the way, I added some useful features to use Python inside packages. (`\pycodekpse`)

A handful of my packages are written using this library, directly or indirectly. (`typstmathinput`, `unicode-math-input`)

------

The TeX package is available on CTAN: https://ctan.org/pkg/pythonimmediate

The Python package is available on PyPI: https://pypi.org/project/pythonimmediate-tex/
with documentation on Read the Docs: https://pythonimmediate.readthedocs.io

------

Description of the TeX package follows.

> Just like PerlTeX or PyLuaTeX (and unlike PythonTeX or lt3luabridge),
> this only requires a single run, and variables are persistent throughout the run.
> 
> Unlike PerlTeX or PyLuaTeX, there's no restriction on compiler or script required to run the code.
> 
> There's also debugging functionalities -- TeX errors results in Python traceback, and Python error results in TeX traceback.
> Errors in code executed with the `pycode` environment gives the correct traceback point to the Python line of code in the TeX file.
> 
> For advanced users, this package allows the user to manipulate the TeX state directly from within Python,
> so you don't need to write a single line of TeX code.

------

### Internal note

To test, run `pytest`. This will also run `mypy` type checking, although not benchmark.

`pytest` also runs, as part of `test_subprocess`, TeX engines (all 3) on the file `tex/test/test_pythonimmediate.tex`.
One may also run this manually.

To test on Overleaf, follow the instructions in the TeX package documentation and compile `tex/test/test_pythonimmediate.tex`.

`tex/` folder contains TeX-related files. The source code of the package is in `tex/pythonimmediate.sty`.

To create the documentation:

```
# sphinx-quickstart docs --sep -p pythonimmediate-tex -a user202729 -r '' -l en

rm docs/pythonimmediate*.rst
SPHINX_APIDOC_OPTIONS='members,show-inheritance' sphinx-apidoc --separate --full --no-toc -o docs pythonimmediate
cd docs
make html
```

To autobuild the documentation

```
cd docs
./run-sphinx-autobuild
```

To create a tag

```
git tag 0.3.0
git push --tags
```

not that the output directory matters, just visit the documentation at `localhost:8000`.

Looks like it's not easy to write the docstrings in Markdown, see https://stackoverflow.com/q/56062402/5267751

There's some unresolved `$ is not defined` issue -- there's https://github.com/readthedocs/readthedocs.org/issues/9414 but it's unrelated

Maybe take a look at mkdocs/mkdocstrings later
