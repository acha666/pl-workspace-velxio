"""Run the grader: ``python -m arduinograder [tests/test.py] [--sketch FILE]``."""

import sys

from .cli import main

sys.exit(main())
