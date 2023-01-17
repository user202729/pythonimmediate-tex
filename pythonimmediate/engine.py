"""
Abstract engine class.
"""

from typing import Optional, Literal, Iterable, List, Dict, Tuple
from abc import ABC, abstractmethod
import sys
import subprocess
from dataclasses import dataclass

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


class Engine(ABC):
	_name: EngineName
	_config: GlobalConfiguration

	def __init__(self):
		self.action_done=False
		self.exited=False  # once the engine exit, it can't be used anymore.
		self._config=GlobalConfiguration()  # dummy value

	# some helper functions for the communication protocol.
	def check_not_finished(self)->None:
		"""
		Internal function.
		"""
		if self.action_done:
			raise RuntimeError("can only do one action per block!")

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

	def check_not_exited(self, message: str)->None:
		"""
		Internal function.
		"""
		if self.exited:
			raise RuntimeError(message)

	def check_not_exited_before(self)->None:
		"""
		Internal function.
		"""
		self.check_not_exited("TeX error already happened, cannot continue")

	def check_not_exited_after(self)->None:
		"""
		Internal function.
		"""
		self.check_not_exited("TeX error!")

	def read(self)->bytes:
		"""
		Internal function.
		
		Read one line from the engine.

		It must not be EOF otherwise there's an error.

		The returned line does not contain the newline character.
		"""
		self.check_not_exited_before()
		while True:
			result=self._read()
			if result.rstrip()!=b"pythonimmediate-naive-flush-line":
				break
			else:
				# ignore this line
				assert self.config.naive_flush
		self.check_not_exited_after()
		return result[:-1]

	def write(self, s: bytes)->None:
		self.check_not_exited_before()
		self._write(s)
		self.check_not_exited_after()

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
	Represent the engine if this process is started by the TeX's pythonimmediate library.

	This should not be used directly. Only pythonimmediate.main module should use this.
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
		assert isinstance(self._config, GlobalConfiguration)

		sys.stdin=None  # type: ignore
		# avoid user mistakenly read

	def _read(self)->bytes:
		line=self.input_file.readline()
		if self.ignore_first_line:
			self.ignore_first_line=False
			return self._read()

		if self.config.debug>=5: print("TeX → Python: " + debug_possibly_shorten(line.decode('u8')))
		if not line: self.exited=True
		return line

	def _write(self, s: bytes)->None:
		if self.config.debug>=5:
			for line in s.splitlines():
				print("Python → TeX: " + debug_possibly_shorten(line.decode('u8')))
		self.config.communicator.send(s)


@dataclass
class SetDefaultEngineContextManager:
	"""
	Context manager, used in conjunction with default_engine.set_engine(...) to revert to the original engine.
	"""
	old_engine: Optional[Engine]

	def __enter__(self)->None:
		pass

	def __exit__(self, exc_type, exc_val, exc_tb)->None:
		default_engine.set_engine(self.old_engine)


class DefaultEngine(Engine):
	"""
	A convenience class that can be used to avoid passing explicit ``engine`` argument to functions.

	This is not thread-safe.

	Users should not instantiate this class directly. Instead, use :const:`default_engine`.

	Usage example::

		default_engine.set_engine(engine)
		execute("hello world")  # this is executed on engine=engine

	.. seealso::
		:meth:`set_engine`
	"""

	def __init__(self)->None:
		super().__init__()
		self.engine: Optional[Engine]=None
		"""
		Stores the engine being set internally.

		Normally there's no reason to access the internal engine directly, as ``self`` can be used
		like the engine inside.
		"""

	def set_engine(self, engine: Optional[Engine])->SetDefaultEngineContextManager:
		"""
		Set the default engine to another engine.

		Can also be used as a context manager to revert to the original engine.
		Example::

			with default_engine.set_engine(...):
				pass  # do something
			# now the original engine is restored
		"""
		assert engine is not self
		result=SetDefaultEngineContextManager(self.engine)
		self.engine=engine
		return result

	def get_engine(self)->Engine:
		"""
		Convenience helper function, return the engine.

		All the other functions that use this one (those that make use of the engine) will raise RuntimeError
		if the engine is None.
		"""
		if self.engine is None:
			raise RuntimeError("Default engine not set!")
		return self.engine

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
		self.get_engine().write(s)


default_engine=DefaultEngine()
"""
A constant that can be used to avoid passing explicit ``engine`` argument to functions.

See documentation of :class:`DefaultEngine` for more details.

For Python running inside a TeX process, useful attributes are :attr:`~Engine.name` and :attr:`~Engine.is_unicode`.
"""





@dataclass
class ChildProcessEngine(Engine):
	r"""
	An object that represents a [TeX] engine that runs as a subprocess of this process.

	Can be used as a context manager to automatically close the subprocess when the context is exited.

	For example, the following Python code, if run alone, will spawn a [TeX] process and use it to write "Hello world" to a file named ``a.txt`` in the temporary directory::

		from pythonimmediate.engine import ChildProcessEngine
		from pythonimmediate import execute

		with ChildProcessEngine("pdftex") as engine:
			# do something with the engine, for example:
			execute(r'''
			\immediate\openout9=a.txt
			\immediate\write9{Hello world}
			\immediate\closeout9
			''', engine=engine)

		# now the engine is closed.

	Note that explicit ``engine`` argument must be passed in most functions.

	See :class:`DefaultEngine` for a way to bypass that.
	"""

	def __init__(self, engine_name: EngineName, args: Iterable[str]=())->None:
		super().__init__()
		self._name=engine_name

		# old method, tried, does not work, see details in sty file

		# create a sym link from /dev/stderr to /tmp/.tex-stderr
		# because TeX can only write to files that contain a period
		#from pathlib import Path
		import tempfile
		#target=Path(tempfile.gettempdir())/"symlink-to-stderr.txt"
		#try:
		#	target.symlink_to(Path("/dev/stderr"))
		#except FileExistsError:
		#	# we assume nothing maliciously create a file named `.symlink-to-stderr` that is not a symlink to stderr...
		#	pass

		self.process: Optional[subprocess.Popen]=None  # guard like this so that __del__ does not blow up if Popen() fails
		self.process=subprocess.Popen(
				[
					engine_name_to_latex_executable[engine_name], "-shell-escape",
						*args, r"\RequirePackage[child-process]{pythonimmediate}\pythonimmediatechildprocessmainloop\stop"],
				stdin=subprocess.PIPE,
				#stdout=subprocess.PIPE,  # we don't need the stdout
				stdout=subprocess.DEVNULL,
				stderr=subprocess.PIPE,
				cwd=tempfile.gettempdir(),
				)

		from . import surround_delimiter, send_raw, substitute_private, get_bootstrap_code
		send_raw(surround_delimiter(substitute_private(
			get_bootstrap_code(self) + 
			r"""
			\cs_new_eq:NN \pythonimmediatechildprocessmainloop \__read_do_one_command:
			"""
			)), engine=self)

	def get_process(self)->subprocess.Popen:
		if self.process is None:
			raise RuntimeError("process is already closed!")
		return self.process

	def _read(self)->bytes:
		process=self.get_process()
		assert process.stderr is not None
		#print("waiting to read")
		line=process.stderr.readline()
		#print("reading", line)
		return line

	def _write(self, s: bytes)->None:
		process=self.get_process()
		assert process.stdin is not None
		#print("writing", s)
		process.stdin.write(s)
		process.stdin.flush()

	def close(self)->None:
		"""
		sent a ``r`` to the process so TeX exits gracefully.

		this might be called from :meth:`__del__` so do not import anything here.
		"""
		process=self.get_process()
		from . import run_none_finish
		run_none_finish(self)
		process.wait()
		assert process.stdin is not None
		assert process.stderr is not None
		process.stdin.close()
		process.stderr.close()
		self.process=None

	def __del__(self)->None:
		if self.process is not None:
			self.close()

	def __enter__(self)->Engine:
		return self

	def __exit__(self, exc_type, exc_val, exc_tb)->None:
		self.close()


