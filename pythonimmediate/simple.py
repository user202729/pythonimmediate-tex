r"""
Simple interface, suitable for users who may not be aware of [TeX] subtleties, such as category codes.

This is only guaranteed to work properly in normal category code situations
(in other words, ``\makeatletter`` or ``\ExplSyntaxOn`` are not officially supported).
In all other cases, use the advanced API.

Nevertheless, there are still some parts that you must be aware of:

*   Any "output", resulted from any command related to Python, can only be used to typeset text,
	it must not be used to pass "values" to other [TeX] commands.

	This is already mentioned in the documentation of the [TeX] file in ``\py`` command, just repeated here.

	For example:

	.. code-block:: latex

		\py{1+1}  % legal, typeset 2

		\setcounter{abc}{\py{1+1}}  % illegal

		% the following is still illegal no many how many ``\expanded`` and such are used
		\edef\tmp{\py{1+1}}
		\setcounter{abc}{\tmp}

		\py{ r'\\setcounter{abc}{' + str(1+1) + '}' }  % legal workaround

	Similar for commands defined with :func:`newcommand`::

		@newcommand
		def test():
			print_TeX("123", end="")

	Then the [TeX] code:

	.. code-block:: latex

		The result is \test.  % legal, typesets "123"
		\setcounter{abc}{\test}  % illegal

*   There's the function :func:`fully_expand`, but some [TeX] commands cannot be used inside this.

	Refer to the :ref:`expansion-issue` section for more details.

*   Regarding values being passed from [TeX] to Python, you can do one of the following:

	* Either simply do ``\py{value = r'''#1'''}``, or
	* ``\py{value = get_arg_str()}{#1}``.

	You can easily see both forms are equivalent, except that in the first form, ``#1`` cannot end with unbalanced ``\``
	or contain triple single quotes.


Start with reading :func:`newcommand` and :func:`execute`. Then read the rest of the functions in this module.
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
from . import Token, parse_meaning_str, peek_next_meaning, run_code_redirect_print_TeX, BalancedTokenList, TokenList, ControlSequenceToken, doc_catcode_table, Catcode, T, ControlSequenceToken, group, UnbalancedTokenListError, CharacterToken
from .lowlevel import scan_Python_call_TeX_module, PTTVerbatimLine, PTTTeXLine, Python_call_TeX_local, check_line, get_random_Python_identifier, TTPEBlock, TTPEmbeddedLine, define_TeX_call_Python, run_block_local, TTPBlock, TTPLine
from .engine import Engine, default_engine, default_engine as engine, TeXProcessExited

if not typing.TYPE_CHECKING:
	__all__ = []

def default_get_catcode(x: int)->Catcode:
	return doc_catcode_table.get(x, Catcode.other)

def _export(f: T2)->T2:
	__all__.append(f.__name__)  # type: ignore
	return f

@_export
def peek_next_char()->str:
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

		This function uses :func:`~pythonimmediate.peek_next_meaning` under the hood to get the meaning of the following token.
		See that function documentation for a warning on undefined behavior.

		Will also return nonempty if the next token is an implicit character token. This case is not supported and
		might give random error.
	"""
	r=parse_meaning_str(peek_next_meaning())
	if r is None:
		return ""
	return r[1]

@_export
def get_next_char()->str:
	"""
	Return the character of the following token as with :func:`peek_next_char`, but also removes it from the input stream.
	"""
	result=Token.get_next()
	assert isinstance(result, CharacterToken), "Next token is not a character!"
	return result.chr

@_export
def put_next(arg: str)->None:
	r"""
	Put some content forward in the input stream.

	:param arg: The content, must be a single line.

		Note that there must not be any verbatim-like commands in the argument, so for example
		``put_next(r"\verb|a|")`` is not allowed.

		If there might be verbatim-like arguments, the problem is (almost) unsolvable.
		Refer to :func:`print_TeX` or :func:`execute` for workarounds,
		or use the advanced interface such as :meth:`pythonimmediate.BalancedTokenList.put_next`.

	For example::

		>>> put_next("{abc}")
		>>> put_next("{def}")
		>>> get_arg_str()
		'def'
		>>> get_arg_str()
		'abc'

	.. note::
		For advanced users: the argument is tokenized in the current category regime.
	"""
	typing.cast(Callable[[PTTTeXLine], None], Python_call_TeX_local(
		r"""
		\cs_new_protected:Npn \__put_next_tmpa {
			%optional_sync%
			\pythonimmediatelisten
		}
		\cs_new_protected:Npn %name% {
			%read_arg0(\__target)%
			\expandafter \__put_next_tmpa \__target
		}
		""", recursive=False))(PTTTeXLine(arg))

def _replace_double_hash(s: str)->str:
	return s.replace("##", "#")

def _replace_par_to_crcr(s: str)->str:
	return s.replace("\\par ", "\n\n")

@_export
def get_arg_str()->str:
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
		- literally-typed ``\par`` in the source code may become double-newline character. (however you should never literally type ``\\par`` in the source code anyway he)
		- Even something like ``\\par`` in the source code may become double-newline character. (this is rare)

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
		Refer to :meth:`~pythonimmediate.BalancedTokenList.get_next()` for a more advanced API.

	"""
	return _replace_par_to_crcr(_replace_double_hash(typing.cast(Callable[[], TTPEmbeddedLine], Python_call_TeX_local(
		r"""
		\cs_new_protected:Npn %name% #1 {
			\__send_content%naive_send%:n {
				r #1
			}
			\pythonimmediatelisten
		}
		""", recursive=False))()))

@_export
def get_arg_estr()->str:
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
	return typing.cast(Callable[[], TTPEBlock], Python_call_TeX_local(
		r"""

		\cs_new_protected:Npn %name% #1 {
			%sync%
			%send_arg0(#1)%
			\pythonimmediatelisten
		}
		""", recursive=False))()

@_export
def get_optional_arg_str()->Optional[str]:
	"""
	Get an optional argument. See also :ref:`str-tokenization`.
	
	.. note::
		For advanced users: This function corresponds to the ``o``-type argument in ``xparse`` package.
	"""
	result=typing.cast(Callable[[], TTPLine], Python_call_TeX_local(
		r"""
		\NewDocumentCommand %name% {o} {
			\__send_content%naive_send%:e {
				r ^^J
				\IfNoValueTF {#1} {
					0
				} {
					\unexpanded{1 #1}
				}
			}
			\pythonimmediatelisten
		}
		""", recursive=False))()
	result_=str(result)
	if result_=="0": return None
	assert result_[0]=="1", result_
	return result_[1:]

@_export
def get_optional_arg_estr()->Optional[str]:
	"""
	Get an optional argument. See also :ref:`estr-expansion`.
	"""
	result=typing.cast(Callable[[], TTPEBlock], Python_call_TeX_local(
		r"""
		\NewDocumentCommand %name% {o} {
			%sync%
			\IfNoValueTF {#1} {
				%send_arg0(0)%
			} {
				%send_arg0(1 #1)%
			}
			\pythonimmediatelisten
		}
		""", recursive=False))()
	result_=str(result)
	if result_=="0": return None
	assert result_[0]=="1", result_
	return result_[1:]

@_export
def get_verb_arg()->str:
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
	return typing.cast(Callable[[], TTPLine], Python_call_TeX_local(
		r"""
		\NewDocumentCommand %name% {v} {
			\__send_content%naive_send%:n {
				r ^^J
				#1
			}
			\pythonimmediatelisten
		}
		""", recursive=False))()

@_export
def get_multiline_verb_arg()->str:
	r"""
	Get a multi-line verbatim argument. Usage is identical to :func:`get_verb_arg`, except newline characters
	in the argument is supported.

	.. note::
		in unusual category regime (such as that in ``\ExplSyntaxOn``), it may return wrong result.
	"""
	# obeyedline: breaking change from https://tex.stackexchange.com/a/722462/250119
	return typing.cast(Callable[[], TTPBlock], Python_call_TeX_local(
		r"""
		\precattl_exec:n {
			\NewDocumentCommand %name% {+v} {
				\__send_content:e { r }
				\str_set:Nn \l_tmpa_tl { #1 }
				\str_replace_all:Nnn \l_tmpa_tl { \obeyedline } { ^^J }
				\__send_block%naive_send%:e { \l_tmpa_tl }
				\pythonimmediatelisten
			}
		}
		""", recursive=False))()  # we cannot set newlinechar=13 because otherwise \__send_block:e does not work properly

def _check_name(name: str)->None:
	"""
	Internal function, check if user provide a valid name (that can be given in a "normal" control sequence)
	"""
	if any(default_get_catcode(ord(ch))!=Catcode.letter for ch in name):
		raise RuntimeError("Invalid name: \\"+name)

T2 = typing.TypeVar("T2", bound=Callable)

class NFFunctionType(Protocol):
	@overload
	def __call__(self, name: str, f: T2)->T2: ...
	@overload
	def __call__(self, f: T2)->T2: ...  # omit name, deduced from f.__name__
	@overload
	def __call__(self, name: str)->Callable[[T2], T2]: ...  # use as decorator
	@overload
	def __call__(self)->Callable[[T2], T2]: ...  # use as decorator and omit name

def make_nf_function(wrapped: Callable[[str, Callable], None])->NFFunctionType:
	"""
	Internal helper decorator.

	Make a function usable like both a function and a decorator that accepts the same kind of arguments as :func:`newcommand`.

	In particular it requires an optional *name* and a mandatory *function*, which may be taken in a single call
	or by argument currying/applying decorator.

	See the documentation of :func:`newcommand` for more details on how the possible ways the resulting command can be used.
	"""
	def wrapped_return_identity(name: str, f: Callable)->Callable:
		wrapped(name, f)
		return f
	@functools.wraps(wrapped, assigned=("__name__", "__doc__"), updated=())  # the annotation is changed, exclude that from `assigned`
	def result(x: Union[str, Callable, None]=None, f: Optional[Callable]=None)->Callable:
		if f is not None: return result(x)(f)
		if x is None: return functools.partial(result)
		if isinstance(x, str): return functools.partial(wrapped_return_identity, x)
		return wrapped_return_identity(x.__name__, x)
	return result  # type: ignore

@_export
@make_nf_function
def newcommand(name: str, f: Callable)->None:
	r"""
	Define a new [TeX]-command.

	The corresponding advanced API is :meth:`.Token.set_func`.

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
	_check_name(name)
	identifier=get_random_Python_identifier()

	typing.cast(Callable[[PTTVerbatimLine, PTTVerbatimLine], None], Python_call_TeX_local(
		r"""
		\cs_new_protected:Npn %name% {
			\begingroup
				\endlinechar=-1~
				%read_arg0(\__line)%
				%read_arg1(\__identifier)%
				\cs_new_protected:cpx {\__line} {
					\__send_content%naive_send%:e { i \__identifier }
					\unexpanded{\pythonimmediatelisten}
				}
			\endgroup
			%optional_sync%
			\pythonimmediatelisten
		}
		""", recursive=False))(PTTVerbatimLine(name), PTTVerbatimLine(identifier))

	_code=define_TeX_call_Python(
			lambda: run_code_redirect_print_TeX(f),
			name, argtypes=[], identifier=identifier)
	# ignore _code, already executed something equivalent in the TeX command

@_export
@make_nf_function
def renewcommand(name: str, f: Callable)->None:
	r"""
	Redefine a [TeX]-command. Usage is similar to :func:`newcommand`.
	"""
	_check_name(name)
	identifier=get_random_Python_identifier()

	typing.cast(Callable[[PTTVerbatimLine, PTTVerbatimLine], None], Python_call_TeX_local(
		r"""
		\cs_new_protected:Npn %name% {
			\begingroup
				\endlinechar=-1~
				\readline \__read_file to \__line
				\readline \__read_file to \__identifier
				\exp_args:Ncx \renewcommand {\__line} {
					\__send_content%naive_send%:e { i \__identifier }
					\unexpanded{\pythonimmediatelisten}
				}
				\exp_args:Nc \MakeRobust {\__line}  % also make the command global
			\endgroup
			%optional_sync%
			\pythonimmediatelisten
		}
		""", recursive=False))(PTTVerbatimLine(name), PTTVerbatimLine(identifier))
	# TODO remove the redundant entry from TeX_handlers (although technically is not very necessary, just cause slight memory leak)
	#try: del TeX_handlers["u"+name]
	#except KeyError: pass

	_code=define_TeX_call_Python(
			lambda: run_code_redirect_print_TeX(f),
			name, argtypes=[], identifier=identifier)
	# ignore _code, already executed something equivalent in the TeX command


@_export
def define_char(char: str)->Callable[[T2], T2]:
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
	def result(f: T2)->T2:
		assert len(char)==1
		identifier=get_random_Python_identifier()
		_code=define_TeX_call_Python(
				lambda: run_code_redirect_print_TeX(f),
				f"(char: {char})", argtypes=[], identifier=identifier)
		# ignore _code, already executed something equivalent while running the TeX command below

		if not engine.is_unicode and ord(char)>127:
			# must define u8:...
			typing.cast(Callable[[PTTVerbatimLine, PTTVerbatimLine], None], Python_call_TeX_local(
				r"""
				\cs_new_protected:Npn %name% {
					\begingroup
						\endlinechar=-1~
						\readline \__read_file to \__line
						\readline \__read_file to \__identifier
						\cs_gset_protected:cpx {u8:\__line} {
							\__send_content%naive_send%:e { i \__identifier }
							\unexpanded{\pythonimmediatelisten}
						}
					\endgroup
					%optional_sync%
					\pythonimmediatelisten
				}
				""", recursive=False))(PTTVerbatimLine(char), PTTVerbatimLine(identifier))
		else:
			typing.cast(Callable[[PTTVerbatimLine, PTTVerbatimLine], None], Python_call_TeX_local(
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
								\__send_content%naive_send%:e { i \__identifier }
								\unexpanded{\pythonimmediatelisten}
							}
						}
					\endgroup
					%optional_sync%
					\pythonimmediatelisten
				}
				""", recursive=False))(PTTVerbatimLine(char), PTTVerbatimLine(identifier))
		return f
	return result

@_export
def undefine_char(char: str)->None:
	"""
	The opposite of :func:`define_char`.
	"""
	assert len(char)==1

	if not engine.is_unicode and ord(char)>127:
		# undefine u8:...
		typing.cast(Callable[[PTTVerbatimLine], None], Python_call_TeX_local(
			r"""
			\cs_new_protected:Npn %name% {
				\begingroup
					\endlinechar=-1~
					\readline \__read_file to \__line
					\cs_undefine:c {u8:\__line}
				\endgroup
				%optional_sync%
				\pythonimmediatelisten
			}
			""", recursive=False))(PTTVerbatimLine(char))
	else:
		# return the normal catcode for the character
		typing.cast(Callable[[PTTVerbatimLine], None], Python_call_TeX_local(
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
					\pythonimmediatelisten
				}
			}
			""", recursive=False))(PTTVerbatimLine(char))

@_export
def execute(block: str, expecting_exit: bool=False)->None:
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
	if expecting_exit:
		try: execute(block)
		except TeXProcessExited: pass
		else: assert False, "Process did not exit even though expecting_exit is True"
	else:
		run_block_local(block)

@_export
def execute_tokenized(line: str)->None:
	"""
	Temporary.
	"""
	typing.cast(Callable[[PTTTeXLine], None], Python_call_TeX_local(
		r"""
		\cs_new_protected:Npn %name% {
			%read_arg0(\__data)%
			\__data

			%optional_sync%
			\pythonimmediatelisten
		}
		"""))(PTTTeXLine(line))

@_export
def put_next_tokenized(line: str)->None:
	"""
	Temporary.
	"""
	typing.cast(Callable[[PTTTeXLine], None], Python_call_TeX_local(
		r"""
		\cs_new_protected:Npn %name% {
			%read_arg0(\__data)%

			%optional_sync%
			\expandafter \pythonimmediatelisten \__data
		}
		"""))(PTTTeXLine(line))

@_export
def print_TeX(*args: Any, **kwargs: Any)->None:
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
def newenvironment(name: str, f: Callable)->None:
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
	begin_identifier=get_random_Python_identifier()
	end_identifier=get_random_Python_identifier()

	typing.cast(Callable[[PTTVerbatimLine, PTTVerbatimLine, PTTVerbatimLine], None], Python_call_TeX_local(
		r"""
		\cs_new_protected:Npn %name% {
			%read_arg0(\__line)%
			%read_arg1(\__begin_identifier)%
			%read_arg2(\__end_identifier)%
			\use:x {
				\noexpand\newenvironment
					{\__line}
					{
						\__send_content%naive_send%:e { i \__begin_identifier }
						\unexpanded{\pythonimmediatelisten}
					}
					{
						\__send_content%naive_send%:e { i \__end_identifier }
						\unexpanded{\pythonimmediatelisten}
					}
			}
			%optional_sync%
			\pythonimmediatelisten
		}
		""", recursive=False))(PTTVerbatimLine(name), PTTVerbatimLine(begin_identifier), PTTVerbatimLine(end_identifier))


	pending_objects: list[tuple[Iterator, int]]=[]  # nonlocal mutable, create one for each environment

	def begin_f()->None:
		a=f()
		next(a)
		pending_objects.append((a, (T.currentgrouplevel.int() if engine.config.debug>=2 else -1)))

	def end_f()->None:
		if not pending_objects:
			assert False, r"\end{" + name + r"} called before \begin{" + name + "} finishes!"

		a, expectedgrouplevel=pending_objects.pop()
		if expectedgrouplevel!=(T.currentgrouplevel.int() if engine.config.debug>=2 else -1):
			assert False, r"\end{" + name + r"} called before \begin{" + name + "} finishes! (likely, wrong group level)"

		try:
			next(a)
			assert False, "Function must yield exactly once!"
		except StopIteration:
			pass

	_code=define_TeX_call_Python(
			lambda: run_code_redirect_print_TeX(begin_f),
			f"(begin environment: {name})", argtypes=[], identifier=begin_identifier)
	_code=define_TeX_call_Python(
			lambda: run_code_redirect_print_TeX(end_f),
			f"(end environment: {name})", argtypes=[], identifier=end_identifier)
	# ignore _code, already executed something equivalent in the TeX command

@_export
def get_env_body_verb_approximate(envname: Optional[str]=None)->tuple[str, str, int]:
	r"""
	This function is to be used inside :func:`newenvironment`'s registered function in order to get the environment body.

	It can only be used once, and it only works if the argument is not already tokenized,
	i.e., it appears at "top-level"/does not appear inside any command or some environments such as ``align``.
	(basically where a ``\verb|...|`` command can appear.)

	:returns: a tuple ``(body, filename, line_number)`` where ``body`` is the body of the environment,
		``filename`` is the filename of the TeX file, and ``line_number`` is the line number of the last line of the environment.

	.. note::
		The returned code may have some tab characters converted to ``^^I``, trailing spaces stripped etc.

		For advanced users:
		Basically it takes the following content until ``\end{⟨value of \@currenvir⟩}``, as by the ``saveenv`` package.
	"""
	if envname is None: envname=T["@currenvir"].tl().detokenize()
	assert envname is not None

	with group:
		endlinechar=T.endlinechar.int()
		BalancedTokenList(r'\cctab_select:N \c_other_cctab').execute()  # also change endlinechar
		T.endlinechar.int(10)

		lineno=T.inputlineno.int()
		result=BalancedTokenList()
		token=Token.get_next()
		if endlinechar>=0:
			if token!=Catcode.other(endlinechar):
				raise RuntimeError(f"Content is already tokenized or environment begin line not on a separate line! "
					f"(first following token is {token})")
		else:
			if T.inputlineno.int()==lineno:
				raise RuntimeError("Content is already tokenized! (current endlinechar is -1)")
			result.append(token)
		result+=BalancedTokenList.get_until(BalancedTokenList.fstr(r'\end{' + T["@currenvir"].tl().detokenize() + "}\n"))
		BalancedTokenList([r'\end{', *T["@currenvir"].tl(), '}']).put_next()
		code=result.detokenize()

		filename: str
		if T.currfileabspath.defined():
			filename=T.currfileabspath.str()
		elif T.currfilename.defined():
			filename=T.currfilename.str()
		else:
			filename="??"

		inputlineno=T.inputlineno.int()

	return code, filename, inputlineno

@_export
@make_nf_function
def newenvironment_verb(name: str, f: Callable[[str], None])->None:
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
	identifier=get_random_Python_identifier()

	typing.cast(Callable[[PTTVerbatimLine, PTTVerbatimLine], None], Python_call_TeX_local(
		r"""
		\cs_new_protected:Npn %name% {
			%read_arg0(\__line)%
			%read_arg1(\__identifier)%
			\use:x {
				\noexpand\newenvironment
					{\__line}
					{
						\__send_content%naive_send%:e { i \__identifier }
						\pythonimmediatelisten
					}
					{}
			}
			%optional_sync%
			\pythonimmediatelisten
		}
		""", recursive=False))(PTTVerbatimLine(name), PTTVerbatimLine(identifier))

	def f1()->None:
		body=typing.cast(Callable[[], TTPBlock], Python_call_TeX_local(
			r"""
			\cs_new_protected:Npn %name% {
				\saveenvreinsert \__tmp {
					%sync%
					%send_arg0_var(\__tmp)%
					\pythonimmediatelisten
				}
			}
			""", recursive=False))()
		f(body)

	_code=define_TeX_call_Python(
			lambda: run_code_redirect_print_TeX(f1),
			f"(verb environment: {name})", argtypes=[], identifier=identifier)

@_export
def fully_expand(content: str)->str:
	r"""
	Expand all macros in the given string.

	.. _expansion-issue:

	Note on unexpandable and fragile macros
	---------------------------------------

	Not all [TeX] commands/macros can be used inside this function.
	If you try to, they will either return the input unchanged, or error out.

	In such cases, the problem is **impossible** to solve, so just look for workarounds.

	An example is the ``\py`` command, which is already mentioned in the initial introduction to the
	:mod:`~pythonimmediate.simple` module::

		>> fully_expand(r"\py{1+1}")
		r"\py{1+1}"

	Some other examples (assuming ``\usepackage{ifthen}`` is used)::

		>> execute(r'\ifthenelse{1=2}{equal}{not equal}')  # legal, typeset "not equal"
		>> fully_expand(r'\ifthenelse{1=2}{equal}{not equal}')  # error out
		
		>> execute(r'\uppercase{abc}')  # legal, typeset "ABC"
		>> fully_expand(r'\uppercase{abc}')  # just returned verbatim
		r'\uppercase {abc}'

	There might be a few workarounds, but they're all dependent on the exact macros involved.

	For if-style commands, assign the desired result to a temporary variable::

		>> execute(r'\ifthenelse{1=2}{\pyc{result = "equal"}}{\pyc{result = "not equal"}}')
		>> result
		"not equal"

	For for-loop-style commands, you can do something similar (demonstrated here with ``tikz``'s ``\foreach`` command)::
		
		>> result = []
		>> execute(r'\foreach \x in {1, 2, ..., 10} {\pyc{result.append(var["x"])}}')
		>> result
		['1', '2', '3', '4', '5', '6', '7', '8', '9', '10']

	For macros such as ``\uppercase{...}``, there's no simple workaround. Reimplement it yourself (such as with ``.upper()`` in Python).
	"""
	return typing.cast(Callable[[PTTTeXLine], TTPEmbeddedLine], Python_call_TeX_local(
		r"""
		\cs_new_protected:Npn %name% {
			%read_arg0(\__content)%
			\exp_args:Nx \pythonimmediatecontinue { \__content }
		}
		"""))(PTTTeXLine(content))

@_export
def is_balanced(content: str)->bool:
	r"""
	Check if the given string is balanced, i.e. if all opening and closing braces match.

	This is a bit tricky to implement, it's recommended to use the library function.

	For example::

		>>> is_balanced("a{b}c")
		True
		>>> is_balanced("a{b}c}")
		False
		>>> is_balanced(r"\{")
		True
	"""
	return TokenList.doc(content).is_balanced()

def _detokenize(t: BalancedTokenList)->str:
	return t.simple_detokenize(default_get_catcode)

@_export
def split_balanced(content: str, /, sep: str, maxsplit: int=-1, do_strip_braces_in_result: bool=True)->List[str]:
	r"""
	Split the given string at the given substring, but only if the parts are balanced.

	This is a bit tricky to implement, it's recommended to use the library function.

	If either *content* or *sep* is unbalanced, the function will raise ValueError.

	It is recommended to set *do_strip_braces_in_result* to ``True`` (the default),
	otherwise the user will not have any way to "quote" the separator in each entry.

	For example::

		>>> split_balanced("a{b,c},c{d}", ",")
		['a{b,c}', 'c{d}']
		>>> split_balanced("a{b,c},{d,d},e", ",", do_strip_braces_in_result=False)
		['a{b,c}', '{d,d}', 'e']
		>>> split_balanced("a{b,c},{d,d},e", ",")
		['a{b,c}', 'd,d', 'e']
		>>> split_balanced(" a = b = c ", "=", maxsplit=1)
		[' a ', ' b = c ']
		>>> split_balanced(r"\{,\}", ",")
		['\\{', '\\}']
		>>> split_balanced("{", "{")
		Traceback (most recent call last):
			...
		ValueError: Content is not balanced!
	"""
	assert maxsplit>=-1, "maxsplit should be either -1 (unbounded) or the maximum number of splits"
	try: content1=BalancedTokenList.doc(content)
	except UnbalancedTokenListError: raise ValueError("Content is not balanced!")
	try: separator1=BalancedTokenList.doc(sep)
	except UnbalancedTokenListError: raise ValueError("Separator is not balanced!")
	result=content1.split_balanced(separator1, maxsplit, do_strip_braces_in_result=do_strip_braces_in_result)
	result1=[_detokenize(x) for x in result]
	return result1

@_export
def strip_optional_braces(content: str)->str:
	"""
	Strip the optional braces from the given string, if the whole string is wrapped in braces.

	For example::

		>>> strip_optional_braces("{a}")
		'a'
		>>> strip_optional_braces("a")
		'a'
		>>> strip_optional_braces("{a},{b}")
		'{a},{b}'
	"""
	t=BalancedTokenList.doc(content)
	return _detokenize(t.strip_optional_braces())

@_export
def parse_keyval_items(content: str)->list[tuple[str, Optional[str]]]:
	"""
	>>> parse_keyval_items("a=b,c=d")
	[('a', 'b'), ('c', 'd')]
	>>> parse_keyval_items("a,c=d")
	[('a', None), ('c', 'd')]
	>>> parse_keyval_items("a = b , c = d")
	[('a', 'b'), ('c', 'd')]
	>>> parse_keyval_items("a ={ b }, c ={ d}")
	[('a', ' b '), ('c', ' d')]
	>>> parse_keyval_items("a={b,c}, c=d")
	[('a', 'b,c'), ('c', 'd')]
	>>> parse_keyval_items("{a=b},c=d")
	[('{a=b}', None), ('c', 'd')]
	"""
	content1=BalancedTokenList.doc(content)
	result=content1.parse_keyval_items()
	return [(_detokenize(k), _detokenize(v) if v is not None else None)
		 for k, v in result]

@_export
def parse_keyval(content: str, allow_duplicate: bool=False)->dict[str, Optional[str]]:
	"""
	Parse a key-value string into a dictionary.

	>>> parse_keyval("a=b,c=d")
	{'a': 'b', 'c': 'd'}
	>>> parse_keyval("a,c=d")
	{'a': None, 'c': 'd'}
	>>> parse_keyval("a = b , c = d")
	{'a': 'b', 'c': 'd'}
	>>> parse_keyval("a ={ b }, c ={ d}")
	{'a': ' b ', 'c': ' d'}
	>>> parse_keyval("a={b,c}, c=d")
	{'a': 'b,c', 'c': 'd'}
	>>> parse_keyval("a=b,a=c")
	Traceback (most recent call last):
		...
	ValueError: Duplicate key: 'a'
	>>> parse_keyval("a=b,a=c", allow_duplicate=True)
	{'a': 'c'}
	"""
	items=parse_keyval_items(content)
	if allow_duplicate: return dict(items)
	result={}
	for k, v in items:
		if k in result:
			raise ValueError(f"Duplicate key: {k!r}")
		result[k]=v
	return result

def set_globals_locals(globals: Any, locals: Any)->Tuple[Optional[dict], Optional[dict]]:
	"""
	Helper function, compute the globals and locals dict of the caller's parent frame.
	"""
	if globals is None and locals is None:
		i=2
		f=sys._getframe(i)
		globals = dict(f.f_globals)
		locals = dict(f.f_locals)

		# https://bugs.python.org/issue21161
		# each list comprehension has its own local namespace
		while f.f_code.co_name in ("<listcomp>", "<genexpr>"):
			i+=1
			f=sys._getframe(i)
			globals = f.f_globals | globals
			locals = f.f_locals | locals

	return globals, locals

T3=TypeVar("T3")
def riffle(s: Iterable[T3], sep: T3)->Iterator[T3]:
	"""
	Helper function, yield the given strings, separated by the given separator.

	>>> [*riffle(["a", "b", "c"], ",")]
	['a', ',', 'b', ',', 'c']
	"""
	for i, x in enumerate(s):
		if i>0:
			yield sep
		yield x

class F1Protocol(Protocol):
	default_escape: Any
	def __call__(self, s: str, globals: Optional[dict]=None, locals: Optional[dict]=None, escape: Optional[Union[Tuple, str]]=None)->str: ...

f1: F1Protocol

@_export  # type: ignore
def f1(s: str, *, globals: Optional[dict]=None, locals: Optional[dict]=None, escape: Optional[Union[Tuple[str, ...], str]]=None)->str:
	"""
	Helper function to construct a string from Python expression parts,
	similar to f-strings, but allow using arbitrary delimiters.

	This is useful for constructing [TeX] code, because the ``{`` and ``}`` characters are frequently used in [TeX].

	Example::

		>>> a = 1
		>>> b = 2
		>>> f1("a=`a`, b=`b`")
		'a=1, b=2'
		>>> f1("`")
		Traceback (most recent call last):
			...
		ValueError: Unbalanced delimiters!

	The escape/delimiter character can be escaped by doubling it::

		>>> f1("a``b")
		'a`b'
		>>> f1("a ` '````' ` b")
		'a `` b'

	It's possible to customize the delimiters::

		>>> f1("a=!a!", escape="!")
		'a=1'

	It's possible to use different delimiters for the opening and the closing::

		>>> f1("a=⟨a⟩, b=⟨b⟩", escape="⟨⟩")
		'a=1, b=2'
		>>> f1("<", escape="<>")
		Traceback (most recent call last):
			...
		ValueError: Unbalanced delimiters!

	There's no way to escape them, they must be balanced in the string::

		>>> f1("a=⟨ '⟨'+str(a)+'⟩' ⟩", escape="⟨⟩")
		'a=⟨1⟩'

	The default value of *escape* is stored in ``f1.default_escape``, it can be reassigned::

		>>> f1.default_escape="!"
		>>> f1("a=!a!")
		'a=1'
		>>> f1.default_escape="`"

	It's even possible to use multiple characters as the delimiter::

		>>> f1("a=**a**, b=**b**", escape=["**"])
		'a=1, b=2'
		>>> f1("a=[[a]], b=[[b]]", escape=["[[", "]]"])
		'a=1, b=2'

	In the first case above, remember to put the delimiter in a list because otherwise it will be interpreted
	as an opening and a closing delimiter.

	Currently, format specifiers such as ``:d`` are not supported.
	"""
	globals, locals=set_globals_locals(globals, locals)

	if escape is None:
		escape=f1.default_escape
	assert len(escape) in (1, 2), "Invalid escape value provided"

	if len(escape)==2:
		opening=escape[0]
		closing=escape[1]
		assert opening!=closing, "If len(escape)==2, the two delimiters must be different"

		parts=[
				small_part
				for part in riffle((
					riffle(part.split(closing), closing)
					for part in s.split(opening)
					), [opening])
				for small_part in part
				]
		degree=0
		result=[]
		partial_code=""

		for part in parts:
			if part==opening:
				if degree>0: partial_code+=part
				degree+=1
			elif part==closing:
				degree-=1
				if degree>0: partial_code+=part
				elif degree<0: raise ValueError("Unbalanced delimiters!")
				else:
					item=eval(partial_code, globals, locals)
					result.append(str(item))
					partial_code=""
			else:
				if degree>0: partial_code+=part
				else: result.append(part)
		if degree!=0: raise ValueError("Unbalanced delimiters!")
		return "".join(result)
	
	else:
		assert len(escape)==1
		parts_=s.split(escape[0])
		if len(parts_)%2==0: raise ValueError("Unbalanced delimiters!")
		result=[]
		partial_code=""
		for i, part in enumerate(parts_):
			if i%2==0:
				# it's the string part e.g. "a = " in "a = `a`", so just append to result
				result.append(part)
			elif parts_[i]=="":
				# e.g. "a `` b", the part between the two backticks is empty
				result.append(escape[0])
			else:
				partial_code+=part
				if i+2<len(parts_) and not parts_[i+1]:
					# it's of the form ` some code ` other code `, so wait for the next part
					partial_code+=escape[0]
				else:
					# it's not of the form ` some code `` other code `, so execute immediately
					item=eval(partial_code, globals, locals)
					result.append(str(item))
					partial_code=""

		assert not partial_code
		return "".join(result)

f1.default_escape="`"

@dataclass
class VarManager:

	def __getitem__(self, key: str)->str:
		"""
		Get the value of a variable.
		"""
		_check_name(key)
		return _replace_double_hash(
				BalancedTokenList([ControlSequenceToken(key)])
				.expand_o()
				.detokenize()
				)

	def __setitem__(self, key: str, val: str)->None:
		"""
		Set the value of a variable.
		"""
		_check_name(key)
		return typing.cast(Callable[[PTTVerbatimLine, PTTTeXLine], None], Python_call_TeX_local(
			r"""
			\cs_new_protected:Npn %name% {
				%read_arg0(\__line)%
				%read_arg1(\__value)%
				\tl_set_eq:cN {\__line} \__value
				%optional_sync%
				\pythonimmediatelisten
			}
			""", recursive=False, sync=None))(PTTVerbatimLine(key), PTTTeXLine(val))

_escape_str_translation=str.maketrans({
	"&": r"\&",
	"%": r"\%",
	"$": r"\$",
	"#": r"\#",
	"_": r"\_",
	"{": r"\{",
	"}": r"\}",
	"~": r"\~{}",
	"^": r"\^{}",
	"\\": r"\textbackslash{}",
	" ": r"\ ",
	"\n": r"\\",
	# OT1:
	"<": r"\textless{}",
	">": r"\textgreater{}",
	})
@_export
def escape_str(s: str)->str:
	r"""
	Given an arbitrary string, output some [LaTeX] code that when executed will typeset the original string.

	Example::

		>>> escape_str("123")
		'123'
		>>> escape_str(r"a%#_^~\?")
		'a\\%\\#\\_\\^{}\\~{}\\textbackslash{}?'
		>>> escape_str("[")
		'['
		>>> escape_str("  ")
		'\\ \\ '
		>>> escape_str("\n")
		'\\\\'

	``\n`` gets escaped to ``\\`` so that multiple consecutive ``\n`` gives multiple line breaks.

	``<`` and ``>`` also needs to be escaped, but only in OT1 font encoding, see https://tex.stackexchange.com/q/2369/250119::

		>>> escape_str("<>")
		'\\textless{}\\textgreater{}'

	Some Unicode characters may not be supported regardless.

	Be careful with initial ``[`` in text which may be interpreted as an optional argument in specific cases.
	For example https://tex.stackexchange.com/questions/34580/escape-character-in-latex/686889#comment1155297_34586.
	"""
	return s.translate(_escape_str_translation)

var=VarManager()
r"""
Get and set value of "variables" in [TeX].

Can be used like this::

	var["myvar"]="myvalue"  # "equivalent" to \def\myvar{myvalue}
	var["myvar"]=r"\textbf{123}"  # "equivalent" to \def\myvar{\textbf{123}}
	var["myvar"]=r"\def\test#1{#1}"  # "equivalent" to \tl_set:Nn \myvar {\def\test#1{#1}}  (note that `#` doesn't need to be doubled here unlike in `\def`)
	var()["myvar"]="myvalue"  # pass explicit engine

	# after ``\def\myvar{myvalue}`` (or ``\edef``, etc.) on TeX you can do:
	print(var["myvar"])  # get the value of the variable, return a string

It's currently undefined behavior if the passed-in value is not a "variable".
(in some future version additional checking might be performed in debug run)

Notes in :ref:`str-tokenization` apply -- in other words, after you set a value it may become slightly different when read back.
"""
if not typing.TYPE_CHECKING:
	__all__.append("var")

scan_Python_call_TeX_module(__name__)
