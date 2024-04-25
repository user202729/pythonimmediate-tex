"""
module to copy everything from stdin to stderr.

needed to allow TeX to write to stderr.

This is placed in a separate module for a performance optimization. Refer to https://stackoverflow.com/q/21298833
"""

import sys
if __name__ == '__main__':
	for line in sys.stdin.buffer:
		sys.stderr.buffer.write(line)
		sys.stderr.buffer.flush()
