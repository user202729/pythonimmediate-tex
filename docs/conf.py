# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

from typing import Any

project = 'pythonimmediate'
copyright = '2024, user202729'
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

autodoc_type_aliases = {
		'DimensionUnit': 'DimensionUnit',
		'EngineName': 'EngineName',
		}
autodoc_typehints_format = 'short'
python_use_unqualified_type_names = True

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

def process_docstring(app: Any, what: str, name: str, obj: Any, options: Any, lines: list[str]) -> None:
	lines[:] = [process_line(line) for line in lines]

from contextlib import suppress
from docutils import nodes
from sphinx import addnodes
from sphinx.errors import NoUri
from sphinx.transforms.post_transforms import SphinxPostTransform
from sphinx.util import logging

logger = logging.getLogger(__name__)

# https://stackoverflow.com/a/62782264/5267751
class MyLinkWarner(SphinxPostTransform):
	default_priority = 5

	def run(self, **kwargs: Any)->None:
		for node in self.document.traverse(addnodes.pending_xref):
			target = node["reftarget"]

			if target.startswith("pythonimmediate."):
				found_ref = False

				with suppress(NoUri, KeyError):
					# let the domain try to resolve the reference
					found_ref = self.env.domains[node["refdomain"]].resolve_xref(
							self.env,
							node.get("refdoc", self.env.docname),
							self.app.builder,
							node["reftype"],
							target,
							node,
							nodes.TextElement("", ""),
							)

				# warn if resolve_xref did not return or raised
				if not found_ref:
					logger.warning(
							f"API link {target} is broken.", location=node, type="ref"
							)

def setup(app: Any)->None:
	app.connect('autodoc-process-docstring', process_docstring)
	app.connect('env-before-read-docs', env_before_read_docs)
	app.add_post_transform(MyLinkWarner)

def env_before_read_docs(app: Any, env: Any, docnames: Any)->None:
	env.settings["tab_width"] = 4  # https://stackoverflow.com/a/75037587/5267751
