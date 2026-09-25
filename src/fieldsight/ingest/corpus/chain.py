""" corpus ingestion as a LangChain pipeline: a CorpusDoc in, its cited chunks out """

from langchain_core.documents import Document
from langchain_core.runnables import Runnable, RunnableLambda

from ...types.corpus import CorpusDoc
from .loader import TextractLoader


def chunk_chain() -> Runnable[CorpusDoc, list[Document]]:
    """ one doc through the loader into its cited chunks; run over the corpus with .batch() """

    return RunnableLambda(lambda doc: TextractLoader(doc).load())
