"""Recursive retriever (with node references)."""

from llama_index import ServiceContext, VectorStoreIndex
from llama_index.llms import OpenAI
from llama_index.embeddings import HuggingFaceEmbedding
from llama_index.node_parser import (
    SentenceSplitter
)
from typing import List, Dict, Any
from llama_index.llama_pack.base import BaseLlamaPack
from llama_index.schema import Document, IndexNode
from llama_index.postprocessor import MetadataReplacementPostProcessor
from llama_index.embeddings import resolve_embed_model
from llama_index.retrievers import RecursiveRetriever
from llama_index.query_engine import RetrieverQueryEngine

class RecursiveRetrieverSmallToBigPack(BaseLlamaPack):
    """Small-to-big retrieval (with recursive retriever).

    Given input documents, and an initial set of "parent" chunks,
    subdivide each chunk further into "child" chunks.
    Link each child chunk to its parent chunk, and index the child chunks.
    
    """

    def __init__(
        self,
        docs: List[Document] = None,
        **kwargs: Any,
    ) -> None:
        """Init params."""
        # create the sentence window node parser w/ default settings
        self.node_parser = SentenceSplitter(chunk_size=1024)
        base_nodes = self.node_parser.get_nodes_from_documents(docs)
        # set node ids to be a constant
        for idx, node in enumerate(base_nodes):
            node.id_ = f"node-{idx}"
        self.embed_model = resolve_embed_model("local:BAAI/bge-small-en")
        self.llm = OpenAI(model="gpt-3.5-turbo")
        self.service_context = ServiceContext.from_defaults(
            llm=self.llm, embed_model=self.embed_model
        )
        # build graph of smaller chunks pointing to bigger parent chunks
        sub_chunk_sizes = [128, 256, 512]
        sub_node_parsers = [SentenceSplitter(chunk_size=c) for c in sub_chunk_sizes]

        all_nodes = []
        for base_node in base_nodes:
            for n in sub_node_parsers:
                sub_nodes = n.get_nodes_from_documents([base_node])
                sub_inodes = [
                    IndexNode.from_text_node(sn, base_node.node_id) for sn in sub_nodes
                ]
                all_nodes.extend(sub_inodes)

            # also add original node to node
            original_node = IndexNode.from_text_node(base_node, base_node.node_id)
            all_nodes.append(original_node)
        all_nodes_dict = {n.node_id: n for n in all_nodes}

        # define recursive retriever
        self.vector_index_chunk = VectorStoreIndex(
            all_nodes, service_context=self.service_context
        )
        vector_retriever_chunk = self.vector_index_chunk.as_retriever(similarity_top_k=2)
        self.recursive_retriever = RecursiveRetriever(
            "vector",
            retriever_dict={"vector": vector_retriever_chunk},
            node_dict=all_nodes_dict,
            verbose=True,
        )
        self.query_engine = RetrieverQueryEngine.from_args(
            self.recursive_retriever, service_context=self.service_context
        )
        

    def get_modules(self) -> Dict[str, Any]:
        """Get modules."""
        return {
            "query_engine": self.query_engine,
            "recursive_retriever": self.recursive_retriever,
            "llm": self.llm,
            "embed_model": self.embed_model,
            "service_context": self.service_context,
        }

    def run(self, *args: Any, **kwargs: Any) -> Any:
        """Run the pipeline."""
        return self.query_engine.query(*args, **kwargs)
