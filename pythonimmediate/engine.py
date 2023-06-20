"""
Abstract engine class.
"""

from typing import Optional, Literal, Iterable, List, Dict, Tuple
from abc import ABC, abstractmethod
import sys
import subprocess
import threading
from dataclasses import dataclass
import atexit
import enum
from pathlib import Path
import tempfile

from . import communicate
from .communicate import GlobalConfiguration


EngineName=Literal["pdftex", "xetex", "luatex"]
engine_names: Tuple[EngineName, ...]=EngineName.__args__  # type: ignore


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


class Engine(ABC):
	_name: EngineName
	_config: GlobalConfiguration
	status: EngineStatus

	def __init__(self):
		self._config=GlobalConfiguration()  # dummy value
		self.status=EngineStatus.waiting

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
			result=self._read()
			if result.rstrip()!=b"pythonimmediate-naive-flush-line":
				break
			else:
				# ignore this line
				assert self.config.naive_flush
		if self.status==EngineStatus.error: raise RuntimeError("TeX error!")
		return result[:-1]

	def write(self, s: bytes)->None:
		if self.status==EngineStatus.error: raise RuntimeError("TeX error!")
		assert self.status==EngineStatus.waiting, self.status
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


def debug_possibly_shorten(line: str)->str:
	if len(line)>=100:
		return line[:100]+"..."
	return line


class ParentProcessEngine(Engine):
	"""
	Represent the engine if this process is started by the [TeX]'s pythonimmediate library.

	This should not be instantiated directly. Only :func:`pythonimmediate.textopy.main` should instantiate this.
	"""
	_logged_communication: bytearray
	def _log_communication(self, s: bytes)->None:
		self._logged_communication += s

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
			import os
			r, w=os.pipe()
			self.input_file=os.fdopen(r, "rb")

			# create a daemon thread to copy the data from stdin to the pipe, by 4096-byte blocks.
			def f()->None:
				buffer=bytearray()
				while True:
					data=sys.__stdin__.buffer.readline()
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

		sys.stdin=None  # type: ignore
		# avoid user mistakenly read

		if self.config.debug_log_communication is not None:
			print(f"[All communications will be logged to {self.config.debug_log_communication}]", flush=True)
			debug_log_communication = self.config.debug_log_communication
			self._logged_communication = bytearray()
			def write_communication_log()->None:
				debug_log_communication.write_bytes(b"Communication log ['>': TeX to Python - include i/r distinction, '<': Python to TeX]:\n" + self._logged_communication)
			atexit.register(write_communication_log)

		from . import surround_delimiter, substitute_private, get_bootstrap_code
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
		if self.config.debug_log_communication is not None and line:
			assert line.endswith(b'\n') and line.count(b'\n')==1, line
			self._log_communication(b">"+line)
		return line

	def _write(self, s: bytes)->None:
		self.config.communicator.send(s)
		if self.config.debug_log_communication is not None and s:
			lines=s.split(b'\n')
			for line in lines[:-1]: self._log_communication(b"<"+line+b'\n')
			if lines[-1]: self._log_communication(b"<"+lines[-1]+b"...\n")


@dataclass
class _SetDefaultEngineContextManager:
	"""
	Context manager, used in conjunction with default_engine.set_engine(...) to revert to the original engine.
	"""
	old_engine: Optional[Engine]
	new_engine: Optional[Engine]
	entered: bool=False

	def __enter__(self)->Optional[Engine]:
		assert not self.entered, "This context manager is not re-entrant!"
		self.entered=True
		return self.new_engine

	def __exit__(self, exc_type, exc_val, exc_tb)->None:
		default_engine.set_engine(self.old_engine)


class DefaultEngine(Engine, threading.local):
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
		#super().__init__()
		self.engine: Optional[Engine]=None
		"""
		Stores the engine being set internally.

		Normally there's no reason to access the internal engine directly, as ``self`` can be used
		like the engine inside.
		"""

	def set_engine(self, engine: Optional[Engine])->_SetDefaultEngineContextManager:
		"""
		Set the default engine to another engine.

		Can also be used as a context manager to revert to the original engine.
		Example::

			with default_engine.set_engine(new_engine) as engine:  # only for this thread
				assert engine is new_engine
				execute("hello world")
			# now the original engine is restored
		"""
		assert engine is not self
		result=_SetDefaultEngineContextManager(old_engine=self.engine, new_engine=engine)
		self.engine=engine
		return result

	def get_engine(self)->Engine:
		"""
		Convenience helper function, return the engine.

		All the other functions that use this one (those that make use of the engine) will raise RuntimeError
		if the engine is None.
		"""
		if self.engine is None:
			raise RuntimeError("Default engine not set for this thread!")
		return self.engine

	# temporary hack ><
	@property
	def status(self)->EngineStatus:
		return self.get_engine().status

	@status.setter
	def status(self, value: EngineStatus)->None:
		self.get_engine().status=value

	@property
	def name(self)->EngineName:
		return self.get_engine().name

	@property
	def config(self)->GlobalConfiguration:
		return self.get_engine().config

	@config.setter
	def config(self, value: GlobalConfiguration)->None:
		raise NotImplementedError

	def _read(self)->bytes:
		line=self.get_engine()._read()
		return line

	def _write(self, s: bytes)->None:
		self.get_engine()._write(s)


default_engine=DefaultEngine()
"""
A constant that can be used to avoid passing explicit ``engine`` argument to functions.

See documentation of :class:`DefaultEngine` for more details.

For Python running inside a [TeX] process, useful attributes are :attr:`~Engine.name` and :attr:`~Engine.is_unicode`.
"""



class TeXProcessError(RuntimeError): pass

class ChildProcessEngine(Engine):
	r"""
	An object that represents a [TeX] engine that runs as a subprocess of this process.

	Can be used as a context manager to automatically close the subprocess when the context is exited. Alternatively :meth:`close` can be used to manually terminate the subprocess.

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

	Note that explicit ``engine`` argument must be passed in most functions.
	See :class:`DefaultEngine` for a way to bypass that.

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

	:param args: List of additional arguments to be passed to the executable, such as ``--recorder`` etc.
	:param env: See documentation of *env* argument in ``subprocess.Popen``.
		Note that it's usually recommended to append environment variables that should be set to
		``os.environ`` instead of replacing it entirely.
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

	def __init__(self, engine_name: EngineName, args: Iterable[str]=(), env=None, autorestart: bool=False)->None:
		super().__init__()
		self._name=engine_name
		self._args=args
		self._env=env
		self._autorestart=autorestart

		self._create_directory()
		"""
		A temporary working directory for the engine.
		"""

		self.process: Optional[subprocess.Popen]=None  # guard like this so that __del__ does not blow up if Popen() fails
		self._start_process()

	def _create_directory(self)->None:
		self._directory: tempfile.TemporaryDirectory=tempfile.TemporaryDirectory(prefix="pyimm-", ignore_cleanup_errors=True)
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

		assert self.process is None
		if not self.directory.is_dir(): self._create_directory()
		self.status=EngineStatus.waiting
		self.process=subprocess.Popen(
				[
					engine_name_to_latex_executable[self._name], "--shell-escape",
						*self._args, r"\RequirePackage[child-process]{pythonimmediate}\pythonimmediatelisten\stop"],
				stdin=subprocess.PIPE,
				stdout=subprocess.PIPE,
				stderr=subprocess.PIPE,
				cwd=self.directory,
				env=self._env,
				start_new_session=True,  # avoid ctrl-C propagating to TeX process (when used in interactive terminal the TeX process should not be killed on ctrl-C)
				)


		# create thread listen for stdout
		self._stdout_thread=threading.Thread(target=self._stdout_thread_func, daemon=True)
		self._stdout_thread.start()

		from . import surround_delimiter, substitute_private, get_bootstrap_code
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
		if not self.process:
			return f"<{s} closed>"
		return s

	def _stdout_thread_func(self)->None:
		assert self.process is not None
		assert self.process.stdin is not None
		assert self.process.stdout is not None

		self._error_marker_line_seen: bool=False
		self._stdout_lines: List[bytes]=[]  # Note that this is asynchronously populated so values may not be always correct
		self._stdout_buffer=bytearray()  # remaining part that does not fit in any line

		while True:
			line: bytes=self.process.stdout.read1()  # type: ignore
			if not line: break

			self._stdout_buffer+=line

			if b"\n" in line:
				# add complete lines to self._stdout_lines and update self._error_marker_line_seen
				parts = self._stdout_buffer.split(b"\n")
				self._stdout_lines+=map(bytes, parts[:-1])
				self._error_marker_line_seen=self._error_marker_line_seen or any(line.startswith(b"<*> ") for line in parts[:-1])
				self._stdout_buffer=parts[-1]
				if b'!  ==> Fatal error occurred, no output PDF file produced!' in parts[:-1]:
					self.status=EngineStatus.error
					self.process.wait()

			# check potential error
			if self._stdout_buffer == b"? " and self._error_marker_line_seen:
				self.status=EngineStatus.error
				self.process.stdin.close()  # close the stdin so process will terminate
				self.process.wait()
				# this is a simple way to break out _read() but it will not allow error recovery

			# debug logging
			#sys.stderr.write(f" | {self._stdout_lines=} | {self._stdout_buffer=} | {self._error_marker_line_seen=} | {self.status=}\n")

	def get_process(self)->subprocess.Popen:
		if self.process is None:
			raise RuntimeError("process is already closed")
		return self.process

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

		>>> with ChildProcessEngine("pdftex") as engine, default_engine.set_engine(engine):
		...		execute(r'\loop\begingroup\iftrue\repeat')
		Traceback (most recent call last):
			...
		pythonimmediate.engine.TeXProcessError: TeX capacity exceeded, sorry [grouping levels=255].
		"""
		if self.status==EngineStatus.error:
			log_lines=(self.directory/"texput.log").read_bytes().splitlines()

			self.close()
			if self._autorestart:
				self._start_process()

			error_lines=[line for i, line in enumerate(log_lines)
			 if line.startswith(b"!") or
			 (i+1<len(log_lines) and log_lines[i+1]==b"stack traceback:")  # Lua error
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
		self._check_no_error()
		return line

	def _write(self, s: bytes)->None:
		process=self.get_process()
		assert process.stdin is not None
		self._check_no_error()
		#print("writing", s)
		process.stdin.write(s)
		process.stdin.flush()

	def close(self)->None:
		"""
		Terminates the [TeX] subprocess gracefully.
		"""
		# this might be called from :meth:`__del__` so do not import anything here
		process=self.get_process()
		assert process.stdin is not None
		assert process.stderr is not None
		if self.status==EngineStatus.error:
			# only _stdout_thread can possibly set status to error, so we just need to wait for _stdout_thread
			self._stdout_thread.join()
		if not process.poll():
			# process has not terminated (it's possible for process to already terminate if it's killed on error)
			from . import run_none_finish
			with default_engine.set_engine(self):
				run_none_finish()
			process.wait()
		process.stdin.close()
		process.stderr.close()
		self._stdout_thread.join()  # _stdout_thread will automatically terminate once process.stderr is no longer readable
		self.process=None
		self._directory.cleanup()

	def __del__(self)->None:
		if self.process is not None:
			self.close()

	def __enter__(self)->Engine:
		return self

	def __exit__(self, exc_type, exc_val, exc_tb)->None:
		if self.process is not None:
			self.close()


