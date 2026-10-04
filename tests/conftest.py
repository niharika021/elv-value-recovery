import os
import tempfile
from pathlib import Path

# Tests never touch the real decision log: point the store at an empty scratch file.
os.environ["ELV_DECISIONS"] = str(Path(tempfile.mkdtemp()) / "decisions.jsonl")
