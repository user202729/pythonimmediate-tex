"""
Classes to facilitate communication between this process and the pytotex half.
"""

from abc import ABC, abstractmethod
import typing
import sys
from typing import List, Any, Optional


class Communicator(ABC):
	character = typing.cast(str, None)

	def send(self, data: bytes)->None:
		raise NotImplementedError

	@staticmethod
	@abstractmethod
	def forward()->None:
		"""
		initially the process will print one line to TeX, and then
		TeX will forward that line to the other process to determine the communication method used.

		another process should initialize a Communicator object with that line,
		call `send()` to send data to this process.
		this process will get all the data and print them to stdout.
		"""
		raise NotImplementedError

	@staticmethod
	@abstractmethod
	def is_available()->bool:
		raise NotImplementedError


class MultiprocessingNetworkCommunicator(Communicator):
	character = 'm'

	def __init__(self, s: str)->None:
		self.address=("localhost", int(s))
		from multiprocessing.connection import Client
		self.connection=Client(self.address)

	def send(self, data: bytes)->None:
		self.connection.send_bytes(data)

	@staticmethod
	def forward()->None:
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

		sys.__stdout__.write(f"{MultiprocessingNetworkCommunicator.character}{port}\n")
		sys.__stdout__.flush()

		with listener:
			with listener.accept() as connection:
				while True:
					try:
						data=connection.recv_bytes()
						sys.__stdout__.buffer.write(data)  # will go to TeX
						sys.__stdout__.buffer.flush()
					except EOFError: break

	@staticmethod
	def is_available()->bool:
		return True


class UnnamedPipeCommunicator(Communicator):
	character = 'u'
	
	def __init__(self, s: str)->None:
		pid, w = map(int, s.split(","))
		self.connection=open(f"/proc/{pid}/fd/{w}", "wb")

	def send(self, data: bytes)->None:
		self.connection.write(data)
		self.connection.flush()  # just in case

	@staticmethod
	def forward()->None:
		import os
		r, w = os.pipe()
		sys.stdout.write(f"{UnnamedPipeCommunicator.character}{os.getpid()},{w}\n")
		sys.stdout.flush()

		closed_w=False
		# TODO if the other process never write anything, this will block forever
		for line in os.fdopen(r, "rb"):
			if not closed_w:
				os.close(w)  # so that the loop will end when the other process closes the pipe
				closed_w=True
			sys.stdout.buffer.write(line)
			sys.stdout.buffer.flush()

	@staticmethod
	def is_available()->bool:
		import os
		from pathlib import Path
		return os.name=="posix" and Path("/proc").is_dir()


communicator_classes: List[Any] = [MultiprocessingNetworkCommunicator, UnnamedPipeCommunicator]
first_char_to_communicator = {c.character: c for c in communicator_classes}
assert len(first_char_to_communicator) == len(communicator_classes)
assert all(len(c)==1 for c in first_char_to_communicator)


def create_communicator(s: str)->Communicator:
	return first_char_to_communicator[s[0]](s[1:])
