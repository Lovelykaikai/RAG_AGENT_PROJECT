import re

from langchain_chroma import Chroma
from langchain_core.documents import Document
from utils.config_handler import chroma_conf
from utils.logger_handler import logger
from utils.path_tool import get_abs_path
from model.factory import embedding_model
from langchain_text_splitters import RecursiveCharacterTextSplitter
from utils.file_handler import pdf_loader, txt_loader, docx_loader, listdir_with_allowed_type, get_file_md5_hex


# 知识库文档里不代表具体城市的小节标题，这些切片不打 city 标签。
_NON_CITY_SECTIONS = ("城市间交通", "总体原则")

# '## 北京市内交通' 这类标题需要剥掉的后缀，剥完才是城市名。
_CITY_TITLE_SUFFIXES = ("市内交通", "市内出行", "交通")


def _extract_city(header: str) -> str | None:
    """从小节标题里取出城市名。

    '## 北京'                  -> '北京'
    '## 上海：近代城市与海派文化' -> '上海'
    '## 广州市内交通'           -> '广州'
    '## 城市间交通'             -> None
    """
    title = header.lstrip("#").strip()
    if not title or title in _NON_CITY_SECTIONS:
        return None

    # 标题里带说明时只取冒号前的部分，中英文冒号都要处理。
    title = re.split(r"[：:]", title)[0].strip()

    for suffix in _CITY_TITLE_SUFFIXES:
        if title.endswith(suffix) and len(title) > len(suffix):
            title = title[: -len(suffix)]
            break

    return title or None


def _load_raw_document(read_path: str) -> list[Document]:
    if read_path.endswith(".txt"):
        return txt_loader(read_path)
    if read_path.endswith(".pdf"):
        return pdf_loader(read_path)
    if read_path.endswith(".docx"):
        return docx_loader(read_path)
    return []


class VectorStoreService:
    def __init__(self):
        self.vector_store = Chroma(
            collection_name = chroma_conf["collection_name"],
            embedding_function = embedding_model,
            persist_directory = get_abs_path(chroma_conf["persist_directory"]),
        )
        self.chunk_size = chroma_conf["chunk_size"]
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=chroma_conf["chunk_overlap"],
            separators=chroma_conf["separators"],
            length_function=len,
        )
        self._known_cities_cache: list[str] | None = None

    def get_retriever(self, city: str | None = None):
        """构造检索器。

        传入 city 时只召回该城市的切片，避免各城市攻略措辞相近导致的串味；
        不传时检索全库，用于跨城市或与城市无关的问题。
        """
        search_kwargs: dict = {"k": chroma_conf["k"]}
        if city:
            search_kwargs["filter"] = {"city": city}
        return self.vector_store.as_retriever(search_kwargs=search_kwargs)

    def known_cities(self) -> list[str]:
        """列出库里已有 city 标签的城市，用于校验调用方传来的城市名。"""
        if self._known_cities_cache is not None:
            return self._known_cities_cache
        try:
            metadatas = self.vector_store.get(include=["metadatas"]).get("metadatas") or []
        except Exception as e:
            logger.warning(f"[知识库]读取城市列表失败: {str(e)}")
            return []
        self._known_cities_cache = sorted({m["city"] for m in metadatas if m and m.get("city")})
        return self._known_cities_cache

    def _split_by_city_section(self, text: str, source: str) -> list[Document]:
        """按 '## ' 标题把文档切成城市小节，并给每个切片打上 city 标签。

        小节本身通常已经短于 chunk_size，只有超长的才继续用递归切分器细分。
        保留标题行在正文里，让检索时城市名本身也参与匹配。
        """
        documents: list[Document] = []

        for part in re.split(r"\n(?=##\s)", text):
            part = part.strip()
            if not part or not part.startswith("##"):
                # 文件顶部的 '# 总标题' 段没有城市信息，跳过。
                continue

            header = part.partition("\n")[0]
            city = _extract_city(header)
            metadata: dict[str, str] = {"source": source}
            if city:
                metadata["city"] = city

            if len(part) <= self.chunk_size:
                documents.append(Document(page_content=part, metadata=dict(metadata)))
                continue

            for chunk in self.splitter.split_text(part):
                documents.append(Document(page_content=chunk, metadata=dict(metadata)))

        return documents

    def _existing_file_state(self, source: str) -> tuple[list[str], str]:
        """查询某个源文件在库里已有的切片 ID 和当时记录的文件 md5。"""
        try:
            existing = self.vector_store.get(where={"source": source})
        except Exception as e:
            logger.warning(f"[加载知识库]查询{source}已有切片失败: {str(e)}")
            return [], ""

        ids = existing.get("ids") or []
        metadatas = existing.get("metadatas") or []
        recorded_md5 = ""
        for metadata in metadatas:
            if metadata and metadata.get("file_md5"):
                recorded_md5 = metadata["file_md5"]
                break

        return ids, recorded_md5

    def load_document(self, force: bool = False):
        """
        从数据文件夹读取文件，按城市小节切分后存入向量库。

        去重依据是库里已记录的 file_md5，不再依赖外部 md5 文件，
        所以「库被清空但去重记录还在」这种不一致状态不会再出现。
        切片 ID 固定为 '{文件md5}:{序号}'，重复执行是 upsert 而非追加。

        :param force: 为 True 时忽略 md5 比对，强制重新切分并覆盖写入
        :return: None
        """
        allowed_file_path: list[str] = listdir_with_allowed_type(
            get_abs_path(chroma_conf["data_path"]),
            tuple(chroma_conf["allow_knowledge_file_type"]),
        )

        for path in allowed_file_path:
            # 获取文件的md5
            md5_hex = get_file_md5_hex(path)

            if not md5_hex:
                logger.warning(f"[加载知识库]无法计算{path}的md5，跳过")
                continue

            existing_ids, recorded_md5 = self._existing_file_state(path)

            if recorded_md5 == md5_hex and not force:
                logger.info(f"[加载知识库]{path} 未变更，跳过")
                continue

            try:
                documents = _load_raw_document(path)

                if not documents:
                    logger.warning(f"[加载知识库]{path}内没有有效文本内容，跳过")
                    continue

                full_text = "\n".join(doc.page_content for doc in documents)
                split_document = self._split_by_city_section(full_text, path)

                if not split_document:
                    logger.warning(f"[加载知识库]{path}分片后没有有效文本内容，跳过")
                    continue

                for doc in split_document:
                    doc.metadata["file_md5"] = md5_hex

                # 文件改过时旧切片数量可能多于新切片，先清掉避免残留旧版本内容。
                if existing_ids:
                    self.vector_store.delete(ids=existing_ids)
                    logger.info(f"[加载知识库]{path} 已变更，清除{len(existing_ids)}条旧切片")

                self.vector_store.add_documents(
                    split_document,
                    ids=[f"{md5_hex}:{index}" for index in range(len(split_document))],
                )
                self._known_cities_cache = None

                cities = sorted({doc.metadata["city"] for doc in split_document if "city" in doc.metadata})
                logger.info(
                    f"[加载知识库]{path} 内容加载成功，切片{len(split_document)}条"
                    f"，覆盖城市{len(cities)}个"
                )

            except Exception as e:
                # exc_info为True，记录详细的报错堆栈，False仅记录报错信息本身
                logger.error(f"[加载知识库]{path}加载失败: {str(e)}", exc_info=True)
                continue

if __name__ == '__main__':
    import sys

    # 传 --force 可忽略md5比对，强制按当前切分配置重建全部切片。
    vs = VectorStoreService()
    vs.load_document(force="--force" in sys.argv)