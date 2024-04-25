"""
Receive things that should be passed to [TeX] from [TeX]-to-Py half (:mod:`pythonimmediate.textopy`),
then pass to [TeX].

User code are not executed here.

**For Python-inside-[TeX] only** (does not apply to :class:`~pythonimmediate.engine.ChildProcessEngine`):
Anything that is put in ``pythonimmediatedebugextraargs`` environment variable
will be appended to the command-line arguments. For example you could invoke [TeX] with
``pythonimmediatedebugextraargs='--debug-log-communication=/tmp/a.diff --debug=5' pdflatex test.tex``
to enable debugging facilities.

Side note ``--debug-log-communication`` also accept a ``$pid`` placeholder.
That is, if you pass ``--debug-log-communication=/tmp/a-$pid.diff``, then the ``$pid`` will be replaced
with the process ID.
This is useful if you want to run multiple [TeX] processes at the same time and want to log them separately.

Supported command-line arguments:

.. argparse::
   :module: pythonimmediate.pytotex
   :func: get_parser
   :prog: pytotex

"""

from __future__ import annotations

import sys
import signal
import argparse
from typing import Type
from pathlib import Path
import os
import shlex

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
	parser.add_argument("--debug-log-communication", type=str, default=None,
					 help="Debug mode, log all communications. Pass the output path. "
					 "For example you may want to specify ``--debug-log-communication=/tmp/a.diff`` to log all communication to ``a.diff`` file "
					 "(because the lines are prefixed with ``<`` and ``>``, diff syntax highlighting works nicely with it). "
					 "Placeholder ``$pid`` is supported.")
	parser.add_argument("--debug-force-buffered", action="store_true",
					 help="""Debug mode, simulate [TeX] writes being 4096-byte buffered. Don't use.

					 "This may raise the error message
					 ``Fatal Python error: could not acquire lock for <_io.BufferedReader name='<stdin>'> at interpreter shutdown, possibly due to daemon threads``
					 because of how it's implemented (a daemon thread read from stdin and forward to a pipe), but this feature is only
					 used for debugging anyway so it does not matter.
					 """)
	parser.add_argument("--naive-flush", action="store_true",
					 help="Naively flush stdout by writing 4096 bytes to it when needed. "
					 "Required in some [TeX] distribution that does not flush output.")
	return parser

def parse_args()->argparse.Namespace:
	return get_parser().parse_args(sys.argv[1:] + shlex.split(os.environ.get("pythonimmediatedebugextraargs", "")))

if __name__ == "__main__":
	signal.signal(signal.SIGINT, signal.SIG_IGN)  # when the other half terminates this one will terminates "gracefully"

	#debug_file=open(Path(tempfile.gettempdir())/"pythonimmediate_debug_pytotex.txt", "w", encoding='u8', buffering=2)
	#debug=functools.partial(print, file=debug_file, flush=True)
	debug=lambda *args, **kwargs: None

	args=parse_args()

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
	if config.naive_flush:
		# append dots (note that dot is not used in base64 encoding) until the length is a multiple of 4096
		# so after the final newline is added, it will be one more than a multiple of 4096 and the line (minus the final newline) will be flushed

		# there must be a nonzero number of dots appended to specify where the actual base64 content ends

		# (note that spaces being appended will not be noticed by TeX so we cannot use spaces)
		config_str=config_str.ljust((len(config_str)//4096+1)*4096, ".")
	config_str+="\n"

	sys.stdout.write(config_str)
	sys.stdout.flush()

	listen_forwarder()
