""" the corpus as a LangChain document loader """

from collections.abc import Iterator

from langchain_core.document_loaders import BaseLoader
from langchain_core.documents import Document

from ...aws.textract import load_output
from ...errors import ExtractionError
from ...types.corpus import CorpusDoc
from .chunking import split_corpus_doc


class TextractLoader(BaseLoader):
    """ a cracked corpus doc as cited chunks, from the Textract output saved under textract/<doc_id> """

    def __init__(self, doc: CorpusDoc):
        self.doc = doc

    def lazy_load(self) -> Iterator[Document]:
        chunks = split_corpus_doc(self.doc, load_output(f"textract/{self.doc['doc_id']}"))
        if not chunks:
            raise ExtractionError(f"{self.doc['doc_id']}: its Textract output has no layout text or tables; was it cracked with LAYOUT?")
        yield from chunks
