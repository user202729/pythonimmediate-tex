from __future__ import annotations

"""
Classes to facilitate communication between this process and the pytotex half.
"""

from abc import ABC, abstractmethod
import typing
import sys
from typing import List, Any, Optional, Dict, Type, TypeVar, IO, Callable
import dataclasses
from dataclasses import dataclass
from io import StringIO
import argparse
from pathlib import Path
from multiprocessing.connection import Client, Connection


char_to_communicator: Dict[str, Type[Communicator]]={}

T1=TypeVar("T1", bound="Communicator")

ListenForwarder=Callable[[], None]  # function that listens to data sent by a communicator and forward them to stdout

class Communicator(ABC):
	character = typing.cast(str, None)

	@abstractmethod
	def send(self, data: bytes)->None:
		"""
		Send data. This function is called in the textopy part.
		"""
		...

	@staticmethod
	@abstractmethod
	def setup()->tuple[Communicator, ListenForwarder]:
		"""
		Constructs an communicator object, that can be used to send information to this process.

		The Communicator should be sent to the other process as part of the GlobalConfiguration object.

		The ListenForwarder should be called in this process.
		"""
		...

	@staticmethod
	@abstractmethod
	def is_available()->bool: ...


@dataclass
class MultiprocessingNetworkCommunicator(Communicator):
	port: int
	connection: Optional[Connection]=dataclasses.field(default=None, repr=False)

	def send(self, data: bytes)->None:
		if self.connection is None:
			self.address=("localhost", self.port)
			self.connection=Client(self.address)

		self.connection.send_bytes(data)

	@staticmethod
	def setup()->tuple[MultiprocessingNetworkCommunicator, ListenForwarder]:
		from multiprocessing.connection import Listener

		# pick address randomly and create listener with it until it succeeds
		import socket
		import random
		while True:
			try:
				port = random.randint(1024, 65535)
				address=("localhost", port)
				listener=Listener(address)
				break
			except socket.error:
				pass

		def listen_forwarder()->None:
			with listener:
				with listener.accept() as connection:
					assert sys.__stdout__ is not None
					while True:
						try:
							data=connection.recv_bytes()
							sys.__stdout__.buffer.write(data)  # will go to TeX
							sys.__stdout__.buffer.flush()
						except EOFError: break

		return MultiprocessingNetworkCommunicator(port), listen_forwarder

	@staticmethod
	def is_available()->bool:
		return True


@dataclass
class UnnamedPipeCommunicator(Communicator):
	pid: int
	fileno: int
	connection: Optional[IO[bytes]]=dataclasses.field(default=None, repr=False)

	def send(self, data: bytes)->None:
		if self.connection is None:
			self.connection=open(f"/proc/{self.pid}/fd/{self.fileno}", "wb")

		self.connection.write(data)
		self.connection.flush()  # just in case

	@staticmethod
	def setup()->tuple[UnnamedPipeCommunicator, ListenForwarder]:
		import os
		r, w = os.pipe()

		def listen_forwarder()->None:
			closed_w=False
			# TODO if the other process never write anything, this will block forever
			for line in os.fdopen(r, "rb"):
				if not closed_w:
					os.close(w)  # so that the loop will end when the other process closes the pipe
					closed_w=True
				sys.stdout.buffer.write(line)
				sys.stdout.buffer.flush()

		return UnnamedPipeCommunicator(os.getpid(), w), listen_forwarder

	@staticmethod
	def is_available()->bool:
		import os
		from pathlib import Path
		return os.name=="posix" and Path("/proc").is_dir()


@dataclass
class GlobalConfiguration:
	"""
	Represents the configuration.

	This will be parsed from command-line argument in pytotex
	using :meth:`from_args`, then sent
	to textopy side (which is where most of the processing is done)
	with a base64 of pickle encoding,
	on the textopy side a pseudo-config is created from the passed command-line arguments,
	then the real config is read in :class:`.ParentProcessEngine`'s constructor.

	Which means it's preferable to avoid any mutable state in the configuration object.
	"""
	debug: int=0
	communicator: Communicator=typing.cast(Communicator, None)
	sanity_check_extra_line: bool=False
	debug_force_buffered: bool=False
	debug_log_communication: Optional[str]=None
	naive_flush: bool=False

	def __post_init__(self)->None:
		assert -9<=self.debug<=9

	@staticmethod
	def from_args(args: argparse.Namespace, communicator: Communicator)->GlobalConfiguration:
		return GlobalConfiguration(
				debug=args.debug,
				communicator=communicator,
				sanity_check_extra_line=args.sanity_check_extra_line,
				debug_force_buffered=args.debug_force_buffered,
				debug_log_communication=args.debug_log_communication,
				naive_flush=args.naive_flush,
				)
