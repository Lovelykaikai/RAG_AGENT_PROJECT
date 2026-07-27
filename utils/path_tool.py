"""
为整个工程提供一个绝对路径
"""

import os

def get_project_root() -> str:
    """
    获取工程所在的根目录
    :return:字符串
    """
    # 当前文件的绝对路径
    current_file = os.path.abspath(__file__)
    # 当前文件夹的绝对路径
    current_dir = os.path.dirname(current_file)
    # 工程文件的路径
    project_root = os.path.dirname(current_dir)

    return project_root

def get_abs_path(relative_path: str) -> str:
    """
    传递相对路径，得到绝对路径
    :param relative_path:相对路径
    :return:绝对路径
    """
    project_root = get_project_root()
    return os.path.join(project_root, relative_path)