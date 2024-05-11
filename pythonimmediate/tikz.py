
"""
Some TikZ bindings.
"""
from __future__ import annotations

from pathlib import Path
import tempfile
import gzip
from typing import Optional

engine: Optional[Engine]=None

from pythonimmediate.multiengine import MultiChildProcessEngine
from pythonimmediate import*  # type: ignore
import pythonimmediate

#format_file=Path(tempfile.mktemp(suffix=".fmt"))
format_file=Path("/tmp/a.fmt")


def clear()->None:
	global engine
	if engine is not None:
		engine.__exit__(None, None, None)
		engine=None
	engine=MultiChildProcessEngine("pdftex", 2, from_dump=True, args=["&"+str(format_file.with_suffix(""))])
	engine.__enter__()
	default_engine.set_engine(engine)
	execute(r'''
	\begin{document}
	\begin{tikzpicture}
	''')
	execute(r'\draw [help lines] (-5, -5) grid (5, 5);')

#clear()

r'''
ipython=get_ipython()

try: ipython.input_transformer_manager.line_transforms.remove(_ipython_hook)
except (ValueError, NameError): pass
def _ipython_hook(l: list[str])->list[str]:
	i=0
	l=list(l)
	while i<len(l):
		if l[i].lstrip().startswith('!'):
			whitespace_at_beginning=l[i][:len(l[i])-len(l[i].lstrip())]
			for j in range(i+1, len(l)+1):
				if j==len(l) or not l[j].lstrip().startswith('!'):
					for k in range(i, j):
						l[k]=l[k].lstrip().removeprefix('!')
						assert '"""' not in l[k], l[k]
					l[i]=whitespace_at_beginning+'pythonimmediate.execute(r"""'+l[i]
					assert l[j-1].endswith('\n'), l[j-1]
					l[j-1]=l[j-1].removesuffix('\n')+'""")\n'
					i=j
					break
		else: i+=1
	return l
ipython.input_transformer_manager.line_transforms.append(_ipython_hook)

path_in_progress: bool=False

def start_path(s: str)->None:
	global path_in_progress
	assert not path_in_progress
	path_in_progress=True
	BalancedTokenList.doc(s+r"\pgfextra\relax").execute()
	# even though I know the library doesn't insert `{` right after the user code to be executed
	# the \relax is there just to safeguard

def insert_path(s: str)->None:
	global path_in_progress
	assert path_in_progress
	BalancedTokenList.doc(r"\endpgfextra "+s+r"\pgfextra\relax").execute()

def end_path(s: str)->None:
	global path_in_progress
	assert path_in_progress
	path_in_progress=False
	assert ";" in s
	BalancedTokenList.doc(r"\endpgfextra "+s).execute()

##

with ChildProcessEngine("pdftex", args=["--ini", "&pdflatex"]) as engine, default_engine.set_engine(engine):
	try: execute(r"""
	\documentclass{article}
	\usepackage{tikz}
	\usepackage[active,tightpage]{preview}
	\PreviewEnvironment{tikzpicture}
	\pythonimmediatechildprocessdump""")
	except TeXProcessExited: pass
	else: assert False
	format_file.write_bytes(gzip.decompress(engine.read_output_file("fmt")))



example::

	! \typeout{123}
	! \typeout{456}


with ChildProcessEngine("pdftex", from_dump=True, args=["&"+str(format_file.with_suffix(""))]) as engine, default_engine.set_engine(engine):
	execute(r"""
	\begin{document}
	\begin{tikzpicture}
	""")
	execute(r'\draw (-5, -5) grid (5, 5);')
	execute(r'\draw (0,0) -- (1,1);')
	execute(r'\end{tikzpicture}')
	engine.terminate()
	Path("/tmp/a.pdf").write_bytes(engine.read_output_file())


##

!\draw (0,0) -- (1,1);
!\draw (0,1) -- (1,0);

!\path (1, 1) node [draw, circle] {abc};

clear()


start_path(r'\path (1, 1)')

insert_path(r'-- (2, 2)')

end_path(r'-- (3, 3);')

get_last_point()

%time [get_last_point() for __ in range(1000)]*0
%time [get_pgfx_pgfy() for __ in range(1000)]*0

Point=tuple[float, float]

def get_point(s: str)->Point:
	assert s.count("?")==1
	with engine.transient_context():
		return (float(T[s.replace("?", "x")].dim("cm")), float(T[s.replace("?", "y")].dim("cm")))

def get_pgfpoint(t: BalancedTokenList)->Point:
	# https://tikz.dev/base-points#sec-101.7
	# input can be e.g. \pgfpoint{1cm}{2pt}
	with engine.transient_context():
		t.execute()
		return get_point("pgf@?") # \pgfgetlastxy

def scan_tikz_point(t: BalancedTokenList)->Point:
	# t can be e.g. (1, 2)
	with engine.transient_context():
		BalancedTokenList([T['tikz@scan@one@point'], T['pgfutil@firstofone'], *t]).execute()
		return get_point("pgf@?") # \pgfgetlastxy

scan_tikz_point(BalancedTokenList.doc("(3, 3)"))

get_pgfpoint(BalancedTokenList.doc(r"\pgfpoint{1cm}{2pt}"))

T['tikz@tangent'].meaning_str()

get_point('pgf@path@last?') # pgfpathmoveto

get_pgfpoint(BalancedTokenList([T['tikz@tangent']]))

get_point("tikz@last?") # \tikz@last@position
get_point("tikz@last?saved") # \tikz@last@position@saved

T['tikz@tangent'].meaning_str()

# equivalent to \pgfgetlastxy


!\path (2, 2) coordinate (a);



continue_until_passed_back_str()

p=get_last_point()

from pythonimmediate import unit_per_pt

	T.l_tmpa_dim.dim("pt", 1)
	!\l_tmpa_dim
	!\l_tmpb_dim

with engine.extract_one() as child:
	#!\draw (0,0) -- (1,1);
	#!\draw (0,1) -- (1,0);
	!\end{tikzpicture}
	child.terminate()
	Path("/tmp/a.pdf").write_bytes(child.read_output_file())

'''
