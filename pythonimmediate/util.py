
"""
Miscellaneous utilities.
"""

from __future__ import annotations
import subprocess
import tempfile
from pathlib import Path
from typing import Iterable


def pdftotext(pdf_content: bytes, args: Iterable[str|bytes]=())->bytes:
	"""
	Convert PDF content to text.

	:param pdf_content: PDF content.
	:param args: Additional arguments to pass to ``pdftotext``.
	"""
	assert not isinstance(args, (str, bytes)), "Pass a list of strings/bytes as arg instead"
	with tempfile.TemporaryDirectory() as tmpdir:
		pdf_path = Path(tmpdir) / 'input.pdf'
		pdf_path.write_bytes(pdf_content)
		text_path = Path(tmpdir) / 'output.txt'
		subprocess.run(['pdftotext', *args, str(pdf_path), str(text_path)])
		return text_path.read_bytes()

