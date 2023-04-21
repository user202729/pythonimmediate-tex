import subprocess
import tempfile
from typing import List

import pytest

import pythonimmediate
from pythonimmediate.engine import ChildProcessEngine, default_engine, engine_names, engine_name_to_latex_executable, EngineName
from pythonimmediate import TokenList, ControlSequenceToken, BalancedTokenList
from pythonimmediate import Catcode as C

T=ControlSequenceToken.make


from pathlib import Path
for name in ["test_pythonimmediate.tex", "helper_file.py"]:
	a=Path("/tmp")/name
	a.unlink(missing_ok=True)
	a.symlink_to(Path(__file__).parent.parent/"tex"/"test"/name)


class Test:
	@pytest.mark.parametrize("engine_name", engine_names)
	def test_child_process_engine(self, engine_name: EngineName)->None:
		engine=ChildProcessEngine(engine_name)

		with default_engine.set_engine(engine):
			s='Æ²×⁴ℝ𝕏'
			pythonimmediate.simple.execute(r'\edef\testa{\detokenize{' + s + '}}')
			assert BalancedTokenList([T.testa]).expand_o().str(engine=engine) == s

			TokenList([T["def"], T.testa, TokenList.doc("123")]).execute()
			assert TokenList([T.testa]).expand_x().str_if_unicode() == "123"

		assert default_engine.engine is None

		with pytest.raises(RuntimeError):
			TokenList([T["def"], T.testa, TokenList.doc("789")]).execute()

		with ChildProcessEngine("pdftex") as new_engine:
			TokenList([T["def"], T.testa, TokenList.doc("456")]).execute(engine=new_engine)
			assert TokenList([T.testa]).expand_x(engine=engine).str_if_unicode() == "123"
			assert TokenList([T.testa]).expand_x(engine=new_engine).str_if_unicode() == "456"

	@pytest.mark.skip
	@pytest.mark.parametrize("engine_name", engine_names)
	def test_child_process_engine_2(self, engine_name: EngineName)->None:
		engine=ChildProcessEngine(engine_name)
		with default_engine.set_engine(engine):
			with pytest.raises(RuntimeError):
				BalancedTokenList([C.other(10)]).execute()


	@pytest.mark.parametrize("engine_name", engine_names)
	@pytest.mark.parametrize("communication_method", ["unnamed-pipe", "multiprocessing-network"])
	@pytest.mark.parametrize("use_8bit", [True, False])
	def test_subprocess(self, engine_name: EngineName, communication_method: str, use_8bit: bool)->None:
		subprocess.run(
				[engine_name_to_latex_executable[engine_name], "-shell-escape", *(
					["-8bit"] if use_8bit else []
					), r"\def\specifymode{"+communication_method+r"}\input{/tmp/test_pythonimmediate.tex}"],
				check=True,
				cwd=tempfile.gettempdir(),
				)

	@pytest.mark.parametrize("engine_name", engine_names)
	def test_nonstopmode_subprocess(self, engine_name: EngineName)->None:
		# https://github.com/user202729/pythonimmediate-tex/issues/1
		process=subprocess.run(
				[
					engine_name_to_latex_executable[engine_name], "-shell-escape", "-interaction=nonstopmode",
					r'\documentclass{article}\usepackage{pythonimmediate}\py{1/0}\py{print(1)}\begin{document}\end{document}',
					],
				check=False,
				cwd=tempfile.gettempdir(),
				stdout=subprocess.PIPE,
				)
		content=process.stdout
		assert process.returncode == 1
		assert b"ZeroDivisionError" in content
		assert b"Transcript written on" in content

	def test_python_flags(self):
		"""
		pass -O to the Python executable and check if assertions are disabled
		"""
		with pytest.raises(subprocess.CalledProcessError):
			subprocess.run(
					["pdflatex", "-shell-escape", r"\RequirePackage{pythonimmediate}\pyc{assert False}\stop"],
					check=True,
					cwd=tempfile.gettempdir(),
					)

		# but this does not raise anything
		subprocess.run(
				["pdflatex", "-shell-escape", r"\RequirePackage[python-flags=-O]{pythonimmediate}\pyc{assert False}\stop"],
				check=True,
				cwd=tempfile.gettempdir(),
				)

	def test_set_globals_locals(self):
		def f():
			f_var = 1
			g()

		def g():
			g_var = 2
			h()

		def h():
			h_var = 3
			i()

		def i():
			g, l = pythonimmediate.simple.set_globals_locals(None, None)
			assert "f_var" not in l
			assert "g_var" not in l
			assert l["h_var"] == 3

		f()

		def h():
			h_var = 4
			x = 5
			[list(i() for x in range(1)) for y in range(1, 2)]

		def i():
			g, l = pythonimmediate.simple.set_globals_locals(None, None)
			assert "f_var" not in l
			assert "g_var" not in l
			assert l["h_var"] == 4
			assert l["x"] == 0
			assert l["y"] == 1

		f()

	def test_f1(self):
		from pythonimmediate.simple import f1
		def f():
		    k = 1
		    return [f"j={j}, k={k}" for j in range(5)]
		assert f() == ['j=0, k=1', 'j=1, k=1', 'j=2, k=1', 'j=3, k=1', 'j=4, k=1']

		def f():
		    k = 1
		    return [f1("j=`j`, k=`k`") for j in range(5)]
		assert f() == ['j=0, k=1', 'j=1, k=1', 'j=2, k=1', 'j=3, k=1', 'j=4, k=1']
