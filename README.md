# pythonimmediate-tex

Python helper library for the `pythonimmediate` TeX package. Description of the TeX package follows.

------

Just like PerlTeX or PyLuaTeX (and unlike PythonTeX or lt3luabridge),
this only requires a single run, and variables are persistent throughout the run.

Unlike PerlTeX or PyLuaTeX, there's no restriction on compiler or script required to run the code.

There's also debugging functionalities -- TeX errors results in Python traceback, and Python error results in TeX traceback.
Errors in code executed with the `pycode` environment gives the correct traceback point to the Python line of code in the TeX file.

For advanced users, this package allows the user to manipulate the TeX state directly from within Python,
so you don't need to write a single line of TeX code.

------

### Internal note

`tex/` folder contains TeX-related files. The source code of the package is in `tex/pythonimmediate.sty`.

To create the documentation:

```
# sphinx-quickstart docs --sep -p pythonimmediate-tex -a user202729 -r '' -l en

sphinx-apidoc --full -o docs pythonimmediate
cd docs
make html
```

To autobuild the documentation

```
cd docs
sphinx-autobuild . /tmp/_build/ --watch ..
```

not that the output directory matters, just visit the documentation at `localhost:8000`.

Looks like it's not easy to write the docstrings in Markdown, see https://stackoverflow.com/q/56062402/5267751

There's some unresolved `$ is not defined` issue -- there's https://github.com/readthedocs/readthedocs.org/issues/9414 but it's unrelated

Maybe take a look at mkdocs/mkdocstrings later
