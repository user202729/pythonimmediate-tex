r"""
This module defines the [TeX] commands and environments that will be available globally when the module is loaded.

The way the argument is absorbed is shown in the type annotation of the function, for example:

* if the type is :class:`.TTPELine` or :class:`.TTPEBlock` then the argument is expanded according to :ref:`estr-expansion`.
* if the type is :class:`.TTPLine` or :class:`.TTPBlock` then the argument is not expanded, but the tokenization
  may change the form of the argument, refer to :ref:`str-tokenization`.

For example, the argument of :func:`py` has annotated type :class:`.TTPEBlock`, which means you can do the following:

.. code-block:: latex

	\def\myvalue{1+2}
	\py{\myvalue}

and the Python code ``1+2`` will be executed and ``3`` printed in [TeX].

Some command are not documented here, refer to:

* :func:`.add_handler` for ``\pythonimmediatecallhandler`` and ``\pythonimmediatelisten``.
* :func:`.continue_until_passed_back` and :func:`.continue_until_passed_back_str`
  for ``\pythonimmediatecontinue`` and ``\pythonimmediatecontinuenoarg``.

"""

from __future__ import annotations

import os
from typing import Optional
from pathlib import Path

from . import RedirectPrintTeX, get_user_scope, run_code_redirect_print_TeX
from .lowlevel import define_TeX_call_Python, run_none_finish, scan_Python_call_TeX_module, TTPLine, define_internal_handler, eval_with_linecache, exec_with_linecache, TTPEBlock, TTPBlock, TTPELine, can_be_mangled_to, mark_bootstrap

@define_internal_handler
def py(code: TTPEBlock)->None:
	r"""
	Evaluate some Python code provided as an argument and typeset the result as [TeX] code.
	For example ``\py{1+1}`` will typeset 2.

	The code is evaluated as if with ``eval()``, so assignments such as ``a=1`` is not suitable here.
	Use :meth:`pyc` instead.
	"""
	from . import _run_block_finish
	_run_block_finish(str(eval_with_linecache(
		code.lstrip(),
		get_user_scope()))+"%")
	# note we use code.lstrip() here because otherwise
	# \py{
	# 1+1}
	# would give IndentationError

@define_internal_handler
def pyfile(filepath: TTPELine)->None:
	r"""
	Execute a Python file from `filepath`, as if with :func:`pyc` or :func:`pycode`.

	Example: ``\pyfile{a/b.py}``
	"""
	with open(filepath, "r") as f:
		source=f.read()
	run_code_redirect_print_TeX(lambda: exec(compile(source, filepath, "exec"), get_user_scope()))

@define_internal_handler
def pyfilekpse(filename: TTPELine)->None:
	r"""
	Given a file name, use ``kpsewhich`` executable to search for its full path, then execute the file at that path.

	This function is meant for library author wanting to execute Python code stored in separate file.

	Example: ``\pyfilekpse{a.py}`` where ``a.py`` is stored along with the ``.sty`` files.
	Running ``kpsewhich a.py`` on the command-line should give the full path to it.
	"""
	import subprocess
	filepath=subprocess.run(["kpsewhich", str(filename)], stdout=subprocess.PIPE, check=True).stdout.decode('u8').rstrip("\n")
	with open(filepath, "r") as f:
		source=f.read()
	run_code_redirect_print_TeX(lambda: exec(compile(source, filepath, "exec"), {"__file__": filepath, "user_scope": get_user_scope()}))

# ======== implementation of ``pycode`` environment
mark_bootstrap(
r"""
\NewDocumentEnvironment{pycode}{}{
	\saveenvreinsert \__code {
		\exp_last_unbraced:Nx \__pycodex {{\__code} {\the\inputlineno} {
			\ifdefined\currfilename \currfilename \fi
		} {
			\ifdefined\currfileabspath \currfileabspath \fi
		}}
	}
}{
	\endsaveenvreinsert
}
""")

def pycode(code: TTPBlock, lineno_: TTPLine, filename: TTPLine, fileabspath: TTPLine)->None:
	r"""
	A [TeX] environment to execute some Python code. Must be used at top-level, and content can be verbatim.

	If the code inside causes any error, the error traceback will point to the correct line in the [TeX] file.

	Example:

	.. code-block:: latex

		\begin{pycode}
		a = 1
		b = 2
		\end{pycode}

	
	.. note::
		Internal note:

		The Python function itself is an auxiliary function.

		The ``code`` is not executed immediately, instead we search for the source [TeX] file that contains the code
		(it must be found, otherwise an error is thrown), then read the source from that file.

		[TeX] might mangle the code a bit before passing it to Python, as such we use :func:`~.lowlevel.can_be_mangled_to`
		(might return some false positive)
		to compare it with the code read from the sourcecode.
	"""
	if not code: return

	lineno=int(lineno_)
	# find where the code comes from... (for easy meaningful traceback)
	target_filename: Optional[str] = None

	code_lines=code.splitlines(keepends=True)
	file_lines=[]

	for f in (fileabspath, filename):
		if not f: continue
		p=Path(f)
		if not p.is_file(): continue
		file_lines=p.read_text(encoding='u8').splitlines(keepends=True)[lineno-len(code_lines)-1:lineno-1]
		if len(file_lines)==len(code_lines) and all(
			can_be_mangled_to(file_line, code_line) for file_line, code_line in zip(file_lines, code_lines)
			):
			target_filename=f
			break

	if not target_filename:
		#if len(file_lines)==len(code_lines):
		#	for file_line, code_line in zip(file_lines, code_lines):
		#		if not can_be_mangled_to(file_line, code_line):
		#			debug(f"different {file_line!r} {code_line!r}")
		raise RuntimeError(f"Source file not found! (cwd={os.getcwd()}, attempted {(fileabspath, filename)})")

	def tmp()->None:
		if target_filename:
			code_=''.join(file_lines)  # restore missing trailing spaces
		code_="\n"*(lineno-len(code_lines)-1)+code_
		if target_filename:
			compiled_code=compile(code_, target_filename, "exec")
			exec(compiled_code, get_user_scope())
		else:
			exec(code_, get_user_scope())
	run_code_redirect_print_TeX(tmp)
	
mark_bootstrap(define_TeX_call_Python(pycode, name="__pycodex"))

def pycodefuzzy(code: TTPBlock, lineno_: TTPLine)->None:
	r"""
	Same as :func:`pycode`, but may mangle the code (strip trailing spaces, etc. Refer to :func:`~.lowlevel.can_be_mangled_to` for technical details).
	Not recommended unless you don't have ``[abspath]currfile`` package loaded.
	"""
	if not code: return
	lineno=int(lineno_)
	code_lines=code.splitlines(keepends=True)
	def tmp()->None:
		code_="\n"*(lineno-len(code_lines)-1)+code
		exec(code_, get_user_scope())
	run_code_redirect_print_TeX(tmp)

mark_bootstrap(define_TeX_call_Python(pycodefuzzy, name="__pycodefuzzyx"))
mark_bootstrap(
r"""
\NewDocumentEnvironment{pycodefuzzy}{}{
	\saveenvreinsert \__code {
		\exp_last_unbraced:Nx \__pycodefuzzyx {{\__code} {\the\inputlineno}}
	}
}{
	\endsaveenvreinsert
}
""")


@define_internal_handler
def pyc(code: TTPEBlock)->None:
	r"""
	Execute some Python code provided as an argument, typeset whatever resulted by :func:`.print_TeX`.

	The Python code is absorbed as described in :ref:`estr-expansion`.

	The code is evaluated as if with ``exec()``, so assignments such as ``\pyc{a=1}`` can be used.
	Nevertheless, for long code :meth:`
	Use :meth:`pyc` instead.
	"""
	run_code_redirect_print_TeX(lambda: exec_with_linecache(code, get_user_scope()))

@define_internal_handler
def pycq(code: TTPEBlock)->None:
	"""
	Similar to :meth:`pyc`, however any output by :func:`.print_TeX` is suppressed.
	"""
	with RedirectPrintTeX(None):
		exec_with_linecache(code, get_user_scope())
	run_none_finish()

mark_bootstrap(
r"""
\NewDocumentCommand\pyv{v}{\py{#1}}
\NewDocumentCommand\pycv{v}{\pyc{#1}}
""")


scan_Python_call_TeX_module(__name__)
