from __future__ import annotations
"""
Receive things that should be passed to [TeX] from [TeX]-to-Py half (:mod:`pythonimmediate.textopy`),
then pass to [TeX].

User code are not executed here.

Supported command-line arguments:

.. argparse::
   :module: pythonimmediate.pytotex
   :func: get_parser
   :prog: pytotex

"""

import sys
import signal
import argparse
from typing import Type

from .communicate import Communicator, MultiprocessingNetworkCommunicator, UnnamedPipeCommunicator

communicator_by_name: dict[str, Type[Communicator]]={
		"unnamed-pipe": UnnamedPipeCommunicator,
		"multiprocessing-network": MultiprocessingNetworkCommunicator,
		}  # sorted by priority. We prefer unnamed-pipe because it's faster

def get_parser()->argparse.ArgumentParser:
	parser=argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
	parser.add_argument("-m", "--mode", choices=list(communicator_by_name.keys()),
					 help="The mode of communication.\n\n"
					 "Refer to :mod:`pythonimmediate.communicate` for the detail on what each mode mean.")
	parser.add_argument("-d", "--debug", type=int, default=0, help="Debug level. In [0..9].")
	return parser

if __name__ == "__main__":
	signal.signal(signal.SIGINT, signal.SIG_IGN)  # when the other half terminates this one will terminates "gracefully"

	#debug_file=open(Path(tempfile.gettempdir())/"pythonimmediate_debug_pytotex.txt", "w", encoding='u8', buffering=2)
	#debug=functools.partial(print, file=debug_file, flush=True)
	debug=lambda *args, **kwargs: None


	parser=get_parser()
	args=parser.parse_args()

	mode=args.mode
	if mode is None:
		for mode in communicator_by_name:
			if communicator_by_name[mode].is_available():
				break
		else:
			raise RuntimeError("No available mode of communication! (this cannot happen)")

	from .communicate import GlobalConfiguration
	communicator, listen_forwarder=communicator_by_name[mode].setup()
	config=GlobalConfiguration(
			debug=args.debug,
			communicator=communicator
			)

	import pickle
	import base64
	config_str=base64.b64encode(pickle.dumps(config)).decode('ascii')
	assert "\n" not in config_str
	sys.stdout.write(config_str+"\n")
	sys.stdout.flush()

	listen_forwarder()
