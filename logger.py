"""极简日志模块：把运行日志写入项目目录下的 pet.log。

避免程序崩溃时"无声消失"，方便排查。
"""
import os
import logging

from config import BASE_DIR

LOG_PATH = os.path.join(BASE_DIR, 'pet.log')

logger = logging.getLogger('keyboard_pet')
logger.setLevel(logging.INFO)

if not logger.handlers:
    # 文件日志（UTF-8，防中文乱码）
    _fh = logging.FileHandler(LOG_PATH, encoding='utf-8')
    _fh.setFormatter(logging.Formatter(
        '%(asctime)s [%(levelname)s] %(message)s'))
    logger.addHandler(_fh)
