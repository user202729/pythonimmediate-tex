import contextlib
from abc import ABC, abstractmethod
from dataclasses import dataclass
import types

from .engine import Engine, ChildProcessEngine, default_engine

class EngineAction(ABC):
	@abstractmethod
	def __call__(self, engine: ChildProcessEngine)->None: ...

@dataclass
class ReadAction(EngineAction):
	line: bytes
	def __call__(self, engine: ChildProcessEngine)->None:
		line1=engine._read()
		assert line1==self.line, (line1, self.line)

@dataclass
class WriteAction(EngineAction):
	line: bytes
	def __call__(self, engine: ChildProcessEngine)->None:
		engine._write(self.line)

class MultiChildProcessEngine(Engine):
	r"""
	An engine that can be used to run multiple identical child processes.
	This is useful for terminating one in order to observe its output.

	.. warning::
		There must be no randomization in the child process.

	Example:

	>>> from pythonimmediate.util import pdftotext
	>>> from pythonimmediate import execute, default_engine
	>>> with MultiChildProcessEngine(2, "pdftex") as engine, default_engine.set_engine(engine):
	... 	execute(r"\documentclass{article} \pagenumbering{gobble} \begin{document} \begin{center} Hello")
	... 	with engine.extract_one() as child1:
	... 		execute(r"\end{center} \end{document}", expecting_exit=True) # only execute on child1
	... 		output1=child1.read_output_file()
	... 	execute(r"world")
	... 	with engine.extract_one() as child2:
	... 		execute(r"\end{center} \end{document}", expecting_exit=True)
	... 		output2=child2.read_output_file()
	>>> pdftotext(output1, ["-nopgbrk"]).strip()
	b'Hello'
	>>> pdftotext(output2, ["-nopgbrk"]).strip()
	b'Hello world'

	Basically you need to:

	* Start an engine. See explanation of parameters below.
	* Note that it is mandatory to call :meth:`__enter__`.
	* Execute commands on the engine.
	* In other to observe the output, use :meth:`extract_one`.

	:param count: the number of child processes to start by at initialization.
		You can start more or less later with :meth:`start_child_process`
		and :meth:`extract_one`.
	:param args: arguments to pass to the child process constructor.
		Refer to :class:`~pythonimmediate.engine.ChildProcessEngine`.
	"""

	def __init__(self, count: int=2, *args, **kwargs):
		super().__init__()
		self._child_process_args=args
		self._child_process_kwargs=kwargs
		self._init_count=count

	def __enter__(self)->"MultiChildProcessEngine":
		self._in_transient_context=False
		self._action_log: list[EngineAction]=[]
		self.child_processes: list[ChildProcessEngine]=[]
		for __ in range(self._init_count):
			self.start_child_process()
		return self

	def __exit__(self, exc_type: type, exc_value: Exception, tb: types.TracebackType)->bool:
		self.close()

	def _close(self)->None:
		stack=contextlib.ExitStack()
		with stack:
			for child_process in self.child_processes:
				stack.push(child_process.__exit__)
		del self._action_log
		del self.child_processes
		del self._in_transient_context

	@contextlib.contextmanager
	def transient_context(self):
		"""
		A context that can be used to mark the code being executed as transient.
		
		This is useful to reduce overhead of restarting the engine when the code
		does not mutate the state of the engine.

		The actual explanation is a bit complicated, and depends on the implementation detail.
		When a child process is restarted, everything is replayed from the beginning.

		>>> from pythonimmediate import T, execute, default_engine
		>>> with MultiChildProcessEngine(2, "pdftex") as engine, default_engine.set_engine(engine):
		... 	T.l_tmpa_tl.str("Hello world") # mutates the state, cannot be put in transient context
		... 	with engine.transient_context():
		...			T.l_tmpa_tl.str() # does not mutate the state, can be put in transient context
		'Hello world'
		'Hello world'
		"""
		assert not self._in_transient_context
		self._in_transient_context=True
		try: yield
		finally: self._in_transient_context=False

	def _read(self)->bytes:
		line=self.child_processes[0]._read()
		action=ReadAction(line)
		if not self._in_transient_context:
			self._action_log.append(action)
		for child_process in self.child_processes[1:]:
			action(child_process)
		return line

	def _write(self, data: bytes)->None:
		action=WriteAction(data)
		if not self._in_transient_context:
			self._action_log.append(action)
		for child_process in self.child_processes:
			action(child_process)

	@contextlib.contextmanager
	def extract_one(self, do_replace: bool=True)->ChildProcessEngine:
		"""
		Extract one child process from the engine.
		See :class:`MultiChildProcessEngine` for an example.

		:param do_replace: whether to replace the extracted child process with a new one.
		"""
		child_process=self.child_processes.pop()
		if do_replace:
			self.start_child_process()
		try:
			with default_engine.set_engine(child_process):
				yield child_process
		finally:
			child_process.__exit__(None, None, None)

	def start_child_process(self)->None:
		child_process=ChildProcessEngine(*self._child_process_args, **self._child_process_kwargs)
		child_process.__enter__()
		for action in self._action_log:
			action(child_process)
		self._name=child_process._name
		self.child_processes.append(child_process)

__all__=["MultiChildProcessEngine"]
