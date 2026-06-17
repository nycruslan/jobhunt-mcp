"""Put the repo root on sys.path so the flat-layout modules import under pytest."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
