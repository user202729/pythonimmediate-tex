# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

project = 'pythonimmediate'
copyright = '2023, user202729'
author = 'user202729'

# -- set sys.path to allow Sphinx-apidoc to find the package
import os
import sys
sys.path.insert(0, os.path.abspath('..'))

# -- set special flag to signify Sphinx build
os.environ['SPHINX_BUILD'] = '1'

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

extensions = [
	'sphinx.ext.autodoc',
	'sphinx.ext.viewcode',
	'sphinx.ext.todo',
	'sphinx_rtd_theme',
	'sphinxarg.ext',
]

templates_path = ['_templates']
exclude_patterns = ['_build', 'Thumbs.db', '.DS_Store']

language = 'en'

# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_theme = 'sphinx_rtd_theme'
html_static_path = ['_static']

# -- Options for todo extension ----------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/extensions/todo.html#configuration

todo_include_todos = True


# it's also possible to define Sphinx custom roles but for just a macro something like :m:`TeX` is too long
# plus I want to be able to output rst (like a real macro...)
# written this way it only works in docstrings though
macros = {
		"[TeX]": r":math:`\TeX`",
		}

def process_line(line: str) -> str:
	for macro, replacement in macros.items():
		line = line.replace(macro, replacement)
	return line

def process_docstring(app, what, name, obj, options, lines):
	lines[:] = [process_line(line) for line in lines]

def setup(app):
	app.connect('autodoc-process-docstring', process_docstring)
	app.connect('env-before-read-docs', env_before_read_docs)

def env_before_read_docs(app, env, docnames):
	env.settings["tab_width"] = 4  # https://stackoverflow.com/a/75037587/5267751
