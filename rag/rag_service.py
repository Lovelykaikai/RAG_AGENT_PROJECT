"""
总结服务，用户提问，搜索参考资料，向模型提交参考资料和提问，让模型总结回复
"""
from langchain_core.documents import Document

from rag.vector_store import VectorStoreService
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

    def retriever_docs(self, query:str) -> list[Document]:
        return self.retriever.invoke(query)

    def rag_summarize(self, query:str) -> str:

        context_docs = self.retriever_docs(query)

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

if __name__ == '__main__':
    rag = RagSummarizeService()

    print(rag.rag_summarize("上海适合去那些地方？"))