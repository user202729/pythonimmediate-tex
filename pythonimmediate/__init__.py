#!/bin/python3
r"""
The main module. Contains Pythonic wrappers for much of [TeX]'s API.

Refer to :mod:`~.simple` for the "simple" API -- which allows users to avoid the need to
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
	  - :meth:`NToken.meaning_eq`
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

Some debug functionalities are provided and can be specified on the command-line, refer to :mod:`~.pytotex` documentation.

"""

from __future__ import annotations
import sys
import os
import inspect
import threading
import contextlib
import io
import functools
from fractions import Fraction
from typing import Optional, Union, Callable, Any, Iterator, Protocol, Iterable, Sequence, Type, Tuple, List, Dict, IO, Set, Literal, Generator
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
from weakref import WeakKeyDictionary
import weakref
import itertools
import string
import numbers
import random
import linecache

from .engine import Engine, default_engine, default_engine as engine, ParentProcessEngine, EngineStatus, TeXProcessError, TeXProcessExited, ChildProcessEngine
from .lowlevel import debugging, is_sphinx_build, _handlers, _per_engine_handlers, run_none_finish, PTTInt, PTTBalancedTokenList, PTTBlock, mark_bootstrap, _run_block_finish, get_random_Python_identifier, run_main_loop, TTPRawLine, TeXToPyData, expansion_only_can_call_Python, _format, _readline, get_random_TeX_identifier, scan_Python_call_TeX_module, Python_call_TeX_local, PTTVerbatimLine, TTPEmbeddedLine

T1 = typing.TypeVar("T1")

DimensionUnit = Literal["pt", "in", "pc", "cm", "mm", "bp", "dd", "cc", "sp"]
"""
[TeX] dimension units. ``ex`` and ``em`` are font-dependent, so excluded.
"""

unit_per_pt: Dict[DimensionUnit, Fraction]={
		"pt": Fraction(1, 1),
		"in": Fraction(7227, 100),
		"pc": Fraction(12, 1),
		"cm": Fraction(7227, 254),
		"mm": Fraction(7227, 2540),
		"bp": Fraction(7227, 7200),
		"dd": Fraction(1238, 1157),
		"cc": Fraction(14856, 1157),
		"sp": Fraction(1, 65536),
		}
assert {*unit_per_pt.keys()}=={*DimensionUnit.__args__}  # type: ignore

@typing.overload
def convert_unit(val: Fraction, from_: DimensionUnit, *, to: DimensionUnit)->Fraction: ...
@typing.overload
def convert_unit(val: float, from_: DimensionUnit, *, to: DimensionUnit)->float: ...

def convert_unit(val: Fraction|float, from_: DimensionUnit, *, to: DimensionUnit)->Fraction|float:
	"""
	Convert between units.

	>>> convert_unit(1, "in", to="cm")
	Fraction(127, 50)
	>>> convert_unit(1., "in", to="cm")
	2.54

	Note that in ``inkex``, then the argument order is reversed,
	i.e. ``convert_unit(1, "cm", "in")`` returns ``2.54``.
	That's why ``to`` is made into a keyword argument.
	"""
	if isinstance(val, float):
		return float(convert_unit(Fraction(val), from_, to=to))
	for unit in from_, to:
		if unit not in unit_per_pt:
			raise ValueError(f'Unknown unit "{unit}"')
	return val*unit_per_pt[from_]/unit_per_pt[to]


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

	The handlers must take a single argument of type :class:`~engine.Engine` as input, and returns nothing.

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

_user_scope: WeakKeyDictionary[Engine, Dict[str, Any]]=WeakKeyDictionary()

def _defaultget_with_cleanup(d: WeakKeyDictionary[Engine, T1], default: Callable[[], T1])->T1:
	e=default_engine.get_engine()
	if e not in d:
		d[e]=default()
		def cleanup(e: Engine)->None:
			try: del d[e]
			except KeyError: pass
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
		>>> assert n==len(_user_scope), (n, len(_user_scope))
	"""
	return _defaultget_with_cleanup(_user_scope, dict)

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
		if self.degree()==0 and isinstance(self, Token):
			result=BalancedTokenList([T.meaning, self]).expand_o().str()
		else:
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
	def put_next(self)->None:
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
			See :meth:`TokenList.str_codes`.
		"""
		# default implementation, might not be correct. Subclass overrides as needed.
		raise ValueError("Token does not represent a string!")

	def degree(self)->int:
		"""
		return the imbalance degree for this token (``{`` -> 1, ``}`` -> -1, everything else -> 0)
		"""
		# default implementation, might not be correct. Subclass overrides as needed.
		return 0

@mark_bootstrap
def _helper_put_next_brace(engine: Engine)->str:
	if engine.name=="luatex":  # TODO https://github.com/latex3/latex3/issues/1540
		return r"""
			\cs_new_protected:Npn \__put_next_unbalanced:n #1 {
				\expandafter \expandafter \expandafter \expandafter \expandafter \expandafter \expandafter \pythonimmediatecontinuenoarg
					\expandafter \expandafter \expandafter \expandafter \char_generate:nn {\__index} {#1} \empty
			}
			"""
	else:
		return r"""
			\cs_new_protected:Npn \__put_next_unbalanced:n #1 {
				\expandafter \expandafter \expandafter \pythonimmediatecontinuenoarg
					\char_generate:nn {\__index} {#1}
			}
			"""

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

	def is_defined(self)->bool:
		"""
		Return whether this token is defined.

		>>> T.relax.is_defined()
		True
		>>> T.undefined.is_defined()
		False
		>>> C.active("~").is_defined()
		True
		>>> C.other("a").is_defined()
		True
		"""
		# use \ifdefined
		return TokenList([T.ifdefined, self, C.other("1"), T.fi]).expand_x().str() == "1"

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
						\__put_next_unbalanced:n 1
					}
					""", recursive=False, sync=True))(PTTInt(self.index))
			else:
				assert d==-1
				typing.cast(Callable[[PTTInt], None], Python_call_TeX_local(
					r"""
					\cs_new_protected:Npn %name% {
						%read_arg0(\__index)%
						\__put_next_unbalanced:n 2
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

	def estr(self)->str:
		r"""
		Expand this token according to :ref:`estr-expansion`.

		It's undefined behavior if the expansion result is unbalanced.

		>>> T.l_tmpa_tl.tl(BalancedTokenList(r'ab\l_tmpb_tl'))
		<BalancedTokenList: a₁₁ b₁₁ \l_tmpb_tl>
		>>> T.l_tmpb_tl.tl(BalancedTokenList(r'cd123+$'))
		<BalancedTokenList: c₁₁ d₁₁ 1₁₂ 2₁₂ 3₁₂ +₁₂ $₃>
		>>> T.l_tmpa_tl.estr()
		'abcd123+$'

		..seealso::
			:meth:`BalancedTokenList.expand_estr`
		"""
		BalancedTokenList([self]).put_next()
		return get_arg_estr()

	@typing.overload
	def dim(self, unit: DimensionUnit, val: int)->int: ...
	@typing.overload
	def dim(self, unit: DimensionUnit, val: float)->float: ...
	@typing.overload
	def dim(self, unit: DimensionUnit, val: Fraction)->Fraction: ...
	@typing.overload
	def dim(self, unit: DimensionUnit)->Fraction: ...
	@typing.overload
	def dim(self, unit: str)->Any: ...
	@typing.overload
	def dim(self, val: float|Fraction, unit: DimensionUnit)->Fraction: ...
	@typing.overload
	def dim(self)->str: ...

	def dim(self, *args: Any, **kwargs: Any)->Any:
		r"""
		Manipulate an expl3 dimension variable.

		>>> T.l_tmpa_dim.dim("100.5pt")
		>>> T.l_tmpa_dim.dim()
		'100.5pt'
		>>> T.l_tmpa_dim.dim(100.5, "pt")
		100.5
		>>> T.l_tmpa_dim.dim("pt")
		Fraction(201, 2)
		>>> T.l_tmpa_dim.dim("1em")
		>>> T.l_tmpa_dim.dim(1, "em")
		1
		>>> T.l_tmpa_dim.dim("em")
		Traceback (most recent call last):
			...
		ValueError: Unknown unit "em"
		>>> T.l_tmpa_dim.dim(100.5)
		Traceback (most recent call last):
			...
		ValueError: Explicit unit is required (e.g. "cm")
		>>> T.l_tmpa_dim.dim("6586368sp")
		>>> T.l_tmpa_dim.dim("sp")
		Fraction(6586368, 1)
		"""
		assert {*kwargs.keys()}<={"val", "unit"}
		val, unit=[*args, *kwargs.values(), None, None][:2]
		if val is None and unit is None:
			return BalancedTokenList([T.the, self]).expand_estr()  # dim() -> "100.5pt"
		if unit is None and val is not None:
			val, unit=unit, val
		if val is None and unit is not None:
			if isinstance(unit, numbers.Number):
				raise ValueError('Explicit unit is required (e.g. "cm")')
			assert isinstance(unit, str), unit
			if {*string.digits}&{*unit}:
				# dim("1pt") -> None
				(BalancedTokenList([self])+BalancedTokenList.fstr(f"={unit}")).execute()
				return None
			else:
				# dim("pt") -> 201/2
				result_sp=BalancedTokenList([T.number, self]).expand_o().int()
				return convert_unit(result_sp, "sp", to=typing.cast(DimensionUnit, unit))
		# dim(1.3, "pt") -> 1.3
		assert unit is not None
		assert val is not None
		if isinstance(val, str): val, unit=unit, val
		(BalancedTokenList([self])+BalancedTokenList.fstr(f"={float(val):.6f}{unit}")).execute()
		# let TeX do the conversion (this will allow em and ex etc.)
		return val

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
% normally LaTeX3 token list cannot hold outer tokens, so we use \xdef.
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
		\xdef \__gtmp {\expandafter \__tldeserialize_start \__gtmp}
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
@mark_bootstrap
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

+

r"""


% serialize token list in #2 store to #1. Call T or F branch depends on whether serialize is successful.
% #1 must be different from \__tmp.
\cs_new_protected:Npn \__nodot:NnTF #1 #2 {
	\tl_if_eq:onTF {\detokenize{#2}} {#2} \__nodot_string:NnTF \__nodot_general:NnTF
		#1 {#2}
}
\cs_generate_variant:Nn \tl_if_eq:nnTF {o}

% same as above but #1 is guaranteed to be string
\precattl_exec:n{
\cs_new_protected:Npn \__nodot_string:NnTF #1 #2 #3 #4 {
	%\tl_set:Nx #1 { \cC{_ _kernel_str_to_other_fast:n}{#2} }
	%\tl_set:Nx #1 { \cO\s  \tl_map_function:NN #1 \__process_string }
	\tl_set:Nx #1 { \cO\s  \str_map_function:nN {#2} \__process_string }
	#3
}
}
% <string> serialize to 's<the string itself>' with weird characters become \xa0 + (weird character + 64)
% note that TeX-side deserialization does not handle this but it's not needed

% refer to __if_weird_charcode for detail
\cs_new:Npn  \__if_weird_charcode_or_esc:n #1 {
	\ifnum #1 < 32 ~ 1 \fi
	\ifnum #1 > 126 ~ \ifnum #1 < 161 ~ 1 \fi \fi
	0
}

\precattl_exec:n{
\cs_new:Npn \__process_string #1 {  % similar to \__content_escaper
	\ifnum 0<\__if_weird_charcode_or_esc:n {`#1} ~
		\cO\^^a0 \char_generate:nn {`#1+64} {12}
	\else
		#1
	\fi
}
}



"""

).replace("__", "__tlserialize_")

mark_bootstrap(
r"""

% same as above but #1 is guaranteed to be not-string
\cs_new_protected:Npn \__tlserialize_nodot_general:NnTF #1 #2 {
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
		assert all(ord(c) <= 0x7f for c in prefix), "Prefix containing non-ASCII characters is not supported because of complexities with is_unicode (see documentation of ControlSequenceToken)"
		self.prefix=prefix
	if enable_get_attribute:
		def __getattribute__(self, a: str)->"ControlSequenceToken":
			return ControlSequenceToken(object.__getattribute__(self, "prefix")+a)
	else:
		def __getattr__(self, a: str)->"ControlSequenceToken":
			return ControlSequenceToken(object.__getattribute__(self, "prefix")+a)
	def __getitem__(self, a: str|bytes)->"ControlSequenceToken":
		if isinstance(a, bytes):
			return ControlSequenceToken(object.__getattribute__(self, "prefix").encode('u8')+a)
		return ControlSequenceToken(object.__getattribute__(self, "prefix")+a)


class ControlSequenceToken(Token):
	r"""
	Represents a control sequence::

		>>> ControlSequenceToken("abc")
		<Token: \abc>
		>>> ControlSequenceToken([97, 98, 99])
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

	Generally, the default way to construct the control sequence will give you what you want.

		>>> with ChildProcessEngine("pdftex") as engine, default_engine.set_engine(engine):
		... 	print(T["u8:×"].meaning_str())
		... 	print(T["u8:×".encode('u8')].meaning_str())
		macro:->\IeC {\texttimes }
		macro:->\IeC {\texttimes }
		>>> with ChildProcessEngine("luatex") as engine, default_engine.set_engine(engine):
		... 	print(C.active("\xAD").meaning_str())  # discretionary hyphen
		... 	BalancedTokenList([r"\expandafter\def\csname\string", C.active("\xAD"), r"\endcsname{123}"]).execute()
		... 	print(T["\xAD"].meaning_str())  # just a convoluted test since no control sequence with non-ASCII name is defined by default in LuaTeX (that I know of)
		macro:->\-
		macro:->123

	*is_unicode* will be fetched from :const:`~engine.default_engine`
	if not explicitly specified.
	"""
	_codes: Tuple[int, ...]  # this is the only thing that is guaranteed to be defined.
	_csname: Optional[str]  # defined if csname is representable as a str. The same control sequence may be represented differently depends on is_unicode.
	_csname_bytes: Optional[bytes]  # defined if csname is representable as a bytes.

	def __init__(self, csname: Union[str, bytes, list[int], tuple[int, ...]], is_unicode: Optional[bool]=None)->None:
		if is_unicode is None and default_engine.engine is not None:
			is_unicode = default_engine.is_unicode

		if isinstance(csname, (list, tuple)):
			self._codes = tuple(csname)
			self._csname = "".join(chr(c) for c in csname)
			return

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
		if not self._codes: return r"\csname\endcsname"
		if self._csname is not None:
			return "\\"+self._csname
		return "\\"+repr(self._csname_bytes)

	def serialize(self)->str:
		return (
				"*"*sum(1 for x in self._codes if x<33) +
				"\\" +
				"".join(' '+chr(x+64) if x<33 else chr(x)   for x in self._codes)
				+ " ")

	def repr1(self)->str:
		if self._csname is not None:
			return f"\\" + repr(self._csname.replace(' ', "␣"))[1:-1]
		return f"\\" + repr(self._csname_bytes).replace(' ', "␣")

	def simple_detokenize(self, get_catcode: Callable[[int], Catcode])->str:
		if not self.csname:
			raise NotImplementedError("\\<null control sequence> isn't simple!")
		if len(self.csname)>1 or get_catcode(ord(self.csname))==Catcode.letter:
			for ch in self.csname:
				if get_catcode(ord(ch))!=Catcode.letter:
					raise NotImplementedError(f"\\{self.csname} isn't simple!")
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

	Another shorthand is available to check if a token has a particular catcode.
	Note that it is not safe to access :attr:`CharacterToken.catcode` directly, as it is
	not available for all tokens.

		>>> C.letter("a") in C.letter
		True
		>>> C.letter("a") in C.space
		False
		>>> T.a in C.letter
		False
		>>> C.letter("a").catcode==C.letter
		True
		>>> T.a.catcode==C.letter
		Traceback (most recent call last):
			...
		AttributeError: 'ControlSequenceToken' object has no attribute 'catcode'

	The behavior with blue tokens might be unexpected, be careful::

		>>> C.active("a").blue in C.active
		True
		>>> T.a.blue in C.letter
		False
		>>> T.a.blue in C.active
		False

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

	def __call__(self, ch: Union[str, bytes, int])->"CharacterToken":
		if isinstance(ch, str): ch=ord(ch)
		elif isinstance(ch, bytes):
			if len(ch)!=1: raise ValueError("bytes must have length 1, received "+repr(ch))
			ch=ch[0]
		return CharacterToken(ch, self)

	def __contains__(self, t: NToken)->bool:
		t=t.no_blue
		return isinstance(t, CharacterToken) and t.catcode==self

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

	Note that it is recommended to use the shorthand documented in :class:`Catcode` to
	check the catcode of a token instead:

	>>> C.letter("a") in C.letter
	True
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
else:  # Python 3.8 compatibility
	TokenListBaseClass = collections.UserList

def TokenList_e3(s: str)->TokenList: return TokenList.e3(s)

class UnbalancedTokenListError(ValueError):
	"""
	Exception raised when a token list is unbalanced.
	"""

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

	The constructor of this class accepts parameters in various different forms to allow convenient
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

		:raises UnbalancedTokenListError: if this is not balanced.
		"""
		if not self.is_balanced():
			raise UnbalancedTokenListError(f"Token list {self} is not balanced")

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
				yield cat(ch)  # type: ignore
				# temporary, see https://github.com/python/mypy/issues/17222
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

		Convert a string to a :class:`TokenList` (or some subclass of it such as :class:`BalancedTokenList`) approximately.

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
			pythonimmediate.UnbalancedTokenListError: Token list <BalancedTokenList: }₂> is not balanced
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
		"""
		Internal function?
		"""
		result: List[Token]=[]
		i=0

		# hack
		data_was_bytes=isinstance(data, bytes)
		if isinstance(data, bytes):
			data="".join(chr(i) for i in data)

		if not data: return cls()
		if data[0]=="s":
			return cls([
				CharacterToken(ord(ch), Catcode.space if ch==' ' else Catcode.other)
				for ch in re.sub("\xA0(.)", lambda match: chr(ord(match[1])-0x40), data[1:])
				])

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
				result.append(ControlSequenceToken(
					bytes(map(ord, csname)) if data_was_bytes else csname,
					is_unicode=not data_was_bytes))

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

	def str_if_unicode(self, unicode: bool=True)->str:
		"""
		Assume this token list represents a string in a (Unicode/non-Unicode) engine, return the string content.

		If the engine is not Unicode, assume the string is encoded in UTF-8.
		"""
		if unicode:
			return "".join(map(chr, self.str_codes()))
		else:
			return bytes(self.str_codes()).decode('u8')

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

	def int(self)->int:
		r"""
		Assume this token list contains an integer (as valid result of ``\number ...``),
		returns the integer value.

		At the moment, not much error checking is done.
		"""
		return int(self.str_if_unicode())


class ImmutableBalancedTokenList(collections.abc.Sequence, collections.abc.Hashable):
	r"""
	Represents an immutable balanced token list.

	Note that this class is not a subclass of :class:`TokenList`, and is not mutable.

	Not many operations are supported. Convert to :class:`BalancedTokenList` to perform more operations.

	Its main use is to be used as a key in a dictionary.

	>>> a=ImmutableBalancedTokenList(BalancedTokenList.e3(r'\def\a{b}'))
	>>> b=ImmutableBalancedTokenList(BalancedTokenList.e3(r'\def\a{b}'))
	>>> c=ImmutableBalancedTokenList(BalancedTokenList.e3(r'\def\a{c}'))
	>>> hash(a)==hash(b)
	True
	>>> a==b
	True
	>>> a!=b
	False
	>>> a==c
	False
	>>> a!=c
	True
	"""
	def __init__(self, a: BalancedTokenList)->None:
		self._data: Tuple[Token, ...]=tuple(a)

	@typing.overload
	def __getitem__(self, i: int)->Token: ...
	@typing.overload
	def __getitem__(self, i: slice)->ImmutableBalancedTokenList: ...

	def __getitem__(self, i: int|slice)->Token|ImmutableBalancedTokenList:
		if isinstance(i, slice): return ImmutableBalancedTokenList(BalancedTokenList(self._data[i]))
		return self._data[i]

	def __len__(self)->int:
		return len(self._data)

	def __repr__(self)->str:
		return TokenList.__repr__(self)  # type: ignore

	def __str__(self)->str:
		return repr(self)

	def __hash__(self)->int:
		return hash(self._data)

	def __eq__(self, other: object)->bool:
		if not isinstance(other, ImmutableBalancedTokenList): return NotImplemented
		return self._data==other._data


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

		:raises UnbalancedTokenListError: if the token list is not balanced.

		>>> BalancedTokenList("{")
		Traceback (most recent call last):
			...
		pythonimmediate.UnbalancedTokenListError: Token list <BalancedTokenList: {₁> is not balanced
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

	def strip_optional_braces(self)->"BalancedTokenList":
		"""
		Strip the optional braces from the given token list, if the whole token list is wrapped in braces.

		For example::

			>>> BalancedTokenList("{a}").strip_optional_braces()
			<BalancedTokenList: a₁₁>
			>>> BalancedTokenList("a").strip_optional_braces()
			<BalancedTokenList: a₁₁>
			>>> BalancedTokenList("{a},{b}").strip_optional_braces()
			<BalancedTokenList: {₁ a₁₁ }₂ ,₁₂ {₁ b₁₁ }₂>
			>>> BalancedTokenList([C.begin_group("X"), C.other("a"), C.end_group("Y")]).strip_optional_braces()
			<BalancedTokenList: a₁₂>

		Note that :class:`BalancedTokenList` is mutable. A copy is returned in any case::

			>>> x=BalancedTokenList("a")
			>>> y=x.strip_optional_braces()
			>>> x is y
			False
			>>> x.append(C.letter("b"))
			>>> x
			<BalancedTokenList: a₁₁ b₁₁>
			>>> y
			<BalancedTokenList: a₁₁>
		"""
		if self and self[0] in C.begin_group and self[-1] in C.end_group and TokenList(self)[1:-1].is_balanced():
			return self[1:-1]
		return self[:]

	def split_balanced(self, /, sep: "BalancedTokenList", maxsplit: int=-1, do_strip_braces_in_result: bool=True)->List["BalancedTokenList"]:
		r"""
		Split the given token list at the given delimiter, but only if the parts are balanced.

		:param sep: the delimiter.
		:param maxsplit: the maximum number of splits.
		:param do_strip_braces_in_result: if ``True``, each element of the result will have the braces stripped, if any.

			It is recommended to set this to ``True`` (the default),
			otherwise the user will not have any way to "quote" the separator in each entry.
		:raises ValueError: if ``self`` or ``sep`` is not balanced.

		For example::

			>>> BalancedTokenList("a{b,c},c{d}").split_balanced(BalancedTokenList(","))
			[<BalancedTokenList: a₁₁ {₁ b₁₁ ,₁₂ c₁₁ }₂>, <BalancedTokenList: c₁₁ {₁ d₁₁ }₂>]
			>>> BalancedTokenList("a{b,c},{d,d},e").split_balanced(BalancedTokenList(","), do_strip_braces_in_result=False)
			[<BalancedTokenList: a₁₁ {₁ b₁₁ ,₁₂ c₁₁ }₂>, <BalancedTokenList: {₁ d₁₁ ,₁₂ d₁₁ }₂>, <BalancedTokenList: e₁₁>]
			>>> BalancedTokenList("a{b,c},{d,d},e").split_balanced(BalancedTokenList(","))
			[<BalancedTokenList: a₁₁ {₁ b₁₁ ,₁₂ c₁₁ }₂>, <BalancedTokenList: d₁₁ ,₁₂ d₁₁>, <BalancedTokenList: e₁₁>]
			>>> BalancedTokenList.doc(" a = b = c ").split_balanced(BalancedTokenList("="), maxsplit=1)
			[<BalancedTokenList:  ₁₀ a₁₁  ₁₀>, <BalancedTokenList:  ₁₀ b₁₁  ₁₀ =₁₂  ₁₀ c₁₁  ₁₀>]
			>>> BalancedTokenList(r"\{,\}").split_balanced(BalancedTokenList(","))
			[<BalancedTokenList: \{>, <BalancedTokenList: \}>]
		"""
		assert maxsplit>=-1, "maxsplit should be either -1 (unbounded) or the maximum number of splits"
		assert self.is_balanced(), "Content is not balanced!"
		assert sep.is_balanced(), "Separator is not balanced!"
		if not sep:
			raise ValueError("Empty separator")
		result: List[BalancedTokenList]=[]
		result_degree=0
		remaining=TokenList()
		i=0
		self_=TokenList(self)
		while i<len(self):
			if len(result)!=maxsplit and i+len(sep)<=len(self) and self_[i:i+len(sep)]==sep and result_degree==0:
				result.append(BalancedTokenList(remaining))
				remaining=TokenList()
				i+=len(sep)
			else:
				remaining.append(self[i])
				result_degree+=self[i].degree()
				assert result_degree>=0, "This cannot happen, the input is balanced"
				i+=1
		result.append(BalancedTokenList(remaining))
		if do_strip_braces_in_result:
			return [x.strip_optional_braces() for x in result]
		return result

	def strip_spaces(self)->"BalancedTokenList":
		r"""
		Strip spaces from the beginning and end of the token list.

		For example::

			>>> BalancedTokenList.doc(" a ").strip_spaces()
			<BalancedTokenList: a₁₁>
			>>> BalancedTokenList([C.space(' '), C.space(' '), " a b "], BalancedTokenList.doc).strip_spaces()
			<BalancedTokenList: a₁₁  ₁₀ b₁₁>
			>>> BalancedTokenList().strip_spaces()
			<BalancedTokenList: >

		Note that only spaces with charcode 32 are stripped::

			>>> BalancedTokenList([C.space('X'), C.space(' '), "a", C.space(' ')]).strip_spaces()
			<BalancedTokenList: X₁₀  ₁₀ a₁₁>

		Similar to :meth:`strip_optional_braces`, a copy is returned in any case::

			>>> x=BalancedTokenList("a")
			>>> y=x.strip_spaces()
			>>> x is y
			False
		"""
		i=0
		while i<len(self) and self[i]==C.space(' '):
			i+=1
		j=len(self)
		while j>i and self[j-1]==C.space(' '):
			j-=1
		return self[i:j]

	def parse_keyval_items(self)->list[tuple[BalancedTokenList, Optional[BalancedTokenList]]]:
		r"""
		Parse a key-value token list into a list of pairs.

		>>> BalancedTokenList("a=b,c=d").parse_keyval_items()
		[(<BalancedTokenList: a₁₁>, <BalancedTokenList: b₁₁>), (<BalancedTokenList: c₁₁>, <BalancedTokenList: d₁₁>)]
		>>> BalancedTokenList("a,c=d").parse_keyval_items()
		[(<BalancedTokenList: a₁₁>, None), (<BalancedTokenList: c₁₁>, <BalancedTokenList: d₁₁>)]
		>>> BalancedTokenList.doc("a = b , c = d").parse_keyval_items()
		[(<BalancedTokenList: a₁₁>, <BalancedTokenList: b₁₁>), (<BalancedTokenList: c₁₁>, <BalancedTokenList: d₁₁>)]
		>>> BalancedTokenList.doc("a ={ b,c }, c = { d}").parse_keyval_items()
		[(<BalancedTokenList: a₁₁>, <BalancedTokenList:  ₁₀ b₁₁ ,₁₂ c₁₁  ₁₀>), (<BalancedTokenList: c₁₁>, <BalancedTokenList:  ₁₀ d₁₁>)]
		>>> BalancedTokenList.doc("{a=b},c=d").parse_keyval_items()
		[(<BalancedTokenList: {₁ a₁₁ =₁₂ b₁₁ }₂>, None), (<BalancedTokenList: c₁₁>, <BalancedTokenList: d₁₁>)]
		"""
		parts=self.split_balanced(BalancedTokenList(","), do_strip_braces_in_result=False)
		result: list[tuple[BalancedTokenList, Optional[BalancedTokenList]]]=[]
		for part in parts:
			kv=part.split_balanced(BalancedTokenList("="), maxsplit=1, do_strip_braces_in_result=False)
			if len(kv)==1:
				result.append((kv[0].strip_spaces(), None))
			else:
				assert len(kv)==2
				result.append((kv[0].strip_spaces(), kv[1].strip_spaces().strip_optional_braces()))
		return result

	def parse_keyval(self, allow_duplicate: bool=False)->dict[ImmutableBalancedTokenList, Optional[BalancedTokenList]]:
		r"""
		Parse a key-value token list into a dictionary.

		>>> BalancedTokenList("a=b,c=d").parse_keyval()
		{<ImmutableBalancedTokenList: a₁₁>: <BalancedTokenList: b₁₁>, <ImmutableBalancedTokenList: c₁₁>: <BalancedTokenList: d₁₁>}
		>>> BalancedTokenList("a,c=d").parse_keyval()
		{<ImmutableBalancedTokenList: a₁₁>: None, <ImmutableBalancedTokenList: c₁₁>: <BalancedTokenList: d₁₁>}
		>>> BalancedTokenList.doc("a = b , c = d").parse_keyval()
		{<ImmutableBalancedTokenList: a₁₁>: <BalancedTokenList: b₁₁>, <ImmutableBalancedTokenList: c₁₁>: <BalancedTokenList: d₁₁>}
		>>> BalancedTokenList.doc("a ={ b,c }, c = { d}").parse_keyval()
		{<ImmutableBalancedTokenList: a₁₁>: <BalancedTokenList:  ₁₀ b₁₁ ,₁₂ c₁₁  ₁₀>, <ImmutableBalancedTokenList: c₁₁>: <BalancedTokenList:  ₁₀ d₁₁>}
		>>> BalancedTokenList("a=b,a=c").parse_keyval()
		Traceback (most recent call last):
			...
		ValueError: Duplicate key: <ImmutableBalancedTokenList: a₁₁>
		>>> BalancedTokenList("a=b,a=c").parse_keyval(allow_duplicate=True)
		{<ImmutableBalancedTokenList: a₁₁>: <BalancedTokenList: c₁₁>}
		"""
		items=[(ImmutableBalancedTokenList(k), v) for k, v in self.parse_keyval_items()]
		if allow_duplicate: return dict(items)
		result={}
		for k, v in items:
			if k in result:
				raise ValueError(f"Duplicate key: {k!r}")
			result[k]=v
		return result

class TTPBalancedTokenList(TeXToPyData, BalancedTokenList):
	# the whole reason why this class is here is because of abuse of inherentance. Will refactor some day probably.
	send_code=_format(r"\__send_balanced_tl:n {{ {} }}%naive_ignore%")
	send_code_var=_format(r"\exp_args:NV \__send_balanced_tl:n {}%naive_ignore%")
	def __repr__(self)->str:
		return repr(BalancedTokenList(self))
	@staticmethod
	def read()->"TTPBalancedTokenList":
		if engine.is_unicode:
			return TTPBalancedTokenList(BalancedTokenList.deserialize(_readline()))
		else:
			return TTPBalancedTokenList(BalancedTokenList.deserialize(engine.read()))

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
		return P.tmp.tl()


class _NoFile: pass
_no_file=_NoFile()
file: Union[_NoFile, None, IO]=_no_file

class RedirectPrintTeX:
	"""
	A context manager. Use like this, where ``t`` is some file object::

		with RedirectPrintTeX(t):
			pass  # some code

	Then all :func:`.print_TeX` function calls will be redirected to ``t``.
	"""
	def __init__(self, t: Optional[IO])->None:
		self.t=t

	def __enter__(self)->None:
		global file
		self.old=file
		file=self.t

	def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any)->None:
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

	:param continue_included: See :func:`add_TeX_handler`.

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

_execute_cache: WeakKeyDictionary[Engine, Dict[tuple[Token, ...], str]]=WeakKeyDictionary()
def _execute_cached0(e: BalancedTokenList, *, continue_included: bool=False)->None:
	r"""
	Internal function, identical to :meth:`BalancedTokenList.execute` but cache the value of ``e``
	such that re-execution of the same token list will be faster.

	:param continue_included: See :func:`add_TeX_handler`.

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

_execute_once_cache: WeakKeyDictionary[Engine, Set[tuple[Token, ...]]]=WeakKeyDictionary()
def _execute_once(e: BalancedTokenList)->bool:
	r"""
	Execute the token list, but only the first time for each engine.

	>>> count[0]=5
	>>> _execute_once(BalancedTokenList(r'\advance\count0 by 1'))
	True
	>>> count[0]
	6
	>>> _execute_once(BalancedTokenList(r'\advance\count0 by 1'))
	False
	>>> count[0]
	6
	>>> with default_engine.set_engine(luatex_engine):
	... 	count[0]=7
	... 	_execute_once(BalancedTokenList(r'\advance\count0 by 1'))  # still executed because new engine
	... 	count[0]
	... 	_execute_once(BalancedTokenList(r'\advance\count0 by 1'))  # not executed
	... 	count[0]
	True
	8
	False
	8
	>>> count[0]  # old engine
	6
	"""
	assert e.is_balanced()
	l=_defaultget_with_cleanup(_execute_once_cache, set)
	t=tuple(e)
	if t not in l:
		l.add(t)
		e.execute()
		return True
	return False

_execute_arg_cache: WeakKeyDictionary[Engine, Dict[tuple[int, tuple[Token, ...]], str]]=WeakKeyDictionary()
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

class _GroupManagerStorage(threading.local):
	# we separate out the storage so that mypy can type check the parent class _GroupManager
	def __init__(self)->None:
		self.running_instances: list=[]

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

	Note that the user must not manually change the group level in a context::

		>>> with group:
		...     group.begin()
		Traceback (most recent call last):
			...
		ValueError: Group level changed during group

	They must not change the engine either::

		>>> tmp_engine=ChildProcessEngine("pdftex")
		>>> with group:
		...     c=default_engine.set_engine(tmp_engine)
		Traceback (most recent call last):
			...
		ValueError: Engine changed during group
		>>> tmp_engine.close()
		>>> c.restore()
		>>> group.end()

	:meta public:
	"""

	def __init__(self)->None:
		self._storage=_GroupManagerStorage()

	@contextlib.contextmanager
	def _run(self)->Generator[None, None, None]:
		engine=default_engine.engine
		self.begin()
		level=T.currentgrouplevel.int()
		try: yield
		finally:
			if engine is not default_engine.engine:
				raise ValueError("Engine changed during group")
			if T.currentgrouplevel.int()!=level:
				raise ValueError("Group level changed during group")
			self.end()

	def begin(self)->None:
		TokenList(r"\begingroup").execute()

	def __enter__(self)->None:
		instance: Any=self._run()
		instance.__enter__()
		self._storage.running_instances.append(instance)

	def end(self)->None:
		TokenList(r"\endgroup").execute()

	def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any)->None:
		instance=self._storage.running_instances.pop()
		instance.__exit__(exc_type, exc_value, traceback)

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
	Interface is similar to :const:`catcode`.

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
See :class:`_UmathcodeManager`.
"""


class _CountManager:
	r"""
	Manipulate count registers. Interface is similar to :const:`catcode`.

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
	Manipulate tok registers. Interface is similar to :const:`catcode`.

	For example::

		>>> toks[0]=BalancedTokenList('abc')
		>>> toks[0]
		<BalancedTokenList: a₁₁ b₁₁ c₁₁>

	:meta public:
	"""
	def __getitem__(self, x: int)->BalancedTokenList:
		return BalancedTokenList([r"\the\toks" + str(x)]).expand_o()

	def __setitem__(self, x: int, val: BalancedTokenList)->None:
		BalancedTokenList([r"\toks" + str(x), val]).execute()

toks=_ToksManager()
"""
See :class:`_ToksManager`.
"""

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
			local result
			local s=token.get_macro"_pythonimmediate_arga"
			local function try_call_print(f)
				local success, f_result=pcall(f)
				if success then
					if f_result==nil then
						result="-"
					else
						result="+"..tostring(f_result)
					end
				else
					result="!"..tostring(f_result)
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
					result="!"..tostring(err)
				end
			end
			tex.sprint(-2, result)
		end
		'''.strip()), r'}']))
	result=P.arga.str()
	assert result
	if result[0]=="+": return result[1:]
	if result[0]=="!": raise RuntimeError(result[1:])
	assert result=="-", result
	return None

def peek_next_meaning()->str:
	r"""
	Get the meaning of the following token, as a string, using the current ``\escapechar``.

	This is recommended over :meth:`Token.peek_next` as it will not tokenize an extra token.

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

scan_Python_call_TeX_module(__name__)
scan_Python_call_TeX_module("pythonimmediate.lowlevel")

from . import simple  # this import also scan the source code and populate bootstrap_code because of scan_Python_call_TeX_module(__name__) call inside
from .simple import get_arg_estr  # needed a few times above

# backwards compatibility
from .simple import execute, print_TeX

from . import texcmds
