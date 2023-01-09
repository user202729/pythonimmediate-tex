import traceback
import os
import sys


def main():
	from .engine import ParentProcessEngine
	from . import PTTBlock, run_error_finish, default_engine, send_bootstrap_code, run_main_loop

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
		run_error_finish(PTTBlock("".join(traceback.format_exc())), engine)

		os._exit(0)


if __name__=="__main__":
	main()
