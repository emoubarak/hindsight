"""Imports shared by the hooks. Every hook fails open: any error means silence, never a blocked prompt."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")
sys.path.insert(0, SCRIPTS)
