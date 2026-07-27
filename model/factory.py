import os

from dotenv import load_dotenv
from abc import ABC, abstractmethod
from langchain.chat_models import init_chat_model
from langchain_community.embeddings import DashScopeEmbeddings
from langchain_core.embeddings import Embeddings
from typing import Optional
from langchain_core.language_models import BaseChatModel
from utils.config_handler import rag_conf

load_dotenv()


DashScope_chat_model = init_chat_model(
    model=rag_conf["chat_model_name"],
    model_provider="openai",
    api_key=os.getenv("DASHSCOPE_API_KEY"),
    base_url=os.getenv("DASHSCOPE_URL"),
)

class BaseModelFactory(ABC):
    @abstractmethod
    def generator(self) -> Optional[Embeddings | BaseChatModel]:
        pass

class ChatModelFactory(BaseModelFactory):
    def generator(self) -> BaseChatModel:
        return DashScope_chat_model

class EmbeddingFactory(BaseModelFactory):
    def generator(self) -> Embeddings:
        return DashScopeEmbeddings(
            model=rag_conf["embedding_model_name"],
            dashscope_api_key=os.getenv("DASHSCOPE_API_KEY"),
        )

chat_model: BaseChatModel = ChatModelFactory().generator()
embedding_model: Embeddings = EmbeddingFactory().generator()