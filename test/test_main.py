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
for name in ["test_pythonimmediate.tex", "test_pythonimmediate_file.py"]:
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
			assert TokenList([T.testa]).expand_x().str_unicode() == "123"

		assert default_engine.engine is None

		with pytest.raises(RuntimeError):
			TokenList([T["def"], T.testa, TokenList.doc("789")]).execute()

		with ChildProcessEngine("pdftex") as new_engine:
			TokenList([T["def"], T.testa, TokenList.doc("456")]).execute(engine=new_engine)
			assert TokenList([T.testa]).expand_x(engine=engine).str_unicode() == "123"
			assert TokenList([T.testa]).expand_x(engine=new_engine).str_unicode() == "456"


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

	@pytest.mark.parametrize("original, mangled", [
		("a", "a"),
		("", ""),
		("\t", ""),
		("\t", "\t"),
		("\t", "^^I"),
		("\ta", "^^Ia"),
		("a b", "a b"),
		("a b  ", "a b"),
		])
	def test_mangle(self, original: str, mangled: str)->None:
		assert pythonimmediate.can_be_mangled_to(original+"\n", mangled+"\n")

	@pytest.mark.parametrize("original, mangled", [
		("a", "b")
		])
	def test_mangle_incorrect(self, original: str, mangled: str)->None:
		assert not pythonimmediate.can_be_mangled_to(original+"\n", mangled+"\n")
