from __future__ import annotations
import traceback
import os
import sys


def main():
	from .engine import ParentProcessEngine
	from . import PTTBlock, PTTVerbatimLine, run_error_finish, default_engine, send_bootstrap_code, run_main_loop

	try:
		engine=ParentProcessEngine()
		default_engine.set_engine(engine)
		send_bootstrap_code(engine=engine)
		run_main_loop(engine=engine)  # if this returns cleanly TeX has no error. Otherwise some readline() will reach eof and print out a stack trace
		assert not engine._read(), "Internal error: TeX sends extra line"

	except:
		# see also documentation of run_error_finish.
		sys.stderr.write("\n")
		traceback.print_exc(file=sys.stderr)

		engine.action_done=False  # force run it

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

		run_error_finish(PTTBlock(full_error), PTTBlock(short_error), engine)
		os._exit(0)


if __name__=="__main__":
	main()
