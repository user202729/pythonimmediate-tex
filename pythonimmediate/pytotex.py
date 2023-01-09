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

from .communicate import MultiprocessingNetworkCommunicator, UnnamedPipeCommunicator

communicator_by_name={
		"multiprocessing-network": MultiprocessingNetworkCommunicator,
		"unnamed-pipe": UnnamedPipeCommunicator,
		}

def get_parser()->argparse.ArgumentParser:
	parser=argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
	parser.add_argument("-m", "--mode", choices=list(communicator_by_name.keys()),
					 required=True,
					 help="The mode of communication.\n\n"
					 "Refer to :mod:`pythonimmediate.communicate` for the detail on what each mode mean.")
	return parser

if __name__ == "__main__":
	signal.signal(signal.SIGINT, signal.SIG_IGN)  # when the other half terminates this one will terminates "gracefully"

	#debug_file=open(Path(tempfile.gettempdir())/"pythonimmediate_debug_pytotex.txt", "w", encoding='u8', buffering=2)
	#debug=functools.partial(print, file=debug_file, flush=True)
	debug=lambda *args, **kwargs: None


	parser=get_parser()
	args=parser.parse_args()

	communicator_by_name[args.mode].forward()
