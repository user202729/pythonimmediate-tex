from __future__ import annotations
import traceback
import os
import sys
import typing


def main()->None:
	"""
	This side does not receive the user-provided arguments directly, instead some parts of the configuration is decided by the pytotex side
	and forwarded to this half.

	The arguments are re-parsed here anyway to provide a "temporary" configuration for the engine to work with before getting the real configuration.
	"""
	from .engine import ParentProcessEngine
	from . import PTTBlock, PTTVerbatimLine, run_error_finish, default_engine, surround_delimiter, substitute_private, get_bootstrap_code, run_main_loop
	from .pytotex import parse_args
	from .communicate import GlobalConfiguration, Communicator

	args=parse_args()
	pseudo_config=GlobalConfiguration.from_args(args, typing.cast(Communicator, None))

	engine=ParentProcessEngine(pseudo_config)

	with default_engine.set_engine(engine):
		try:
			engine.write(surround_delimiter(substitute_private(get_bootstrap_code(engine))).encode('u8'))
			run_main_loop()  # if this returns cleanly TeX has no error. Otherwise some readline() will reach eof and print out a stack trace
			if engine.config.sanity_check_extra_line:
				assert not engine._read(), "Internal error: TeX sends extra line"

		except:
			# see also documentation of run_error_finish.
			sys.stderr.write("\n")
			traceback.print_exc(file=sys.stderr)

			full_error = "".join(traceback.format_exc())  # to be printed on TeX's log file

			# the short_error will be printed on the terminal, so make sure it's not too long.

			type_, value, tb = sys.exc_info()

			short_error = "".join(
					traceback.format_exception_only(type_, value) +
					["--\n"] +
					traceback.format_tb(tb, limit=-1)
					).strip()

			# force limit the line width of the error message
			import textwrap
			short_error="\n".join(
					wrapped_line
					for paragraph in short_error.splitlines()
					for wrapped_line in textwrap.wrap(paragraph, width=40)
					)

			run_error_finish(PTTBlock(full_error), PTTBlock(short_error))


if __name__=="__main__":
	main()
