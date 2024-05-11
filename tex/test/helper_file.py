import unittest
import pythonimmediate
from typing import Any, Generator, Union
from pythonimmediate import Token, TokenList, BalancedTokenList, Catcode, ControlSequenceToken, frozen_relax_token, BlueToken, NTokenList, catcode, remove_handler, group, expand_once
from pythonimmediate import Catcode as C
from pythonimmediate import CharacterToken, print_TeX
from pythonimmediate.engine import default_engine
from pythonimmediate.simple import execute, get_arg_estr, get_arg_str, get_env_body_verb_approximate, get_multiline_verb_arg, get_optional_arg_estr, get_optional_arg_str, get_verb_arg, newcommand, peek_next_char, peek_next_meaning, put_next, renewcommand, define_char, undefine_char, newenvironment, newenvironment_verb, var
T=ControlSequenceToken.make

assert default_engine.name in ["pdftex", "xetex", "luatex"]

assert default_engine.name==T.c_sys_engine_str.str()

is_unicode: bool=default_engine.is_unicode

y=None

need_speed_up=default_engine.config.naive_flush

class Test(unittest.TestCase):
	def test_simple_run_tokenized_line_local(self)->None:
		execute(r'\testa {123} {456}')
		self.assertEqual(x, "123")
		self.assertEqual(y, "456")

	def test_implicit_hash_token(self)->None:
		with group:
			T.aaa.set_eq(C.param("#"))
			C.active("?").set_eq(C.param("#"))
			for s in [BalancedTokenList([T.aaa]), BalancedTokenList([C.active("?")])]:
				s.put_next()
				assert BalancedTokenList.get_next() ==s

	def test_renewcommand_non_Python_defined(self)->None:
		execute(r'\def \testb {}')

		@renewcommand
		def testb()->None: pass

	def test_newcommand(self)->None:
		global x
		x=1

		@newcommand
		def testa()->None:
			global x
			x=2

		self.assertEqual(x, 1)
		execute(r'\testa')
		self.assertEqual(x, 2)

	def test_meaning_eq(self)->None:
		assert T["@firstoftwo"].meaning_eq(T["use_i:nn"])
		assert T["@secondoftwo"].meaning_eq(T["use_ii:nn"])
		assert not T["@secondoftwo"].meaning_eq(T["use_i:nn"])
		assert T["@firstofone"].meaning_eq(T["use:n"])

	def test_unicode_str(self)->None:
		s='Æ²×⁴ℝ𝕏'
		put_next('{' + s + '}')
		self.assertEqual(get_arg_str(), s)

		put_next('{' + s + '}')
		self.assertEqual(get_arg_estr(), s)

		put_next(r'\expandafter{\detokenize{' + s + '}}')
		expand_once()
		t=BalancedTokenList.get_next()
		assert t.str()==s

	def test_csname_unicode(self)->None:
		s='Æ²×⁴ℝ𝕏'
		execute(r'\edef\testb{\expandafter \noexpand \csname \detokenize{' + s + r'}\endcsname}')
		
		self.assertEqual(BalancedTokenList([T.testb]).expand_o(), BalancedTokenList([ControlSequenceToken(s)]))
		if default_engine.is_unicode:
			execute(r'\edef\testb{\expandafter \noexpand \csname \detokenize{' + f"^^^^{ord('ℝ'):04x}" + r'}\endcsname}')
			self.assertEqual(BalancedTokenList([T.testb]).expand_o(), BalancedTokenList([ControlSequenceToken("ℝ", is_unicode=True)]))
		else:
			execute(r'\edef\testb{\expandafter \noexpand \csname \detokenize{' +
						   "".join(f"^^{a:02x}" for a in 'ℝ'.encode('u8')) +
						   r'}\endcsname}')
			self.assertEqual(BalancedTokenList([T.testb]).expand_o(), BalancedTokenList([ControlSequenceToken("ℝ".encode('u8'))]))

	def test_hash(self)->None:
		for put, get in [
				("#", None),
				("#1#2#3##", None),
				(r"\#", None),
				(r"\##", None),
				(r"#\#", None),
				]:
			put_next('{' + put + '}')
			self.assertEqual(get_arg_str(), (put if get is None else get))


	def test_newcommand_with_name(self)->None:
		@newcommand("testd")
		def testa()->None:
			global x
			x=3

		self.assertEqual(x, 2)
		execute(r'\testd')
		self.assertEqual(x, 3)

		@renewcommand  # type: ignore
		def testa()->None:
			global x, y
			x=get_arg_str()
			y=get_arg_str()

		@newcommand
		def testc()->str:
			self.assertEqual(get_arg_str(), "ab")
			self.assertEqual(get_optional_arg_str(), "cd")
			self.assertEqual(get_optional_arg_str(), None)
			self.assertEqual(get_verb_arg(), "ef")
			self.assertEqual(get_optional_arg_str(), None)
			self.assertEqual(get_verb_arg(), "gh")
			self.assertEqual(get_multiline_verb_arg(), "ijk\nlm")
			print_TeX("123", end="")
			return "456"

		execute("789%")
		execute("789%")

		execute(r"""\testc {ab} [cd]|ef|{gh}|ijk""" + "\n" + r"""lm|%""")

		execute("789%")


	def test_tokens(self)->None:
		global x
		x=0

		@renewcommand
		def testd()->None:
			global x
			x=1

			a=BalancedTokenList.get_next()

			put_next(r'{123}')
			b=BalancedTokenList.get_next()

			put_next(r'{1 a\relax}')
			for t, meaning in [
					(Catcode.bgroup('{'), "begin-group character {"),
					(Catcode.other ('1'), "the character 1"),
					(Catcode.space (' '), "blank space  "),
					(Catcode.letter('a'), "the letter a"),
					(ControlSequenceToken('relax'), r"\relax"),
					(Catcode.egroup('}'), "end-group character }"),
					]:
				self.assertEqual(peek_next_meaning(), meaning)
				self.assertEqual(Token.peek_next(), t)
				self.assertEqual(Token.get_next(), t)


			a.put_next()
			c=BalancedTokenList.get_next()

			self.assertEqual(c, a[1:-1])


		self.assertEqual(x, 0)
		execute(
		r'''
		\precattlExec{ \testd {{ab\cC {}\cC{123}\relax\cFrozenRelax {}\cP*$^_ \cS\a}} }
		''')
		self.assertEqual(x, 1)

	def test_get_until(self)->None:
		TokenList.e3(r'abc{}\test def').put_next()
		assert BalancedTokenList.get_until(BalancedTokenList.e3(r'ef')) == TokenList.e3(r'abc{}\test d')

		TokenList.e3(r'{abc{}\test d}ef').put_next()
		assert BalancedTokenList.get_until(BalancedTokenList.e3(r'ef')) == TokenList.e3(r'abc{}\test d')

		TokenList.e3(r'{abc{}\test d}ef').put_next()
		self.assertEqual(BalancedTokenList.get_until(BalancedTokenList.e3(r'ef'), remove_braces=False), TokenList.e3(r'{abc{}\test d}'))

	def test_catcode(self)->None:
		assert catcode["a"] == Catcode.letter
		assert catcode[ord("a")] == Catcode.letter
		catcode["a"] = Catcode.other
		assert catcode[ord("a")] == Catcode.other
		catcode["a"] = Catcode.letter

	def test_tokens2(self)->None:
		for t in [
				frozen_relax_token,
				ControlSequenceToken(">>"),
				ControlSequenceToken(""),
				ControlSequenceToken("	"),
				ControlSequenceToken(" > a b>\\> "),
				Catcode.space(' '),
				Catcode.other(' '),
				Catcode.letter(' '),
				Catcode.space('\\'),
				Catcode.other('\\'),
				Catcode.letter('\\'),
				Catcode.bgroup(' '),
				Catcode.egroup(' '),
				]:
			with self.subTest(t=t):
				t.put_next()
				self.assertEqual(Token.peek_next(), t)
				self.assertEqual(Token.get_next(), t)

	def test_tokens_control_chars(self)->None:
		for i in range(0, 700, (50 if need_speed_up else 1)):
			s: Union[str, bytes]=chr(i) if is_unicode or i>=256 else bytes([i])
			for t in [
				Catcode.active(s),
				Catcode.bgroup(s),
				Catcode.egroup(s),
				Catcode.other (s),
				ControlSequenceToken([i]),
				ControlSequenceToken([i, i]),
				*(
					[] if is_unicode else
					[ ControlSequenceToken(chr(i).encode('u8')), ControlSequenceToken(chr(i).encode('u8')*2) ]
					),
				]:
				if t==Catcode.active(' '): continue  # https://github.com/latex3/latex3/issues/1539
				#if default_engine.name=="luatex" and t in [ControlSequenceToken("\x00"), ControlSequenceToken("\x00\x00")]:
				#	continue  # LuaTeX bug fixed upstream https://tex.stackexchange.com/questions/640267/lualatex-does-not-handle-control-sequence-consist-of-a-single-null-character-cor
				#if default_engine.name=="pdftex" and t==Catcode.active(0x0c):
				#	continue  # https://tex.stackexchange.com/q/669877/250119

				try:
					t1=t
					with self.subTest(s=s, t=t):
						if is_unicode:
							should_give_error=False
						else:
							if isinstance(t, CharacterToken):
								should_give_error=t.index>=256
							else:
								assert isinstance(t, ControlSequenceToken)
								should_give_error=max(t.codes)>=256
						if should_give_error:
							with self.assertRaises(ValueError):
								t.put_next()
						else:
							t.put_next()
							t1=Token.get_next()
							self.assertEqual(t1, t)
				except:
					raise ValueError(f"{s=!r} {ord(s)=} {t=!r} {t1=!r}")

	def test_put_get_next(self)->None:
		put_next("a")
		self.assertEqual(peek_next_char(), "a")

		put_next(r"\a")
		self.assertEqual(peek_next_char(), "")
		Token.get_next()

		put_next(r"\par")
		self.assertEqual(peek_next_char(), "")
		assert Token.get_next()==ControlSequenceToken("par")

		CharacterToken(ord(' '), Catcode.space).put_next()
		self.assertEqual(peek_next_char(), " ")

		put_next(r"\relax")
		self.assertEqual(peek_next_char(), "")

		put_next(r"\begingroup\endgroup")
		self.assertEqual(peek_next_char(), "")

		put_next(r"\bgroup\egroup")
		self.assertEqual(peek_next_char(), "{")

	def test_balanced(self)->None:
		a=TokenList.doc(r'}{')
		self.assertFalse(a.is_balanced())
		with self.assertRaises(ValueError):
			a.check_balanced()

	def test_get_next_tokenlist(self)->None:
		t=BalancedTokenList.doc(r'{}abc:  d?&#^_\test+\test a\##') + [frozen_relax_token]
		u=BalancedTokenList([t])
		self.assertEqual(len(u), len(t)+2)
		u.put_next()
		self.assertEqual(BalancedTokenList.get_next(), t)


	def test_from_str(self)->None:
		self.assertEqual(TokenList.doc(r'}{abc:  d?&#^_\test+\test a\##'),
			  TokenList([
				  C.egroup("}"),
				  C.bgroup("{"),
				  C.letter("a"),
				  C.letter("b"),
				  C.letter("c"),
				  C.other(":"),
				  C.space(" "),
				  C.letter("d"),
				  C.other("?"),
				  C.alignment("&"),
				  C.parameter("#"),
				  C.superscript("^"),
				  C.subscript("_"),
				  ControlSequenceToken("test"),
				  C.other("+"),
				  ControlSequenceToken("test"),
				  C.letter("a"),
				  ControlSequenceToken("#"),
				  C.parameter("#"),
				  ]))
		self.assertEqual(TokenList.e3(r'abc:  d~?&#^_\test+\test a'),
			  TokenList([
				  C.letter("a"),
				  C.letter("b"),
				  C.letter("c"),
				  C.letter(":"),
				  C.letter("d"),
				  C.space(" "),
				  C.other("?"),
				  C.alignment("&"),
				  C.parameter("#"),
				  C.superscript("^"),
				  C.letter("_"),
				  ControlSequenceToken("test"),
				  C.other("+"),
				  ControlSequenceToken("test"),
				  C.letter("a"),
				  ]))
		self.assertEqual(TokenList([C.letter("a"), "bc", ["def{", r"}\test\test"]]),
				   TokenList([
					   C.letter("a"),
					   C.letter("b"),
					   C.letter("c"),
					   C.bgroup("{"),
					   C.letter("d"),
					   C.letter("e"),
					   C.letter("f"),
					   C.bgroup("{"),
					   C.egroup("}"),
					   T["test"],
					   T["test"],
					   C.egroup("}"),
					   ]))
		self.assertEqual(TokenList(r"\tl_set:Nn \a \b"),
				   TokenList([
					   T["tl_set:Nn"],
					   T["a"],
					   T["b"],
					   ]))

	def test_balanced_parts(self)->None:
		for s in [
				r"",
				r"}{",
				r"ab{cd}ef}{gh}{{ij}",
				r"}}}}}{{{",
				r"{{{}}}}}",
				]:
			t=TokenList.doc(s)
			parts=t.balanced_parts()
			self.assertEqual(t, [x for part in parts for x in (part if isinstance(part, BalancedTokenList) else [part])])
			for part in parts:
				if isinstance(part, Token):
					self.assertNotEqual(part.degree(), 0)
				else:
					self.assertNotEqual(len(part), 0)

			t.put_next()
			for x in t:
				self.assertEqual(Token.get_next(), x)

	def test_expand(self)->None:
		BalancedTokenList.doc(r'\def\testexpand{\testexpanda}\def\testexpanda{123}').execute()
		self.assertEqual(BalancedTokenList.doc(r'\testexpand').expand_o(), BalancedTokenList.doc(r'\testexpanda'))
		self.assertEqual(BalancedTokenList.doc(r'\testexpand').expand_x(), BalancedTokenList.doc(r'123'))
		self.assertEqual(BalancedTokenList.doc(' ').expand_o(), BalancedTokenList.doc(' '))
		self.assertEqual(BalancedTokenList.doc(' ').expand_x(), BalancedTokenList.doc(' '))
		self.assertEqual(1, len(BalancedTokenList.doc(' ')))
		self.assertEqual(BalancedTokenList([frozen_relax_token]).expand_x(), BalancedTokenList([frozen_relax_token]))
		self.assertEqual(TokenList.doc(r'\string}\string{\number`{').expand_x().str(), "}{123")

	def test_get_arg_estr(self)->None:
		BalancedTokenList.doc(r'{123}').put_next()
		self.assertEqual(get_arg_estr(), "123")

		BalancedTokenList.doc(r'{\empty}').put_next()
		self.assertEqual(get_arg_estr(), "")

		BalancedTokenList.doc(r'{a\ \\\{\}\$\&\#\^\_\%\~~b}').put_next()
		self.assertEqual(get_arg_estr(), r"a \{}$&#^_%~~b")

		
	def test_get_optional_arg_estr(self)->None:
		BalancedTokenList.doc(r'[123]').put_next()
		self.assertEqual(get_optional_arg_estr(), "123")

		# outermost only {} get stripped
		BalancedTokenList.doc(r'[{123}]').put_next()
		self.assertEqual(get_optional_arg_estr(), "123")

		# can also be used to hide the ]
		BalancedTokenList.doc(r'[{]}]').put_next()
		self.assertEqual(get_optional_arg_estr(), "]")

		# can also hide this way
		BalancedTokenList.doc(r'[\]]').put_next()
		self.assertEqual(get_optional_arg_estr(), "]")

		# test expansion
		BalancedTokenList.doc(r'[\empty]').put_next()
		self.assertEqual(get_optional_arg_estr(), "")

		# test balancedness & keep braces (supported by xparse)
		BalancedTokenList.doc(r'[{a}\ \\\{\}\$\&\#\^\_\%\~~b[]]').put_next()
		self.assertEqual(get_optional_arg_estr(), r"{a} \{}$&#^_%~~b[]")

		# test nonexistent optional argument
		BalancedTokenList.doc(r'{ab}').put_next()
		self.assertEqual(get_optional_arg_estr(), None)
		self.assertEqual(get_arg_str(), "ab")

	def test_control_sequence_token_maker(self)->None:
		self.assertEqual(ControlSequenceToken("ab_c"), ControlSequenceToken.make.ab_c)
		self.assertEqual(ControlSequenceToken("ab_c"), ControlSequenceToken.make["ab_c"])

	def test_expand_once(self)->None:
		BalancedTokenList.doc(r'\def\aaa{\bbb}').execute()
		T.aaa.put_next()
		expand_once()
		self.assertEqual(Token.get_next(), T.bbb)

	def test_blue_tokens(self)->None:
		self.assertEqual(
				T.empty.meaning_str(),
				"macro:->")
		self.assertIn(
				T.empty.blue.meaning_str(),
				[r"\relax", r"[unknown command code! (0, 1)]"])

		Catcode.active("a").tl(BalancedTokenList.doc("abc"))

		self.assertEqual(Catcode.active("a").meaning_str(), "macro:->abc")
		self.assertIn(
				Catcode.active("a").blue.meaning_str(),
				[r"\relax", r"[unknown command code! (0, 1)]"])

	def test_set_func_and_group(self)->None:
		a=1
		def f()->None:
			nonlocal a
			a=2
		handler_f=T.abc.set_func(f)

		self.assertEqual(a, 1)
		TokenList(r"\abc").execute()
		self.assertEqual(a, 2)

		for global_ in [False, True]:
			with group:
				def g()->None:
					nonlocal a
					a=3
				handler_g=T.abc.set_func(g, global_=global_)
				a=1
				TokenList(r"\abc").execute()
				self.assertEqual(a, 3)

			a=1
			TokenList(r"\abc").execute()
			if global_: self.assertEqual(a, 3)
			else: self.assertEqual(a, 2)
			remove_handler(handler_g)

		remove_handler(handler_f)

	def test_cannot_blue_tokens(self)->None:
		for t in [
				Catcode.letter("a"),
				Catcode.other("a"),
				frozen_relax_token
				]:
			self.assertEqual(t.noexpand, t)
			with self.assertRaises(ValueError):
				t.blue

	def test_meaning_equal(self)->None:
		self.assertFalse(T.empty.blue.meaning_eq(T.empty))
		self.assertFalse(T.empty.meaning_eq(T.empty.blue))
		self.assertTrue(T.relax.blue.meaning_eq(T.relax))
		self.assertTrue(T.empty.blue.meaning_eq(T.empty.blue))

	def test_set_to_blue(self)->None:
		NTokenList([T.let, T.aaa.blue, T.ifx]).execute()
		self.assertTrue(T.aaa.meaning_eq(T.ifx))

		NTokenList([T.futurelet, T.aaa.blue, T["@gobble"], T.ifcat]).execute()
		self.assertTrue(T.aaa.meaning_eq(T.ifcat))

	def test_make_tokenlist_from_blue(self)->None:
		with self.assertRaises(RuntimeError):
			TokenList([T.aaa.blue])

	def test_set(self)->None:
		for t in [T.ifx, T.ifx.blue, C.other("="), C.space(' '), T.empty, T.relax, T.empty.blue]:
			with self.subTest(t=t):
				T.aaa.set_eq(t)
				self.assertTrue(T.aaa.meaning_eq(t))

				t.put_next()
				T.aaa.set_future()
				self.assertTrue(T.aaa.meaning_eq(t))

				T.aaa.set_eq(T.empty)

				T.empty.put_next()
				T.aaa.set_future2()
				self.assertTrue(T.aaa.meaning_eq(t.no_blue))

				assert Token.get_next()==T.empty
				assert Token.get_next()==t.no_blue

				T.aaa.set_eq(T.empty)

				NTokenList([T.empty, t]).put_next()
				T.aaa.set_future2()
				self.assertTrue(T.aaa.meaning_eq(t))

				assert Token.get_next()==T.empty
				assert Token.get_next()==t.no_blue

	def test_outer_token(self)->None:
		TokenList.doc(r"\outer\def\outertest{}").execute()

		self.assertEqual(
				TokenList.doc(r"\string}\string}\string\outertest\string{\string{").expand_x().str(),
				r"}}\outertest{{")

		T.outertest.put_next()
		self.assertEqual(Token.get_next(), T.outertest)

	def test_deserialize_not_accidentally_define(self)->None:
		self.assertEqual(
				TokenList.doc(r'\meaning\undefined').expand_x().str(),
				r'undefined')

	def test_define_char(self)->None:
		for c in ":×":
			with self.subTest(c=c):
				a = 1

				@define_char(c)
				def f()->None:
					nonlocal a
					a = 2

				self.assertEqual(a, 1)
				execute(c)
				self.assertEqual(a, 2)

				undefine_char(c)

	def test_new_environment(self)->None:
		import random
		l=[]
		@newenvironment("myenv")
		def	myenv()->Generator[None, None, None]:
			x=random.randint(1, 10**18)
			l.append(f"begin {x}")
			yield
			l.append(f"end {x}")


		execute(r"""
		\begin{myenv}
		\begin{myenv}
		\end{myenv}
		\end{myenv}
		""")

		self.assertEqual(len(l), 4)
		assert l[0].startswith("begin "), l
		assert l[1].startswith("begin "), l
		assert l[2].startswith("end "), l
		assert l[3].startswith("end "), l
		self.assertEqual(l[0][6:], l[3][4:])
		self.assertEqual(l[1][6:], l[2][4:])

	def test_new_verbatim_environment(self)->None:
		a=0
		@newenvironment_verb("myenv*")
		def myenv(s: str)->None:
			nonlocal a
			a=1
			self.assertEqual(s, "hello world\n \\#^&%$\n")

		self.assertEqual(a, 0)
		import textwrap
		execute(textwrap.dedent(r"""
		\begin{myenv*}
		hello world
		 \#^&%$
		\end{myenv*}
		"""))
		self.assertEqual(a, 1)
		
	def test_get_env_body_verb_approximate(self)->None:
		a=0
		@newenvironment("myenv**")
		def myenv()->Generator[None, None, None]:
			s, _, _=get_env_body_verb_approximate()
			nonlocal a
			a=1
			self.assertEqual(s, "hello world\n \\#^&%$\n")
			yield

		self.assertEqual(a, 0)
		import textwrap
		execute(textwrap.dedent(r"""
		\begin{myenv**}
		hello world
		 \#^&%$
		\end{myenv**}
		"""))
		self.assertEqual(a, 1)

	def test_var(self)->None:
		var["abc"]=r"\test  \###\a\b{}#&?"
		self.assertEqual(var["abc"], r"\test \###\a \b {}#&?")


suite = unittest.defaultTestLoader.loadTestsFromTestCase(Test)
result = unittest.TextTestRunner(failfast=True).run(suite)
assert not result.errors


x: Any=2
