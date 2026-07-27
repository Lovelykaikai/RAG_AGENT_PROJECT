
import os
import hashlib

from utils.logger_handler import logger
from langchain_core.documents import Document
from langchain_community.document_loaders import PyPDFLoader, TextLoader, Docx2txtLoader

def get_file_md5_hex(file_path: str):         # 获取文件的md5的十六进制字符串
    if not os.path.exists(file_path):
        logger.error(f"[md5计算]文件{file_path}不存在")
        return

    if not os.path.isfile(file_path):
        logger.error(f"[md5计算]文件{file_path}不是文件")
        return

    md5_obj = hashlib.md5()

    chunk_size = 4096           # 4KB文件大小，防止文件过大
    try:
        with open(file_path, "rb") as f:
            while chunk := f.read(chunk_size):
                md5_obj.update(chunk)
            md5_hex = md5_obj.hexdigest()
            return md5_hex

    except Exception as e:
        logger.error(f"计算文件{file_path}md5失败，{str(e)}")
        return None

def listdir_with_allowed_type(path: str, allowed_type: tuple[str]):        # 返回文件夹内允许的类型文件
    file = []

    if not os.path.isdir(path):
        logger.error(f"{path}不是文件夹")
        return allowed_type

    for f in os.listdir(path):
        if f.endswith(allowed_type):
            file.append(os.path.join(path, f))

    return tuple(file)

def _check_file(file_path: str) -> bool:
    if not os.path.isfile(file_path):
        logger.error(f"[文件加载]文件不存在或不是文件: {file_path}")
        return False
    return True

def pdf_loader(file_path: str, password: str | bytes | None = None) -> list[Document]:
    if not _check_file(file_path):
        return []

    try:
        return PyPDFLoader(file_path, password=password).load()
    except Exception as e:
        logger.error(f"[PDF加载]文件{file_path}加载失败: {str(e)}")
        return []

def txt_loader(file_path: str, encoding: str = "utf-8") -> list[Document]:
    if not _check_file(file_path):
        return []

    try:
        return TextLoader(
            file_path,
            encoding=encoding,
            autodetect_encoding=True,
        ).load()
    except Exception as e:
        logger.error(f"[TXT加载]文件{file_path}加载失败: {str(e)}")
        return []

def docx_loader(file_path: str) -> list[Document]:
    if not _check_file(file_path):
        return []

    try:
        return Docx2txtLoader(file_path).load()
    except Exception as e:
        logger.error(f"[DOCX加载]文件{file_path}加载失败: {str(e)}")
        return []
