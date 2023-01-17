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
	parser.add_argument("--sanity-check-extra-line", action="store_true",
					 help="Sanity check that there's no extra line printed from [TeX] process. "
					 "Should never be necessary unless the package is buggy. "
					 "Might not work on Windows/MikTeX.")
	parser.add_argument("--no-sanity-check-extra-line", dest="sanity_check_extra_line", action="store_false")
	parser.add_argument("--debug-force-buffered", action="store_true",
					 help="Debug mode, simulate [TeX] writes being 4096-byte buffered. Don't use.")
	parser.add_argument("--naive-flush", action="store_true",
					 help="Naively flush stdout by writing 4096 bytes to it when needed. "
					 "Required in some [TeX] distribution that does not flush output.")
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
	config=GlobalConfiguration.from_args(args, communicator)

	import pickle
	import base64
	config_str=base64.b64encode(pickle.dumps(config)).decode('ascii')
	assert "\n" not in config_str
	config_str+="\n"
	if config.naive_flush:
		# prepend spaces until the length is one less than a multiple of 4096
		# (note that spaces being appended will not be noticed by TeX)
		config_str=config_str.rjust((len(config_str)+4096)//4096*4096-1)

	sys.stdout.write(config_str)
	sys.stdout.flush()

	listen_forwarder()
