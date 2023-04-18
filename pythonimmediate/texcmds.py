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

"""

from . import*

@define_internal_handler
def py(code: TTPEBlock, engine: Engine)->None:
	r"""
	Evaluate some Python code provided as an argument and typeset the result as [TeX] code.
	For example ``\py{1+1}`` will typeset 2.

	The code is evaluated as if with ``eval()``, so assignments such as ``a=1`` is not suitable here.
	Use :meth:`pyc` instead.
	"""
	pythonimmediate.run_block_finish(str(eval_with_linecache(
		code.lstrip(),
		user_scope))+"%", engine=engine)
	# note we use code.lstrip() here because otherwise
	# \py{
	# 1+1}
	# would give IndentationError

@define_internal_handler
def pyfile(filepath: TTPELine, engine: Engine)->None:
	r"""
	Execute a Python file from `filepath`, as if with :func:`pyc` or :func:`pycode`.

	Example: ``\pyfile{a/b.py}``
	"""
	with open(filepath, "r") as f:
		source=f.read()
	run_code_redirect_print_TeX(lambda: exec(compile(source, filepath, "exec"), user_scope), engine=engine)

@define_internal_handler
def pyfilekpse(filename: TTPELine, engine: Engine)->None:
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
	run_code_redirect_print_TeX(lambda: exec(compile(source, filepath, "exec"), {"__file__": filepath, "user_scope": user_scope}), engine=engine)

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

def pycode(code: TTPBlock, lineno_: TTPLine, filename: TTPLine, fileabspath: TTPLine, engine: Engine)->None:
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

		[TeX] might mangle the code a bit before passing it to Python, as such we use :func:`.can_be_mangled_to`
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
		if len(file_lines)==len(code_lines):
			for file_line, code_line in zip(file_lines, code_lines):
				if not can_be_mangled_to(file_line, code_line):
					debug(f"different {file_line!r} {code_line!r}")
		raise RuntimeError(f"Source file not found! (cwd={os.getcwd()}, attempted {(fileabspath, filename)})")

	def tmp()->None:
		if target_filename:
			code_=''.join(file_lines)  # restore missing trailing spaces
		code_="\n"*(lineno-len(code_lines)-1)+code_
		if target_filename:
			compiled_code=compile(code_, target_filename, "exec")
			exec(compiled_code, user_scope)
		else:
			exec(code_, user_scope)
	run_code_redirect_print_TeX(tmp, engine=engine)
	
bootstrap_code_functions.append(define_TeX_call_Python(pycode, name="__pycodex"))

@define_internal_handler
def pyc(code: TTPEBlock, engine: Engine)->None:
	r"""
	Execute some Python code provided as an argument, typeset whatever resulted by :func:`.print_TeX`.

	The Python code is absorbed as described in :ref:`estr-expansion`.

	The code is evaluated as if with ``exec()``, so assignments such as ``\pyc{a=1}`` can be used.
	Nevertheless, for long code :meth:`
	Use :meth:`pyc` instead.
	"""
	run_code_redirect_print_TeX(lambda: exec_with_linecache(code, user_scope), engine=engine)

@define_internal_handler
def pycq(code: TTPEBlock, engine: Engine)->None:
	"""
	Similar to :meth:`pyc`, however any output by :meth:`print_TeX` is suppressed.
	"""
	with RedirectPrintTeX(None):
		exec_with_linecache(code, user_scope)
	run_none_finish(engine)

mark_bootstrap(
r"""
\NewDocumentCommand\pyv{v}{\py{#1}}
\NewDocumentCommand\pycv{v}{\pyc{#1}}
""")


scan_Python_call_TeX_module(__name__)
