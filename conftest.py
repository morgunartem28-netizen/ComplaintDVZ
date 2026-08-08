"""Гарантирует, что корень проекта есть в sys.path независимо от того, как
запущен pytest (`pytest`, `python -m pytest`, из другой рабочей директории и
т.п.) — иначе `from utils... import ...` / `from keyboards import ...` в
tests/ падает с ModuleNotFoundError."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
