"""
Abstract engine class.
"""

from typing import Optional
from abc import ABC, abstractmethod
import sys

class Engine(ABC):
	@property
	@abstractmethod
	def is_unicode(self)->bool: 
		...

	@abstractmethod
	def read(self)->bytes:
		"""
		Read one line from the engine.

		Should return b"⟨line⟩\n" or b"" (if EOF) on each call.
		"""
		...

	@abstractmethod
	def write(self, s: bytes)->None:
		"""
		Write data to the engine.

		Because TeX can only read whole lines s should be newline-terminated.
		"""
		...


class ParentProcessEngine(Engine):
	"""
	Represent the engine if this process is started by the TeX's pythonimmediate library.
	"""
	def __init__(self)->None:
		line=self.read().decode('u8')
		assert line.endswith("\n")

		self._is_unicode={"a": False, "u": True}[line[0]]
		line=line[1:]

		from . import communicate
		self.communicator=communicate.create_communicator(line[:-1])

		sys.stdin=None  # type: ignore
		# avoid user mistakenly read

	@property
	def is_unicode(self)->bool:
		return self._is_unicode

	def read(self)->bytes:
		return sys.__stdin__.buffer.readline()

	def write(self, s: bytes)->None:
		self.communicator.send(s)


class DefaultEngine(Engine):
	def __init__(self)->None:
		self.engine: Optional[Engine]=None

	def set_engine(self, engine: Optional[Engine])->None:
		self.engine=engine

	def get_engine(self)->Engine:
		assert self.engine is not None, "Default engine not set!"
		return self.engine

	@property
	def is_unicode(self)->bool:
		return self.get_engine().is_unicode

	def read(self)->bytes:
		return self.get_engine().read()

	def write(self, s: bytes)->None:
		self.get_engine().write(s)


default_engine=DefaultEngine()
