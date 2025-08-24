
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

T1 = typing.TypeVar("T1")

is_sphinx_build = "SPHINX_BUILD" in os.environ

expansion_only_can_call_Python=False  # normally. May be different in LuaTeX etc.

debugging: bool=True
if os.environ.get("pythonimmediatenodebug", "").lower() in ["true", "1"]:
	debugging=False

	
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
"""
def mark_bootstrap(code: str|EngineDependentCode)->None:
	if isinstance(code, str):
		bootstrap_code_functions.append(lambda _engine: code)
	else:
		bootstrap_code_functions.append(code)

# check TeX package version.
mark_bootstrap(r"""
\use:c{@ifpackagelater} {pythonimmediate} {%} {
} {
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

@mark_bootstrap
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
	"""
	mark_bootstrap(wrap_naive_replace(code))

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
	"""
	if braces:
		assert line.count("{") == line.count("}")
	if newline:
		assert '\n' not in line
		assert '\r' not in line  # this is not the line separator but just in case
	if continue_==True: assert "pythonimmediatecontinue" in line
	elif continue_==False: assert "pythonimmediatecontinue" not in line


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

def _format(s: str)->Callable:
	def _result(*args: str)->str:
		"""
		"""
		return s.format(*args)
	return _result

class TTPRawLine(TeXToPyData, bytes):
	send_code=_format(r"\__send_content%naive_send%:n {{ {} }}")
	send_code_var=_format(r"\__send_content%naive_send%:n {{ {} }}")
	@staticmethod
	def read()->"TTPRawLine":
		line=engine.read()
		return TTPRawLine(line)

class TTPLine(TeXToPyData, str):
	send_code=_format(r"\__send_content%naive_send%:n {{ {} }}")
	send_code_var=_format(r"\__send_content%naive_send%:n {{ {} }}")
	@staticmethod
	def read()->"TTPLine":
		return TTPLine(_readline())

class TTPELine(TeXToPyData, str):
	"""
	Same as :class:`TTPEBlock`, but for a single line only.
	"""
	send_code=_format(r"\__begingroup_setup_estr: \__send_content%naive_send%:e {{ {} }} \endgroup")
	send_code_var=_format(r"\__begingroup_setup_estr: \__send_content%naive_send%:e {{ {} }} \endgroup")
	@staticmethod
	def read()->"TTPELine":
		return TTPELine(_readline())

class TTPEmbeddedLine(TeXToPyData, str):
	@staticmethod
	def send_code(arg: str)->str:
		raise RuntimeError("Must be manually handled")
	@staticmethod
	def send_code_var(arg: str)->str:
		raise RuntimeError("Must be manually handled")
	@staticmethod
	def read()->"TTPEmbeddedLine":
		raise RuntimeError("Must be manually handled")

class TTPBlock(TeXToPyData, str):
	send_code=_format(r"\__send_block:n {{ {} }} %naive_flush%")
	send_code_var=_format(r"\__send_block:V {} %naive_flush%")
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
	send_code=_format(r"\__begingroup_setup_estr: \__send_block%naive_send%:e {{ {} }} \endgroup")
	send_code_var=_format(r"\__begingroup_setup_estr: \__send_block%naive_send%:e {{ {} }} \endgroup")
	@staticmethod
	def read()->"TTPEBlock":
		return TTPEBlock(_read_block())

@mark_bootstrap
def _send_balanced_tl(engine: Engine)->str:
	if engine.name=="luatex": return ""
	return naive_replace(r"""
	\cs_new_protected:Npn \__send_balanced_tl:n #1 {
		\__tlserialize_nodot:Nn \__tmp { #1 }
		\__send_content%naive_send%:e {\unexpanded\expandafter{ \__tmp } }
	}
	""", engine)

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
	read_code=_format(r"\__str_get:N {} ")
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
	read_code=_format(r"\__get:N {}")
	def serialize(self)->bytes:
		assert "\n" not in self.data
		return (self.data+"\n").encode('u8')

@dataclass
class PTTBlock(PyToTeXData):
	data: str
	read_code=_format(r"\__read_block:N {}")

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
	read_code=_format(r"\__str_get:N {0}  \__tldeserialize_dot:NV {0} {0}")
	def serialize(self)->bytes:
		return PTTVerbatimRawLine(self.data.serialize_bytes()+b".").serialize()


# ======== define TeX functions that execute Python code ========
# ======== implementation of ``\py`` etc. Doesn't support verbatim argument yet. ========

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

_handlers: Dict[str, Callable[[], None]]={}
_per_engine_handlers: WeakKeyDictionary[Engine, Dict[str, Callable[[], None]]]=WeakKeyDictionary()

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

FunctionType = typing.TypeVar("FunctionType", bound=Callable)

def define_internal_handler(f: FunctionType)->FunctionType:
	"""
	Define a TeX function with TeX name = ``f.__name__`` that calls f().

	This does not define the specified function in any particular engine, just add them to the :const:`bootstrap_code`.
	"""
	mark_bootstrap(define_TeX_call_Python(f))
	return f



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
	if mode=="exec": exec(compiled_code, globals)
	else: eval(compiled_code, globals)

	#del linecache.cache[sourcename]
	# we never delete the cache, in case some function is defined here then later are called...

def exec_with_linecache(code: str, globals: Dict[str, Any])->None:
	exec_or_eval_with_linecache(code, globals, "exec")

def eval_with_linecache(code: str, globals: Dict[str, Any])->Any:
	return exec_or_eval_with_linecache(code, globals, "eval")


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
		ttp_argtypes = result_type.__args__

	extra=Python_call_TeX_extra(
			ptt_argtypes=Tx,
			ttp_argtypes=ttp_argtypes
			)
	if data in Python_call_TeX_defined:
		assert Python_call_TeX_defined[data][0]==extra, "different function with exact same code is not supported for now"
	else:
		if  isinstance(ttp_argtypes, type) and issubclass(ttp_argtypes, TeXToPyData):
			# special case, return a single object instead of a tuple of length 1
			code, result1=define_Python_call_TeX(TeX_code=TeX_code, ptt_argtypes=[*extra.ptt_argtypes], ttp_argtypes=[ttp_argtypes],
																  recursive=recursive, sync=sync, finish=finish,
																  )
			def result(*args: Any)->Any:
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
		mark_bootstrap(code)

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
	"""
	import ast
	from copy import deepcopy
	from . import TTPBalancedTokenList  # as explained in TTPBalancedTokenList sourcecode, this is caused by abuse of inherentance
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
			print(f"======== while scanning file for Python_call_TeX_local(...) -- error on line {getattr(node, 'lineno', '??')} of file {filename} ========", file=sys.stderr)
			raise

def scan_Python_call_TeX_module(name: str)->None:
	"""
	Internal function.
	Can be used as ``scan_Python_call_TeX_module(__name__)`` to scan the current module.
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

	def f(*args: Any)->Optional[Tuple[TeXToPyData, ...]]:
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

def run_none_finish()->None:
	typing.cast(Callable[[], None], Python_call_TeX_local(
		r"""
		\cs_new_eq:NN %name% \relax
		""", finish=True, sync=False))()

def run_error_finish(full_error: PTTBlock, short_error: PTTBlock)->None:
	"""
	Internal function.

	``run_error_finish`` is fatal to [TeX], so we only run it when it's fatal to Python.

	We want to make sure the Python traceback is printed strictly before run_error_finish() is called,
	so that the Python traceback is not interleaved with [TeX] error messages.
	"""
	typing.cast(Callable[[PTTBlock, PTTBlock], None], Python_call_TeX_local(
		r"""
		\msg_new:nnn {pythonimmediate} {python-error} {Python~error:~#1.}
		\cs_new_protected:Npn %name% {
			%read_arg0(\__data)%
			%read_arg1(\__summary)%
			\wlog{^^JPython~error~traceback:^^J\__data^^J}
			\msg_error:nnx {pythonimmediate} {python-error} {\__summary}
			\__close_write:
		}
		""", finish=True, sync=False))(full_error, short_error)

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

def get_bootstrap_code(engine: Engine)->str:
	"""
	Return the bootstrap code for an engine.

	This is before the call to :meth:`substitute_private`.
	"""
	return "\n".join(
			f(engine)
			for f in bootstrap_code_functions)

if typing.TYPE_CHECKING:
	from . import BalancedTokenList

