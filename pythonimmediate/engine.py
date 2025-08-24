"""
Abstract engine class.
"""

from __future__ import annotations

from typing import Optional, Literal, Iterable, List, Dict, Tuple, Callable, Any
from abc import ABC, abstractmethod
import sys
import os
import subprocess
import threading
from dataclasses import dataclass
import atexit
import enum
from pathlib import Path
import tempfile
import weakref

import pythonimmediate
from . import communicate
from .communicate import GlobalConfiguration


EngineName=Literal["pdftex", "xetex", "luatex"]
"""
The ``EngineName`` type is a string that specifies the name of the engine.
"""

engine_names: Tuple[EngineName, ...]=EngineName.__args__  # type: ignore

_DEFAULT_TIMEOUT=5
"""
Internal setting.

When we know the process should exit soon, wait for at most this long.
Normally it should terminate before timeout is over, if it isn't then there's an internal error.
"""

mark_to_engine_names: Dict[str, EngineName]={
		"p": "pdftex",
		#"P": "ptex",
		#"u": "uptex",
		"x": "xetex",
		"l": "luatex",
		}
assert len(mark_to_engine_names)==len(engine_names)
assert set(mark_to_engine_names.values())==set(engine_names)


engine_is_unicode: Dict[EngineName, bool]={
		"pdftex": False,
		#"ptex": False,
		#"uptex": False,
		"xetex": True,
		"luatex": True,
		}
assert len(engine_is_unicode)==len(engine_names)
assert set(engine_is_unicode)==set(engine_names)


engine_name_to_latex_executable: Dict[EngineName, str]={
		"pdftex": "pdflatex",
		"xetex": "xelatex",
		"luatex": "lualatex",
		}
assert len(engine_name_to_latex_executable)==len(engine_names)
assert set(engine_name_to_latex_executable)==set(engine_names)


class EngineStatus(enum.Enum):
	"""
	Represent the status of the engine. Helper functions are supposed to manage the status by itself.

	* running: the engine is running [TeX] code and Python cannot write to it, only wait for Python commands.
	* waiting: the engine is waiting for Python to write a handler.
	* error: an error happened.
	* exited: the engine exited cleanly.
	"""
	running=enum.auto()
	waiting=enum.auto()
	error  =enum.auto()
	exited =enum.auto()


def _try_close_log_communication_file(o: Any)->Callable[[], None]:
	def f()->None:
		p=o()
		if p:
			p.close_log_communication_file()
	return f

class Engine(ABC):
	_name: EngineName
	_config: GlobalConfiguration
	status: EngineStatus
	_log_communication_file: Any=None

	def _log_communication(self, s: bytes)->None:
		if self._log_communication_file:
			self._log_communication_file.write(s)
			self._log_communication_file.flush()

	def set_log_communication_file(self, path: str|Path)->None:
		print(f"[All communications will be logged to {path}]", flush=True)
		self._log_communication_file=open(path, "wb")
		self._log_communication(b"Communication log ['>': TeX to Python - include i/r distinction, '<': Python to TeX]:\n")
		atexit.register(_try_close_log_communication_file(weakref.ref(self)))

	def close_log_communication_file(self)->None:
		if self._log_communication_file:
			self._log_communication_file.close()

	def __init__(self)->None:
		self._config=GlobalConfiguration()  # dummy value
		self.status=EngineStatus.waiting
		self._on_close_list: List[Callable[[Engine], None]]=[]
		self._log: Optional[bytes]=None

	def add_on_close(self, f: Callable[[Engine], None])->None:
		r"""
		Add a function that will be executed when the engine is closed.

		This function takes the engine object itself as the only argument
		to avoid a circular reference issue which would prevent the engine
		from being garbage-collected.

		>>> e=ChildProcessEngine("pdftex")
		>>> e.add_on_close(lambda _: print(1))
		>>> e.add_on_close(lambda _: print(2))
		>>> e.close()
		1
		2

		The same engine may be closed multiple times in case of ``autorestart``,
		in that case the function will only be called once.

		>>> e=ChildProcessEngine("pdftex", autorestart=True)
		>>> a=[1, 2, 3]
		>>> e.add_on_close(lambda e: a.pop())
		>>> from pythonimmediate import execute
		>>> with default_engine.set_engine(e): execute(r"\error")
		Traceback (most recent call last):
			...
		pythonimmediate.engine.TeXProcessError: Undefined control sequence.
		>>> a
		[1, 2, 3]
		>>> e.close()
		>>> a
		[1, 2]
		"""
		self._on_close_list.append(f)

	@property
	def name(self)->EngineName:
		"""
		Self-explanatory.
		"""
		return self._name

	@property
	def config(self)->GlobalConfiguration:
		"""
		Self-explanatory.
		"""
		return self._config

	@property
	def is_unicode(self)->bool: 
		"""
		Self-explanatory.
		"""
		return engine_is_unicode[self.name]

	def read(self)->bytes:
		"""
		Internal function.
		
		Read one line from the engine.

		It must not be EOF otherwise there's an error.

		The returned line does not contain the newline character.
		"""
		if self.status==EngineStatus.error: raise RuntimeError("TeX error!")
		assert self.status==EngineStatus.running, self.status
		while True:
			line=self._read()
			if line:
				assert line.endswith(b'\n') and line.count(b'\n')==1, line
				self._log_communication(b">"+line)
			if line.rstrip()!=b"pythonimmediate-naive-flush-line":
				break
			else:
				# ignore this line
				assert self.config.naive_flush
		if self.status==EngineStatus.error: raise RuntimeError("TeX error!")
		assert line[-1]==10, line  # 10: '\n'
		return line[:-1]

	def write(self, s: bytes)->None:
		if self.status==EngineStatus.error: raise RuntimeError("TeX error!")
		assert self.status==EngineStatus.waiting, self.status
		if s:
			lines=s.split(b'\n')
			for line in lines[:-1]: self._log_communication(b"<"+line+b'\n')
			if lines[-1]: self._log_communication(b"<"+lines[-1]+b"...\n")
		self._write(s)

	@abstractmethod
	def _read(self)->bytes:
		"""
		Read one line from the engine.

		Should return b"⟨line⟩\n" or b"" (if EOF) on each call.
		"""
		...

	@abstractmethod
	def _write(self, s: bytes)->None:
		"""
		Write data to the engine.

		Because TeX can only read whole lines s should be newline-terminated.
		"""
		...

	@abstractmethod
	def __enter__(self)->Engine:
		...

	@abstractmethod
	def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any)->None:
		...

	def close(self)->None:
		"""
		Terminates the [TeX] subprocess gracefully.
		"""
		self._close()
		self.close_log_communication_file()
		l=self._on_close_list
		self._on_close_list=[]
		for f in l: f(self)

	@abstractmethod
	def _close(self)->None:
		...


def debug_possibly_shorten(line: str)->str:
	if len(line)>=100:
		return line[:100]+"..."
	return line


class ParentProcessEngine(Engine):
	"""
	Represent the engine if this process is started by the [TeX]'s pythonimmediate library.

	This should not be instantiated directly. Only :func:`pythonimmediate.textopy.main` should instantiate this.
	"""
	def __init__(self, pseudo_config: GlobalConfiguration)->None:
		super().__init__()

		import threading
		def f()->None:
			"""
			Sanity check, just in case the readline() below block forever. (should never happen.)
			"""
			raise RuntimeError("Cannot read anything from TeX!")
		timer=threading.Timer(3, f)
		timer.start()

		self.input_file=sys.stdin.buffer

		if pseudo_config.debug_force_buffered:
			r, w=os.pipe()
			self.input_file=os.fdopen(r, "rb")

			# create a daemon thread to copy the data from stdin to the pipe, by 4096-byte blocks.
			def f()->None:
				buffer=bytearray()
				assert sys.__stdin__ is not None
				while True:
					data=sys.__stdin__.buffer.readline()  # type: ignore
					if pseudo_config.debug>=5: print("TeX → Python (buffered): " + debug_possibly_shorten(data.decode('u8')))
					if not data:
						os.write(w, buffer)
						break
					buffer.extend(data)
					while len(buffer)>4096:
						os.write(w, buffer[:4096])
						buffer=buffer[4096:]
			debug_force_buffered_worker_thread=threading.Thread(target=f, daemon=True)
			debug_force_buffered_worker_thread.start()


		if pseudo_config.naive_flush:
			content=bytearray()
			while True:
				content.extend(self.input_file.read(4096))
				if content[-1]==ord("."): break
			line=content.decode('u8')
			self.ignore_first_line=True
		else:
			line=self.input_file.readline().decode('u8')  # can't use self._read() here, config is uninitialized
			self.ignore_first_line=False
		timer.cancel()

		self._name=mark_to_engine_names[line[0]]
		line=line[1:]

		#self.config=eval(line)  # this is not safe but there should not be anything except the TeX process writing here anyway
		import base64
		import pickle
		self._config=pickle.loads(base64.b64decode(line))
		assert isinstance(self.config, GlobalConfiguration)

		sys.stdin=None
		# avoid user mistakenly read

		if self.config.debug_log_communication is not None:
			from string import Template
			debug_log_communication = Path(Template(self.config.debug_log_communication).safe_substitute(pid=os.getpid()))
			self.set_log_communication_file(debug_log_communication)

		from .lowlevel import surround_delimiter, substitute_private, get_bootstrap_code
		self.write(surround_delimiter(substitute_private(get_bootstrap_code(self))).encode('u8'))
		self.status=EngineStatus.running

	def _read(self)->bytes:
		while True:
			line=self.input_file.readline()
			if self.ignore_first_line:
				self.ignore_first_line=False
				continue
			break

		if not line: self.status=EngineStatus.error
		return line

	def _write(self, s: bytes)->None:
		self.config.communicator.send(s)

	def _close(self)->None:
		raise RuntimeError("Cannot close ParentProcessEngine!")

	def __enter__(self)->Engine:
		raise RuntimeError("ParentProcessEngine should not be used as a context manager!")

	def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any)->None:
		raise RuntimeError("ParentProcessEngine should not be used as a context manager!")


@dataclass
class _SetDefaultEngineContextManager:
	"""
	Context manager, used in conjunction with default_engine.set_engine(...) to revert to the original engine.
	"""
	_old_engine: Optional[Engine]
	_new_engine: Optional[Engine]
	entered: bool=False
	restored: bool=False

	def __enter__(self)->Optional[Engine]:
		assert not self.entered, "This context manager is not re-entrant!"
		self.entered=True
		result=self._new_engine
		self._new_engine=None
		return result

	def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any)->None:
		assert self.entered, "__exit__ called manually without __enter__ called"
		if not self.restored: self.restore()

	def restore(self)->None:
		if self.restored: raise RuntimeError("Already restored!")
		self.restored=True
		default_engine.set_engine(self._old_engine)
		self._old_engine=None
		self._new_engine=None  # allow the engine to be garbage collected


class _DefaultEngineStorage(threading.local):
	def __init__(self)->None:
		self.engine: Optional[Engine]=None
		"""
		Stores the engine being set internally.

		Normally there's no reason to access the internal engine directly, as ``self`` can be used
		like the engine inside.
		"""


class DefaultEngine:
	"""
	A convenience class that can be used to avoid passing explicit ``engine`` argument to functions.

	This is thread-safe, which means that each thread can have its own set default engine
	and :meth:`set_engine` for one thread does not affect other threads.

	Users should not instantiate this class directly. Instead, use :const:`default_engine`.

	Usage example::

		default_engine.set_engine(engine)  # set only for this thread
		execute("hello world")  # this is executed on engine=engine

	.. seealso::
		:meth:`set_engine`
	"""

	def __init__(self)->None:
		self._storage=_DefaultEngineStorage()

	def set_engine(self, engine: Optional[Engine])->_SetDefaultEngineContextManager:
		r"""
		Set the default engine to another engine.

		Can also be used as a context manager to revert to the original engine.
		Example:

		>>> from pythonimmediate import execute
		>>> _new_engine=ChildProcessEngine("pdftex")
		>>> with default_engine.set_engine(_new_engine) as engine:  # only for this thread
		... 	assert engine is _new_engine
		... 	assert default_engine.engine is _new_engine
		... 	execute(r"\count0=5")
		>>> # now the original engine is restored
		>>> _new_engine.close()

		Note that the following form, while allowed, is discouraged because it may cause resource leak
		(the engine may keeps running even after the block exits depends on whether it's garbage-collected):

		>>> with default_engine.set_engine(ChildProcessEngine("pdftex")):
		...		pass

		It's recommended to write the following instead, which will close ``e`` at the end of the block:

		>>> with ChildProcessEngine("pdftex") as e, default_engine.set_engine(e):
		...		pass
		"""
		assert engine is not self
		result=_SetDefaultEngineContextManager(_old_engine=self.engine, _new_engine=engine)
		self._storage.engine=engine
		return result

	def get_engine(self)->Engine:
		"""
		Convenience helper function, return the engine.

		All the other functions that use this one (those that make use of the engine) will raise RuntimeError
		if the engine is None.
		"""
		if self._storage.engine is None:
			raise RuntimeError("Default engine not set for this thread!")
		return self._storage.engine

	@property
	def status(self)->EngineStatus:
		return self.get_engine().status

	@status.setter
	def status(self, value: EngineStatus)->None:
		self.get_engine().status=value

	@property
	def engine(self)->Optional[Engine]:
		"""
		Return the engine, or None if the engine is not set.
		"""
		return self._storage.engine

	@property
	def is_unicode(self)->bool:
		return self.get_engine().is_unicode

	@property
	def name(self)->EngineName:
		return self.get_engine().name

	@property
	def config(self)->GlobalConfiguration:
		return self.get_engine().config

	@config.setter
	def config(self, value: GlobalConfiguration)->None:
		raise NotImplementedError

	def read(self)->bytes:
		return self.get_engine().read()

	def write(self, s: bytes)->None:
		self.get_engine().write(s)

	def _log_communication(self, s: bytes)->None:
		self.get_engine()._log_communication(s)

	def add_on_close(self, f: Callable[[Engine], None])->None:
		assert False

	def _close(self)->None:
		assert False


default_engine=DefaultEngine()
"""
A constant that can be used to avoid passing explicit ``engine`` argument to functions.

See documentation of :class:`DefaultEngine` for more details.

For Python running inside a [TeX] process, useful attributes are :attr:`~Engine.name` and :attr:`~Engine.is_unicode`.
"""


class TeXProcessExited(Exception):
	r"""
	An exception that will be raised if some operation makes the process exits.

	It is, however, safe to just catch this in case of :class:`ChildProcessEngine`.
	See there for an example.

	>>> from pythonimmediate import execute, BalancedTokenList
	>>> execute(r'\documentclass{article}\begin{document}hello world')
	>>> execute(r'\end{document}')
	Traceback (most recent call last):
		...
	pythonimmediate.engine.TeXProcessExited
	>>> execute(r'\documentclass{article}\begin{document}hello world')
	>>> BalancedTokenList(r'\end{document}').execute()
	Traceback (most recent call last):
		...
	pythonimmediate.engine.TeXProcessExited
	"""
	pass

class TeXProcessError(RuntimeError): pass

class ChildProcessEngine(Engine):
	r"""
	An object that represents a [TeX] engine that runs as a subprocess of this process.

	Can be used as a context manager to automatically close the subprocess when the context is exited. Alternatively :meth:`~Engine.close` can be used to manually terminate the subprocess.

	For example, the following Python code, if run alone, will spawn a [TeX] process and use it to write "Hello world" to a file named ``a.txt`` in the temporary directory:

	>>> from pythonimmediate.engine import ChildProcessEngine, default_engine
	>>> from pythonimmediate import execute
	>>> from pathlib import Path
	>>> with ChildProcessEngine("pdftex") as engine, default_engine.set_engine(engine):
	... 	# do something with the engine, for example:
	... 	execute(r'''
	... 	\immediate\openout9=a.txt
	... 	\immediate\write9{Hello world}
	... 	\immediate\closeout9
	... 	''')
	... 	(Path(engine.directory)/"a.txt").read_text()
	'Hello world\n'
	>>> # now the engine is closed and the file is cleaned up.
	>>> (Path(engine.directory)/"a.txt").is_file()
	False

	You can also use this to generate PDF file programmatically:

	>>> with ChildProcessEngine("pdftex") as engine, default_engine.set_engine(engine):
	... 	execute(r'\documentclass{article}')
	... 	execute(r'\usepackage[pdfversion=1.5]{hyperref}')
	... 	execute(r'\begin{document}')
	... 	execute(r'Hello world')
	... 	engine.terminate()
	... 	print(engine.read_output_file()[:9])
	b'%PDF-1.5\n'

	See :class:`DefaultEngine` for how to use the resulting engine object.

	We attempt to do correct error detection on the Python side by parsing the output/log file:

	>>> with ChildProcessEngine("pdftex") as engine, default_engine.set_engine(engine):
	...		execute(r'\error')
	Traceback (most recent call last):
		...
	pythonimmediate.engine.TeXProcessError: Undefined control sequence.

	However, it's not always easy.
	For example the following code will reproduce the output on error identically:

	.. code-block:: latex

		\message{^^J! error.^^J%
		l.1 \errmessage{error}^^J%
		^^J%
		? }
		\readline -1 to \xx

	As an alternative to :meth:`terminate`, you can also just execute ``\end{document}``, but
	be sure to catch :class:`TeXProcessExited` if you do so.
	If you do this, there's no need to call :meth:`terminate`.

	>>> with ChildProcessEngine("pdftex") as engine, default_engine.set_engine(engine):
	... 	execute(r'\documentclass{article}')
	... 	execute(r'\usepackage[pdfversion=1.5]{hyperref}')
	... 	execute(r'\begin{document}')
	... 	execute(r'Hello world')
	... 	try: execute(r'\end{document}')
	... 	except TeXProcessExited: pass
	... 	print(engine.read_output_file()[:9])
	b'%PDF-1.5\n'

	:param args: List of additional arguments to be passed to the executable, such as ``--recorder`` etc.
	:param env: See documentation of *env* argument in ``subprocess.Popen``.
		Note that it's usually recommended to append environment variables that should be set to
		``os.environ`` instead of replacing it entirely.
	:param from_dump: Slightly undocumented feature at the moment.

		Refer to https://tex.stackexchange.com/a/687427 for explanation. Decompressing the format file
		is optional, explained in that link.

		Example:

		>>> from pythonimmediate import BalancedTokenList
		>>> from pathlib import Path
		>>> import tempfile
		>>> import gzip
		>>> with ChildProcessEngine("pdftex", args=["--ini", "&pdflatex"]) as engine, default_engine.set_engine(engine):
		... 	try: execute(r"\documentclass{article} \usepackage{tikz} \pythonimmediatechildprocessdump")
		... 	except TeXProcessExited: pass
		... 	else: assert False
		... 	f=Path(tempfile.mktemp(suffix=".fmt"))
		... 	_size=f.write_bytes(gzip.decompress(engine.read_output_file("fmt")))
		>>> with ChildProcessEngine("pdftex", from_dump=True, args=["&"+str(f.with_suffix(""))]) as engine, default_engine.set_engine(engine):
		... 	BalancedTokenList(r"\the\numexpr 12+34\relax").expand_o()
		<BalancedTokenList: 4₁₂ 6₁₂>
		>>> f.unlink()

	:param autorestart: Mostly for testing purpose -- whenever an error happen, the engine will be killed and automatically restarted.
		
		For example:

		>>> from pythonimmediate import count
		>>> engine=ChildProcessEngine("pdftex")
		>>> with default_engine.set_engine(engine): execute(r'\error')
		Traceback (most recent call last):
			...
		pythonimmediate.engine.TeXProcessError: Undefined control sequence.
		>>> with default_engine.set_engine(engine): count[0]
		Traceback (most recent call last):
			...
		pythonimmediate.engine.TeXProcessError: error already happened

		>>> engine=ChildProcessEngine("pdftex", autorestart=True)
		>>> count[0]=2
		>>> with default_engine.set_engine(engine): execute(r'\error')
		Traceback (most recent call last):
			...
		pythonimmediate.engine.TeXProcessError: Undefined control sequence.
		>>> with default_engine.set_engine(engine): count[0]
		1
		>>> with default_engine.set_engine(engine): execute(r'\error')
		Traceback (most recent call last):
			...
		pythonimmediate.engine.TeXProcessError: Undefined control sequence.

	"""

	def __init__(self, engine_name: EngineName, args: Iterable[str]=(), env: Optional[dict[str, str]]=None, autorestart: bool=False, debug_log_communication: Optional[str|Path]=None, from_dump: bool=False)->None:
		super().__init__()
		if debug_log_communication is not None:
			self.set_log_communication_file(debug_log_communication)
		self._name=engine_name
		self._from_dump=from_dump
		assert not isinstance(args, str), "Pass a list/tuple of strings as args"
		self._args=args
		self._env=env
		self._autorestart=autorestart

		self._create_directory()
		"""
		A temporary working directory for the engine.
		"""

		self._stdout_lines: List[bytes]=[]  # for debugging purpose only

		self._process: Optional[subprocess.Popen]=None  # guard like this so that __del__ does not blow up if Popen() fails
		self._start_process()

	def _create_directory(self)->None:
		self._directory: tempfile.TemporaryDirectory
		if sys.version_info >= (3, 10):
			self._directory=tempfile.TemporaryDirectory(prefix="pyimm-", ignore_cleanup_errors=True)
		else:
			self._directory=tempfile.TemporaryDirectory(prefix="pyimm-")
		self.directory: Path=Path(self._directory.name)

	def _start_process(self)->None:
		# old method, tried, does not work, see details in sty file
		# create a sym link from /dev/stderr to /tmp/.tex-stderr
		# because TeX can only write to files that contain a period
		#from pathlib import Path
		#target=Path(tempfile.gettempdir())/"symlink-to-stderr.txt"
		#try:
		#	target.symlink_to(Path("/dev/stderr"))
		#except FileExistsError:
		#	# we assume nothing maliciously create a file named `.symlink-to-stderr` that is not a symlink to stderr...
		#	pass

		assert self._process is None
		if not self.directory.is_dir(): self._create_directory()
		self.status=EngineStatus.waiting
		self._process=subprocess.Popen(
				[
					engine_name_to_latex_executable[self._name], "--shell-escape",
						*self._args,
						*([] if self._from_dump else [r"\RequirePackage[child-process]{pythonimmediate}\pythonimmediatelisten\stop"])
						],
				stdin=subprocess.PIPE,
				stdout=subprocess.PIPE,
				stderr=subprocess.PIPE,
				cwd=self.directory,
				env=self._env,
				start_new_session=True,  # avoid ctrl-C propagating to TeX process (when used in interactive terminal the TeX process should not be killed on ctrl-C)
				)


		# create thread listen for stdout
		self._stdout_thread=threading.Thread(target=ChildProcessEngine._stdout_thread_func, args=(weakref.ref(self),), daemon=True)
		self._stdout_thread.start()

		if not self._from_dump:
			from .lowlevel import surround_delimiter, substitute_private, get_bootstrap_code
			self.write(surround_delimiter(substitute_private(
				get_bootstrap_code(self)
				)).encode('u8'))

	def __repr__(self)->str:
		r"""
		Example::

			>>> e = ChildProcessEngine("pdftex", args=["--8bit"])
			>>> e
			ChildProcessEngine('pdftex')
			>>> e.close()
			>>> e
			<ChildProcessEngine('pdftex') closed>

			>>> e = ChildProcessEngine("luatex")
			>>> e
			ChildProcessEngine('luatex')
			>>> from pythonimmediate import BalancedTokenList
			>>> with default_engine.set_engine(e): BalancedTokenList(r"\undefined").expand_x()
			Traceback (most recent call last):
				...
			pythonimmediate.engine.TeXProcessError: Undefined control sequence.
			>>> e
			<ChildProcessEngine('luatex') error>
		"""
		s = f"ChildProcessEngine('{self.name}')"
		if self.status==EngineStatus.error:
			return f"<{s} error>"
		if not self._process:
			return f"<{s} closed>"
		return s

	@staticmethod
	def _stdout_thread_func(ref: weakref.ref[ChildProcessEngine])->None:
		def get_engine()->ChildProcessEngine:
			engine=ref()
			assert engine is not None
			return engine
		process=get_engine()._process
		assert process is not None
		assert process.stdin is not None
		assert process.stdout is not None

		_error_marker_line_seen: bool=False
		_stdout_lines: List[bytes]=[]  # Note that this is asynchronously populated so values may not be always correct
		_stdout_buffer=bytearray()  # remaining part that does not fit in any line

		get_engine()._stdout_lines=_stdout_lines  # for debugging purpose only

		while True:
			line: bytes=process.stdout.read1()  # type: ignore
			if not line:
				process.wait(timeout=_DEFAULT_TIMEOUT)
				break

			_stdout_buffer+=line

			if b"\n" in line:
				# add complete lines to _stdout_lines and update _error_marker_line_seen
				parts = _stdout_buffer.split(b"\n")
				_stdout_lines+=map(bytes, parts[:-1])
				_error_marker_line_seen=_error_marker_line_seen or any(line.startswith(b"<*> ") for line in parts[:-1])
				_stdout_buffer[:]=parts[-1]
				if b'!  ==> Fatal error occurred, no output PDF file produced!' in parts[:-1]:
					get_engine().status=EngineStatus.error
					process.wait(timeout=_DEFAULT_TIMEOUT)
					break

			# check potential error
			if _stdout_buffer == b"? " and _error_marker_line_seen:
				get_engine().status=EngineStatus.error
				process.stdin.close()  # close the stdin so process will terminate
				process.wait(timeout=_DEFAULT_TIMEOUT)
				break
				# this is a simple way to break out _read() but it will not allow error recovery
		process.stdin.close()
		process.stdout.close()

	def _print_stdout(self)->None:
		"""
		For debug purpose only. If the engine is still running there's a chance the log is not flushed when this function is called.
		"""
		print(b"\n".join(self._stdout_lines).decode('u8', "replace"))

	def get_process(self)->subprocess.Popen:
		if self._process is None:
			raise RuntimeError("process is already closed")
		return self._process

	def read_output_file(self, extension: str="pdf")->bytes:
		"""
		Read the output file with the given extension.

		This is only reliable when the process has already been terminated. Refer to :meth:`terminate`.

		See :class:`ChildProcessEngine` for an usage example.
		See :class:`~pythonimmediate.multiengine.MultiChildProcessEngine` for another example.
		"""
		return (self.directory/("texput."+extension)).read_bytes()

	def _read_log(self)->bytes:
		return self.read_output_file("log")

	def _print_log(self)->None:
		"""
		For debug purpose only. If the engine is still running there's a chance the log is not flushed when this function is called.
		"""
		print((self._read_log() if self._log is None else self._log).decode('u8', "replace"))

	def _check_no_error(self)->None:
		r"""
		Internal function, check for TeX error.

		>>> from pythonimmediate import execute
		>>> with ChildProcessEngine("luatex") as engine, default_engine.set_engine(engine):
		...		execute(r'\directlua{error("hello")}')
		Traceback (most recent call last):
			...
		pythonimmediate.engine.TeXProcessError: [\directlua]:1: hello

		>>> with ChildProcessEngine("luatex") as engine, default_engine.set_engine(engine):
		...		(engine.directory/"a.lua").write_text('error("hello")')
		...		execute(r'\directlua{dofile("a.lua")}')
		Traceback (most recent call last):
			...
		pythonimmediate.engine.TeXProcessError: a.lua:1: hello

		>>> with ChildProcessEngine("luatex") as engine, default_engine.set_engine(engine):
		...		execute(r'\directlua{do)}')
		Traceback (most recent call last):
			...
		pythonimmediate.engine.TeXProcessError: [\directlua]:1: unexpected symbol near ')'.

		>>> execute(r'\loop\begingroup\iftrue\repeat')
		Traceback (most recent call last):
			...
		pythonimmediate.engine.TeXProcessError: TeX capacity exceeded, sorry [grouping levels=255].

		>>> execute(r'a')
		Traceback (most recent call last):
			...
		pythonimmediate.engine.TeXProcessError: LaTeX Error: Missing \begin{document}.
		"""
		if self.status==EngineStatus.error:
			self._log=self._read_log()
			log_lines=self._log.splitlines()

			self.terminate()
			if self._autorestart:
				self._start_process()

			error_lines=[line for i, line in enumerate(log_lines)
			 if line.startswith(b"!") or
			 (i+1<len(log_lines) and log_lines[i+1]==b"stack traceback:") or  # Lua error
			 (line.startswith(br"[\directlua]:"))  # Lua error at the very-top level, there will be no stack traceback
			 ]

			# find the line right before the last "emergency stop" line in error_lines:
			emergency_stop_lines=[i for i, line in enumerate(error_lines) if line==b'! Emergency stop.']
			if not emergency_stop_lines:
				emergency_stop_lines=[i for i, line in enumerate(error_lines) if line==b'!  ==> Fatal error occurred, no output PDF file produced!']
			if not emergency_stop_lines or emergency_stop_lines[-1]==0:
				raise TeXProcessError("TeX error")  # cannot find the error message
			raise TeXProcessError(
					error_lines[emergency_stop_lines[-1]-1].removeprefix(b"!").lstrip()
					.decode('u8', "replace"))

	def _read(self)->bytes:
		process=self.get_process()
		assert process.stderr is not None
		self._check_no_error()
		line=process.stderr.readline()
		if not line:
			process.wait(timeout=_DEFAULT_TIMEOUT)
			self.terminate()
			self._check_no_error()  # it is important that this is done after terminate(),
			# because _stdout_thread is the one responsible for setting error status
			if self._autorestart:
				self._start_process()
			raise TeXProcessExited
		return line

	def _write(self, s: bytes)->None:
		process=self.get_process()
		assert process.stdin is not None
		self._check_no_error()
		process.stdin.write(s)
		process.stdin.flush()

	def _close(self)->None:
		# this might be called from :meth:`__del__` so do not import anything here
		self.terminate()
		self._directory.cleanup()

	_EngineStatus=EngineStatus

	def terminate(self)->None:
		r"""
		Terminate the current process.

		This must be used in place of :meth:`~Engine.close` in order to stop the process but still keep the generated files.

		See :class:`ChildProcessEngine` for an usage example.

		Similar to ``file.close``, ``subprocess.Popen.wait`` or ``subprocess.Popen.kill``,
		this method does nothing if the process is already terminated.

		>>> from pythonimmediate import execute
		>>> with ChildProcessEngine("pdftex") as engine, default_engine.set_engine(engine):
		...		execute(r'\typeout{123}')
		...		engine.terminate()
		...		engine.terminate()
		...		engine.close()
		>>> engine.terminate()
		>>> engine.close()
		>>> engine.close()
		"""
		if self._process is None: return
		process=self.get_process()
		assert process.stdin is not None
		assert process.stderr is not None

		# we need to use self._EngineStatus instead of EngineStatusbecause when :meth:`__del__` is called the objects might already be torn down
		# only _stdout_thread can possibly set status to error, so we just need to wait for _stdout_thread
		if self.status==self._EngineStatus.error:
			self._stdout_thread.join()

		if not process.poll():
			# process has not terminated (it's possible for process to already terminate if it's killed on error)
			if (
					self.status==self._EngineStatus.waiting
					and pythonimmediate is not None and pythonimmediate.run_none_finish is not None  # this may fail when the Python process exits
					):
				with default_engine.set_engine(self):
					pythonimmediate.run_none_finish()
			else:
				process.kill()
			process.wait(timeout=_DEFAULT_TIMEOUT)

		# we must not close stdin here, let _stdout_thread do it
		# because otherwise the "? " may overrun (rare race condition) (I guess)
		process.stderr.close()
		self._stdout_thread.join()  # _stdout_thread will automatically terminate once process.stderr is no longer readable

		if self.status!=self._EngineStatus.error:
			self.status=self._EngineStatus.exited

		self._process=None

	def __del__(self)->None:
		self.close()

	def __enter__(self)->ChildProcessEngine:
		return self

	def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any)->None:
		self.close()

