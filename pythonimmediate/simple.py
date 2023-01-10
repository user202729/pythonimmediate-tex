r"""
Simple interface, suitable for users who may not be aware of [TeX] subtleties, such as category codes.

This is only guaranteed to work properly in normal category code situations. In other cases, use the advanced API.

Start with reading  :func:`newcommand` and :func:`execute`.
"""

from __future__ import annotations

import sys
import inspect
from typing import Optional, Union, Callable, Any, Iterator, Protocol, Iterable, Sequence, Type, Tuple, List, Dict, TypeVar, overload
import typing
import functools
import re
from dataclasses import dataclass

import pythonimmediate
from . import scan_Python_call_TeX_module, PTTTeXLine, PTTVerbatimLine, PTTTeXLine, Python_call_TeX_local, check_line, Token, TTPEBlock, TTPEmbeddedLine, get_random_identifier, CharacterToken, define_TeX_call_Python, parse_meaning_str, peek_next_meaning, run_block_local, run_code_redirect_print_TeX, TTPBlock, TTPLine, BalancedTokenList, ControlSequenceToken
from .engine import Engine, default_engine

if not typing.TYPE_CHECKING:
	__all__ = []

T = TypeVar("T", bound=Callable)

def _export(f: T)->T:
	__all__.append(f.__name__)
	return f

@_export
def run_tokenized_line_local(line: str, *, check_braces: bool=True, check_newline: bool=True, check_continue: bool=True, engine: Engine=  default_engine)->None:
	check_line(line, braces=check_braces, newline=check_newline, continue_=(False if check_continue else None))
	typing.cast(Callable[[PTTTeXLine, Engine], None], Python_call_TeX_local(
		r"""
		\cs_new_protected:Npn %name% {
			%read_arg0(\__data)%
			\__data
			%optional_sync%
			\__read_do_one_command:
		}
		"""))(PTTTeXLine(line), engine)

@_export
def peek_next_char(engine: Engine=  default_engine)->str:
	r"""
	Get the character of the following token, or empty string if it's not a character.

	This function can be used as follows to simulate ``e``-type argument specifiers
	of ``xparse``::

		if peek_next_char()=="^":
			get_next_char()
			result = get_arg_str()
			# the following content in the input stream is ``^{...}`` and we stored the content inside to ``result``
		else:
			pass  # there's no ``^...`` following in the input stream

	It can also simulate ``s``-type argument specifier (optional star)::

		if peek_next_char()=="*":
			get_next_char()
			# there's a star
		else:
			pass  # there's no star

	It can even simulate ``o``-type argument specifier (optional argument delimited by ``[...]``)::

		if peek_next_char()=="[":
			get_next_char()  # skip the `[`
			result=""
			while True:
				if peek_next_char():
					c=get_next_char()
					if c=="]": break
					result+=c
				else:
					# following in the input stream must be a control sequence, such as `\relax`
					result+=get_arg_str()
			# now result contains the content inside the `[...]`
		else:
			pass  # there's no optional argument

	Note that the above does not take into account the balance of braces or brackets, so:

	- If the following content in the input is ``[ab{cd]ef}gh]`` then the result will be ``ab{cd``.
	- If the following content in the input is ``[ab[cd]ef]`` then the result will be ``ab[cd``.

	.. note::
		For advanced users:

		This function uses :func:`~pythonimmediate.textopy.peek_next_meaning` under the hood to get the meaning of the following token.
		See that function documentation for a warning on undefined behavior.

		Will also return nonempty if the next token is an implicit character token. This case is not supported and
		might give random error.
	"""
	r=parse_meaning_str(peek_next_meaning())
	if r is None:
		return ""
	return r[1]

@_export
def get_next_char(engine: Engine=  default_engine)->str:
	"""
	Return the character of the following token as with :func:`peek_next_char`, but also removes it from the input stream.
	"""
	result=Token.get_next(engine=engine)
	assert isinstance(result, CharacterToken), "Next token is not a character!"
	return result.chr

@_export
def put_next(arg: str, engine: Engine=  default_engine)->None:
	r"""
	Put some content forward in the input stream.

	:param arg: The content, must be a single line.

		Note that there must not be any verbatim-like commands in the argument, so for example
		``put_next(r"\verb|a|")`` is not allowed.

		If there might be verbatim-like arguments, the problem is (almost) unsolvable.
		Refer to :func:`print_TeX` or :func:`execute` for workarounds,
		or use the advanced interface such as :meth:`pythonimmediate.BalancedTokenList.put_next`.

	For example, if the following content in the input stream are ``{abc}{def}``::

		s = get_arg_str()  # s = "abc"
		t = get_arg_str()  # t = "def"
		put_next("{" + t + "}")
		put_next("{" + s + "}")
	
	After the above code, the content in the input stream is "mostly unchanged".

	.. note::
		For advanced users: the argument is tokenized in the current category regime.
	"""
	typing.cast(Callable[[PTTTeXLine, Engine], None], Python_call_TeX_local(
		r"""
		\cs_new_protected:Npn \__put_next_tmpa {
			%optional_sync%
			\__read_do_one_command:
		}
		\cs_new_protected:Npn %name% {
			%read_arg0(\__target)%
			\expandafter \__put_next_tmpa \__target
		}
		""", recursive=False))(PTTTeXLine(arg), engine)

def _replace_double_hash(s: str)->str:
	return s.replace("##", "#")

@_export
def get_arg_str(engine: Engine=  default_engine)->str:
	r"""
	Get a mandatory argument from the input stream.

	It's slightly difficult to explain what this does, so here's an example::

		@newcommand
		def foo():
			a = get_arg_str()
			b = get_arg_str()
			c = get_arg_str()

	The above defines a [TeX] function ``\foo``, if it's called in [TeX] code as::

		\foo{xx}{yy}{zz}

	then the variable ``a`` will be the string ``"xx"``, ``b`` will be ``"yy"``, and ``c`` will be ``"zz"``.

	.. _str-tokenization:

	Note on parameter tokenization
	------------------------------

	.. note::
		This function, as well as all the `_str` functions, return the argument that might be mangled in the following ways:

		- A space might be added after each command that consist of multiple characters
		- the ``^^xx`` or ``^^xxxx`` etc. notation is replaced by the character itself, or vice versa -- literal tab character might get replaced with ``^^I``
		- multiple space characters may be collapsed into one
		- newline character may become space character
		- double-newline character may become ``\par``

		For example, ``\*\hell^^6F{  }`` may become the string ``r"\*\hello { }"`` in Python.

		As such, verbatim-like commands in the argument are not supported. See :func:`get_verb_arg` for a workaround.

		Nevertheless, if the argument consist of only "normal" [TeX] commands, re-executing the string should do the same
		thing as the original code.

		In case of doubt, print out the string and check it manually.

	.. note::

		For advanced users:

		This function corresponds to the ``m``-type argument in ``xparse`` package.

		It gets the argument, detokenize it, pass it through :func:`_replace_double_hash`, and return the result.

		This is the simple API, as such it assumes normal category code values.
		Refer to :meth:`BalancedTokenList.get_next()` for a more advanced API.

	"""
	return _replace_double_hash(typing.cast(Callable[[Engine], TTPEmbeddedLine], Python_call_TeX_local(
		r"""
		\cs_new_protected:Npn %name% #1 {
			\immediate\write\__write_file { \unexpanded {
				r #1
			}}
			\__read_do_one_command:
		}
		""", recursive=False))(engine))

@_export
def get_arg_estr(engine: Engine=  default_engine)->str:
	r"""
	Get a mandatory argument from the input stream, then process it as described in :ref:`estr-expansion`.

	.. _estr-expansion:

	Note on argument expansion of ``estr``-type functions
	-----------------------------------------------------

	These functions return a string, however they're meant for strings other than [TeX] code.

	The argument is fully expanded, and any "escaped character" are passed as the character itself to Python.

	The behavior is similar to that of the ``\py`` command argument processing, see also the [TeX] package documentation.

	Some examples: After the [TeX] code ``\def\myvalue{123abc}`` is executed, then:

	- if the argument in [TeX] code is ``{abc}``, then the Python function will return ``"abc"`` (similar to as if :func:`get_arg_str` is used),
	- if the argument in [TeX] code is ``{\%a\#b\\\~}``, then the Python function will return ``r"%a#b\~"``,
	- if the argument in [TeX] code is ``{\myvalue}``, then the Python function will return ``"123abc"``.
	"""
	return typing.cast(Callable[[Engine], TTPEBlock], Python_call_TeX_local(
		r"""

		\cs_new_protected:Npn %name% #1 {
			%sync%
			%send_arg0(#1)%
			\__read_do_one_command:
		}
		""", recursive=False))(engine)

@_export
def get_optional_arg_str(engine: Engine=  default_engine)->Optional[str]:
	"""
	Get an optional argument. See also :ref:`str-tokenization`.
	
	.. note::
		For advanced users: This function corresponds to the ``o``-type argument in ``xparse`` package.
	"""
	result=typing.cast(Callable[[Engine], TTPLine], Python_call_TeX_local(
		r"""
		\NewDocumentCommand %name% {o} {
			\immediate\write \__write_file {
				r ^^J
				\IfNoValueTF {#1} {
					0
				} {
					\unexpanded{1 #1}
				}
			}
			\__read_do_one_command:
		}
		""", recursive=False))(engine)
	result_=str(result)
	if result_=="0": return None
	assert result_[0]=="1", result_
	return result_[1:]

@_export
def get_optional_arg_estr(engine: Engine=  default_engine)->Optional[str]:
	"""
	Get an optional argument. See also :ref:`estr-expansion`.
	"""
	result=typing.cast(Callable[[Engine], TTPEBlock], Python_call_TeX_local(
		r"""
		\NewDocumentCommand %name% {o} {
			%sync%
			\IfNoValueTF {#1} {
				%send_arg0(0)%
			} {
				%send_arg0(1 #1)%
			}
			\__read_do_one_command:
		}
		""", recursive=False))(engine)
	result_=str(result)
	if result_=="0": return None
	assert result_[0]=="1", result_
	return result_[1:]

@_export
def get_verb_arg(engine: Engine=  default_engine)->str:
	r"""
	Get a verbatim argument.

	Similar to ``\verb``, defined [TeX] commands that use this function
	can only be used at top level i.e. not inside any arguments.

	This function behavior is identical to ``v``-type argument in ``xparse`` package, you can use it like this::

		\foo{xx%^\?}  % delimited with braces
		\foo|xx%^\?|  % delimited with another symbol

	.. seealso::

		:func:`get_multiline_verb_arg` to support newline character in the argument.

	.. note::

		Hard TAB character in the argument gives an error until the corresponding LaTeX3 bug is fixed,
		see https://tex.stackexchange.com/q/508001/250119.
	"""
	return typing.cast(Callable[[Engine], TTPLine], Python_call_TeX_local(
		r"""
		\NewDocumentCommand %name% {v} {
			\immediate\write\__write_file { \unexpanded {
				r ^^J
				#1
			}}
			\__read_do_one_command:
		}
		""", recursive=False))(engine)

@_export
def get_multiline_verb_arg(engine: Engine=  default_engine)->str:
	r"""
	Get a multi-line verbatim argument. Usage is identical to :func:`get_verb_arg`, except newline characters
	in the argument is supported.

	.. note::
		in unusual category regime (such as that in ``\ExplSyntaxOn``), it may return wrong result.
	"""
	return typing.cast(Callable[[Engine], TTPBlock], Python_call_TeX_local(
		r"""
		\precattl_exec:n {
			\NewDocumentCommand %name% {+v} {
				\immediate\write\__write_file { r }
				\str_set:Nn \l_tmpa_tl { #1 }
				\str_replace_all:Nnn \l_tmpa_tl { \cO\^^M } { ^^J }
				\__send_block:e { \l_tmpa_tl }
				\__read_do_one_command:
			}
		}
		""", recursive=False))(engine)  # we cannot set newlinechar=13 because otherwise \__send_block:e does not work properly

def _check_function_name(name: str)->None:
	if not re.fullmatch("[A-Za-z]+", name) or (len(name)==1 and ord(name)<=0x7f):
		raise RuntimeError("Invalid function name: "+name)

T1 = typing.TypeVar("T1", bound=Callable)

class NFFunctionType(Protocol):
	@overload
	def __call__(self, name: str, f: T1, engine: Engine=default_engine)->T1: ...
	@overload
	def __call__(self, f: T1, engine: Engine=default_engine)->T1: ...  # omit name, deduced from f.__name__
	@overload
	def __call__(self, name: str, engine: Engine=default_engine)->Callable[[T1], T1]: ...  # use as decorator
	@overload
	def __call__(self, engine: Engine=default_engine)->Callable[[T1], T1]: ...  # use as decorator and omit name

def make_nf_function(wrapped: Callable[[str, Callable, Engine], None])->NFFunctionType:
	"""
	Internal helper decorator.
	"""
	def wrapped_return_identity(name: str, f: Callable, engine: Engine)->Callable:
		wrapped(name, f, engine)
		return f
	@functools.wraps(wrapped, assigned=("__name__", "__doc__"), updated=())  # the annotation is changed, exclude that from `assigned`
	def result(x: Union[str, Callable, None]=None, f: Optional[Callable]=None, engine: Engine=  default_engine)->Callable:
		if f is not None: return result(x, engine=engine)(f)
		if x is None: return functools.partial(result, engine=engine)
		if isinstance(x, str): return functools.partial(wrapped_return_identity, x, engine=engine)
		return wrapped_return_identity(x.__name__, x, engine)
	return result  # type: ignore

@_export
@make_nf_function
def newcommand(name: str, f: Callable, engine: Engine)->None:
	r"""
	Define a new [TeX]-command.

	Example::

		@newcommand
		def myfunction():
			print_TeX("Hello world!", end="")
	
	The above is mostly equivalent to ``\newcommand{\myfunction}{Hello world!}``,
	it defines a [TeX] command ``\myfunction`` that prints ``Hello world!``.

	See also documentation of :func:`print_TeX` to understand the example above.

	It can be used as either a decorator or a function::

		def myfunction():
			print_TeX("Hello world!", end="")

		newcommand("myfunction", myfunction)

	An explicit command name can also be provided::

		@newcommand("hello")
		def myfunction():
			print_TeX("Hello world!", end="")

	The above defines a [TeX] command ``\hello`` that prints ``Hello world!``.

	If name is not provided, it's automatically deduced from the Python function name.

	The above is not by itself very useful.
	Read the documentation of the following functions sequentially
	for a guide on how to define commands that take arguments:

	- :func:`get_arg_str`
	- :func:`get_arg_estr`
	- :func:`get_verb_arg`
	- :func:`get_optional_arg_str`
	- :func:`peek_next_char`
	- :func:`get_next_char`

	Then see also (as natural extensions of the above):

	- :func:`get_multiline_verb_arg`
	- :func:`get_optional_arg_estr`

	.. _trailing-newline:

	Note on trailing newline
	------------------------

	.. note::

		Regarding the ``end=""`` part in the example above, it's used to prevent a spurious space, otherwise if you run the [TeX] code::

			123\myfunction 456
		
		it will be "equivalent" to::

			123Hello world!
			456

		and the newline inserts a space.

		Internally, the feature is implemented by appending ``%`` to the last line, as most of the time the code::

			123Hello world!%
			456

		will be equivalent to::

			123Hello world!456

		but in unusual category code cases or cases of malformed [TeX] code (such as a trailing backslash at the end of the line),
		it may not be equivalent. Use the advanced API, or always include a final newline and manually add the comment character,
		if these cases happen.

	"""
	identifier=get_random_identifier()

	typing.cast(Callable[[PTTVerbatimLine, PTTVerbatimLine, Engine], None], Python_call_TeX_local(
		r"""
		\cs_new_protected:Npn %name% {
			\begingroup
				\endlinechar=-1~
				%read_arg0(\__line)%
				%read_arg1(\__identifier)%
				\cs_new_protected:cpx {\__line} {
					\unexpanded{\immediate\write \__write_file} { i \__identifier }
					\unexpanded{\__read_do_one_command:}
				}
			\endgroup
			%optional_sync%
			\__read_do_one_command:
		}
		""", recursive=False))(PTTVerbatimLine(name), PTTVerbatimLine(identifier), engine)

	_code=define_TeX_call_Python(
			lambda engine: run_code_redirect_print_TeX(f, engine=engine),
			name, argtypes=[], identifier=identifier)
	# ignore _code, already executed something equivalent in the TeX command

@_export
@make_nf_function
def renewcommand(name: str, f: Callable, engine: Engine)->None:
	r"""
	Redefine a [TeX]-command. Usage is similar to :func:`newcommand`.
	"""
	identifier=get_random_identifier()

	typing.cast(Callable[[PTTVerbatimLine, PTTVerbatimLine, Engine], None], Python_call_TeX_local(
		r"""
		\cs_new_protected:Npn %name% {
			\begingroup
				\endlinechar=-1~
				\readline \__read_file to \__line
				\readline \__read_file to \__identifier
				\exp_args:Ncx \renewcommand {\__line} {
					\unexpanded{\immediate\write \__write_file} { i \__identifier }
					\unexpanded{\__read_do_one_command:}
				}
				\exp_args:Nc \MakeRobust {\__line}  % also make the command global
			\endgroup
			%optional_sync%
			\__read_do_one_command:
		}
		""", recursive=False))(PTTVerbatimLine(name), PTTVerbatimLine(identifier), engine)
	# TODO remove the redundant entry from TeX_handlers (although technically is not very necessary, just cause slight memory leak)
	#try: del TeX_handlers["u"+name]
	#except KeyError: pass

	_code=define_TeX_call_Python(
			lambda engine: run_code_redirect_print_TeX(f, engine=engine),
			name, argtypes=[], identifier=identifier)
	# ignore _code, already executed something equivalent in the TeX command


@_export
def define_char(char: str, engine: Engine=  default_engine)->Callable[[T1], T1]:
	r"""
	Define a character to do some specific action.

	Can be used as a decorator::

		@define_char("×")
		def multiplication_sign():
			print_TeX(end=r"\times")

	.. note::
		It's **not recommended** to define commonly-used characters, for example if you define ``n``
		then commands whose name contains ``n`` cannot be used anymore.

		As another example, if you define ``-``, then commands like ``\draw (1, 2) -- (3, 4);`` in TikZ
		cannot be used.

		:func:`undefine_char` can be used to undo the effect.
	"""
	def result(f: T1)->T1:
		assert len(char)==1
		identifier=get_random_identifier()
		_code=define_TeX_call_Python(
				lambda engine: run_code_redirect_print_TeX(f, engine=engine),
				"__unused", argtypes=[], identifier=identifier)
		# ignore _code, already executed something equivalent while running the TeX command below

		if not engine.is_unicode and ord(char)>127:
			# must define u8:...
			typing.cast(Callable[[PTTVerbatimLine, PTTVerbatimLine, Engine], None], Python_call_TeX_local(
				r"""
				\cs_new_protected:Npn %name% {
					\begingroup
						\endlinechar=-1~
						\readline \__read_file to \__line
						\readline \__read_file to \__identifier
						\cs_gset_protected:cpx {u8:\__line} {
							\unexpanded{\immediate\write \__write_file} { i \__identifier }
							\unexpanded{\__read_do_one_command:}
						}
					\endgroup
					%optional_sync%
					\__read_do_one_command:
				}
				""", recursive=False))(PTTVerbatimLine(char), PTTVerbatimLine(identifier), engine)
		else:
			typing.cast(Callable[[PTTVerbatimLine, PTTVerbatimLine, Engine], None], Python_call_TeX_local(
				r"""
				\cs_new_protected:Npn %name% {
					\begingroup
						\endlinechar=-1~
						\readline \__read_file to \__line
						\readline \__read_file to \__identifier
						\global \catcode \expandafter`\__line \active
						\use:x {
							\protected \gdef
							\expandafter \expandafter \expandafter \noexpand \char_generate:nn{\expandafter`\__line}{13}
							{
								\unexpanded{\immediate\write \__write_file} { i \__identifier }
								\unexpanded{\__read_do_one_command:}
							}
						}
					\endgroup
					%optional_sync%
					\__read_do_one_command:
				}
				""", recursive=False))(PTTVerbatimLine(char), PTTVerbatimLine(identifier), engine)
		return f
	return result

@_export
def undefine_char(char: str, engine: Engine=  default_engine)->None:
	"""
	The opposite of :func:`define_char`.
	"""
	assert len(char)==1

	if not engine.is_unicode and ord(char)>127:
		# undefine u8:...
		typing.cast(Callable[[PTTVerbatimLine, Engine], None], Python_call_TeX_local(
			r"""
			\cs_new_protected:Npn %name% {
				\begingroup
					\endlinechar=-1~
					\readline \__read_file to \__line
					\cs_undefine:c {u8:\__line}
				\endgroup
				%optional_sync%
				\__read_do_one_command:
			}
			""", recursive=False))(PTTVerbatimLine(char), engine)
	else:
		# return the normal catcode for the character
		typing.cast(Callable[[PTTVerbatimLine, Engine], None], Python_call_TeX_local(
			r"""
			\precattl_exec:n {
				\cs_new_protected:Npn %name% {
					%read_arg0(\__line)%
					\global \catcode \expandafter`\__line = \cctab_item:Nn  \c_document_cctab {\expandafter`\__line} \relax
					\int_compare:nNnT {\catcode \expandafter`\__line} = {13} {
						\expandafter \token_if_eq_charcode:NNTF \__line \cO\~ {
							% restore ~'s original meaning
							\global \def \cA\~ { \nobreakspace {} }
						} {
							% not sure what to do here
							\msg_error:nn {pythonimmediate} {internal-error}
						}
					}
					%optional_sync%
					\__read_do_one_command:
				}
			}
			""", recursive=False))(PTTVerbatimLine(char), engine)

@_export
def execute(block: str, engine: Engine=default_engine)->None:
	r"""
	Run a block of [TeX]-code (might consist of multiple lines).

	A simple example is ``execute('123')`` which simply typesets ``123`` (with a trailing newline, see the note in :func:`newcommand` documentation).

	This is similar to :func:`print_TeX` but it's executed immediately, and any error is immediately reported
	with Python traceback points to the caller.

	On the other hand, because this is executed immediately, each part must be "self-contained".
	With :func:`print_TeX` you can do the following::

		print_TeX(r"\abc", end="")
		print_TeX(r"def", end="")

	and a single command ``\abcdef`` will be executed, but it does not work with this method.

	As another consequence, all :func:`execute` are done before all :func:`print_TeX` in the same block.
	For example::

		print_TeX(r"3")
		execute(r"1")
		print_TeX(r"4")
		execute(r"2")

	will typeset ``1 2 3 4``.

	.. note::

		For advanced users: it's implemented with ``\scantokens``, so catcode-changing commands are allowed inside.
	"""
	run_block_local(block, engine=engine)

@_export
def print_TeX(*args, **kwargs)->None:
	r"""
	Unlike other packages, the normal ``print()`` function prints to the console.

	This function can be used to print [TeX] code to be executed. For example::

		\begin{pycode}
		print_TeX("Hello world!")
		\end{pycode}

	It can also be used inside a custom-defined command, see the documentation of :func:`newcommand` for an example.

	The signature is identical to that of ``print()``. Passing explicit ``file=`` argument is not allowed.

	Remark: normally the ``print()`` function prints out a newline with each invocation.
	A newline will appear as a spurious space in the output
	Use ``print_TeX(end="")`` to prevent this, see :ref:`trailing-newline`.
	"""
	if not hasattr(pythonimmediate, "file"):
		raise RuntimeError("Internal error: attempt to print to TeX outside any environment!")
	if "file" in kwargs:
		raise TypeError("print_TeX() got an unexpected keyword argument 'file'")
	if pythonimmediate.file is not None:
		functools.partial(print, file=pythonimmediate.file)(*args, **kwargs)  # allow user to override `file` kwarg

@_export
@make_nf_function
def newenvironment(name: str, f: Callable, engine: Engine)->None:
	r"""
	Define a new [TeX] normal environment.

	Note that the environment will normally not have access to the body of the environment,
	see :func:`newenvironment_verb` for some alternatives.

	:param name: the name of the environment, e.g. ``"myenv"`` or ``"myenv*"``.
	:param f: a function that should execute the code for the begin part of the environment, ``yield``, then execute the code for the end part of the environment.
	:param engine: the engine to use.

	Usage example::

		@newenvironment("myenv")
		def	myenv():
			x=random.randint(1, 100)
			print_TeX(f"begin {x}")
			yield
			print_TeX(f"end {x}")

	then the following [TeX] code::

		\begin{myenv}
		\begin{myenv}
		Hello world!
		\end{myenv}
		\end{myenv}

	might typeset the following content::

		begin 42
		begin 24
		Hello world!
		end 24
		end 42

	Functions such as :func:`get_arg_str` etc. can also be used in the first part of the function
	to take arguments.

	If the name is omitted, the function name is used as the environment name.

	It can be used either as a decorator or a function, see :func:`newcommand` for details.
	"""
	begin_identifier=get_random_identifier()
	end_identifier=get_random_identifier()

	typing.cast(Callable[[PTTVerbatimLine, PTTVerbatimLine, PTTVerbatimLine, Engine], None], Python_call_TeX_local(
		r"""
		\cs_new_protected:Npn %name% {
			%read_arg0(\__line)%
			%read_arg1(\__begin_identifier)%
			%read_arg2(\__end_identifier)%
			\use:x {
				\noexpand\newenvironment
					{\__line}
					{
						\unexpanded{\immediate\write \__write_file} { i \__begin_identifier }
						\unexpanded{\__read_do_one_command:}
					}
					{
						\unexpanded{\immediate\write \__write_file} { i \__end_identifier }
						\unexpanded{\__read_do_one_command:}
					}
			}
			%optional_sync%
			\__read_do_one_command:
		}
		""", recursive=False))(PTTVerbatimLine(name), PTTVerbatimLine(begin_identifier), PTTVerbatimLine(end_identifier), engine)


	pending_objects=[]  # nonlocal mutable, create one for each environment

	def begin_f():
		a=f()
		next(a)
		pending_objects.append(a)

	def end_f():
		a=pending_objects.pop()
		try:
			next(a)
			assert False, "Function must yield exactly once!"
		except StopIteration:
			pass

	_code=define_TeX_call_Python(
			lambda engine: run_code_redirect_print_TeX(begin_f, engine=engine),
			"__unused", argtypes=[], identifier=begin_identifier)
	_code=define_TeX_call_Python(
			lambda engine: run_code_redirect_print_TeX(end_f, engine=engine),
			"__unused", argtypes=[], identifier=end_identifier)
	# ignore _code, already executed something equivalent in the TeX command

@_export
@make_nf_function
def newenvironment_verb(name: str, f: Callable[[str], None], engine: Engine)->None:
	r"""
	Define a new [TeX] environment that reads its body verbatim.

	Note that space characters at the end of each line are removed.

	The environment must not take any argument. For example the following built-in ``tabular`` environment takes some argument, so cannot be implemented with this function:

	.. code-block:: latex

		\begin{tabular}[t]
			...
		\end{tabular}

	It can be used either as a decorator or a function, see :func:`newenvironment` for details.

	Some usage example::

		@newenvironment_verb("myenv")
		def myenv(body: str):
			execute(body.replace("a", "b"))

	If later the following [TeX] code is executed:

	.. code-block:: latex
	
		\begin{myenv}
		aaa
		\end{myenv}

	then the value of the variable ``body`` will be ``"aaa\n"``, and the following content will be typeset::
	
		bbb

	.. note::
		For advanced users: unlike a typical environment, the code will not be executed in a new [TeX] *group*.
	"""
	identifier=get_random_identifier()

	typing.cast(Callable[[PTTVerbatimLine, PTTVerbatimLine, Engine], None], Python_call_TeX_local(
		r"""
		\cs_new_protected:Npn %name% {
			%read_arg0(\__line)%
			%read_arg1(\__identifier)%
			\use:x {
				\noexpand\newenvironment
					{\__line}
					{
						\immediate\write \noexpand\__write_file { i \__identifier }
						\noexpand\__read_do_one_command:
					}
					{}
			}
			%optional_sync%
			\__read_do_one_command:
		}
		""", recursive=False))(PTTVerbatimLine(name), PTTVerbatimLine(identifier), engine)

	def f1():
		body=typing.cast(Callable[[Engine], TTPBlock], Python_call_TeX_local(
			r"""
			\cs_new_protected:Npn %name% {
				\saveenvreinsert \__tmp {
					%sync%
					\__send_block:e {\__tmp}
					\__read_do_one_command:
				}
			}
			""", recursive=False))(engine)
		f(body)

	_code=define_TeX_call_Python(
			lambda engine: run_code_redirect_print_TeX(f1, engine=engine),
			"__unused", argtypes=[], identifier=identifier)


@dataclass
class VarManager:
	engine: Engine

	def __call__(self, engine: Engine)->VarManager:
		"""
		Shorthand to bind to another engine.
		"""
		return VarManager(engine)

	def __getitem__(self, key: str)->str:
		"""
		Get the value of a variable.
		"""
		return _replace_double_hash(
				BalancedTokenList([ControlSequenceToken(key)])
				.expand_o(engine=self.engine)
				.detokenize(engine=self.engine)
				)

	def __setitem__(self, key: str, val: str)->None:
		"""
		Set the value of a variable.
		"""
		return typing.cast(Callable[[PTTVerbatimLine, PTTTeXLine, Engine], None], Python_call_TeX_local(
			r"""
			\cs_new_protected:Npn %name% {
				%read_arg0(\__line)%
				%read_arg1(\__value)%
				\tl_set_eq:cN {\__line} \__value
				%optional_sync%
				\__read_do_one_command:
			}
			""", recursive=False, sync=None))(PTTVerbatimLine(key), PTTTeXLine(val), self.engine)


var=VarManager(default_engine)
r"""
Can be used like this::

	var["myvar"]="myvalue"  # "equivalent" to \def\myvar{myvalue}
	var["myvar"]=r"\textbf{123}"  # "equivalent" to \def\myvar{\textbf{123}}
	var["myvar"]=r"\def\test#1{#1}"  # "equivalent" to \tl_set:Nn \myvar {\def\test#1{#1}}  (note that `#` doesn't need to be doubled here unlike in `\def`)
	var(engine)["myvar"]="myvalue"  # pass explicit engine
	print(var["myvar"])  # get the value of the variable, return a string

Notes in :ref:`str-tokenization` apply -- in other words, after you set a value it may become slightly different when read back.
"""
__all__.append("var")

scan_Python_call_TeX_module(__name__)
