#!/usr/bin/env python3
"""Download the local-only models used by the competition knowledge base."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
from pathlib import Path

os.environ.setdefault("ORT_DISABLE_TELEMETRY", "true")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(".ci-agent/models"),
        help="Model root (default: .ci-agent/models)",
    )
    parser.add_argument("--force", action="store_true", help="Refresh already downloaded Docling assets")
    return parser.parse_args()


def download_huggingface_model(repo_id: str, target: Path, cache_dir: Path) -> None:
    from huggingface_hub import snapshot_download

    target.mkdir(parents=True, exist_ok=True)
    snapshot_download(
        repo_id=repo_id,
        local_dir=target,
        cache_dir=cache_dir,
    )


def main() -> int:
    args = parse_args()
    root = args.root.resolve()
    cache_dir = root / ".huggingface-cache"
    root.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("HF_HOME", str(cache_dir))

    print("Downloading BGE-M3 embedding model...")
    download_huggingface_model(
        "BAAI/bge-m3",
        root / "embeddings" / "bge-m3",
        cache_dir,
    )
    print("Downloading BGE reranker...")
    download_huggingface_model(
        "BAAI/bge-reranker-v2-m3",
        root / "rerankers" / "bge-reranker-v2-m3",
        cache_dir,
    )

    docling_tools = shutil.which("docling-tools")
    if not docling_tools:
        raise RuntimeError("docling-tools is unavailable; run make install first")
    command = [
        docling_tools,
        "models",
        "download",
        "layout",
        "tableformer",
        "rapidocr",
        "--output-dir",
        str(root / "docling"),
    ]
    if args.force:
        command.append("--force")
    print("Downloading Docling and RapidOCR assets...")
    subprocess.run(command, check=True)

    print("Preparing the FastEmbed BM25 cache...")
    from fastembed import SparseTextEmbedding

    SparseTextEmbedding(
        model_name="Qdrant/bm25",
        cache_dir=str(root / "fastembed"),
    )

    print(f"RAG models are ready under {root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
