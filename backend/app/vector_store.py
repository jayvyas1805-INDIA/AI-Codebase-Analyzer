"""
Vector store for RAG (Phase 5a).

Builds a fresh, in-memory ChromaDB collection for EACH analysis request,
containing every parsed CSS rule, import statement, and JSX className usage
as a separate embedded "document". This lets the explanation step retrieve
context beyond just the exact issue — e.g. the import that connects a JSX
file to the CSS file defining its classes, or other rules touching the
same class name.

Uses Ollama for embeddings (see llm_client.py) instead of ChromaDB's default
embedding model, per the project's "open-source, self-hosted" requirement.
"""
from typing import List, Optional

import chromadb
from chromadb import Documents, EmbeddingFunction, Embeddings

from .models import CSSFileParseResult, JSXFileParseResult
from .llm_client import call_ollama_embedding


class OllamaEmbeddingFunction(EmbeddingFunction):
    def __call__(self, input: Documents) -> Embeddings:
        return [call_ollama_embedding(text) for text in input]


def build_context_collection(
    css_results: List[CSSFileParseResult], jsx_results: List[JSXFileParseResult]
):
    """
    Raises if Ollama/embeddings aren't reachable — the caller (main.py)
    decides how to degrade gracefully (skip RAG, still return issues).
    """
    client = chromadb.Client()  # in-memory; nothing persists after this request
    collection = client.create_collection(
        name="project_context",
        embedding_function=OllamaEmbeddingFunction(),
    )

    documents, metadatas, ids = [], [], []
    doc_id = 0

    for css_result in css_results:
        for rule in css_result.rules:
            decl_text = "; ".join(f"{d.property}: {d.value}" for d in rule.declarations)
            documents.append(
                f"CSS rule in {rule.file_path} (line {rule.line_number}): "
                f"selector '{rule.selector}' sets {decl_text}."
            )
            metadatas.append({"type": "css_rule", "file_path": rule.file_path})
            ids.append(f"doc-{doc_id}")
            doc_id += 1

    for jsx_result in jsx_results:
        for imp in jsx_result.imports:
            target = f" (resolved to {imp.resolved_path})" if imp.resolved_path else ""
            documents.append(f"{jsx_result.file_path} imports '{imp.source}'{target}")
            metadatas.append({"type": "import", "file_path": jsx_result.file_path})
            ids.append(f"doc-{doc_id}")
            doc_id += 1

        for usage in jsx_result.class_name_usages:
            classes = ", ".join(usage.static_classes) if usage.static_classes else "(none static)"
            documents.append(
                f"JSX element <{usage.element}> in {jsx_result.file_path} "
                f"(line {usage.line_number}) uses className(s): {classes}."
            )
            metadatas.append({"type": "jsx_usage", "file_path": jsx_result.file_path})
            ids.append(f"doc-{doc_id}")
            doc_id += 1

    if documents:
        collection.add(documents=documents, metadatas=metadatas, ids=ids)

    return collection


def retrieve_context(collection, query_text: str, top_k: int = 5) -> List[str]:
    if collection is None or collection.count() == 0:
        return []
    results = collection.query(query_texts=[query_text], n_results=min(top_k, collection.count()))
    return results["documents"][0] if results["documents"] else []
