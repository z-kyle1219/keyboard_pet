"""pytest 配置：把项目根目录加入 sys.path，使 tests/ 能 import 顶层模块。

pytest 会在收集测试时自动加载项目根的 conftest.py，并把其所在目录
（项目根）加入 sys.path，于是 `import weather` / `import scheduler` 可用。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
