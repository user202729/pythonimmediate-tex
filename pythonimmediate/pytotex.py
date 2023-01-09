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
		"unnamed-pipe": UnnamedPipeCommunicator,
		"multiprocessing-network": MultiprocessingNetworkCommunicator,
		}  # sorted by priority. We prefer unnamed-pipe because it's faster

def get_parser()->argparse.ArgumentParser:
	parser=argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
	parser.add_argument("-m", "--mode", choices=list(communicator_by_name.keys()),
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

	mode=args.mode
	if mode is None:
		for mode in communicator_by_name:
			if communicator_by_name[mode].is_available():
				break
		else:
			raise RuntimeError("No available mode of communication! (this cannot happen)")

	communicator_by_name[mode].forward()
