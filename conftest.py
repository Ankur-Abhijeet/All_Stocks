"""
conftest.py — pytest configuration for mf_faq project.
Adds src/ to sys.path so that `import mf_faq` works without pip install.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))
