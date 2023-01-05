r"""
Simple interface, suitable for users who may not be aware of TeX subtleties, such as category codes.
"""

import sys
import inspect
from typing import Optional, Union, Callable, Any, Iterator, Protocol, Iterable, Sequence, Type, Tuple, List, Dict
import typing
import functools
import re

import pythonimmediate
from .textopy import export_function_to_module, scan_Python_call_TeX, PTTTeXLine, Python_call_TeX_local, check_line, user_documentation, Token, TTPEBlock, TTPEmbeddedLine, get_random_identifier, CharacterToken, define_TeX_call_Python, parse_meaning_str, peek_next_meaning, PTTVerbatimLine, run_block_local, run_code_redirect_print_TeX, TTPBlock, TTPLine
from .engine import Engine, default_engine


@export_function_to_module
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

@export_function_to_module
@user_documentation
def peek_next_char(engine: Engine=  default_engine)->str:
	"""
	Get the character of the following token, or empty string if it's not a character.
	Will also return nonempty if the next token is an implicit character token.

	Uses peek_next_meaning() under the hood to get the meaning of the following token. See peek_next_meaning() for a warning on undefined behavior.
	"""

	#return str(peek_next_char_()[0])
	# too slow (marginally slower than peek_next_meaning)

	r=parse_meaning_str(peek_next_meaning())
	if r is None:
		return ""
	return r[1]

@export_function_to_module
def get_next_char(engine: Engine=  default_engine)->str:
	result=Token.get_next(engine=engine)
	assert isinstance(result, CharacterToken), "Next token is not a character!"
	return result.chr

@export_function_to_module
@user_documentation
def put_next(arg: str, engine: Engine=  default_engine)->None:
	"""
	Put some content forward in the input stream.

	arg: has type |str| (will be tokenized in the current catcode regime, must be a single line)
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

def replace_double_hash(s: str)->str:
	return s.replace("##", "#")

@export_function_to_module
@user_documentation
def get_arg_str(engine: Engine=  default_engine)->str:
	"""
	Get a mandatory argument.
	"""
	return replace_double_hash(typing.cast(Callable[[Engine], TTPEmbeddedLine], Python_call_TeX_local(
		r"""
		\cs_new_protected:Npn %name% #1 {
			\immediate\write\__write_file { \unexpanded {
				r #1
			}}
			\__read_do_one_command:
		}
		""", recursive=False))(engine))

@export_function_to_module
@user_documentation
def get_arg_estr(engine: Engine=  default_engine)->str:
	return str(typing.cast(Callable[[Engine], Tuple[TTPEBlock]], Python_call_TeX_local(
r"""

\cs_new_protected:Npn %name% #1 {
	%sync%
	%send_arg0(#1)%
	\__read_do_one_command:
}
""", recursive=False))(engine)[0])


@export_function_to_module
@user_documentation
def get_optional_arg_str(engine: Engine=  default_engine)->Optional[str]:
	"""
	Get an optional argument.
	"""
	[result]=typing.cast(Callable[[Engine], Tuple[TTPLine]], Python_call_TeX_local(
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



@export_function_to_module
@user_documentation
def get_optional_arg_estr(engine: Engine=  default_engine)->Optional[str]:
	[result]=typing.cast(Callable[[Engine], Tuple[TTPEBlock]], Python_call_TeX_local(
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
""", recursive=False)) (engine)
	result_=str(result)
	if result_=="0": return None
	assert result_[0]=="1", result_
	return result_[1:]


@export_function_to_module
@user_documentation
def get_verb_arg(engine: Engine=  default_engine)->str:
	"""
	Get a verbatim argument. Since it's verbatim, there's no worry of |#| being doubled,
	but it can only be used at top level.
	"""
	return str(typing.cast(Callable[[Engine], Tuple[TTPLine]], Python_call_TeX_local(
r"""
\NewDocumentCommand %name% {v} {
	\immediate\write\__write_file { \unexpanded {
		r ^^J
		#1
	}}
	\__read_do_one_command:
}
""", recursive=False))
		(engine)[0])

@export_function_to_module
@user_documentation
def get_multiline_verb_arg(engine: Engine=  default_engine)->str:
	"""
	Get a multi-line verbatim argument.
	"""
	return str(typing.cast(Callable[[Engine], Tuple[TTPBlock]], Python_call_TeX_local(
r"""
\NewDocumentCommand %name% {+v} {
	\immediate\write\__write_file { r }
	\begingroup
		\newlinechar=13~  % this is what +v argument type in xparse uses
		\__send_block:n { #1 }
	\endgroup
	\__read_do_one_command:
}
""", recursive=False))(engine)[0])



def check_function_name(name: str)->None:
	if not re.fullmatch("[A-Za-z]+", name) or (len(name)==1 and ord(name)<=0x7f):
		raise RuntimeError("Invalid function name: "+name)

def newcommand_(name: str, f: Callable, engine: Engine)->Callable:
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
""", recursive=False)) (PTTVerbatimLine(name), PTTVerbatimLine(identifier), engine)

	_code=define_TeX_call_Python(
			lambda engine: run_code_redirect_print_TeX(f, engine=engine),
			name, argtypes=[], identifier=identifier)
	# ignore _code, already executed something equivalent in the TeX command
	return f

def renewcommand_(name: str, f: Callable, engine: Engine)->Callable:
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
""", recursive=False)) (PTTVerbatimLine(name), PTTVerbatimLine(identifier), engine)
	# TODO remove the redundant entry from TeX_handlers (although technically is not very necessary, just cause slight memory leak)
	#try: del TeX_handlers["u"+name]
	#except KeyError: pass

	_code=define_TeX_call_Python(
			lambda engine: run_code_redirect_print_TeX(f, engine=engine),
			name, argtypes=[], identifier=identifier)
	# ignore _code, already executed something equivalent in the TeX command
	return f

@export_function_to_module
def newcommand(x: Union[str, Callable, None]=None, f: Optional[Callable]=None, engine: Engine=  default_engine)->Callable:
	r"""
	Define a new \TeX\ command.
	If name is not provided, it's automatically deduced from the function.

	this is a TeX logo in rst: :math:`\TeX`
	"""
	if f is not None: return newcommand(x, engine=engine)(f)
	if x is None: return newcommand  # weird design but okay (allow |@newcommand()| as well as |@newcommand|)
	if isinstance(x, str): return functools.partial(newcommand_, x, engine=engine)
	return newcommand_(x.__name__, x, engine=engine)

@export_function_to_module
def renewcommand(x: Union[str, Callable, None]=None, f: Optional[Callable]=None, engine: Engine=  default_engine)->Callable:
	r"""
	Redefine a \TeX\ command.
	If name is not provided, it's automatically deduced from the function.
	"""
	if f is not None: return renewcommand(x, engine=engine)(f)
	if x is None: return renewcommand  # weird design but okay (allow |@newcommand()| as well as |@newcommand|)
	if isinstance(x, str): return functools.partial(renewcommand_, x, engine=engine)
	return renewcommand_(x.__name__, x, engine=engine)

@user_documentation
@export_function_to_module
def execute(block: str, engine: Engine)->None:
	r"""
	Run a block of \TeX\ code (might consist of multiple lines).
	Catcode-changing commands are allowed inside.

	A simple example is |pythonimmediate.run_block_local('123')| which simply typesets |123|.

	A more complicated example is |pythonimmediate.run_block_local(r'\verb+%+')|.
	"""
	run_block_local(block, engine=engine)

@export_function_to_module
def print_TeX(*args, **kwargs)->None:
	if not hasattr(pythonimmediate, "file"):
		raise RuntimeError("Internal error: attempt to print to TeX outside any environment!")
	if pythonimmediate.file is not None:
		functools.partial(print, file=pythonimmediate.file)(*args, **kwargs)  # allow user to override `file` kwarg

scan_Python_call_TeX(inspect.getsource(sys.modules[__name__]))


