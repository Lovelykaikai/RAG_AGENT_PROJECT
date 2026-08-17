"""
总结服务，用户提问，搜索参考资料，向模型提交参考资料和提问，让模型总结回复
"""
from langchain_core.documents import Document

from rag.vector_store import VectorStoreService
from utils.logger_handler import logger
from utils.prompt_loader import load_rag_prompt
from langchain_core.prompts import PromptTemplate
from model.factory import chat_model
from langchain_core.output_parsers import StrOutputParser

class RagSummarizeService(object):
    def __init__(self):
        self.vector_store = VectorStoreService()
        self.retriever = self.vector_store.get_retriever()
        self.prompt_text = load_rag_prompt()
        self.prompt_template = PromptTemplate.from_template(self.prompt_text)
        self.model = chat_model
        self.chain = self._init_chain()

    def _init_chain(self):
        chain = self.prompt_template | self.model | StrOutputParser()
        return chain

    def retriever_docs(self, query: str, city: str | None = None) -> list[Document]:
        """按 city 过滤检索；city 为空或不在库中时退回全库检索。"""
        if not city:
            return self.retriever.invoke(query)

        # 传进来的城市名可能是模型猜的，库里没有就别过滤，否则会召回 0 条。
        if city not in self.vector_store.known_cities():
            logger.info(f"[rag]知识库没有{city}的资料，改为全库检索")
            return self.retriever.invoke(query)

        return self.vector_store.get_retriever(city).invoke(query)

    def rag_summarize(self, query: str, city: str | None = None) -> str:

        context_docs = self.retriever_docs(query, city)

        context = ""
        counter = 0
        for doc in context_docs:
            counter += 1
            context += f"[参考资料{counter}]:{doc.page_content} | 参考元数据:{doc.metadata}\n"

        return self.chain.invoke(
            {
                "input":query,
                "context":context
            }
        )

    def summarize_text(self, query: str, context: str) -> str:
        """对外部参考文本（如联网搜索结果）做同样风格的总结，不经过向量检索。"""
        return self.chain.invoke({"input": query, "context": context})

if __name__ == '__main__':
    rag = RagSummarizeService()

    print(rag.rag_summarize("上海适合去那些地方？"))