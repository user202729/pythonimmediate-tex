#!/bin/python3
r"""
The main module. Contains Pythonic wrappers for much of [TeX]'s API.

Refer to :mod:`~pythonimmediate.simple` for the "simple" API -- which allows users to avoid the need to
know [TeX] internals such as category codes.

The fundamental data of [TeX] is a token, this is represented by Python's :class:`Token` object.
A list of tokens is represented by :class:`TokenList` object. If it's balanced,
:class:`BalancedTokenList` should be used.

With that, you can manipulate the [TeX] input stream with :meth:`BalancedTokenList.get_next`,
:meth:`BalancedTokenList.get_until`, :meth:`TokenList.put_next`.

Furthermore, executing [TeX] code is possible using :func:`continue_until_passed_back`.
For example, the following code::

	TokenList(r"\typeout{123}\pythonimmediatecontinuenoarg").put_next()
	continue_until_passed_back()

will just use [TeX] to execute the code ``\typeout{123}``.

With the 3 functions above, you can do *everything* that can be done in [TeX]
(although maybe not very conveniently or quickly). Some other functions are provided,
and for educational purposes, the way to implement it using the primitive functions are discussed.

* :func:`expand_once`: ``TokenList(r"\expandafter\pythonimmediatecontinuenoarg").put_next(); continue_until_passed_back()``
* :meth:`BalancedTokenList.expand_o`: ``TokenList(r"\expandafter\pythonimmediatecontinuenoarg\expandafter", self).put_next(); continue_until_passed_back(); return BalancedTokenList.get_next()``

  For example, if the current token list is `\test`, the lines above will:

  * put ``\expandafter\pythonimmediatecontinuenoarg\expandafter{\test}`` following in the input stream,
  * pass control to [TeX],
  * after one expansion step, the input stream becomes ``\pythonimmediatecontinuenoarg{⟨content of \test⟩}``,
  * ``\pythonimmediatecontinuenoarg`` is executed, and execution is returned to Python,
  * finally :func:`BalancedTokenList.get_next` gets the content of ``\test``, as desired.

* :meth:`TokenList.execute`: ``(self+TokenList(r"\pythonimmediatecontinuenoarg")).put_next(); continue_until_passed_back()``
* :func:`NToken.put_next`: ``TokenList("\expandafter\pythonimmediatecontinuenoarg\noexpand\abc").put_next(); continue_until_passed_back()`` (as an example of putting a blue ``\abc`` token following in the input stream)
* etc.

This is a table of [TeX] primitives, and their Python wrapper:

.. list-table::
	:header-rows: 1

	* - :math:`TeX`
	  - Python
	* - ``\let``
	  - :meth:`Token.set_eq`
	* - ``\ifx``
	  - :meth:`Token.meaning_eq`
	* - ``\meaning``
	  - :meth:`NToken.meaning_str`
	* - ``\futurelet``
	  - :meth:`Token.set_future`, :meth:`Token.set_future2`
	* - ``\def``
	  - :meth:`Token.tl` (no parameter),
	    :meth:`Token.set_func` (define function to do some task)
	* - ``\edef``
	  - :meth:`BalancedTokenList.expand_x`
	* - Get undelimited argument
	  - :meth:`BalancedTokenList.get_next`
	* - Get delimited argument
	  - :meth:`BalancedTokenList.get_until`, :meth:`BalancedTokenList.get_until_brace`
	* - ``\catcode``
	  - :const:`catcode`
	* - ``\count``
	  - :const:`count`, :meth:`Token.int`
	* - ``\Umathcode``
	  - :const:`umathcode`
	* - ``\detokenize``
	  - :meth:`BalancedTokenList.detokenize`
	* - ``\begingroup``, ``\endgroup``
	  - :const:`group`

In order to get a "value" stored in a "variable"
(using expl3 terminology, this has various meanings e.g. a ``\countdef`` token, or a typical macro storing a token list),
use a property on the token object itself:

* :meth:`Token.int` for ``\int_use:N \int_set:Nn``,
* :meth:`Token.tl` for ``\tl_use:N \tl_set:Nn``,
* :meth:`Token.str` for ``\str_use:N \str_set:Nn``,
* :meth:`Token.bool`,
* etc.

A token list can be:

* interpreted as a string (provide it is already a string) using :meth:`TokenList.str`,
* converted from a Python string (opposite of the operation above) using :meth:`TokenList.fstr`,
* interpreted as an integer using :meth:`TokenList.int`,
* detokenized using :meth:`BalancedTokenList.detokenize`,
* expanded with :meth:`BalancedTokenList.expand_x` or :meth:`BalancedTokenList.expand_o`,
* etc.

Some debug functionalities are provided and can be specified on the command-line, refer to :mod:`~pythonimmediate.pytotex` documentation.

"""

from __future__ import annotations
import sys
import os
import inspect
import contextlib
import io
import functools
from typing import Optional, Union, Callable, Any, Iterator, Protocol, Iterable, Sequence, Type, Tuple, List, Dict, IO
import typing
from abc import ABC, abstractmethod
from pathlib import Path
from dataclasses import dataclass
import tempfile
import signal
import traceback
import re
import collections
from collections import defaultdict
import enum

T1 = typing.TypeVar("T1")

is_sphinx_build = "SPHINX_BUILD" in os.environ


#debug_file=open(Path(tempfile.gettempdir())/"pythonimmediate_debug_textopy.txt", "w", encoding='u8', buffering=2)
#debug=functools.partial(print, file=debug_file, flush=True)
debug=functools.partial(print, file=sys.stderr, flush=True)
debug=lambda *args, **kwargs: None  # type: ignore



expansion_only_can_call_Python=False  # normally. May be different in LuaTeX etc.
from .engine import Engine, default_engine, default_engine as engine, ParentProcessEngine, EngineStatus, TeXProcessError, TeXProcessExited, ChildProcessEngine


debugging: bool=True
if os.environ.get("pythonimmediatenodebug", "").lower() in ["true", "1"]:
	debugging=False

FunctionType = typing.TypeVar("FunctionType", bound=Callable)

import random
def surround_delimiter(block: str)->str:
	while True:
		delimiter=str(random.randint(0, 10**12))
		if delimiter not in block: break
	return delimiter + "\n" + block + "\n" + delimiter + "\n"

EngineDependentCode=Callable[[Engine], str]

bootstrap_code_functions: list[EngineDependentCode]=[]
"""
Internal constant.
Contains functions that takes an engine object and returns some code before :meth:`substitute_private` is applied on it.

:meta hide-value:
:meta private:
"""
def mark_bootstrap(code: str)->None:
	bootstrap_code_functions.append(lambda _engine: code)

# check TeX package version.
mark_bootstrap(r"""
\exp_args:Nx \str_if_in:nnF {\csname ver@pythonimmediate.sty\endcsname} {%} {
	\msg_new:nnn {pythonimmediate} {incompatible-version} {Incompatible~ TeX~ package~ version~ (#1)~ installed!~ Need~ at~ least~ %.}
	\msg_error:nnx {pythonimmediate} {incompatible-version} {\csname ver@pythonimmediate.sty\endcsname}
}
""".replace("%", "v0.5.0"))

def substitute_private(code: str)->str:
	assert "_pythonimmediate_" not in code  # avoid double-apply this function
	return (code
		  #.replace("\n", ' ')  # because there are comments in code, cannot
		  .replace("__", "_" + "pythonimmediate" + "_")
		 )

def postprocess_send_code(s: str, put_sync: bool)->str:
	assert have_naive_replace(s), s
	if put_sync:
		# keep the naive-sync operation
		pass
	else:
		# remove it
		s=naive_replace(s, False)
	return s

# ========


# as the name implies, this reads one "command" from Python side and execute it.
# the command might do additional tasks e.g. read more [TeX]-code.
#
# e.g. if ``block`` is read from the communication channel, run ``\__run_block:``.

@bootstrap_code_functions.append
def _naive_flush_data_define(engine: Engine)->str:
	if engine.config.naive_flush:
		# the function x-expand to something in a single line that is at least 4095 bytes long and ignored by Python
		# (plus the newline would be 4096)
		return r"""
			\cs_new:Npn \__naive_flush_data: {
				pythonimmediate-naive-flush-line \prg_replicate:nn {4063} {~}
			}
			"""
	return ""

@typing.overload
def naive_replace(code: str, naive_flush: bool, /)->str: ...
@typing.overload
def naive_replace(code: str, engine: Engine, /)->str: ...

def naive_replace(code: str, x: Union[Engine, bool])->str:
	code1=code
	if (x.config.naive_flush if isinstance(x, Engine) else x):
		code1=code1.replace("%naive_inline%", r"^^J \__naive_flush_data: ")
		code1=code1.replace("%naive_flush%", r"\__send_content:e {\__naive_flush_data:}")
		code1=code1.replace("%naive_send%", r"_naive_flush")
	else:
		code1=code1.replace("%naive_inline%", "")
		code1=code1.replace("%naive_flush%", "")
		code1=code1.replace("%naive_send%", "")
	code1=code1.replace("%naive_ignore%", "")
	return code1

def have_naive_replace(code: str)->bool:
	return naive_replace(code, False)!=code

def wrap_naive_replace(code: str)->EngineDependentCode:
	return functools.partial(naive_replace, code)

def mark_bootstrap_naive_replace(code: str)->None:
	r"""
	Similar to :func:`mark_bootstrap`, but code may contain one of the following:

	- ``%naive_inline``: replaced with ``^^J \__naive_flush_data:``
		if :attr:`Engine.config.naive_flush` is ``True``, else become empty
	- ``%naive_flush%``: replaced with ``\__send_content:e {\__naive_flush_data:}``
		if :attr:`Engine.config.naive_flush` is ``True``

	:meta private:
	"""
	bootstrap_code_functions.append(wrap_naive_replace(code))

mark_bootstrap_naive_replace(
r"""
\cs_new_protected:Npn \pythonimmediatelisten {
	\begingroup
		\endlinechar=-1~
		\readline \__read_file to \__line
		\expandafter
	\endgroup % also this will give an error instead of silently do nothing when command is invalid
		\csname __run_ \__line :\endcsname
}

\cs_new_protected:Npn \pythonimmediatecallhandlerasync #1 {
	\__send_content:e {i #1 %naive_inline% }
}

\cs_new_protected:Npn \pythonimmediatecallhandler #1 {
	\pythonimmediatecallhandlerasync {#1} \pythonimmediatelisten
}

% read documentation of ``_peek`` commands for details what this command does.
\cs_new_protected:Npn \pythonimmediatecontinue #1 {
	\__send_content:e {r #1 %naive_inline% }
	\pythonimmediatelisten
}

\cs_new_protected:Npn \pythonimmediatecontinuenoarg {
	\pythonimmediatecontinue {}
}


\cs_new_protected:Npn \__send_content:n #1 {
	\__send_content:e { \unexpanded{#1} }
}

\cs_new_protected:Npn \__send_content_naive_flush:e #1 {
	\__send_content:e { #1 %naive_inline% }
}

\cs_new_protected:Npn \__send_content_naive_flush:n #1 {
	\__send_content_naive_flush:e { \unexpanded{#1} }
}

% the names are such that \__send_content%naive_send%:n {something} results in the correct content

% internal function. Just send an arbitrary block of data to Python.
% this function only works properly when newlinechar = 10.
\cs_new_protected:Npn \__send_block:e #1 {
	\__send_content:e {
		#1 ^^J
		pythonimm?""" + '"""' + r"""?'''?  % following character will be newline
	}
}

\cs_new_protected:Npn \__send_block:n #1 {
	\__send_block:e {\unexpanded{#1}}
}

\cs_new_protected:Npn \__send_block_naive_flush:e #1 {
	\__send_content:e {
		#1 ^^J
		pythonimm?""" + '"""' + r"""?'''?  % following character will be newline
		%naive_inline%
	}
}

\cs_new_protected:Npn \__send_block_naive_flush:n #1 {
	\__send_block_naive_flush:e {\unexpanded{#1}}
}

\cs_generate_variant:Nn \__send_block:n {V}
\cs_generate_variant:Nn \__send_block_naive_flush:n {V}

\bool_if:NF \__child_process {
	\AtEndDocument{
		\__send_content:e {r %naive_inline%}
		\pythonimmediatelisten
		\__close_write:
	}
}
""")
# the last one don't need to flush because will close anyway (right?)


# ========

_handlers: Dict[str, Callable[[], None]]={}
_per_engine_handlers: Dict[Engine, Dict[str, Callable[[], None]]]={}

def add_handler_async(f: Callable[[], None], *, all_engines: bool=False)->str:
	r"""
	This function is for micro-optimization. Usage is not really recommended.

	Similar to :func:`add_handler`, however, the function has these additional restrictions:

	* Within the function, **it must not send anything to [TeX].**
	* It **must not cause a Python error**, otherwise the error reporting facility
	  may not work properly (does not print the correct [TeX] traceback).

	Also, on the [TeX] side you need ``\pythonimmediatecallhandlerasync``.

	Example::

		def myfunction():
			print(1)
		identifier = add_handler(myfunction)
		execute(r"\def\test{\pythonimmediatecallhandlerasync{" + identifier + "}}")

	Note that in order to allow the Python function to call [TeX], it's necessary to
	"listen" for callbacks on [TeX] side as well -- as [TeX] does not have the capability
	to execute multiple threads, it's necessary to explicitly listen for instructions from the Python side,
	which is what the command ``\pythonimmediatelisten`` in ``\pythonimmediatecallhandler``'s implementation does.

	.. note::
		Internally, ``\pythonimmediatecallhandlerasync{abc}``
		sends ``i⟨string⟩`` from [TeX] to Python
		(optionally flushes the output),
		and the function with index ``⟨string⟩`` in this dict is called.

	"""
	identifier=get_random_Python_identifier()
	assert identifier not in _handlers
	if all_engines:
		_handlers[identifier]=f
	else:
		e=default_engine.get_engine()
		l=_defaultget_with_cleanup(_per_engine_handlers, dict)
		assert identifier not in l
		l[identifier]=f
	return identifier

def add_handler(f: Callable[[], None], *, all_engines: bool=False)->str:
	r"""
	This function provides the facility to efficiently call Python code from [TeX]
	and without polluting the global namespace.

	First, note that with :func:`.pyc` you can do the following:

		>>> a=get_user_scope()["a"]=[]
		>>> execute(r"\def\test{\pyc{a.append(1)}}")

	Then every time ``\test`` is executed on [TeX] side the corresponding Python code will be executed:

		>>> a
		[]
		>>> execute(r"\test")
		>>> a
		[1]

	However, this pollutes the Python global namespace as well as having to parse the string
	``a.append(1)`` into Python code every time it's called.

	With this function, you can do the following::

		>>> def myfunction(): execute(r"\advance\count0 by 1 ")  # it's possible to execute TeX code here
		>>> identifier = add_handler(myfunction)
		>>> execute(r"\def\test{\pythonimmediatecallhandler{" + identifier + r"}}")

		>>> count[0]=5
		>>> execute(r"\test")
		>>> count[0]
		6

	The returned value, `identifier`, is a string consist of only English alphabetical letters,
	which should be used to pass into ``\pythonimmediatecallhandler`` [TeX] command
	and :func:`remove_handler`.

	The handlers must take a single argument of type :class:`Engine` as input, and returns nothing.

	.. seealso::
		:func:`add_handler_async`, :func:`remove_handler`.
	"""
	def g()->None:
		assert engine.status==EngineStatus.running
		engine.status=EngineStatus.waiting
		f()
		if engine.status==EngineStatus.waiting:
			run_none_finish()
		assert engine.status==EngineStatus.running

	return add_handler_async(g, all_engines=all_engines)

def remove_handler(identifier: str, *, all_engines: bool=False)->None:
	"""
	Remove a handler with the given `identifier`.

	Note that even if the corresponding [TeX] command is deleted, the command might have been
	copied to another command, so use this function with care.

	.. seealso::
		:func:`add_handler`.
	"""
	if all_engines:
		del _handlers[identifier]
	else:
		del _per_engine_handlers[default_engine.get_engine()][identifier]

TeXToPyObjectType=Optional[str]

def run_main_loop()->TeXToPyObjectType:
	assert engine.status==EngineStatus.running
	while True:
		line=_readline()
		if line[0]=="i":
			identifier=line[1:]
			f=_handlers.get(identifier)
			if f is None: _per_engine_handlers[default_engine.get_engine()][identifier]()
			else: f()
		elif line[0]=="r":
			return line[1:]
		else:
			raise RuntimeError("Internal error: unexpected line "+line)

def run_main_loop_get_return_one()->str:
	assert engine.status==EngineStatus.running
	line=_readline()
	assert line[0]=="r", line
	return line[1:]


def _run_block_finish(block: str)->None:
	assert default_engine.status==EngineStatus.waiting
	engine.write(("block\n" + surround_delimiter(block)).encode('u8'))
	default_engine.status=EngineStatus.running


def check_line(line: str, *, braces: bool, newline: bool, continue_: Optional[bool])->None:
	"""
	check user-provided line before sending to TeX for execution

	:meta private:
	"""
	if braces:
		assert line.count("{") == line.count("}")
	if newline:
		assert '\n' not in line
		assert '\r' not in line  # this is not the line separator but just in case
	if continue_==True: assert "pythonimmediatecontinue" in line
	elif continue_==False: assert "pythonimmediatecontinue" not in line


_user_scope: Dict[Engine, Dict[str, Any]]={}

def _defaultget_with_cleanup(d: Dict[Engine, T1], default: Callable[[], T1])->T1:
	e=default_engine.get_engine()
	if e not in d:
		d[e]=default()
		def cleanup()->None: del d[e]
		e.add_on_close(cleanup)
	return d[e]

def get_user_scope()->Dict[str, Any]:
	r"""
	This is the global namespace where codes in :func:`.py`, :func:`.pyc`, :func:`.pycode` etc. runs in.
	Mainly useful for :class:`.ChildProcessEngine` or cases when the scope is not the global scope (e.g. :func:`.pyfilekpse`) only.

	>>> aaa=1
	>>> execute(r'\pyc{aaa}')
	Traceback (most recent call last):
		...
	NameError: name 'aaa' is not defined
	>>> get_user_scope()["aaa"]=1
	>>> execute(r'\pyc{aaa}')

	..
		Internally this must be cleaned up properly.

		>>> n=len(_user_scope)
		>>> from pythonimmediate.engine import ChildProcessEngine
		>>> with ChildProcessEngine("pdftex") as e, default_engine.set_engine(e):
		...		assert n==len(_user_scope)
		...		execute(r'\pyc{a=1}')
		...		assert n+1==len(_user_scope)
		>>> assert n==len(_user_scope)
	"""
	return _defaultget_with_cleanup(_user_scope, dict)

def _readline()->str:
	line=engine.read().decode('u8')
	return line

block_delimiter: str="pythonimm?\"\"\"?'''?"

def _read_block()->str:
	r"""
	Internal function to read one block sent from [TeX]
	(including the final delimiter line, but the delimiter line is not returned)
	"""
	lines: List[str]=[]
	while True:
		line=_readline()
		if line==block_delimiter:
			return '\n'.join(lines)
		else:
			lines.append(line)


class NToken(ABC):
	"""
	Represent a possibly-notexpanded token.
	For convenience, a notexpanded token is called a blue token.
	It's not always possible to determine the notexpanded status of a following token in the input stream.

	Implementation note: Token objects must be frozen.
	"""

	@abstractmethod
	def __str__(self)->str: ...

	@abstractmethod
	def repr1(self)->str: ...

	def meaning_str(self, escapechar: Optional[int|str]=None)->str:
		r"""
		Get the meaning of this token as a string.

		>>> C.other("-").meaning_str()
		'the character -'
		>>> T.relax.meaning_str(escapechar="?")
		'?relax'
		>>> T.relax.meaning_str()
		'\\relax'

		Note that all blue tokens have the meaning equal to ``\relax``
		(or ``[unknown command code! (0, 1)]`` in a buggy LuaTeX implementation)
		with the backslash replaced
		by the current ``escapechar``.
		"""
		if escapechar is not None:
			tmp=count["escapechar"]
			count["escapechar"]=_get_charcode(escapechar)
		result=NTokenList([T.meaning, self]).expand_x().str()
		if escapechar is not None:
			count["escapechar"]=tmp
		return result


	@property
	@abstractmethod
	def noexpand(self)->"NToken":
		r"""
		Return the result of ``\noexpand`` applied on this token.
		"""
		...

	@property
	@abstractmethod
	def no_blue(self)->"Token":
		r"""
		Return the result of this token after being "touched", which drops its blue status if any.
		"""
		...

	@abstractmethod
	def put_next(self):
		"""
		Put this token forward in the input stream.
		"""
		...

	def meaning_eq(self, other: "NToken")->bool:
		r"""
		Whether this token is the same in meaning as the token specified in the parameter *other*.
		Equivalent to [TeX]'s ``\ifx``.

		Note that two tokens might have different meaning despite having equal :meth:`meaning_str`.
		"""
		return bool(NTokenList([T.ifx, self, other, Catcode.other("1"), T.fi]).expand_x())

	def is_str(self)->bool:
		return False

	def str_code(self)->int:
		"""
		``self`` must represent a character of a [TeX] string. (i.e. equal to itself when detokenized)

		:return: the character code.

		.. note::
			See :meth:`NTokenList.str_codes`.
		"""
		# default implementation, might not be correct. Subclass overrides as needed.
		raise ValueError("Token does not represent a string!")

	def degree(self)->int:
		"""
		return the imbalance degree for this token (``{`` -> 1, ``}`` -> -1, everything else -> 0)
		"""
		# default implementation, might not be correct. Subclass overrides as needed.
		return 0


class Token(NToken):
	"""
	Represent a [TeX] token, excluding the notexpanded possibility.
	See also documentation of :class:`NToken`.
	"""

	@property
	@abstractmethod
	def can_blue(self)->bool:
		"""
		Return whether this token can possibly be blue i.e. expandable.
		"""
		...

	@property
	def blue(self)->"BlueToken":
		r"""
		Return a :class:`BlueToken` containing ``self``. :attr:`can_blue` must be true. 
		"""
		if not self.can_blue:
			raise ValueError("Token cannot be blue!")
		return BlueToken(self)

	@property
	def noexpand(self)->"NToken":
		if not self.can_blue:
			return self
		return BlueToken(self)

	@abstractmethod
	def serialize(self)->str:
		"""
		Internal function, serialize this token to be able to pass to [TeX].
		"""
		...

	@abstractmethod
	def simple_detokenize(self, get_catcode: Callable[[int], Catcode])->str:
		"""
		Simple approximate detokenizer, implemented in Python.
		"""
		...

	@property
	@abstractmethod
	def assignable(self)->bool:
		"""
		Whether this token can be assigned to i.e. it's control sequence or active character.
		"""
		...

	def is_expandable(self)->bool:
		r"""
		>>> T.relax.is_expandable()
		False
		>>> T.expandafter.is_expandable()
		True
		>>> T.undefined.is_expandable()
		True
		>>> BalancedTokenList([r'\protected\def\__protected_empty{}']).execute()
		>>> T.__protected_empty.is_expandable()
		True
		>>> C.active("a").set_eq(T.empty)
		>>> C.active("a").is_expandable()
		True
		>>> C.other("a").is_expandable()
		False
		"""
		return TokenList([
			T.expandafter, T.ifx, T.noexpand, self, self, C.other("1"), T.fi
			]).expand_x().str() == ""

	def set_eq(self, other: "NToken", global_: bool=False)->None:
		"""
		Assign the meaning of this token to be equivalent to that of the other token.
		"""
		assert self.assignable
		NTokenList([r"\global" if global_ else "", T.let, self, C.other("="), C.space(' '), other]).execute()

	def set_future(self)->None:
		r"""
		Assign the meaning of this token to be equivalent to that of the following token in the input stream.

		For example if this token is ``\a``, and the input stream starts with ``bcde``, then ``\a``'s meaning
		will be assigned to that of the explicit character ``b``.

		.. note::
			Tokenizes one more token in the input stream, and remove its blue status if any.
		"""
		assert self.assignable
		typing.cast(Callable[[PTTBalancedTokenList], None], Python_call_TeX_local(
			r"""
			\cs_new_protected:Npn %name% {
				%read_arg0(\__data)%
				\expandafter \futurelet \__data \pythonimmediatecontinuenoarg
			}
			""" , sync=True))(PTTBalancedTokenList(BalancedTokenList([self])))

	def set_future2(self)->None:
		r"""
		Assign the meaning of this token to be equivalent to that of the second-next token in the input stream.

		For example if this token is ``\a``, and the input stream starts with ``bcde``, then ``\a``'s meaning
		will be assigned to that of the explicit character ``c``.

		.. note::
			Tokenizes two more tokens in the input stream, and remove their blue status if any.
		"""
		assert self.assignable
		typing.cast(Callable[[PTTBalancedTokenList], None], Python_call_TeX_local(
			r"""
			\cs_new_protected:Npn %name% {
				%read_arg0(\__data)%
				\afterassignment \pythonimmediatecontinuenoarg \expandafter \futurelet \__data 
			}
			""" , sync=True))(PTTBalancedTokenList(BalancedTokenList([self])))


	def set_func(self, f: Callable[[], None], global_: bool=False)->str:
		"""
		Assign this token to call the Python function `f` when executed.

		Returns an identifier, as described in :func:`add_handler`.
		"""
		identifier = add_handler(f)
		TokenList([T.gdef if global_ else r"\def", self, r"{"
			 r"\pythonimmediatecallhandler{"+identifier+r"}"
			 r"}"]).execute()
		return identifier

	@property
	def no_blue(self)->"Token": return self

	def __repr__(self)->str:
		return f"<Token: {self.repr1()}>"

	@staticmethod
	def deserialize(s: str|bytes)->"Token":
		"""
		See documentation of :meth:`TokenList.deserialize`.

		Always return a single token.
		"""
		t=TokenList.deserialize(s)
		assert len(t)==1
		return t[0]

	@staticmethod
	def deserialize_bytes(data: bytes)->"Token":
		"""
		See documentation of :meth:`TokenList.deserialize_bytes`.

		Always return a single token.
		"""
		if engine.is_unicode:
			return Token.deserialize(data.decode('u8'))
		else:
			return Token.deserialize(data)

	@typing.overload
	@staticmethod
	def get_next()->Token: ...

	@typing.overload
	@staticmethod
	def get_next(count: int)->TokenList: ...

	@staticmethod
	def get_next(count: Optional[int]=None)->Token|TokenList:
		r"""
		Get the following token.

		.. note::
			in LaTeX3 versions without the commit https://github.com/latex3/latex3/commit/24f7188904d6
			sometimes this may error out.

		.. note::
			because of the internal implementation of ``\peek_analysis_map_inline:n``, this may
			tokenize up to 2 tokens ahead (including the returned token),
			as well as occasionally return the wrong token in unavoidable cases.
		"""
		if count is None: return Token.deserialize_bytes(
			typing.cast(Callable[[], TTPRawLine], Python_call_TeX_local(
				r"""
				\cs_new_protected:Npn \__get_next_callback #1 {
					\peek_analysis_map_break:n { \pythonimmediatecontinue {^^J#1} }
				}
				\cs_new_protected:Npn %name% {
					\peek_analysis_map_inline:n {
						\__tlserialize_char_unchecked:nNnN {##2}##3{##1} \__get_next_callback
					}
				}
				""", recursive=False))())
		assert count>=0
		return TokenList([Token.get_next() for __ in range(count)])

	@staticmethod
	def peek_next()->"Token":
		"""
		Get the following token without removing it from the input stream.

		Equivalent to :meth:`get_next` then :meth:`put_next` immediately. See documentation of :meth:`get_next` for some notes.
		"""
		t=Token.get_next()
		t.put_next()
		return t

	def defined(self)->bool:
		"""
		Return whether this token is defined, that is, its meaning is not ``undefined``.
		"""
		assert self.assignable
		return not BalancedTokenList([T.ifx, self, T["@undefined"], Catcode.other("1"), T.fi]).expand_x()


	def put_next(self)->None:
		d=self.degree()
		if d==0:
			BalancedTokenList([self]).put_next()
		else:
			assert isinstance(self, CharacterToken)
			if not engine.is_unicode and self.index>=256:
				raise ValueError("Cannot put this token for non-Unicode engine!")
			if d==1:
				typing.cast(Callable[[PTTInt], None], Python_call_TeX_local(
					r"""
					\cs_new_protected:Npn %name% {
						%read_arg0(\__index)%
						\expandafter \expandafter \expandafter \pythonimmediatecontinuenoarg
							\char_generate:nn {\__index} {1}
					}
					""", recursive=False, sync=True))(PTTInt(self.index))
			else:
				assert d==-1
				typing.cast(Callable[[PTTInt], None], Python_call_TeX_local(
					r"""
					\cs_new_protected:Npn %name% {
						%read_arg0(\__index)%
						\expandafter \expandafter \expandafter \pythonimmediatecontinuenoarg
							\char_generate:nn {\__index} {2}
					}
					""", recursive=False, sync=True))(PTTInt(self.index))

	def tl(self, content: Optional[BalancedTokenList]=None, *, global_: bool=False)->BalancedTokenList:
		r"""
		Manipulate an expl3 tl variable.

		>>> BalancedTokenList(r'\tl_set:Nn \l_tmpa_tl {1{2}}').execute()
		>>> T.l_tmpa_tl.tl()
		<BalancedTokenList: 1₁₂ {₁ 2₁₂ }₂>
		>>> T.l_tmpa_tl.tl(BalancedTokenList('3+4'))
		<BalancedTokenList: 3₁₂ +₁₂ 4₁₂>
		>>> T.l_tmpa_tl.tl()
		<BalancedTokenList: 3₁₂ +₁₂ 4₁₂>

		"""
		if content is not None:
			TokenList([T.xdef if global_ else T.edef, self, [T.unexpanded, content]]).execute()
			return content
		return BalancedTokenList([self]).expand_o()

	def str(self, val: Optional[str]=None)->str:
		r"""
		Manipulate an expl3 str variable.

		>>> BalancedTokenList(r'\str_set:Nn \l_tmpa_str {a+b}').execute()
		>>> T.l_tmpa_str.str()
		'a+b'
		>>> T.l_tmpa_str.str('e+f')
		'e+f'
		>>> T.l_tmpa_str.str()
		'e+f'
		>>> T.l_tmpa_str.str('e+f\ng')
		'e+f\ng'
		>>> T.l_tmpa_str.str()
		'e+f\ng'
		"""
		if val is not None:
			if PTTVerbatimLine(val).valid():
				typing.cast(Callable[[PTTBalancedTokenList, PTTVerbatimLine], None], Python_call_TeX_local(
					r"""
					\cs_new_protected:Npn %name% {
						%read_arg0(\__container)%
						%read_arg1(\__value)%
						\expandafter \let \__container \__value
						\pythonimmediatecontinuenoarg
					}
					""", recursive=False, sync=True))(PTTBalancedTokenList(BalancedTokenList([self])), PTTVerbatimLine(val))
			elif PTTBlock(val).valid():
				typing.cast(Callable[[PTTBalancedTokenList, PTTBlock], None], Python_call_TeX_local(
					r"""
					\cs_new:Npn \__remove_nl_relax #1 ^^J \relax {#1}
					\cs_new_protected:Npn %name% {
						%read_arg0(\__container)%
						%read_arg1(\__value)%
						\expandafter \__str_continue \expandafter {
							\exp:w \expandafter \expandafter \expandafter \exp_end: \expandafter
							\__remove_nl_relax \__value \relax }
						\pythonimmediatecontinuenoarg
					}
					\cs_new_protected:Npn \__str_continue { \expandafter \def \__container }
					""", recursive=False, sync=True))(PTTBalancedTokenList(BalancedTokenList([self])), PTTBlock(val))
			else:
				self.tl(BalancedTokenList.fstr(val))
			return val
		t=self.tl()
		try: return t.str()
		except ValueError: raise ValueError(f"Token contains {t} which is not a string!")

	def int(self, val: Optional[int]=None)->int:
		r"""
		Manipulate an expl3 int variable.

		>>> BalancedTokenList(r'\int_set:Nn \l_tmpa_int {5+6}').execute()
		>>> T.l_tmpa_int.int()
		11
		
		.. seealso:: :data:`count`.
		"""
		if val is not None:
			(BalancedTokenList([self])+BalancedTokenList.fstr('=' + str(val))).execute()
			return val
		return BalancedTokenList([T.the, self]).expand_o().int()

	def bool(self)->bool:
		r"""
		Manipulate an expl3 bool variable.

		>>> BalancedTokenList(r'\bool_set_true:N \l_tmpa_bool').execute()
		>>> T.l_tmpa_bool.bool()
		True
		"""
		return bool(len(BalancedTokenList([r"\bool_if:NT", self, "1"]).expand_x()))




# TeX code for serializing and deserializing a token list.
# Convert a token list from/to a string.
# functions moved outside in commit 37888c65ecd96f636ea41cf5cacd1763258eff4c.
# Probably a better idea but doesn't seem to be much faster.
mark_bootstrap(
r"""
\precattl_exec:n {

\def \__tldeserialize_start #1 { \csname #1 \endcsname }
\def \cC{__tldeserialize_\^} #1 #2        { \csname #1 \expandafter \expandafter \expandafter \endcsname \char_generate:nn {`#2-64} {12} }
\def \cC{__tldeserialize_\>} #1 #2 \cO\   { \csname #1 \endcsname #2  \cU\  }
\def \cC{__tldeserialize_\*} #1 #2 \cO\  #3 { \csname #1 \endcsname #2  \char_generate:nn {`#3-64} {12} }
\def \cC{__tldeserialize_\\} #1 \cO\   #2 { \unexpanded \expandafter \expandafter \expandafter { \expandafter \noexpand \csname #1 \endcsname }                                 \csname #2 \endcsname }
\def \cC{__tldeserialize_1} #1        #2 { \char_generate:nn {`#1} {1}                                                   \csname #2 \endcsname }
\def \cC{__tldeserialize_2} #1        #2 { \char_generate:nn {`#1} {2}                                                   \csname #2 \endcsname }
\def \cC{__tldeserialize_3} #1        #2 { \char_generate:nn {`#1} {3}                                                   \csname #2 \endcsname }
\def \cC{__tldeserialize_4} #1        #2 { \char_generate:nn {`#1} {4}                                                   \csname #2 \endcsname }
\def \cC{__tldeserialize_6} #1        #2 { ## \char_generate:nn {`#1} {6}                                              \csname #2 \endcsname }
\def \cC{__tldeserialize_7} #1        #2 { \char_generate:nn {`#1} {7}                                                   \csname #2 \endcsname }
\def \cC{__tldeserialize_8} #1        #2 { \char_generate:nn {`#1} {8}                                                   \csname #2 \endcsname }
\def \__tldeserialize_A #1        #2 { \char_generate:nn {`#1} {10}                                                  \csname #2 \endcsname }
\def \__tldeserialize_B #1        #2 { \char_generate:nn {`#1} {11}                                                  \csname #2 \endcsname }
\def \__tldeserialize_C #1        #2 { #1                                                   \csname #2 \endcsname }
\def \__tldeserialize_helper { \expandafter \exp_end: \noexpand }
\def \__tldeserialize_D #1        #2 { \unexpanded \expandafter { \exp:w \expandafter \expandafter \expandafter \__tldeserialize_helper \char_generate:nn {`#1} {13} } \csname #2 \endcsname }
\def \__tldeserialize_R #1            { \cFrozenRelax                                                                  \csname #1 \endcsname }

% here #1 is the target token list to store the result to, #2 is a string with the final '.'.
\cs_new_protected:Npn \__tldeserialize_dot:Nn #1 #2 {
	\begingroup
		%\tl_gset:Nn \__gtmp {#2}
		%\tl_greplace_all:Nnn \__gtmp {~} {\cO\ }
		\tl_gset:Nx \__gtmp {\cC{_ _kernel_str_to_other_fast:n}{#2}}

		\let \^ \cC{__tldeserialize_\^}
		\let \> \cC{__tldeserialize_\>}
		\let \* \cC{__tldeserialize_\*}
		\let \\ \cC{__tldeserialize_\\}
		\let \1 \cC{__tldeserialize_1}
		\let \2 \cC{__tldeserialize_2}
		\let \3 \cC{__tldeserialize_3}
		\let \4 \cC{__tldeserialize_4}
		\let \6 \cC{__tldeserialize_6}
		\let \7 \cC{__tldeserialize_7}
		\let \8 \cC{__tldeserialize_8}
		\let \A \__tldeserialize_A 
		\let \B \__tldeserialize_B 
		\let \C \__tldeserialize_C 
		\let \D \__tldeserialize_D 
		\let \R \__tldeserialize_R 

		\let \. \empty
		\tl_gset:Nx \__gtmp {\expandafter \__tldeserialize_start \__gtmp}
	\endgroup
	\tl_set_eq:NN #1 \__gtmp
}
}

% deserialize as above but #2 does not end with '.'.
\cs_new_protected:Npn \__tldeserialize_nodot:Nn #1 #2 {
	\__tldeserialize_dot:Nn #1 {#2 .}
}
""")

# callback will be called exactly once with the serialized result (either other or space catcode)
# and, as usual, with nothing leftover following in the input stream

# the token itself can be gobbled or \edef-ed to discard it.
# if it's active outer or control sequence outer then gobble fails.
# if it's { or } then edef fails.
@bootstrap_code_functions.append
def _tlserialize(engine: Engine)->str:
	#if engine.name=="luatex": return ""
	return (

r"""

\cs_new_protected:Npn \__char_unchecked:nNnN #char #cat {
	\int_compare:nNnTF {
		\if #cat 1  1 \fi 
		\if #cat 2  1 \fi 
		0
	} = {0} {
		% it's neither 1 nor 2, can edef
		\tl_set:Nn \__process_after_edef { \__continue_after_edef {#char} #cat }
		\afterassignment \__process_after_edef
		\edef \__the_token
	} {
		% it's either 1 or 2
		% might not be able to edef, but can gobble
		\__process_gobble {#char} #cat
	}
}

\precattl_exec:n {

\def \__frozen_relax_container { \cFrozenRelax }
\def \__null_cs_container { \cC{} }

%\edef \__endwrite_container { \noexpand \cEndwrite }
%\tl_if_eq:NnT \__endwrite_container { \cC{cEndwrite} } {
%	\errmessage { endwrite~token~not~supported }
%}

\cs_new:Npn \__prefix_escaper #1 {
	\ifnum 0<\__if_weird_charcode_or_space:n {`#1} ~
		*
	\fi
}
\cs_new:Npn \__content_escaper #1 {
	\ifnum 0<\__if_weird_charcode_or_space:n {`#1} ~
		\cO\  \char_generate:nn {`#1+64} {12}
	\else
		#1
	\fi
}

% fully expand to zero if #1 is not weird, otherwise expand to nonzero
% weird means as can be seen below <32 or =127 (those that will be ^^-escaped without -8bit)
% XeLaTeX also make 80..9f weird
\cs_new:Npn  \__if_weird_charcode:n #1 {
	\ifnum #1 < 32 ~ 1 \fi
	\ifnum #1 > 126 ~ \ifnum #1 < 160 ~ 1 \fi \fi
	0
}

\cs_new:Npn  \__if_weird_charcode_or_space:n #1 {
	\ifnum #1 < 33 ~ 1 \fi
	\ifnum #1 > 126 ~ \ifnum #1 < 160 ~ 1 \fi \fi
	0
}

\cs_new_protected:Npn \__continue_after_edef #char #cat #callback {
	\token_if_eq_charcode:NNTF #cat 0 {
		\tl_if_eq:NNTF \__the_token \__frozen_relax_container {
			#callback {\cO{ R }}
		} {
			\tl_if_eq:NNTF \__the_token \__null_cs_container {
				#callback {\cO{ \\\  }}
			} {
				\tl_set:Nx \__name { \expandafter \cs_to_str:N \__the_token }
				\exp_args:Nx #callback {
					\str_map_function:NN \__name \__prefix_escaper
					\cO\\
					\str_map_function:NN \__name \__content_escaper
					\cO\  }
			}
		}
	} {
		\exp_args:Nx #callback {
			\ifnum 0<\__if_weird_charcode:n {#char} ~
				\cO{^} #cat \char_generate:nn {#char+64} {12}
			\else
				#cat \expandafter \string \__the_token
			\fi
		}
	}
}
"""
.replace("#char", "#1")
.replace("#cat", "#2")
.replace("#callback", "#3")

+

r"""
\cs_new_protected:Npn \__process_gobble #char #cat #token #callback {
	\exp_args:Nx #callback {
		\ifnum 0<\__if_weird_charcode:n {#char} ~
			\cO{^} #cat \char_generate:nn {#char+64} {12}
		\else
			#cat \expandafter \string #token
		\fi
	}
}
"""
.replace("#char", "#1")
.replace("#cat", "#2")
.replace("#token", "#3")
.replace("#callback", "#4")

+

r"""
}

"""

+

(
		"" if engine.name=="luatex" else 
r"""
% serialize token list in #2 store to #1.
\cs_new_protected:Npn \__nodot_unchecked:Nn #1 #2 {
	\tl_build_begin:N #1
	\tl_set:Nn \__callback { \tl_build_put_right:Nn #1 }
	\tl_analysis_map_inline:nn {#2} {
		\__char_unchecked:nNnN {##2}##3{##1} \__callback
	}
	\tl_build_end:N #1
}
""")

).replace("__", "__tlserialize_")

mark_bootstrap(
r"""

% serialize token list in #2 store to #1. Call T or F branch depends on whether serialize is successful.
% #1 must be different from \__tlserialize_tmp.
\cs_new_protected:Npn \__tlserialize_nodot:NnTF #1 #2 {
	\__tlserialize_nodot_unchecked:Nn #1 {#2}
	\__tldeserialize_nodot:NV \__tlserialize_nodot_tmp #1

	\tl_if_eq:NnTF \__tlserialize_nodot_tmp {#2} % dangling
}

\cs_new_protected:Npn \__tlserialize_nodot:NnF #1 #2 {
	\__tlserialize_nodot:NnTF #1 {#2} {} % dangling
}

\cs_new_protected:Npn \__tlserialize_nodot:NnT #1 #2 #3 { \__tlserialize_nodot:NnTF #1 {#2} {#3} {} }

\msg_new:nnn {pythonimmediate} {cannot-serialize} {Token~list~cannot~be~serialized~<#1>}

\cs_new_protected:Npn \__tlserialize_nodot:Nn #1 #2{
	\__tlserialize_nodot:NnF #1 {#2} {
		\msg_error:nnx {pythonimmediate} {cannot-serialize} {\detokenize{#2} -> #1}
	}
}

\cs_generate_variant:Nn \__tldeserialize_dot:Nn {NV}
\cs_generate_variant:Nn \__tldeserialize_nodot:Nn {NV}
\cs_generate_variant:Nn \__tlserialize_nodot:Nn {NV}
""")


enable_get_attribute=True

if is_sphinx_build:
	enable_get_attribute=False  # otherwise it conflicts with sphinx-autodoc's mechanism to inspect the objects

class ControlSequenceTokenMaker:
	r"""
	Shorthand to create :class:`ControlSequenceToken` objects in Python easier.

	>>> from pythonimmediate import T
	>>> assert T is ControlSequenceToken.make
	>>> T.hello
	<Token: \hello>
	>>> T["a@b"]  # for the "harder to construct" tokens
	<Token: \a@b>
	>>> P=ControlSequenceTokenMaker("__mymodule_")
	>>> P.a
	<Token: \__mymodule_a>
	"""
	def __init__(self, prefix: str)->None:
		self.prefix=prefix
	if enable_get_attribute:
		def __getattribute__(self, a: str)->"ControlSequenceToken":
			return ControlSequenceToken(object.__getattribute__(self, "prefix")+a)
	else:
		def __getattr__(self, a: str)->"ControlSequenceToken":
			return ControlSequenceToken(object.__getattribute__(self, "prefix")+a)
	def __getitem__(self, a: str|bytes)->"ControlSequenceToken":
		if isinstance(a, bytes):
			a="".join(map(chr, a))
		return ControlSequenceToken(object.__getattribute__(self, "prefix")+a)


class ControlSequenceToken(Token):
	r"""
	Represents a control sequence::

		>>> ControlSequenceToken("abc")
		<Token: \abc>

	The preferred way to construct a control sequence is :data:`T`.

	Some care is needed to construct control sequence tokens whose name contains Unicode characters,
	as the exact token created depends on whether the engine is Unicode-based:

		>>> with default_engine.set_engine(None):  # if there's no default_engine...
		...     ControlSequenceToken("×")  # this will raise an error
		Traceback (most recent call last):
			...
		AssertionError: Cannot construct a control sequence with non-ASCII characters without specifying is_unicode

	The same control sequences may appear differently on Unicode and non-Unicode engines, and conversely,
	different control sequences may appear the same between Unicode and non-Unicode engines::

		>>> a = ControlSequenceToken("u8:×", is_unicode=False)
		>>> a
		<Token: \u8:×>
		>>> a == ControlSequenceToken(b"u8:\xc3\x97", is_unicode=False)
		True
		>>> a.codes
		(117, 56, 58, 195, 151)
		>>> b = ControlSequenceToken("u8:×", is_unicode=True)
		>>> b
		<Token: \u8:×>
		>>> b.codes
		(117, 56, 58, 215)
		>>> a == b
		False
		>>> a == ControlSequenceToken("u8:\xc3\x97", is_unicode=True)
		True

	*is_unicode* will be fetched from :const:`~pythonimmediate.engine.default_engine`
	if not explicitly specified.
	"""
	_codes: Tuple[int, ...]  # this is the only thing that is guaranteed to be defined.
	_csname: Optional[str]  # defined if csname is representable as a str. The same control sequence may be represented differently depends on is_unicode.
	_csname_bytes: Optional[bytes]  # defined if csname is representable as a bytes.

	def __init__(self, csname: Union[str, bytes], is_unicode: Optional[bool]=None)->None:
		if is_unicode is None and default_engine.engine is not None:
			is_unicode = default_engine.is_unicode

		if is_unicode is None:
			# check csname can only be interpreted as one way (i.e. all codes ≤ 0x7f)
			if isinstance(csname, str):
				assert all(ord(c) <= 0x7f for c in csname), "Cannot construct a control sequence with non-ASCII characters without specifying is_unicode"
			else:
				assert all(c <= 0x7f for c in csname), "Cannot construct a control sequence with non-ASCII characters without specifying is_unicode"

		if isinstance(csname, str):
			self._csname = csname
			self._csname_bytes = csname.encode("u8")
			if is_unicode:
				self._codes = tuple(ord(c) for c in csname)
			else:
				self._codes = tuple(self._csname_bytes)

		else:
			assert is_unicode in (None, False), "Cannot construct control sequence from bytes if is_unicode"
			self._csname_bytes = csname
			try: self._csname = csname.decode('u8')
			except UnicodeDecodeError: self._csname = None
			self._codes = tuple(self._csname_bytes)

	def __eq__(self, other: Any)->bool:
		if not isinstance(other, ControlSequenceToken): return False
		return self._codes == other._codes

	def __hash__(self)->int:
		return hash(self._codes)

	@property
	def codes(self)->Tuple[int, ...]:
		r"""
		Return the codes of this control sequence -- that is, if ``\detokenize{...}`` is applied on this token,
		the tokens with the specified character codes (plus ``\escapechar``) will result.
		"""
		return self._codes

	@property
	def csname(self)->str:
		r"""
		Return some readable name of the control sequence. Might return ``None`` if the name is not representable in UTF-8.
		"""
		assert self._csname is not None
		return self._csname

	@property
	def csname_bytes(self)->bytes:
		assert self._csname_bytes is not None
		return self._csname_bytes

	make=typing.cast(ControlSequenceTokenMaker, None)  # some interference makes this incorrect. Manually assign below
	"""
	Refer to the documentation of :class:`ControlSequenceTokenMaker`.
	"""

	can_blue=True

	@property
	def assignable(self)->bool:
		return True
	def __str__(self)->str:
		if self.csname=="": return r"\csname\endcsname"
		return "\\"+self.csname

	def serialize(self)->str:
		return (
				"*"*sum(1 for x in self.csname if ord(x)<33) +
				"\\" +
				"".join(' '+chr(ord(x)+64) if ord(x)<33 else x   for x in self.csname)
				+ " ")

	def repr1(self)->str:
		return f"\\" + repr(self.csname.replace(' ', "␣"))[1:-1]

	def simple_detokenize(self, get_catcode: Callable[[int], Catcode])->str:
		if not self.csname:
			raise NotImplementedError("This isn't simple!")
		if len(self.csname)>1 or get_catcode(ord(self.csname))==Catcode.letter:
			for ch in self.csname:
				if get_catcode(ord(ch))!=Catcode.letter:
					raise NotImplementedError("This isn't simple!")
			return "\\"+self.csname+" "
		return "\\"+self.csname


ControlSequenceToken.make=ControlSequenceTokenMaker("")

T=ControlSequenceToken.make
"""
See :class:`ControlSequenceTokenMaker`.
"""
P=ControlSequenceTokenMaker("_pythonimmediate_")  # create private tokens

if enable_get_attribute:
	assert isinstance(T.testa, ControlSequenceToken)

class Catcode(enum.Enum):
	"""
	Enum, consist of ``begin_group``, ``end_group``, etc.

	The corresponding enum value is the [TeX] code for the catcode:

	>>> Catcode.letter.value
	11

	This class contains a shorthand to allow creating a token with little Python code.
	The individual :class:`Catcode` objects
	can be called with either a character or a character code to create the object::

		>>> C.letter("a")  # creates a token with category code letter and character code "a"=chr(97)
		<Token: a₁₁>
		>>> C.letter(97)  # same as above
		<Token: a₁₁>

	Both of the above forms are equivalent to ``CharacterToken(index=97, catcode=Catcode.letter)``.

	See also :ref:`token-list-construction` for more ways of constructing token lists.
	"""

	begin_group=bgroup=1
	end_group=egroup=2
	math_toggle=math=3
	alignment=4
	parameter=param=6
	math_superscript=superscript=7
	math_subscript=subscript=8
	space=10
	letter=11
	other=12
	active=13

	escape=0
	end_of_line=paragraph=line=5
	ignored=9
	comment=14
	invalid=15

	@property
	def for_token(self)->bool:
		"""
		Return whether a :class:`CharacterToken`  may have this catcode.

		>>> Catcode.escape.for_token
		False
		>>> Catcode.letter.for_token
		True
		"""
		return self not in (Catcode.escape, Catcode.line, Catcode.ignored, Catcode.comment, Catcode.invalid)

	def __call__(self, ch: Union[str, int])->"CharacterToken":
		if isinstance(ch, str): ch=ord(ch)
		return CharacterToken(ch, self)

	@staticmethod
	def lookup(x: int)->Catcode:
		"""
		Construct from [TeX] code.

		>>> C.lookup(11)
		<Catcode.letter: 11>
		"""
		return _catcode_value_to_member[x]

_catcode_value_to_member = {item.value: item for item in Catcode}

C=Catcode

@dataclass(repr=False, frozen=True)  # must be frozen because bgroup and egroup below are reused
class CharacterToken(Token):
	"""
	Represent a character token. The preferred way to construct a character token
	is using :data:`C`.
	"""

	index: int
	"""
	The character code of this token.

	>>> C.letter("a").index
	97
	"""
	catcode: Catcode
	"""
	>>> C.letter("a").catcode
	<Catcode.letter: 11>
	"""

	@property
	def can_blue(self)->bool:
		return self.catcode==Catcode.active

	@property
	def chr(self)->str:
		"""
		The character of this token.

		>>> C.letter("a").chr
		'a'
		"""
		return chr(self.index)
	def __post_init__(self)->None:
		assert isinstance(self.index, int)
		assert self.index>=0
		assert self.catcode.for_token
	def __str__(self)->str:
		return self.chr
	def serialize(self)->str:
		if self.index<0x10:
			return f"^{self.catcode.value:X}{chr(self.index+0x40)}"
		else:
			return f"{self.catcode.value:X}{self.chr}"
	def repr1(self)->str:
		cat=str(self.catcode.value).translate(str.maketrans("0123456789", "₀₁₂₃₄₅₆₇₈₉"))
		return f"{repr(self.chr)[1:-1]}{cat}"
	@property
	def assignable(self)->bool:
		return self.catcode==Catcode.active
	def degree(self)->int:
		if self.catcode==Catcode.bgroup:
			return 1
		elif self.catcode==Catcode.egroup:
			return -1
		else:
			return 0
	def is_str(self)->bool:
		catcode=Catcode.space if self.index==32 else Catcode.other
		return catcode==self.catcode
	def str_code(self)->int:
		if not self.is_str(): raise ValueError("this CharacterToken does not represent a string!")
		return self.index
	def simple_detokenize(self, get_catcode: Callable[[int], Catcode])->str:
		return self.chr

class _FrozenRelaxToken(Token):
	r"""
	>>> frozen_relax_token
	<Token: [frozen]\relax>
	>>> BalancedTokenList(r'\ifnum 0=0\fi').expand_x()
	<BalancedTokenList: [frozen]\relax>

	:meta public:
	"""
	can_blue=False
	assignable=False

	def __str__(self)->str:
		return r"\relax"
	def serialize(self)->str:
		return "R"
	def repr1(self)->str:
		return r"[frozen]\relax"
	def simple_detokenize(self, get_catcode: Callable[[int], Catcode])->str:
		raise NotImplementedError("This isn't simple!")

frozen_relax_token=_FrozenRelaxToken()
r"""
Constant representing the frozen ``\relax`` token. See :class:`_FrozenRelaxToken`.
"""

# other special tokens later...

bgroup=Catcode.bgroup("{")
egroup=Catcode.egroup("}")
space=Catcode.space(" ")



@dataclass(frozen=True)
class BlueToken(NToken):
	"""
	Represents a blue token (see documentation of :class:`NToken`).
	"""
	token: Token

	@property
	def noexpand(self)->"BlueToken": return self

	@property
	def no_blue(self)->"Token": return self.token

	def __str__(self)->str: return str(self.token)

	def repr1(self)->str: return "notexpanded:"+self.token.repr1()

	def put_next(self)->None:
		typing.cast(Callable[[PTTBalancedTokenList], None], Python_call_TeX_local(
			r"""
			\cs_new_protected:Npn \__put_next_blue_tmp {
				%optional_sync%
				\expandafter \pythonimmediatelisten \noexpand
			}
			\cs_new_protected:Npn %name% {
				%read_arg0(\__target)%
				\expandafter \__put_next_blue_tmp \__target
			}
			""", recursive=False))(PTTBalancedTokenList(BalancedTokenList([self.token])))


doc_catcode_table: Dict[int, Catcode]={}
doc_catcode_table[ord("{")]=Catcode.begin_group
doc_catcode_table[ord("}")]=Catcode.end_group
doc_catcode_table[ord("$")]=Catcode.math_toggle
doc_catcode_table[ord("&")]=Catcode.alignment
doc_catcode_table[ord("#")]=Catcode.parameter
doc_catcode_table[ord("^")]=Catcode.math_superscript
doc_catcode_table[ord("_")]=Catcode.math_subscript
doc_catcode_table[ord(" ")]=Catcode.space
doc_catcode_table[ord("~")]=Catcode.active
for ch in range(ord('a'), ord('z')+1): doc_catcode_table[ch]=Catcode.letter
for ch in range(ord('A'), ord('Z')+1): doc_catcode_table[ch]=Catcode.letter
doc_catcode_table[ord("\\")]=Catcode.escape
doc_catcode_table[ord("%")]=Catcode.comment

e3_catcode_table=dict(doc_catcode_table)
e3_catcode_table[ord("_")]=Catcode.letter
e3_catcode_table[ord(":")]=Catcode.letter
e3_catcode_table[ord(" ")]=Catcode.ignored
e3_catcode_table[ord("\t")]=Catcode.ignored
e3_catcode_table[ord("~")]=Catcode.space


TokenListType = typing.TypeVar("TokenListType", bound="TokenList")

if typing.TYPE_CHECKING:
	TokenListBaseClass = collections.UserList[Token]
	# these are just for type-checking purposes...
	_Bool = bool
	_Str = str
else:  # Python 3.8 compatibility
	TokenListBaseClass = collections.UserList

def TokenList_e3(s: str)->TokenList: return TokenList.e3(s)

class TokenList(TokenListBaseClass):
	r"""
	Represent a [TeX] token list, none of which can contain a blue token.

	The class can be used identical to a Python list consist of :class:`Token` objects,
	plus some additional methods to operate on token lists.

	The list of tokens represented by this class does not need to be balanced.
	Usually you would want to use :class:`BalancedTokenList` instead.

	.. _token-list-construction:

	Token list construction
	-----------------------

	:meth:`__init__` is the constructor of the class, and it accepts parameters in various different forms to allow convenient
	construction of token lists.

	Most generally, you can construct a token list from any iterable consist of (recursively) iterables,
	or tokens, or strings. For example::

		>>> TokenList([Catcode.letter("a"), "bc", [r"def\gh"]])
		<TokenList: a₁₁ b₁₁ c₁₁ {₁ d₁₁ e₁₁ f₁₁ \gh }₂>

	This will make `a` be the token list with value ``abc{def\gh }``.

	Note that the list that is recursively nested inside is used to represent a nesting level.
	A string will be "flattened" into the closest level, but a token list will not be flattened --
	they can be manually flattened with Python ``*`` syntax.

	As a special case, you can construct from a string::

		>>> TokenList(r"\let \a \b")
		<TokenList: \let \a \b>

	The constructor of other classes such as :class:`BalancedTokenList` and :class:`NTokenList`
	works the same way.

	The above working implies that:

	- If you construct a token list from an existing token list, it will be copied (because a :class:`TokenList`
	  is a ``UserList`` of tokens, and iterating over it gives :class:`Token` objects),
	  similar to how you can copy a list with the ``list`` constructor::

		>>> a = TokenList(["hello world"])
		>>> b = TokenList(a)
		>>> b
		<TokenList: h₁₁ e₁₁ l₁₁ l₁₁ o₁₁ w₁₁ o₁₁ r₁₁ l₁₁ d₁₁>
		>>> a==b
		True
		>>> a is b
		False

	- Construct a token list from a list of tokens::

		>>> TokenList([Catcode.letter("a"), Catcode.other("b"), T.test])
		<TokenList: a₁₁ b₁₂ \test>

	  The above will define ``a`` to be ``ab\test``, provided ``T`` is
	  the object referred to in :class:`ControlSequenceTokenMaker`.

	  See also :class:`Catcode` for the explanation of the ``Catcode.letter("a")`` form.

	By default, strings will be converted to token lists using :meth:`TokenList.e3`, although you can customize it by:

	- Passing the second argument to the constructor.
	- Manually specify the type:

		>>> TokenList([T.directlua, [*TokenList.fstr(r"hello%world\?")]])
		<TokenList: \directlua {₁ h₁₂ e₁₂ l₁₂ l₁₂ o₁₂ %₁₂ w₁₂ o₁₂ r₁₂ l₁₂ d₁₂ \\₁₂ ?₁₂ }₂>
	"""

	@staticmethod
	def force_token_list(a: Iterable, string_tokenizer: Callable[[str], TokenList])->Iterable[Token]:
		for x in NTokenList.force_token_list(a, string_tokenizer):
			if not isinstance(x, Token):
				raise RuntimeError(f"Cannot make TokenList from object {x} of type {type(x)}")
			yield x

	def is_balanced(self)->bool:
		"""
		See :meth:`NTokenList.is_balanced`.
		"""
		degree=0
		for x in self:
			degree+=x.degree()
			if degree<0: return False
		return degree==0

	def check_balanced(self)->None:
		"""
		ensure that this is balanced.

		:raises ValueError: if this is not balanced.
		"""
		if not self.is_balanced():
			raise ValueError(f"Token list {self} is not balanced")

	def balanced_parts(self)->"List[Union[BalancedTokenList, Token]]":
		"""
		Internal function, used for serialization and sending to [TeX].

		Split this :class:`TokenList` into a list of balanced parts and unbalanced ``{``/``}`` tokens.
		"""
		degree=0
		min_degree=0, 0
		for i, token in enumerate(self):
			degree+=token.degree()
			min_degree=min(min_degree, (degree, i+1))
		min_degree_pos=min_degree[1]

		left_half: List[Union[BalancedTokenList, Token]]=[]
		degree=0
		last_pos=0
		for i in range(min_degree_pos):
			d=self[i].degree()
			degree+=d
			if degree<0:
				degree=0
				if last_pos!=i:
					left_half.append(BalancedTokenList(self[last_pos:i]))
				left_half.append(self[i])
				last_pos=i+1
		if min_degree_pos!=last_pos:
			left_half.append(BalancedTokenList(self[last_pos:min_degree_pos]))

		right_half: List[Union[BalancedTokenList, Token]]=[]
		degree=0
		last_pos=len(self)
		for i in range(len(self)-1, min_degree_pos-1, -1):
			d=self[i].degree()
			degree-=d
			if degree<0:
				degree=0
				if i+1!=last_pos:
					right_half.append(BalancedTokenList(self[i+1:last_pos]))
				right_half.append(self[i])
				last_pos=i
		if min_degree_pos!=last_pos:
			right_half.append(BalancedTokenList(self[min_degree_pos:last_pos]))

		return left_half+right_half[::-1]

	def put_next(self)->None:
		"""
		Put this token list forward in the input stream.
		"""
		for part in reversed(self.balanced_parts()): part.put_next()

	@property
	def balanced(self)->"BalancedTokenList":
		"""
		``self`` must be balanced.

		:return: a :class:`BalancedTokenList` containing the content of this object.
		"""
		return BalancedTokenList(self)

	@staticmethod
	def _iterable_from_string(s: str, get_catcode: Callable[[int], Catcode])->Iterable[Token]:
		"""
		Refer to documentation of :meth:`from_string` for details.
		"""
		i=0
		while i<len(s):
			ch=s[i]
			i+=1
			cat=get_catcode(ord(ch))
			if cat==Catcode.space:
				yield space
				# special case: collapse multiple spaces into one but only if character code is space
				if get_catcode(32) in (Catcode.space, Catcode.ignored):
					while i<len(s) and s[i]==' ':
						i+=1
			elif cat.for_token:
				yield cat(ch)
			elif cat==Catcode.ignored:
				continue
			else:
				assert cat==Catcode.escape, f"cannot create TokenList from string containing catcode {cat}"
				cat=get_catcode(ord(s[i]))
				if cat!=Catcode.letter:
					yield ControlSequenceToken(s[i])
					i+=1
				else:
					csname=s[i]
					i+=1
					while i<len(s) and get_catcode(ord(s[i]))==Catcode.letter:
						csname+=s[i]
						i+=1
					yield ControlSequenceToken(csname)
					# special case: remove spaces after control sequence but only if character code is space
					if get_catcode(32) in (Catcode.space, Catcode.ignored):
						while i<len(s) and s[i]==' ':
							i+=1

	@classmethod
	def from_string(cls: Type[TokenListType], s: str, get_catcode: Callable[[int], Catcode], endlinechar: str)->TokenListType:
		"""
		Approximate tokenizer implemented in Python.

		Convert a string to a :class:`TokenList` (or some subclass of it such as :class:`BalancedTokenList` approximately.

		This is an internal function and should not be used directly. Use one of :meth:`e3` or :meth:`doc` instead.

		These are used to allow constructing a :class:`TokenList` object in Python without being too verbose.
		Refer to :ref:`token-list-construction` for alternatives.

		The tokenization algorithm is slightly different from [TeX]'s in the following respect:

		* multiple spaces are collapsed to one space, but only if it has character code space (32).
		  i.e. in expl3 catcode, ``~~`` get tokenized to two spaces.
		* spaces with character code different from space (32) after a control sequence is not ignored.
		  i.e. in expl3 catcode, ``~`` always become a space.
		* ``^^`` syntax are not supported. Use Python's escape syntax (e.g. ``\x01``) as usual
		  (of course that does not work in raw Python strings ``r"..."``).

		:param get_catcode: A function that given a character code, return its desired category code.
		"""
		assert len(endlinechar)<=1
		return cls(TokenList._iterable_from_string(s.replace('\n', endlinechar), get_catcode))

	@classmethod
	def e3(cls: Type[TokenListType], s: str)->TokenListType:
		r"""
		Approximate tokenizer in expl3 (``\ExplSyntaxOn``) catcode regime.

		Refer to documentation of :meth:`from_string` for details.

		Usage example::

			>>> BalancedTokenList.e3(r'\cs_new_protected:Npn \__mymodule_myfunction:n #1 { #1 #1 }')
			<BalancedTokenList: \cs_new_protected:Npn \__mymodule_myfunction:n #₆ 1₁₂ {₁ #₆ 1₁₂ #₆ 1₁₂ }₂>
			>>> BalancedTokenList.e3('a\tb\n\nc')
			<BalancedTokenList: a₁₁ b₁₁ c₁₁>
		"""
		return cls.from_string(s, lambda x: e3_catcode_table.get(x, Catcode.other), ' ')

	@classmethod
	def fstr_if_unicode(cls: Type[TokenListType], s: str|bytes, is_unicode: bool)->TokenListType:
		if isinstance(str, bytes):
			assert not is_unicode, "Cannot use bytes if is_unicode"
		if not is_unicode and isinstance(s, str):
			s=s.encode('u8')
		return cls(space if ch in (32, ' ') else C.other(ch) for ch in s)

	@classmethod
	def fstr(cls: Type[TokenListType], s: str, is_unicode: Optional[bool]=None)->TokenListType:
		r"""
		Approximate tokenizer in detokenized catcode regime.

		Refer to documentation of :meth:`from_string` for details.
		``^^J`` (or ``\n``) is used to denote newlines.

		>>> BalancedTokenList.fstr('hello world')
		<BalancedTokenList: h₁₂ e₁₂ l₁₂ l₁₂ o₁₂  ₁₀ w₁₂ o₁₂ r₁₂ l₁₂ d₁₂>
		>>> BalancedTokenList.fstr('ab\\c  d\n \t')
		<BalancedTokenList: a₁₂ b₁₂ \\₁₂ c₁₂  ₁₀  ₁₀ d₁₂ \n₁₂  ₁₀ \t₁₂>

		Some care need to be taken for Unicode strings.
		>>> with default_engine.set_engine(None): BalancedTokenList.fstr('α')
		Traceback (most recent call last):
			...
		RuntimeError: Default engine not set for this thread!
		>>> with default_engine.set_engine(luatex_engine): BalancedTokenList.fstr('α')
		<BalancedTokenList: α₁₂>
		>>> BalancedTokenList.fstr('α')
		<BalancedTokenList: Î₁₂ ±₁₂>
		"""
		if is_unicode is None: is_unicode=engine.is_unicode
		return cls.fstr_if_unicode(s, is_unicode=is_unicode)

	@classmethod
	def doc(cls: Type[TokenListType], s: str)->TokenListType:
		r"""
		Approximate tokenizer in document (normal) catcode regime.

		Refer to documentation of :meth:`from_string` for details.

		Usage example::

			>>> BalancedTokenList.doc(r'\def\a{b}')
			<BalancedTokenList: \def \a {₁ b₁₁ }₂>
			>>> BalancedTokenList.doc('}')
			Traceback (most recent call last):
				...
			ValueError: Token list <BalancedTokenList: }₂> is not balanced
			>>> BalancedTokenList.doc('\n\n')
			Traceback (most recent call last):
				...
			NotImplementedError: Double-newline to \par not implemented yet!
			>>> TokenList.doc('}')
			<TokenList: }₂>
		"""
		if "\n\n" in s:
			raise NotImplementedError(r"Double-newline to \par not implemented yet!")
		return cls.from_string(s, lambda x: doc_catcode_table.get(x, Catcode.other), ' ')

	def __init__(self, a: Iterable=(), string_tokenizer: Callable[[str], TokenList]=TokenList_e3)->None:
		"""
		Refer to :class:`TokenList` on how to use this function.
		"""
		super().__init__(TokenList.force_token_list(a, string_tokenizer))
		
	def serialize(self)->str:
		return "".join(t.serialize() for t in self)

	def serialize_bytes(self)->bytes:
		"""
		Internal function.

		Given an engine, serialize it in a form that is suitable for writing directly to the engine.
		"""
		if engine.is_unicode:
			return self.serialize().encode('u8')
		else:
			result=self.serialize()
			try:
				return bytes(ord(ch) for ch in result)
			except ValueError:
				raise ValueError("Cannot serialize TokenList for non-Unicode engine!")

	@classmethod
	def deserialize(cls: Type[TokenListType], data: str|bytes)->TokenListType:
		result: List[Token]=[]
		i=0

		# hack
		if isinstance(data, bytes):
			data="".join(chr(i) for i in data)

		while i<len(data):

			if data[i] in "\\>*":
				start=data.find("\\", i)
				pos=start+1
				csname=""
				for op in data[i:start]:
					if op==">":
						assert False
					elif op=="*":
						n=data.find(' ', pos)+2
						csname+=data[pos:n-2]+chr(ord(data[n-1])-64)
						pos=n
					else:
						assert False

				i=data.find(' ', pos)+1
				csname+=data[pos:i-1]
				result.append(ControlSequenceToken(csname))

			elif data[i]=="R":
				result.append(frozen_relax_token)
				i+=1
			elif data[i]=="^":
				result.append(CharacterToken(index=ord(data[i+2])-0x40, catcode=Catcode(int(data[i+1], 16))))
				i+=3
			else:
				result.append(CharacterToken(index=ord(data[i+1]), catcode=Catcode(int(data[i], 16))))
				i+=2
		return cls(result)

	@classmethod
	def deserialize_bytes(cls: Type[TokenListType], data: bytes)->TokenListType:
		"""
		Internal function.

		Given a bytes object read directly from the engine, deserialize it.
		"""
		if engine.is_unicode:
			return cls.deserialize(data.decode('u8'))
		else:
			return cls.deserialize(data)

	def __repr__(self)->str:
		return '<' + type(self).__name__ + ': ' + ' '.join(t.repr1() for t in self) + '>'

	def execute(self)->None:
		r"""
		Execute this token list. It must not "peek ahead" in the input stream.

		For example the token list ``\catcode1=2\relax`` can be executed safely
		(and sets the corresponding category code),
		but there's no guarantee what will be assigned to ``\tmp`` when ``\futurelet\tmp`` is executed.
		"""
		NTokenList(self).execute()

	def expand_x(self)->"BalancedTokenList":
		"""
		Return the ``x``-expansion of this token list.

		The result must be balanced, otherwise the behavior is undefined.
		"""
		return NTokenList(self).expand_x()

	def is_str(self)->bool:
		return all(t.is_str() for t in self)

	def simple_detokenize(self, get_catcode: Callable[[int], Catcode])->str:
		return "".join(token.simple_detokenize(get_catcode) for token in self)

	def str_codes(self)->list[int]:
		"""
		``self`` must represent a [TeX] string. (i.e. equal to itself when detokenized)

		:return: the string content.

		>>> BalancedTokenList("abc").str_codes()
		Traceback (most recent call last):
			...
		ValueError: this CharacterToken does not represent a string!
		>>> BalancedTokenList("+-=").str_codes()
		[43, 45, 61]

		.. note::
			In non-Unicode engines, each token will be replaced with a character
			with character code equal to the character code of that token.
			UTF-8 characters with character code ``>=0x80`` will be represented by multiple
			characters in the returned string.
		"""
		return [t.str_code() for t in self]

	def str(self)->str:
		"""
		``self`` must represent a [TeX] string. (i.e. equal to itself when detokenized)

		:return: the string content.

		>>> BalancedTokenList([C.other(0xce), C.other(0xb1)]).str()
		'α'
		>>> with default_engine.set_engine(luatex_engine): BalancedTokenList([C.other('α')]).str()
		'α'
		"""
		return self.str_if_unicode(engine.is_unicode)

	def str_if_unicode(self, unicode: bool=True)->_Str:
		"""
		Assume this token list represents a string in a (Unicode/non-Unicode) engine, return the string content.

		If the engine is not Unicode, assume the string is encoded in UTF-8.
		"""
		if unicode:
			return "".join(map(chr, self.str_codes()))
		else:
			return bytes(self.str_codes()).decode('u8')

	def int(self)->int:
		r"""
		Assume this token list contains an integer (as valid result of ``\number ...``),
		returns the integer value.

		At the moment, not much error checking is done.
		"""
		return int(self.str_if_unicode())


class BalancedTokenList(TokenList):
	"""
	Represents a balanced token list.

	Some useful methods to interact with [TeX]
	include :meth:`expand_o`, :meth:`expand_x`, :meth:`get_next` and :meth:`put_next`.
	See the corresponding methods' documentation for usage examples.

	See also :ref:`token-list-construction` for shorthands to construct token lists in Python code.

	.. note::
		Runtime checking is not strictly enforced,
		use :meth:`~TokenList.is_balanced()` method explicitly if you need to check.
	"""

	def __init__(self, a: Iterable=(), string_tokenizer: Callable[[str], TokenList]=TokenList.e3)->None:
		"""
		Constructor.

		:raises ValueError: if the token list is not balanced.
		"""
		super().__init__(a, string_tokenizer)
		self.check_balanced()

	def expand_o(self)->"BalancedTokenList":
		"""
		Return the ``o``-expansion of this token list.

		The result must be balanced, otherwise the behavior is undefined.
		"""
		return typing.cast(Callable[[PTTBalancedTokenList], TTPBalancedTokenList], Python_call_TeX_local(
			r"""
			\cs_new_protected:Npn %name% {
				%read_arg0(\__data)%
				\exp_args:NNV \tl_set:No \__data \__data
				%sync%
				%send_arg0_var(\__data)%
				\pythonimmediatelisten
			}
			""", recursive=expansion_only_can_call_Python))(PTTBalancedTokenList(self))

	def expand_x(self)->"BalancedTokenList":
		return typing.cast(Callable[[PTTBalancedTokenList], TTPBalancedTokenList], Python_call_TeX_local(
		r"""
		\cs_new_protected:Npn %name% {
			%read_arg0(\__data)%
			\tl_set:Nx \__data {\__data}
			%sync%
			%send_arg0_var(\__data)%
			\pythonimmediatelisten
		}
		""", recursive=expansion_only_can_call_Python))(PTTBalancedTokenList(self))

	def expand_estr(self)->str:
		"""
		Expand this token list according to :ref:`estr-expansion`.

		It's undefined behavior if the expansion result is unbalanced.
		"""
		BalancedTokenList([self]).put_next()
		return get_arg_estr()

	def execute(self)->None:
		typing.cast(Callable[[PTTBalancedTokenList], None], Python_call_TeX_local(
			r"""
			\cs_new_protected:Npn %name% {
				%read_arg0(\__data)%
				\__data
				%optional_sync%
				\pythonimmediatelisten
			}
			"""))(PTTBalancedTokenList(self))

	def put_next(self)->None:
		typing.cast(Callable[[PTTBalancedTokenList], None], Python_call_TeX_local(
			r"""
			\cs_new_protected:Npn \__put_next_tmp {
				%optional_sync%
				\pythonimmediatelisten
			}
			\cs_new_protected:Npn %name% {
				%read_arg0(\__target)%
				\expandafter \__put_next_tmp \__target
			}
			""", recursive=False))(PTTBalancedTokenList(self))

	@staticmethod
	def get_next()->"BalancedTokenList":
		"""
		Get an (undelimited) argument from the [TeX] input stream.
		"""
		return typing.cast(Callable[[], TTPBalancedTokenList], Python_call_TeX_local(
			r"""
			\cs_new_protected:Npn %name% #1 {
				%sync%
				%send_arg0(#1)%
				\pythonimmediatelisten
			}
			""", recursive=False))()

	@staticmethod
	def _get_until_raw(delimiter: BalancedTokenList, long: bool)->"BalancedTokenList":
		"""
		Internal function.

		Get a delimited argument from the [TeX] input stream, delimited by `delimiter`.

		This works the same way as delimited argument, so in particular the argument must be balanced,
		and the delimiter must not contain any ``#`` or braces.
		No error-checking is done.

		The delimiter itself will also be removed.

		As a special case, delimiter can be a token list consist of a single ``#``, in which case the corresponding [TeX] behavior
		will be used and it takes from the input stream until a ``{``, and the ``{`` itself will not be removed.
		"""
		assert delimiter, "Delimiter cannot be empty!"
		try:
			return typing.cast(Callable[[PTTBalancedTokenList], TTPBalancedTokenList], Python_call_TeX_local(
				# '#1' is either \long or [], '#2' is the delimiter
				r"""
				\cs_new_protected:Npn \__get_until_tmp #1 #2 {
					#1 \def \__delimit_tmpii ##1 #2 {
						%sync%
						%send_arg0(##1)%
						\pythonimmediatelisten
					}
					\__delimit_tmpii
				}
				\cs_new_protected:Npn %name% {
					%read_arg0(\__arg)%
					\expandafter \__get_until_tmp \__arg
				}
				""", recursive=False))(PTTBalancedTokenList(BalancedTokenList([r"\long" if long else [], delimiter])))
		except:
			print(f"Error in _get_until_raw with delimiter = {delimiter}")
			raise

	@staticmethod
	def get_until(delimiter: BalancedTokenList, remove_braces: bool=True, long: bool=True)->"BalancedTokenList":
		r"""
		Get a delimited argument from the [TeX] input stream, delimited by `delimiter`.

		The delimiter itself will also be removed from the input stream.

		:param long: Works the same as ``\long`` primitive in [TeX] -- if this is ``False``
			then [TeX] fatal error ``Runaway argument`` will be raised if there's a ``\par`` token in the argument.
		"""
		assert delimiter, "Delimiter cannot be empty!"
		for t in delimiter:
			if isinstance(t, CharacterToken):
				assert t.catcode not in [Catcode.bgroup, Catcode.egroup, Catcode.param], f"A token with catcode {t.catcode} cannot be a delimiter!"

		if not remove_braces:
			auxiliary_token = T.empty
			if delimiter[0]==auxiliary_token: auxiliary_token = T.relax
			auxiliary_token.put_next()
		result = BalancedTokenList._get_until_raw(delimiter, long=long)
		if not remove_braces:
			assert result[0]==auxiliary_token
			del result[0]

		return result

	@staticmethod
	def get_until_brace(long: bool=True)->"BalancedTokenList":
		r"""
		Get a TokenList from the input stream delimited by ``{``. The brace is not removed from the input stream.
		"""
		return BalancedTokenList._get_until_raw(BalancedTokenList("#"), long=long)

	def detokenize(self)->str:
		r"""
		:return: a string, equal to the result of ``\detokenize`` applied to this token list.
		"""
		return BalancedTokenList([T.detokenize, self]).expand_x().str()


if typing.TYPE_CHECKING:
	NTokenListBaseClass = collections.UserList[NToken]
else:  # Python 3.8 compatibility
	NTokenListBaseClass = collections.UserList

class NTokenList(NTokenListBaseClass):
	"""
	Similar to :class:`TokenList`, but can contain blue tokens.

	The class can be used identical to a Python list consist of :class:`NToken` objects,
	plus some additional methods to operate on token lists.

	Refer to the documentation of :class:`TokenList` for some usage example.
	"""

	@staticmethod
	def force_token_list(a: Iterable, string_tokenizer: Callable[[str], TokenList])->Iterable[NToken]:
		if isinstance(a, str):
			yield from string_tokenizer(a)
			return
		for x in a:
			if isinstance(x, NToken):
				yield x
			elif isinstance(x, str):
				yield from string_tokenizer(x)
			elif isinstance(x, Sequence):
				yield bgroup
				child=BalancedTokenList(x)
				assert child.is_balanced()
				yield from child
				yield egroup
			else:
				raise RuntimeError(f"Cannot make TokenList from object {x} of type {type(x)}")

	def __init__(self, a: Iterable=(), string_tokenizer: Callable[[str], TokenList]=TokenList.e3)->None:
		super().__init__(NTokenList.force_token_list(a, string_tokenizer))

	def is_balanced(self)->bool:
		"""
		Check if this is balanced.
		"""
		return TokenList(self).is_balanced()  # a bit inefficient (need to construct a TokenList) but good enough

	def simple_parts(self)->List[Union[BalancedTokenList, Token, BlueToken]]:
		"""
		Internal function.

		Split this :class:`NTokenList` into a list of balanced non-blue parts,
		unbalanced ``{``/``}`` tokens, and blue tokens.
		"""
		parts: List[Union[TokenList, BlueToken]]=[TokenList()]
		for i in self:
			if isinstance(i, BlueToken):
				parts+=i, TokenList()
			else:
				assert isinstance(i, Token)
				last_part=parts[-1]
				assert isinstance(last_part, TokenList)
				last_part.append(i)
		result: List[Union[BalancedTokenList, Token, BlueToken]]=[]
		for large_part in parts:
			if isinstance(large_part, BlueToken):
				result.append(large_part)
			else:
				result+=large_part.balanced_parts()
		return result

	def put_next(self)->None:
		"""
		See :meth:`BalancedTokenList.put_next`.
		"""
		for part in reversed(self.simple_parts()): part.put_next()
		
	def execute(self)->None:
		"""
		See :meth:`BalancedTokenList.execute`.
		"""
		parts=self.simple_parts()
		if len(parts)==1:
			x=parts[0]
			if isinstance(x, BalancedTokenList):
				x.execute()
				return
		NTokenList([*self, T.pythonimmediatecontinue, []]).put_next()
		continue_until_passed_back()

	def expand_x(self)->BalancedTokenList:
		"""
		See :meth:`BalancedTokenList.expand_x`.
		"""
		NTokenList([T.edef, P.tmp, bgroup, *self, egroup]).execute()
		return BalancedTokenList([P.tmp]).expand_o()


class TeXToPyData(ABC):
	"""
	Internal class (for now). Represent a data type that can be sent from [TeX] to Python.
	"""

	@staticmethod
	@abstractmethod
	def read()->"TeXToPyData":
		"""
		Given that [TeX] has just sent the data, read into a Python object.
		"""
		...
	@staticmethod
	@abstractmethod
	def send_code(arg: str)->str:
		"""
		Return some [TeX] code that sends the argument to Python, where *arg* represents a token list or equivalent (such as ``#1``).
		"""
		pass
	@staticmethod
	@abstractmethod
	def send_code_var(var: str)->str:
		r"""
		Return some [TeX] code that sends the argument to Python, where *var* represents a token list variable
		(such as ``\l__my_var_tl``) that contains the content to be sent.
		"""
		pass

# tried and failed
#@typing.runtime_checkable
#class TeXToPyData(Protocol):
#	@staticmethod
#	def read()->"TeXToPyData":
#		...
#
#	#send_code: str
#
#	#@staticmethod
#	#@property
#	#def send_code()->str:
#	#	...


class TTPRawLine(TeXToPyData, bytes):
	send_code=r"\__send_content%naive_send%:n {{ {} }}".format
	send_code_var=r"\__send_content%naive_send%:n {{ {} }}".format
	@staticmethod
	def read()->"TTPRawLine":
		line=engine.read()
		return TTPRawLine(line)

class TTPLine(TeXToPyData, str):
	send_code=r"\__send_content%naive_send%:n {{ {} }}".format
	send_code_var=r"\__send_content%naive_send%:n {{ {} }}".format
	@staticmethod
	def read()->"TTPLine":
		return TTPLine(_readline())

class TTPELine(TeXToPyData, str):
	"""
	Same as :class:`TTPEBlock`, but for a single line only.
	"""
	send_code=r"\__begingroup_setup_estr: \__send_content%naive_send%:e {{ {} }} \endgroup".format
	send_code_var=r"\__begingroup_setup_estr: \__send_content%naive_send%:e {{ {} }} \endgroup".format
	@staticmethod
	def read()->"TTPELine":
		return TTPELine(_readline())

class TTPEmbeddedLine(TeXToPyData, str):
	@staticmethod
	def send_code(self)->str:
		raise RuntimeError("Must be manually handled")
	@staticmethod
	def send_code_var(self)->str:
		raise RuntimeError("Must be manually handled")
	@staticmethod
	def read()->"TTPEmbeddedLine":
		raise RuntimeError("Must be manually handled")

class TTPBlock(TeXToPyData, str):
	send_code=r"\__send_block:n {{ {} }} %naive_flush%".format
	send_code_var=r"\__send_block:V {} %naive_flush%".format
	@staticmethod
	def read()->"TTPBlock":
		return TTPBlock(_read_block())

class TTPEBlock(TeXToPyData, str):
	r"""
	A kind of argument that interprets "escaped string" and fully expand anything inside.
	For example, ``{\\}`` sends a single backslash to Python, ``{\{}`` sends a single ``{`` to Python.

	Done by fully expand the argument in ``\escapechar=-1`` and convert it to a string.
	Additional precaution is needed, see the note above (TODO write documentation).

	Refer to :ref:`estr-expansion` for more details.
	"""
	send_code=r"\__begingroup_setup_estr: \__send_block%naive_send%:e {{ {} }} \endgroup".format
	send_code_var=r"\__begingroup_setup_estr: \__send_block%naive_send%:e {{ {} }} \endgroup".format
	@staticmethod
	def read()->"TTPEBlock":
		return TTPEBlock(_read_block())

@bootstrap_code_functions.append
def _send_balanced_tl(engine: Engine)->str:
	if engine.name=="luatex": return ""
	return naive_replace(r"""
	\cs_new_protected:Npn \__send_balanced_tl:n #1 {
		\__tlserialize_nodot:Nn \__tmp { #1 }
		\__send_content%naive_send%:e {\unexpanded\expandafter{ \__tmp } }
	}
	""", engine)

class TTPBalancedTokenList(TeXToPyData, BalancedTokenList):
	send_code=r"\__send_balanced_tl:n {{ {} }}%naive_ignore%".format
	send_code_var=r"\exp_args:NV \__send_balanced_tl:n {}%naive_ignore%".format
	def __repr__(self):
		return repr(BalancedTokenList(self))
	@staticmethod
	def read()->"TTPBalancedTokenList":
		if engine.is_unicode:
			return TTPBalancedTokenList(BalancedTokenList.deserialize(_readline()))
		else:
			return TTPBalancedTokenList(BalancedTokenList.deserialize(engine.read()))


class PyToTeXData(ABC):
	"""
	Internal class (for now). Represent a data type that can be sent from Python to [TeX].
	"""

	@staticmethod
	@abstractmethod
	def read_code(var: str)->str:
		r"""
		Takes an argument, the variable name (with backslash prefixed such as ``"\abc"``.)

		:return: some [TeX] code that when executed in expl3 category code regime,
		will read a value of the specified data type and assign it to the variable.
		"""
		...
	@abstractmethod
	def serialize(self)->bytes:
		"""
		Return a bytes object that can be passed to ``engine.write()`` directly.
		"""
		...

@dataclass
class PTTVerbatimRawLine(PyToTeXData):
	r"""
	Represents a line to be tokenized verbatim. Internally the ``\readline`` primitive is used, as such, any trailing spaces are stripped.
	The trailing newline is not included, i.e. it's read under ``\endlinechar=-1``.
	"""
	data: bytes
	read_code=r"\__str_get:N {} ".format
	def valid(self)->bool:
		return b"\n" not in self.data and self.data.rstrip()==self.data
	def serialize(self)->bytes:
		assert self.valid()
		return self.data+b"\n"

@dataclass
class PTTVerbatimLine(PyToTeXData):
	data: str
	read_code=PTTVerbatimRawLine.read_code
	@property
	def _raw(self)->PTTVerbatimRawLine:
		return PTTVerbatimRawLine(self.data.encode('u8'))
	def valid(self)->bool:
		return self._raw.valid()
	def serialize(self)->bytes:
		return self._raw.serialize()

@dataclass
class PTTInt(PyToTeXData):
	data: int
	read_code=PTTVerbatimLine.read_code
	def serialize(self)->bytes:
		return PTTVerbatimLine(str(self.data)).serialize()

@dataclass
class PTTTeXLine(PyToTeXData):
	r"""
	Represents a line to be tokenized in \TeX's current catcode regime.
	The trailing newline is not included, i.e. it's tokenized under ``\endlinechar=-1``.
	"""
	data: str
	read_code=r"\exp_args:Nno \use:nn {{ \endlinechar-1 \ior_get:NN \__read_file {} \endlinechar}} {{\the\endlinechar\relax}}".format
	def serialize(self)->bytes:
		assert "\n" not in self.data
		return (self.data+"\n").encode('u8')

@dataclass
class PTTBlock(PyToTeXData):
	data: str
	read_code=r"\__read_block:N {}".format

	@staticmethod
	def ignore_last_space(s: str)->PTTBlock:
		"""
		Construct a block from arbitrary string, deleting trailing spaces on each line.
		"""
		return PTTBlock("\n".join(line.rstrip() for line in s.split("\n")))

	@staticmethod
	def coerce(s: str)->PTTBlock:
		"""
		Construct a block from arbitrary string, delete some content if needed.
		"""
		return PTTBlock("\n".join(line.rstrip() for line in s.split("\n")))

	def valid(self)->bool:
		return "\r" not in self.data and all(line==line.rstrip() for line in self.data.splitlines())

	def serialize(self)->bytes:
		assert self.valid(), self
		return surround_delimiter(self.data).encode('u8')

@dataclass
class PTTBalancedTokenList(PyToTeXData):
	data: BalancedTokenList
	read_code=r"\__str_get:N {0}  \__tldeserialize_dot:NV {0} {0}".format
	def serialize(self)->bytes:
		return PTTVerbatimRawLine(self.data.serialize_bytes()+b".").serialize()


# ======== define TeX functions that execute Python code ========
# ======== implementation of ``\py`` etc. Doesn't support verbatim argument yet. ========

import itertools
import string

def random_TeX_identifiers()->Iterator[str]:  # do this to avoid TeX hash collision while keeping the length short
	for len_ in itertools.count(0):
		for value in range(1<<len_):
			for initial in string.ascii_letters:
				identifier = initial
				if len_>0:
					identifier += f"{value:0{len_}b}".translate({ord("0"): "a", ord("1"): "b"})
				yield identifier

def random_Python_identifiers()->Iterator[str]:  # these are used for keys in
	for len_ in itertools.count(0):
		for s in itertools.product(string.ascii_letters, repeat=len_):
			yield "".join(s)

random_TeX_identifier_iterable=random_TeX_identifiers()
random_Python_identifier_iterable=random_Python_identifiers()

def get_random_TeX_identifier()->str: return next(random_TeX_identifier_iterable)
def get_random_Python_identifier()->str: return next(random_Python_identifier_iterable)


def define_TeX_call_Python(f: Callable[..., None], name: Optional[str]=None, argtypes: Optional[List[Type[TeXToPyData]]]=None, identifier: Optional[str]=None)->EngineDependentCode:
	r"""
	This function setups some internal data structure, and
	returns the [TeX]-code to be executed on the [TeX]-side to define the macro.

	:param f: the Python function to be executed.
		It should take some arguments plus a keyword argument ``engine`` and eventually (optionally) call one of the ``_finish`` functions.
	:param name: the macro name on the [TeX]-side. This should only consist of letter characters in ``expl3`` catcode regime.
	:param argtypes: list of argument types. If it's None it will be automatically deduced from the function ``f``'s signature.
	:param identifier: should be obtained by :func:`get_random_Python_identifier`.
	:returns: some code (to be executed in ``expl3`` catcode regime) as explained above.

	:meta private:
	"""
	if argtypes is None:
		argtypes=[p.annotation for p in inspect.signature(f).parameters.values()]

	for i, argtype in enumerate(argtypes):
		if isinstance(argtype, str):
			assert argtype in globals(), f"cannot resolve string annotation {argtype}"
			argtypes[i]=argtype=globals()[argtype]

	argtypes=[t for t in argtypes if t is not Engine]  # temporary hack

	for argtype in argtypes:
		if not issubclass(argtype, TeXToPyData):
			raise RuntimeError(f"Argument type {argtype} is incorrect, should be a subclass of TeXToPyData")

	if name is None: name=f.__name__

	if identifier is None: identifier=get_random_Python_identifier()
	assert identifier not in _handlers, identifier

	@functools.wraps(f)
	def g()->None:
		if engine.config.debug>=5:
			print("TeX macro", name, "called")
		assert argtypes is not None
		args=[argtype.read() for argtype in argtypes]

		assert engine.status==EngineStatus.running  # this is the status just before the handler is called
		engine.status=EngineStatus.waiting

		f(*args)
		if engine.status==EngineStatus.waiting:
			run_none_finish()
			assert engine.status==EngineStatus.running, engine.status

		assert engine.status==EngineStatus.running, engine.status

	_handlers[identifier]=g

	TeX_argspec = ""
	TeX_send_input_commands = ""
	for i, argtype in enumerate(argtypes):
		arg = f"#{i+1}"
		TeX_send_input_commands += postprocess_send_code(argtype.send_code(arg), put_sync=i==len(argtypes)-1)
		TeX_argspec += arg
	if not argtypes:
		TeX_send_input_commands += "%naive_flush%"

	assert have_naive_replace(TeX_send_input_commands)

	return wrap_naive_replace(r"""
	\cs_new_protected:Npn """ + "\\"+name + TeX_argspec + r""" {
		\__send_content:e { i """ + identifier + """ }
		""" + TeX_send_input_commands + r"""
		\pythonimmediatelisten
	}
	""")


def define_internal_handler(f: FunctionType)->FunctionType:
	"""
	Define a TeX function with TeX name = ``f.__name__`` that calls f().

	This does not define the specified function in any particular engine, just add them to the :const:`bootstrap_code`.

	:meta private:
	"""
	bootstrap_code_functions.append(define_TeX_call_Python(f))
	return f


import linecache

# https://stackoverflow.com/questions/47183305/file-string-traceback-with-line-preview
def exec_or_eval_with_linecache(code: str, globals: dict, mode: str)->Any:
	sourcename: str="<usercode>"
	i=0
	while sourcename in linecache.cache:
		sourcename="<usercode" + str(i) + ">"
		i+=1

	lines=code.splitlines(keepends=True)
	linecache.cache[sourcename] = len(code), None, lines, sourcename

	compiled_code=compile(code, sourcename, mode)
	return (exec if mode=="exec" else eval)(compiled_code, globals)

	#del linecache.cache[sourcename]
	# we never delete the cache, in case some function is defined here then later are called...

def exec_with_linecache(code: str, globals: Dict[str, Any])->None:
	exec_or_eval_with_linecache(code, globals, "exec")

def eval_with_linecache(code: str, globals: Dict[str, Any])->Any:
	return exec_or_eval_with_linecache(code, globals, "eval")


class _NoFile: pass
_no_file=_NoFile()
file: Union[_NoFile, None, IO]=_no_file

class RedirectPrintTeX:
	"""
	A context manager. Use like this, where ``t`` is some file object::

		with RedirectPrintTeX(t):
			pass  # some code

	Then all :meth:`print_TeX` function calls will be redirected to ``t``.
	"""
	def __init__(self, t)->None:
		self.t=t

	def __enter__(self)->None:
		global file
		self.old=file
		file=self.t

	def __exit__(self, exc_type, exc_value, tb)->None:
		global file
		file=self.old

def run_code_redirect_print_TeX(f: Callable[[], Any])->None:
	"""
	Extension of :class:`RedirectPrintTeX`, where the resulting code while the code
	is executed will be interpreted as [TeX] code to be executed when the function returns.

	Also, any return value of function ``f`` will be appended to the result.

	:meta private:
	"""
	with io.StringIO() as t:
		with RedirectPrintTeX(t):
			result=f()
			if result is not None:
				t.write(str(result)+"%")
		content=t.getvalue()
		if content.endswith("\n"):
			content=content[:-1]
		elif not content:
			if engine.status!=EngineStatus.running:
				run_none_finish()
			return
		else:
			#content+=r"\empty"  # this works too
			content+="%"
		_run_block_finish(content)


"""
In some engine, when -8bit option is not enabled, the code will be escaped before being sent to Python.
So for example if the original code contains a literal tab character, ``^^I`` might be sent to Python instead.
This do a fuzzy-normalization over these so that the sourcecode can be correctly matched.
"""
potentially_escaped_characters=str.maketrans({
	chr(i): "^^" + chr(i^0x40)
	for i in [*range(0, 32), 127]
	})

def normalize_line(line: str)->str:
	assert line.endswith("\n")
	line=line[:-1]
	while line.endswith("^^I"): line=line[:-3]
	return line.rstrip(" \t").translate(potentially_escaped_characters)

def can_be_mangled_to(original: str, mangled: str)->bool:
	r"""
	Internal functions, used to implemented :func:`.pycode` environment.

	If *original* is put in a [TeX] file, read in other catcode regime (possibly drop trailing spaces/tabs),
	and then sent through ``\write`` (possibly convert control characters to ``^^``-notation),
	is it possible that the written content is equal to *mangled*?

	The function is somewhat tolerant (might return ``True`` in some cases where ``False`` should be returned), but not too tolerant.

	Example::

		>>> can_be_mangled_to("a\n", "a\n")
		True
		>>> can_be_mangled_to("\n", "\n")
		True
		>>> can_be_mangled_to("\t\n", "\n")
		True
		>>> can_be_mangled_to("\t\n", "\t\n")
		True
		>>> can_be_mangled_to("\t\n", "^^I\n")
		True
		>>> can_be_mangled_to("\ta\n", "^^Ia\n")
		True
		>>> can_be_mangled_to("a b\n", "a b\n")
		True
		>>> can_be_mangled_to("a b  \n", "a b\n")
		True
		>>> can_be_mangled_to("a\n", "b\n")
		False

	:meta private:
	"""
	return normalize_line(original)==normalize_line(mangled)



def _template_substitute(template: str, pattern: str, substitute: Union[str, Callable[[re.Match], str]], optional: bool=False)->str:
	if not optional:
		#assert template.count(pattern)==1
		assert len(re.findall(pattern, template))==1
	return re.sub(pattern, substitute, template)

#typing.TypeVarTuple(PyToTeXData)

#PythonCallTeXFunctionType=Callable[[PyToTeXData], Optional[Tuple[TeXToPyData, ...]]]

class PythonCallTeXFunctionType(Protocol):  # https://stackoverflow.com/questions/57658879/python-type-hint-for-callable-with-variable-number-of-str-same-type-arguments
	def __call__(self, *args: PyToTeXData)->Optional[Tuple[TeXToPyData, ...]]: ...

class PythonCallTeXSyncFunctionType(PythonCallTeXFunctionType, Protocol):  # https://stackoverflow.com/questions/57658879/python-type-hint-for-callable-with-variable-number-of-str-same-type-arguments
	def __call__(self, *args: PyToTeXData)->Tuple[TeXToPyData, ...]: ...


@dataclass(frozen=True)
class Python_call_TeX_data:
	TeX_code: str
	recursive: bool
	finish: bool
	sync: Optional[bool]

@dataclass(frozen=True)
class Python_call_TeX_extra:
	ptt_argtypes: Tuple[Type[PyToTeXData], ...]
	ttp_argtypes: Union[Type[TeXToPyData], Tuple[Type[TeXToPyData], ...]]

Python_call_TeX_defined: Dict[Python_call_TeX_data, Tuple[Python_call_TeX_extra, Callable]]={}

def Python_call_TeX_local(TeX_code: str, *, recursive: bool=True, sync: Optional[bool]=None, finish: bool=False)->Callable:
	"""
	Internal function. See :func:`scan_Python_call_TeX`.
	"""
	data=Python_call_TeX_data(
			TeX_code=TeX_code, recursive=recursive, sync=sync, finish=finish
			)
	return Python_call_TeX_defined[data][1]

def build_Python_call_TeX(T: Type, TeX_code: str, *, recursive: bool=True, sync: Optional[bool]=None, finish: bool=False)->None:
	"""
	Internal function. See :func:`scan_Python_call_TeX`.

	T has the form Callable[[T1, T2], Tuple[U1, U2]]
	where the Tx are subclasses of PyToTeXData and the Ux are subclasses of TeXToPyData

	The Tuple[...] can optionally be a single type, then it is almost equivalent to a tuple of one element
	It can also be None

	:meta private:
	"""

	assert T.__origin__ == typing.Callable[[], None].__origin__  # type: ignore
	# might be typing.Callable or collections.abc.Callable depends on Python version
	data=Python_call_TeX_data(
			TeX_code=TeX_code, recursive=recursive, sync=sync, finish=finish
			)

	# T.__args__ consist of the argument types int

	Tx=T.__args__[:-1]

	for Ti in Tx: assert issubclass(Ti, PyToTeXData), Ti

	result_type: Any = T.__args__[-1]  # Tuple[U1, U2]
	ttp_argtypes: Union[Type[TeXToPyData], Tuple[Type[TeXToPyData], ...]]
	if result_type is type(None):
		ttp_argtypes = ()
	elif isinstance(result_type, type) and issubclass(result_type, TeXToPyData):
		# special case, return a single object instead of a tuple of length 1
		ttp_argtypes = result_type
	else:
		ttp_argtypes = result_type.__args__  # type: ignore

	extra=Python_call_TeX_extra(
			ptt_argtypes=Tx,
			ttp_argtypes=ttp_argtypes
			)  # type: ignore
	if data in Python_call_TeX_defined:
		assert Python_call_TeX_defined[data][0]==extra, "different function with exact same code is not supported for now"
	else:
		if  isinstance(ttp_argtypes, type) and issubclass(ttp_argtypes, TeXToPyData):
			# special case, return a single object instead of a tuple of length 1
			code, result1=define_Python_call_TeX(TeX_code=TeX_code, ptt_argtypes=[*extra.ptt_argtypes], ttp_argtypes=[ttp_argtypes],
																  recursive=recursive, sync=sync, finish=finish,
																  )
			def result(*args):
				tmp=result1(*args)
				assert tmp is not None
				assert len(tmp)==1
				return tmp[0]
		else:

			for t in ttp_argtypes:
				assert issubclass(t, TeXToPyData)

			code, result=define_Python_call_TeX(TeX_code=TeX_code, ptt_argtypes=[*extra.ptt_argtypes], ttp_argtypes=[*ttp_argtypes],
																  recursive=recursive, sync=sync, finish=finish,
																  )
		bootstrap_code_functions.append(code)

		Python_call_TeX_defined[data]=extra, result

def scan_Python_call_TeX(sourcecode: str, filename: Optional[str]=None)->None:
	"""
	Internal function.

	Scan the file in filename for occurrences of ``typing.cast(T, Python_call_TeX_local(...))``,
	then call ``build_Python_call_TeX(T, ...)`` for each occurrence.

	The way the whole thing work is:

	- In the Python code, some ``typing.cast(T, Python_call_TeX_local(...))`` are used.
	- This function is called on all the library source codes to scan for those occurrences,
	  build necessary data structures for the :meth:`Python_call_TeX_local` function calls to work correctly.
	- When :meth:`Python_call_TeX_local` is actually called, it does some magic to return the correct function.

	Done this way, the type checking works correctly and it's not necessary to define global
	temporary variables.

	Don't use this function on untrusted code.

	:meta private:
	"""
	import ast
	from copy import deepcopy
	for node in ast.walk(ast.parse(sourcecode, mode="exec")):
		try:
			if isinstance(node, ast.Call):
				if (
						isinstance(node.func, ast.Attribute) and
						isinstance(node.func.value, ast.Name) and
						node.func.value.id == "typing" and
						node.func.attr == "cast"
						):
					T = node.args[0]
					if isinstance(node.args[1], ast.Call):
						f_call = node.args[1]
						if isinstance(f_call.func, ast.Name):
							if f_call.func.id == "Python_call_TeX_local":
								f_call=deepcopy(f_call)
								assert isinstance(f_call.func, ast.Name)
								f_call.func.id="build_Python_call_TeX"
								f_call.args=[T]+f_call.args
								eval(compile(ast.Expression(body=f_call), "<string>", "eval"))
		except:
			print(f"======== while scanning file for Python_call_TeX_local(...) -- error on line {node.lineno} of file {filename} ========", file=sys.stderr)
			raise

def scan_Python_call_TeX_module(name: str)->None:
	"""
	Internal function.
	Can be used as ``scan_Python_call_TeX_module(__name__)`` to scan the current module.

	:meta private:
	"""
	assert name != "__main__"  # https://github.com/python/cpython/issues/86291
	scan_Python_call_TeX(inspect.getsource(sys.modules[name]), name)


def define_Python_call_TeX(TeX_code: str, ptt_argtypes: List[Type[PyToTeXData]], ttp_argtypes: List[Type[TeXToPyData]],
						   *,
						   recursive: bool=True,
						   sync: Optional[bool]=None,
						   finish: bool=False,
						   )->Tuple[EngineDependentCode, PythonCallTeXFunctionType]:
	r"""
	Internal function.

	``TeX_code`` should be some expl3 code that defines a function with name ``%name%`` that when called should:

	* run some [TeX]-code (which includes reading the arguments, if any)
	* do the following if ``sync``:
	  * send ``r`` to Python (equivalently write %sync%)
	  * send whatever needed for the output (as in ``ttp_argtypes``)
	* call ``\pythonimmediatelisten`` iff not ``finish``.

	This is allowed to contain the following:
	
	* %name%: the name of the function to be defined as explained above.
	* %read_arg0(\var_name)%, %read_arg1(...)%: will be expanded to code that reads the input.
	* %send_arg0(...)%, %send_arg1(...)%: will be expanded to code that sends the content.
	* %send_arg0_var(\var_name)%, %send_arg1_var(...)%: will be expanded to code that sends the content in the variable.
	* %optional_sync%: expanded to code that writes ``r`` (to sync), if ``sync`` is True.
	* %naive_flush% and %naive_inline%: as explained in :func:`mark_bootstrap_naive_replace`.
	  (although usually you don't need to explicitly write this, it's embedded in the ``send*()`` command
	  of the last argument, or ``%sync%``)

	:param ptt_argtypes: list of argument types to be sent from Python to TeX (i.e. input of the TeX function)

	:param ttp_argtypes: list of argument types to be sent from TeX to Python (i.e. output of the TeX function)

	:param recursive: whether the TeX_code might call another Python function. Default to True.
		It does not hurt to always specify True, but performance would be a bit slower.

	:param sync: whether the Python function need to wait for the TeX function to finish.
		Required if ``ttp_argtypes`` is not empty.
		This should be left to be the default None most of the time. (which will make it always sync if ``debugging``,
		otherwise only sync if needed i.e. there's some output)

	:param finish: Include this if and only if ``\pythonimmediatelisten`` is omitted.
		Normally this is not needed, but it can be used as a slight optimization; and it's needed internally to implement
		``run_none_finish`` among others.
		For each TeX-call-Python layer, \emph{exactly one} ``finish`` call can be made. If the function itself doesn't call
		any ``finish`` call (which happens most of the time), then the wrapper will call ``run_none_finish``.

	:returns: some TeX code to be executed, and a Python function object that when called will call the TeX function
		on the passed-in TeX engine and return the result.

	Note that the TeX_code must eventually be executed on the corresponding engine for the program to work correctly.

	Possible optimizations:

	* the ``r`` is not needed if not recursive and ``ttp_argtypes`` is nonempty
	  (the output itself tells Python when the [TeX]-code finished)
	* the first line of the output may be on the same line as the ``r`` itself (done, use :class:`TTPEmbeddedLine` type, although a bit hacky)

	:meta private:
	"""
	if ttp_argtypes!=[]:
		assert sync!=False
		sync=True

	if sync is None:
		sync=debugging
		assert not ttp_argtypes
		TeX_code=_template_substitute(TeX_code, "%optional_sync%",
							   lambda _: r'\__send_content%naive_send%:e { r }' if sync else '',)

	if sync:
		sync_code=r'\__send_content%naive_send%:e { r }'
		if ttp_argtypes is not None:
			# then don't need to sync here, can sync when the last argument is sent
			sync_code=naive_replace(sync_code, False)
	else:
		sync_code=""

	TeX_code=_template_substitute(TeX_code, "%sync%", lambda _: sync_code, optional=True)

	assert sync is not None
	if ttp_argtypes: assert sync
	assert ttp_argtypes.count(TTPEmbeddedLine)<=1
	identifier=get_random_TeX_identifier()

	TeX_code=_template_substitute(TeX_code, "%name%", lambda _: r"\__run_" + identifier + ":")

	for i, argtype_ in enumerate(ptt_argtypes):
		TeX_code=_template_substitute(TeX_code, r"%read_arg" + str(i) + r"\(([^)]*)\)%",
							   lambda match: argtype_.read_code(match[1]),
							   optional=True)

	for i, argtype in enumerate(ttp_argtypes):


		TeX_code=_template_substitute(TeX_code, f"%send_arg{i}" + r"\(([^)]*)\)%",
							   lambda match: postprocess_send_code(argtype.send_code(match[1]), i==len(ttp_argtypes)-1),
							   optional=True)
		TeX_code=_template_substitute(TeX_code, f"%send_arg{i}_var" + r"\(([^)]*)\)%",
							   lambda match: postprocess_send_code(argtype.send_code_var(match[1]), i==len(ttp_argtypes)-1),
							   optional=True)

	def f(*args)->Optional[Tuple[TeXToPyData, ...]]:
		assert len(args)==len(ptt_argtypes), f"passed in {len(args)} = {args}, expect {len(ptt_argtypes)}"

		if engine.status==EngineStatus.error:
			raise TeXProcessError("error already happened")
		assert engine.status==EngineStatus.waiting, engine.status

		sending_content=(identifier+"\n").encode('u8')  # function header

		# function args. We build all the arguments before sending anything, just in case some serialize() error out
		for arg, argtype in zip(args, ptt_argtypes):
			assert isinstance(arg, argtype)
			sending_content+=arg.serialize()

		engine.write(sending_content)

		if sync:

			# wait for the result
			engine.status=EngineStatus.running
			if recursive:
				result_=run_main_loop()
			else:
				result_=run_main_loop_get_return_one()
			assert engine.status==EngineStatus.running, engine.status

			result: List[TeXToPyData]=[]
			if TTPEmbeddedLine not in ttp_argtypes:
				assert not result_
			for argtype_ in ttp_argtypes:
				if argtype_==TTPEmbeddedLine:
					result.append(TTPEmbeddedLine(result_))
				else:
					result.append(argtype_.read())

		if finish:
			engine.status=EngineStatus.running
		else:
			engine.status=EngineStatus.waiting

		if sync: return tuple(result)
		else: return None

	return wrap_naive_replace(TeX_code), f

scan_Python_call_TeX_module(__name__)

run_none_finish=typing.cast(Callable[[], None], Python_call_TeX_local(
r"""
\cs_new_eq:NN %name% \relax
""", finish=True, sync=False))

def _make_param_spec(x: int)->BalancedTokenList:
	r"""
	Internal function.

	>>> _make_param_spec(0)
	<BalancedTokenList: >
	>>> _make_param_spec(1)
	<BalancedTokenList: #₆ 1₁₂>
	>>> _make_param_spec(9)
	<BalancedTokenList: #₆ 1₁₂ #₆ 2₁₂ #₆ 3₁₂ #₆ 4₁₂ #₆ 5₁₂ #₆ 6₁₂ #₆ 7₁₂ #₆ 8₁₂ #₆ 9₁₂>
	>>> _make_param_spec(10)
	Traceback (most recent call last):
		...
	AssertionError
	"""
	assert 0<=x<=9
	return BalancedTokenList([t for i in range(1, x+1) for t in [C.param("#"), C.other(str(i))]])

def add_TeX_handler_param(t: BalancedTokenList, param: int|BalancedTokenList, *, continue_included: bool=False)->str:
	r"""
	Similar to :func:`add_TeX_handler`, however it will take parameters following in the input stream.

	>>> identifier=add_TeX_handler_param(BalancedTokenList(r"\def\l_tmpa_tl{#2,#1}"), 2)
	>>> BalancedTokenList(r'{123}{456}').put_next()
	>>> call_TeX_handler(identifier)
	>>> T.l_tmpa_tl.tl()
	<BalancedTokenList: 4₁₂ 5₁₂ 6₁₂ ,₁₂ 1₁₂ 2₁₂ 3₁₂>
	>>> remove_TeX_handler(identifier)
	"""
	if not continue_included: t=t+[T.pythonimmediatecontinuenoarg]
	identifier=get_random_TeX_identifier()
	if isinstance(param, int): param=_make_param_spec(param)
	BalancedTokenList([T.gdef, P["run_"+identifier+":"], *param, t]).execute()
	return identifier

def add_TeX_handler(t: BalancedTokenList, *, continue_included: bool=False)->str:
	r"""
	See :func:`call_TeX_handler`.

	:param continue_included: If this is set to True, ``\pythonimmediatecontinuenoarg`` token should be put when you want to return control to Python.

		>>> with group: identifier=add_TeX_handler(BalancedTokenList(
		...		r"\afterassignment\pythonimmediatecontinuenoarg \toks0="), continue_included=True)
		>>> BalancedTokenList([["abc"]]).put_next()
		>>> call_TeX_handler(identifier)  # this will assign \toks0 to be the following braced group
		>>> toks[0]
		<BalancedTokenList: a₁₁ b₁₁ c₁₁>
	"""
	if not continue_included: t=t+[T.pythonimmediatecontinuenoarg]
	identifier=get_random_TeX_identifier()
	P["run_"+identifier+":"].tl(t, global_=True)
	return identifier

def call_TeX_handler_returns(identifier: str)->str:
	if engine.status==EngineStatus.error:
		raise TeXProcessError("error already happened")
	assert engine.status==EngineStatus.waiting, engine.status

	engine.write((identifier+"\n").encode('u8'))
	engine.status=EngineStatus.running

	result=run_main_loop()
	assert result is not None
	engine.status=EngineStatus.waiting
	return result

def call_TeX_handler(identifier: str)->None:
	r"""
	Define some "handlers" in [TeX] that can be called quickly without re-sending the code every time it's called.

	Analog for :func:`add_handler`, :func:`remove_handler`, but on the [TeX] side.

	The advantage is that it's much faster than using :meth:`BalancedTokenList.execute` every time.
	Otherwise the effect is identical.

	Of course this is only for the current engine, and is global.

	>>> identifier=add_TeX_handler(BalancedTokenList(r"\advance\count0 by 1"))
	>>> count[0]=5
	>>> count[0]
	5
	>>> call_TeX_handler(identifier)
	>>> count[0]
	6
	>>> remove_TeX_handler(identifier)
	"""
	result=call_TeX_handler_returns(identifier)
	assert result==""

def remove_TeX_handler(identifier: str)->None:
	"""
	See :func:`call_TeX_handler`.
	"""
	P["run_"+identifier+":"].set_eq(T.relax, global_=True)

_execute_cache: Dict[Engine, Dict[tuple[Token, ...], str]]={}

def _execute_cached0(e: BalancedTokenList, *, continue_included: bool=False)->None:
	r"""
	Internal function, identical to :meth:`BalancedTokenList.execute` but cache the value of ``e``
	such that re-execution of the same token list will be faster.

	>>> count[0]=5
	>>> _execute_cached0(BalancedTokenList(r'\advance\count0 by 1'))
	>>> count[0]
	6
	>>> _execute_cached0(BalancedTokenList(r'\advance\count0 by 1'))
	>>> count[0]
	7
	"""
	assert e.is_balanced()
	l=_defaultget_with_cleanup(_execute_cache, dict)
	identifier=l.get(tuple(e))
	if identifier is None:
		identifier=l[tuple(e)]=add_TeX_handler(e, continue_included=continue_included)
	call_TeX_handler(identifier)

_execute_arg_cache: Dict[Engine, Dict[tuple[int, tuple[Token, ...]], str]]={}
def _execute_cached0_arg(e: BalancedTokenList, count: int)->None:
	assert e.is_balanced()
	l=_defaultget_with_cleanup(_execute_arg_cache, dict)
	identifier=l.get((count, tuple(e)))
	if identifier is None:
		identifier=l[(count, tuple(e))]=add_TeX_handler_param(e, count)
	call_TeX_handler(identifier)

_arg_tokens=[P.arga, P.argb, P.argc]
_arg1=_arg_tokens[0]

def _store_to_arg1(e: BalancedTokenList)->None:
	r"""
	Internal function for a few things...

	..
		>>> def test(t): _store_to_arg1(t); assert _arg1.tl()==t, (_arg1.tl(), t)
		>>> for i in range(700): test(BalancedTokenList.fstr(chr(i)))
		>>> with default_engine.set_engine(luatex_engine):
		...		for i in range(700): test(BalancedTokenList.fstr(chr(i)))
	"""
	if e.is_str():
		_arg1.str(e.str())
	else:
		_arg1.tl(e)

def _putnext_braced_arg1()->None:
	"""
	>>> _store_to_arg1(BalancedTokenList('ab'))
	>>> _putnext_braced_arg1()
	>>> Token.get_next(4)
	<TokenList: {₁ a₁₁ b₁₁ }₂>
	"""
	typing.cast(Callable[[], None], Python_call_TeX_local(
		r"""
		\cs_new_protected:Npn %name% {
			%optional_sync%
			\expandafter \pythonimmediatelisten \expandafter { \__arga }
		}
		""", recursive=False))()

def _copy_arg1_to(e: Token)->None:
	if e==P.argb:
		typing.cast(Callable[[], None], Python_call_TeX_local(
			r"\cs_new_protected:Npn %name% { \let \__argb \__arga %optional_sync% \pythonimmediatelisten }", recursive=False))
		return
	if e==P.argc:
		typing.cast(Callable[[], None], Python_call_TeX_local(
			r"\cs_new_protected:Npn %name% { \let \__argc \__arga %optional_sync% \pythonimmediatelisten }", recursive=False))
		return
	assert False
	e.set_eq(_arg1)

def _execute_cached(e: BalancedTokenList|str, *args: BalancedTokenList|str)->None:
	r"""
	Internal function, identical to :func:`_execute_cached0`, only *e* is cached, the rest are
	passed in every time and accessible as ``_arg_tokens[0]`` etc.

	>>> group.begin()
	>>> _execute_cached(r'\catcode \_pythonimmediate_arga', '15=7')
	>>> catcode[15].value
	7
	>>> group.end()
	"""
	assert len(args)<=len(_arg_tokens)
	for a, t in reversed([*zip(args, _arg_tokens)]):
		_store_to_arg1(BalancedTokenList.fstr(a) if isinstance(a, str) else a)
		if t!=_arg1: _copy_arg1_to(t)
	_execute_cached0(BalancedTokenList(e))

def _execute_cached_arg(e: BalancedTokenList|str, *args: BalancedTokenList|str)->None:
	assert len(args)<=9
	for a, t in reversed([*zip(args, _arg_tokens)]):
		_store_to_arg1(BalancedTokenList.fstr(a) if isinstance(a, str) else a)
		_putnext_braced_arg1()
	_execute_cached0_arg(BalancedTokenList(e), len(args))


run_error_finish=typing.cast(Callable[[PTTBlock, PTTBlock], None], Python_call_TeX_local(
r"""
\msg_new:nnn {pythonimmediate} {python-error} {Python~error:~#1.}
\cs_new_protected:Npn %name% {
	%read_arg0(\__data)%
	%read_arg1(\__summary)%
	\wlog{^^JPython~error~traceback:^^J\__data^^J}
    \msg_error:nnx {pythonimmediate} {python-error} {\__summary}
	\__close_write:
}
""", finish=True, sync=False))
"""
Internal function.

``run_error_finish`` is fatal to [TeX], so we only run it when it's fatal to Python.

We want to make sure the Python traceback is printed strictly before run_error_finish() is called,
so that the Python traceback is not interleaved with [TeX] error messages.

:meta private:
"""

# normally the close_write above is not necessary but sometimes error can be skipped through
# in which case we must make sure the pipe is not written to anymore
# https://github.com/user202729/pythonimmediate-tex/issues/1


def run_tokenized_line_peek(line: str, *, check_braces: bool=True, check_newline: bool=True, check_continue: bool=True)->str:
	check_line(line, braces=check_braces, newline=check_newline, continue_=(True if check_continue else None))
	return typing.cast(
			Callable[[PTTTeXLine], Tuple[TTPEmbeddedLine]],
			Python_call_TeX_local(
				r"""
				\cs_new_protected:Npn %name% {
					%read_arg0(\__data)%
					\__data
				}
				""")
			)(PTTTeXLine(line))[0]


def run_block_local(block: str)->None:
	typing.cast(Callable[[PTTBlock], None], Python_call_TeX_local(
		r"""
		\cs_new_protected:Npn %name% {
			%read_arg0(\__data)%
			\begingroup \newlinechar=10~ \expandafter \endgroup
			\scantokens \expandafter{\__data}
			% trick described in https://tex.stackexchange.com/q/640274 to scantokens the code with \newlinechar=10

			%optional_sync%
			\pythonimmediatelisten
		}
		"""))(PTTBlock.ignore_last_space(block))


def continue_until_passed_back_str()->str:
	r"""
	Usage:

	First put some tokens in the input stream that includes ``\pythonimmediatecontinue{...}``
	(or ``%sync% \pythonimmediatelisten``), then call ``continue_until_passed_back()``.

	The function will only return when the ``\pythonimmediatecontinue`` is called.
	"""
	return typing.cast(Callable[[], TTPEmbeddedLine], Python_call_TeX_local(
		r"""
		\cs_new_eq:NN %name% \relax
		"""))()

def continue_until_passed_back()->None:
	r"""
	Same as ``continue_until_passed_back_str()`` but nothing can be returned from [TeX] to Python.

	So, this resumes the execution of [TeX] code until ``\pythonimmediatecontinuenoarg`` is executed.

	See :mod:`pythonimmediate` for some usage examples.
	"""
	result=continue_until_passed_back_str()
	assert not result


def expand_once()->None:
	r"""
	Expand the following content in the input stream once.

	>>> BalancedTokenList(r'\iffalse 1 \else 2 \fi').put_next()  # now following tokens in the input stream is '\iffalse 1 \else 2 \fi'
	>>> expand_once()  # now following tokens in the input stream is '2 \fi'
	>>> Token.get_next()
	<Token: 2₁₂>
	>>> Token.get_next()
	<Token: \fi>
	>>> BalancedTokenList(r'\fi').execute()
	"""
	typing.cast(Callable[[], None], Python_call_TeX_local(
		r"""
		\cs_new_protected:Npn %name% { \expandafter \pythonimmediatecontinuenoarg }
		""", recursive=False, sync=True))()


def _get_charcode(x: str|int)->int:
	if isinstance(x, int): return x
	assert len(x)==1
	return ord(x)

"""
we need to put the docstring in the class instead of member
because although Sphinx supports docstring after member
https://stackoverflow.com/a/20230473
pytest doctest doesn't
https://github.com/pytest-dev/pytest/issues/6996

so we use :meta public: to force include docstring of private member in documentation
"""


class _GroupManager:
	"""
	Create a semi-simple group.

	Use as ``group.begin()`` and ``group.end()``, or as a context manager::

		>>> count[0]=5
		>>> with group:
		...     count[0]=6
		...     count[0]
		6
		>>> count[0]
		5

	:meta public:
	"""
	def begin(self):
		TokenList(r"\begingroup").execute()
	def __enter__(self)->None:
		self.begin()
	def end(self):
		TokenList(r"\endgroup").execute()
	def __exit__(self, _exc_type, _exc_value, _traceback)->None:
		self.end()

group=_GroupManager()
r"""
See :class:`_GroupManager`.
"""

class _CatcodeManager:
	"""
	Python interface to manage the category code. Example usage::

		>>> catcode[97]
		<Catcode.letter: 11>
		>>> catcode["a"] = C.letter

	:meta public:
	"""
	def __getitem__(self, x: str|int)->Catcode:
		return Catcode.lookup(
			BalancedTokenList([r"\the\catcode" + str(_get_charcode(x))]).expand_o().int()
			)

	def __setitem__(self, x: str|int, catcode: Catcode)->None:
		#BalancedTokenList([r"\catcode" + str(_get_charcode(x)) + "=" + str(catcode.value)]).execute(); return
		typing.cast(Callable[[PTTVerbatimLine], None], Python_call_TeX_local(
			r"""
			\cs_new_protected:Npn %name% {
				%read_arg0(\__data)%
				\catcode \__data \pythonimmediatecontinuenoarg
			}
			""" , sync=True))(PTTVerbatimLine(str(_get_charcode(x)) + "=" + str(catcode.value)))


catcode=_CatcodeManager()
r"""
See :class:`_CatcodeManager`.
"""


class MathClass(enum.Enum):
	ord = 0
	op = 1
	bin = 2
	rel = 3
	open = 4
	close = 5
	punct = 6
	variable_family = varfam = 7

	@staticmethod
	def lookup(x: int)->MathClass:
		return _mathclass_value_to_member[x]

_mathclass_value_to_member = {item.value: item for item in MathClass}

@dataclass(frozen=True)
class Umathcode:
	r"""
	Example of using *active*::

		>>> Umathcode.parse(0x1000000)
		Umathcode.active
		>>> Umathcode.active.family
		1

	:meta public:
	"""

	family: int
	cls: MathClass
	position: int

	active=typing.cast("Umathcode", None)  # class member

	@staticmethod
	def parse(x: int)->Umathcode:
		if x==0x1000000: return Umathcode.active
		assert -0x80000000 <= x <= 0x7fffffff
		position = x&((1<<21)-1)
		x>>=21
		cls = MathClass.lookup(x&((1<<3)-1))
		x>>=3
		assert -0x80 <= x <= 0x7f
		family = x&((1<<8)-1)
		return Umathcode(family, cls, position)

	@property
	def value(self)->int:
		return (self.family<<3|self.cls.value)<<21|self.position

	def __repr__(self)->str:
		if self==Umathcode.active: return "Umathcode.active"
		try:
			c = chr(self.position)
			return f'Umathcode(family={self.family}, cls={self.cls!r}, position={self.position} {c!r})'
		except ValueError:
			return f'Umathcode(family={self.family}, cls={self.cls!r}, position={self.position})'

Umathcode.active = Umathcode(family=1, cls=MathClass.ord, position=0)



class _UmathcodeManager:
	"""
	For example::

		>>> umathcode[0]
		Traceback (most recent call last):
			...
		RuntimeError: umathcode is not available for non-Unicode engines!
		>>> from pythonimmediate.engine import ChildProcessEngine
		>>> with default_engine.set_engine(luatex_engine): umathcode["A"]
		Umathcode(family=1, cls=<MathClass.variable_family: 7>, position=65 'A')

	:meta public:
	"""

	def _ensure_unicode(self)->None:
		if not engine.is_unicode: raise RuntimeError("umathcode is not available for non-Unicode engines!")

	def __getitem__(self, x: str|int)->Umathcode:
		self._ensure_unicode()
		return Umathcode.parse(
			BalancedTokenList([r"\the\Umathcodenum" + str(_get_charcode(x))]).expand_o().int()
			)

	def __setitem__(self, x: str|int, code: Umathcode)->None:
		self._ensure_unicode()
		BalancedTokenList([r"\Umathcodenum" + str(_get_charcode(x)) + "=" + str(code.value)]).execute(); return


umathcode=_UmathcodeManager()
r"""
Similar to :const:`~pythonimmediate.catcode`.

See :class:`_UmathcodeManager`.
"""


class _CountManager:
	r"""
	Manipulate count registers. Interface is similar to :const:`~pythonimmediate.catcode`.

	For example::

		>>> count[5]=6  # equivalent to `\count5=6`
		>>> count[5]
		6
		>>> count["endlinechar"]=10  # equivalent to `\endlinechar=10`
		>>> T.endlinechar.int()  # can also be accessed this way
		10
		>>> count["endlinechar"]=13

	As shown in the last example, accessing named count registers can also be done through :meth:`Token.int`.

	:meta public:
	"""
	def __getitem__(self, x: str|int)->int:
		if isinstance(x, int):
			return BalancedTokenList([r"\the\count" + str(_get_charcode(x))]).expand_o().int()
		else:
			assert isinstance(x, str)
			return T[x].int()

	def __setitem__(self, x: str|int, val: int)->None:
		if isinstance(x, int):
			BalancedTokenList([r"\count" + str(x) + "=" + str(val)]).execute()
		else:
			assert isinstance(x, str)
			T[x].int(val)


count=_CountManager()
"""
See :class:`_CountManager`.
"""


class _ToksManager:
	r"""
	Manipulate tok registers. Interface is similar to :const:`~pythonimmediate.catcode`.

	For example::

		>>> toks[0]=BalancedTokenList('abc')
		>>> toks[0]
		<BalancedTokenList: a₁₁ b₁₁ c₁₁>
	"""
	def __getitem__(self, x: int)->BalancedTokenList:
		return BalancedTokenList([r"\the\toks" + str(x)]).expand_o()

	def __setitem__(self, x: int, val: BalancedTokenList)->None:
		BalancedTokenList([r"\toks" + str(x), val]).execute()

toks=_ToksManager()
"""
See :class:`_ToksManager`.
"""

# ========

def wlog(s: str)->None:
	r"""
	Wrapper around LaTeX's ``\wlog``.
	"""
	_execute_cached(r'\wlog{\_pythonimmediate_arga}', s)

def typeout(s: str)->None:
	r"""
	Wrapper around LaTeX's ``\typeout``.
	"""
	_execute_cached(r'\typeout{\_pythonimmediate_arga}', s)

def _ensure_lua_engine()->None:
	assert default_engine.engine, "No current engine!"
	assert default_engine.name=="luatex", f"Current engine is {default_engine.name}, not LuaTeX!"

def _lua_exec_cached(s: str)->None:
	_ensure_lua_engine()
	_execute_cached(BalancedTokenList([r'\directlua', BalancedTokenList.fstr(s)]))

def lua_try_eval(s: str)->Optional[str]:
	r"""
	Evaluate some Lua code, if fail then execute it.
	Works like an interactive shell, first try to evaluate it as an expression, if fail execute it.

	If you use IPython shell/Jupyter notebook, it may be desired to add a magic command to execute Lua code.
	For example in IPython: Create a file ``.ipython/profile_default/startup/lua_magic.py``::

		# Support %l <code> and %%l <newline> <line(s) of code> to execute Lua code in the LuaTeX engine.
		from typing import Optional
		from pythonimmediate import lua_try_eval
		from IPython.core.magic import register_line_magic, register_cell_magic
		register_line_magic("l")(lambda line: lua_try_eval(line))
		@register_cell_magic("l")
		def _cell_magic(line: str, cell: str)->Optional[str]:
			assert not line.strip(), "first line after %%l must be empty!"
			return lua_try_eval(cell)


	>>> c=default_engine.set_engine(ChildProcessEngine("luatex"))
	>>> lua_try_eval("2+3")
	'5'
	>>> lua_try_eval("do local a=2; return a+4 end")
	'6'
	>>> lua_try_eval("do local a=2 end")
	>>> c.restore()
	"""
	_ensure_lua_engine()
	_store_to_arg1(BalancedTokenList.fstr(s))
	_execute_cached0(BalancedTokenList([r'\edef\_pythonimmediate_arga{\directlua',
		BalancedTokenList.fstr(r'''
		do
			local s=token.get_macro"_pythonimmediate_arga"
			local function try_call_print(f)
				local success, result=pcall(f)
				if success then
					if result==nil then
						tex.sprint(-2, "-")
					else
						tex.sprint(-2, "+"..tostring(result))
					end
				else
					tex.sprint(-2, "!"..tostring(result))
				end
			end
			local f, err=load("return "..s..";", "=stdin", "t")
			if f~=nil then
				try_call_print(f)
			else
				f, err=load(s)
				if f~=nil then
					try_call_print(f)
				else
					tex.sprint(-2, "!"..tostring(err))
				end
			end
		end
		'''.strip()), '}']))
	result=P.arga.str()
	assert result
	if result[0]=="+": return result[1:]
	if result[0]=="!": raise RuntimeError(result[1:])
	assert result=="-", result
	return None

def peek_next_meaning()->str:
	r"""
	Get the meaning of the following token, as a string, using the current ``\escapechar``.
	
	This is recommended over :func:`peek_next_token` as it will not tokenize an extra token.

	It's undefined behavior if there's a newline (``\newlinechar`` or ``^^J``, the latter is OS-specific)
	in the meaning string.

	>>> BalancedTokenList("2").put_next()
	>>> peek_next_meaning()
	'the character 2'
	>>> Token.get_next()
	<Token: 2₁₂>
	"""
	return typing.cast(Callable[[], TTPEmbeddedLine], Python_call_TeX_local(
			r"""
			\cs_new_protected:Npn \__peek_next_meaning_callback: {

				\edef \__tmp {\meaning \__tmp}  % just in case ``\__tmp`` is outer, ``\write`` will not be able to handle it
				\__send_content%naive_send%:e { r \__tmp }

				\pythonimmediatelisten
			}
			\cs_new_protected:Npn %name% {
				\futurelet \__tmp \__peek_next_meaning_callback:
			}
			""", recursive=False))()


meaning_str_to_catcode: Dict[str, Catcode]={
		"begin-group character ": Catcode.bgroup,
		"end-group character ": Catcode.egroup,
		"math shift character ": Catcode.math,
		"alignment tab character ": Catcode.alignment,
		"macro parameter character ": Catcode.parameter,
		"superscript character ": Catcode.superscript,
		"subscript character ": Catcode.subscript,
		"blank space ": Catcode.space,
		"the letter ": Catcode.letter,
		"the character ": Catcode.other,
		}

def parse_meaning_str(s: str)->Optional[Tuple[Catcode, str]]:
	if s and s[:-1] in meaning_str_to_catcode:
		return meaning_str_to_catcode[s[:-1]], s[-1]
	return None


from .simple import *
# also scan the source code and populate bootstrap_code

def get_bootstrap_code(engine: Engine)->str:
	"""
	Return the bootstrap code for an engine.

	This is before the call to :meth:`substitute_private`.
	
	:meta private:
	"""
	return "\n".join(
			f(engine)
			for f in bootstrap_code_functions)

from . import texcmds
