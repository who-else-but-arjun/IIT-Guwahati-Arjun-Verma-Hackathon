"""Save, load, and run the selected financial NLP models.

Composite Hugging Face models are stored with their tokenizer and architecture
metadata. Fine-tuned Laya directories are copied intact and loaded through the
Laya package, which preserves the package's native checkpoint format.
"""
from __future__ import annotations

import json
import math
import re
import shutil
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

import torch
from transformers import AutoTokenizer

from . import FinancialTextClassifier, FinancialTextRegressor
from constants import (FLANG_ROBERTA, DEFAULT_SENTIMENT_LABELS,
                       KAGGLE_MODEL_HANDLES, SP100_COMPANIES, STOCK_SELECTOR_TOP_K,
                       STOCK_SELECTOR_TEMPERATURE)


def save_composite_model(model, tokenizer, output_dir, *, task: str, labels=None, max_length=128):
    """Persist a trained composite model and enough metadata to reconstruct it."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    model_config = {
        "task": task,
        "model_name": getattr(model, "model_name", FLANG_ROBERTA),
        "max_length": int(max_length),
        "dropout": getattr(model, "dropout", 0.2),
        "head_hidden_sizes": list(getattr(model, "head_hidden_sizes", (256,))),
    }
    if task == "classification":
        model_config["num_labels"] = model.num_labels
        model_config["labels"] = list(labels or DEFAULT_SENTIMENT_LABELS)
    elif task != "regression":
        raise ValueError("task must be 'classification' or 'regression'")
    model_config["backend"] = "composite_transformer"
    model.cpu()
    torch.save(model.state_dict(), output_dir / "model_state.pt")
    tokenizer.save_pretrained(output_dir / "tokenizer")
    (output_dir / "config.json").write_text(json.dumps(model_config, indent=2), encoding="utf-8")
    return output_dir


def save_laya_model(source_dir, output_dir):
    """Copy a completed native Laya checkpoint directory into artifacts."""
    source_dir, output_dir = Path(source_dir), Path(output_dir)
    if not source_dir.is_dir():
        raise FileNotFoundError(f"Fine-tuned Laya checkpoint directory not found: {source_dir}")
    if output_dir.exists():
        shutil.rmtree(output_dir)
    shutil.copytree(source_dir, output_dir)
    (output_dir / "codex_model_config.json").write_text(
        json.dumps({"backend": "laya", "checkpoint_dir": "."}, indent=2), encoding="utf-8"
    )
    return output_dir


def save_selected_models(*, classification_model, classification_tokenizer,
                         regression_model, regression_tokenizer, laya_checkpoint_dir,
                         output_root=None):
    """Save the selected FLANG-RoBERTa models and fine-tuned Laya checkpoint.

    Call after training/loading the best validation checkpoint for each task.
    """
    output_root = Path(output_root) if output_root is not None else Path(__file__).parent / "artifacts"
    save_composite_model(classification_model, classification_tokenizer,
                         output_root / "flang_roberta_sentiment_classifier",
                         task="classification", labels=DEFAULT_SENTIMENT_LABELS)
    save_composite_model(regression_model, regression_tokenizer,
                         output_root / "flang_roberta_sentiment_regressor", task="regression")
    save_laya_model(laya_checkpoint_dir, output_root / "laya_finetuned")
    return output_root


def load_model(model_key, *, device=None):
    """Download and load a published model from Kaggle Models.

    Accepted keys are ``sentiment_classification``, ``sentiment_scorer``,
    ``flang_laya``, and ``stock_selector``.
    """
    key = str(model_key).strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {"sentiment_regression": "sentiment_scorer", "laya": "flang_laya",
               "ticker_selector": "stock_selector", "classifier": "sentiment_classification"}
    key = aliases.get(key, key)
    handle = KAGGLE_MODEL_HANDLES.get(key)
    if handle is None:
        raise ValueError(f"Unknown Kaggle model {model_key!r}. Choose one of: sentiment_classification, sentiment_scorer, flang_laya, stock_selector")
    try:
        import kagglehub
    except ImportError as exc:
        raise ImportError("Install kagglehub to load the published model: pip install kagglehub") from exc
    model_dir = Path(kagglehub.model_download(handle))
    device = torch.device(device or ("cuda" if torch.cuda.is_available() else "cpu"))
    config_path = model_dir / "config.json"
    if not config_path.exists() and (model_dir / "model_config.json").exists():
        config_path = model_dir / "model_config.json"
    selector_config_path = model_dir / "selector_config.json"
    if selector_config_path.exists():
        from transformers import AutoModel
        config = json.loads(selector_config_path.read_text(encoding="utf-8"))
        if config.get("backend") != "cosine_embedding":
            raise ValueError(f"Unsupported ticker-selector backend in {selector_config_path}")
        model = AutoModel.from_pretrained(model_dir / "encoder")
        model.to(device).eval()
        model.tokenizer = AutoTokenizer.from_pretrained(model_dir / "tokenizer", use_fast=True)
        model.task_config = config
        model._ticker_embedding_cache = None
        return model

    if not config_path.exists():
        laya_config = model_dir / "codex_model_config.json"
        if laya_config.exists():
            import laya
            return laya.Agent(str(model_dir), device=str(device))
        # Native Laya checkpoint from the notebook can also be loaded directly.
        if (model_dir / "rl_agent_config.json").exists():
            import laya
            return laya.Agent(str(model_dir), device=str(device))
        raise FileNotFoundError(f"No model config found in {model_dir}")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    backend = config.get("backend")
    if backend not in {"composite_transformer", "encoder_plus_head"}:
        raise ValueError(f"Unsupported backend in {config_path}")
    model_name = config.get("model_name", config.get("model_id", FLANG_ROBERTA))
    if backend == "encoder_plus_head":
        model_name = str(model_dir / "encoder")
    common = dict(model_name=model_name, dropout=config.get("dropout", 0.2),
                  head_hidden_sizes=tuple(config.get("head_hidden_sizes", [config.get("head_hidden_size", 256)])))
    if config["task"] == "classification":
        labels = config.get("labels") or DEFAULT_SENTIMENT_LABELS
        num_labels = int(config.get("num_labels", len(labels)))
        model = FinancialTextClassifier(**common, num_labels=num_labels)
    elif config["task"] == "regression":
        model = FinancialTextRegressor(**common)
    else:
        raise ValueError(f"Unsupported task: {config['task']}")
    if backend == "encoder_plus_head":
        state = torch.load(model_dir / "head.pt", map_location="cpu", weights_only=True)
        # Kaggle exports may store either the task-head module (keys such as
        # ``network.0.weight``) or the Sequential network alone (``0.weight``).
        if state and not any(key.startswith("network.") for key in state):
            model.head.network.load_state_dict(state)
        else:
            model.head.load_state_dict(state)
    else:
        state = torch.load(model_dir / "model_state.pt", map_location="cpu", weights_only=True)
        model.load_state_dict(state)
    model.to(device).eval()
    model.tokenizer = AutoTokenizer.from_pretrained(model_dir / "tokenizer", use_fast=True)
    model.task_config = config
    return model


@torch.inference_mode()
def infer_text(model: Any, texts: str | Sequence[str], *, batch_size=16):
    """Infer sentiment labels/probabilities or regression scores from raw text."""
    if not isinstance(texts, str) and hasattr(model, "predict_batch"):
        raise TypeError("Laya uses its question-based predict_batch API; call infer_laya instead.")
    is_single = isinstance(texts, str)
    texts = [texts] if is_single else list(texts)
    tokenizer = getattr(model, "tokenizer", None)
    config = getattr(model, "task_config", None)
    if tokenizer is None or config is None:
        raise TypeError("infer_text expects a composite model returned by load_model.")
    device = next(model.parameters()).device
    outputs = []
    for start in range(0, len(texts), batch_size):
        tokens = tokenizer(texts[start:start + batch_size], truncation=True,
                           max_length=config.get("max_length", 128), padding=True,
                           return_tensors="pt")
        logits = model.infer(tokens, device=device)
        if config["task"] == "classification":
            probs = torch.softmax(logits, dim=-1).cpu()
            labels = _labels_in_index_order(
                config.get("labels") or config.get("id2label") or DEFAULT_SENTIMENT_LABELS,
                probs.shape[-1],
            )
            outputs.extend([{"label": labels[int(p.argmax())], "probabilities": dict(zip(labels, p.tolist()))}
                            for p in probs])
        else:
            outputs.extend(logits.float().cpu().tolist())
    return outputs[0] if is_single else outputs


def _labels_in_index_order(labels: Any, count: int) -> list[str]:
    """Normalize list and JSON object label maps to the model's class order."""
    if isinstance(labels, Mapping):
        ordered = []
        for index in range(count):
            value = labels.get(index, labels.get(str(index), labels.get(f"LABEL_{index}")))
            if value is None:
                value = next((name for name, class_index in labels.items()
                              if str(class_index) == str(index)), f"class_{index}")
            ordered.append(str(value))
        return ordered
    ordered = [str(label) for label in labels]
    return (ordered + [f"class_{index}" for index in range(len(ordered), count)])[:count]


def infer_laya(agent, states, question, *, batch_size=8):
    """Run native Laya question-conditioned inference for states and a question."""
    single = isinstance(states, str)
    states = [states] if single else list(states)
    outputs = []
    for start in range(0, len(states), batch_size):
        outputs.extend(agent.predict_batch(states[start:start + batch_size],
                                           {"sentiment": question}, batch_size=batch_size,
                                           sort_by_length=True))
    return outputs[0] if single else outputs


@torch.inference_mode()
def infer_stock_candidates(model, text: str, *, top_k: int | None = None) -> list[dict[str, float | str]]:
    """Shortlist stocks by fusing FLANG embedding similarity and BM25 entity terms."""
    tokenizer = getattr(model, "tokenizer", None)
    config = getattr(model, "task_config", None)
    if tokenizer is None or config is None or config.get("backend") != "cosine_embedding":
        raise TypeError("infer_stock_candidates expects a cosine-embedding selector from load_model().")
    count = max(1, min(int(STOCK_SELECTOR_TOP_K if top_k is None else top_k), len(SP100_COMPANIES)))
    device = next(model.parameters()).device
    cache = getattr(model, "_ticker_embedding_cache", None)
    if cache is None:
        symbols = list(SP100_COMPANIES)
        profiles = [f"{symbol}: {SP100_COMPANIES[symbol]}" for symbol in symbols]
        profile_embeddings = _encode_embeddings(model, tokenizer, profiles, device,
                                                int(config.get("max_length", 128)), batch_size=32)
        cache = (symbols, profile_embeddings)
        model._ticker_embedding_cache = cache
    symbols, profile_embeddings = cache
    article_embedding = _encode_embeddings(model, tokenizer, [str(text)], device,
                                           int(config.get("max_length", 128)), batch_size=1)[0]
    cosine = torch.mv(profile_embeddings, article_embedding).clamp(-1.0, 1.0)
    temperature = max(float(config.get("temperature", STOCK_SELECTOR_TEMPERATURE)), 1e-4)
    relevance = torch.sigmoid(cosine / temperature)
    embedding_order = torch.argsort(cosine, descending=True).tolist()
    keyword_scores = _bm25_company_scores(text, symbols)
    keyword_order = sorted(
        (index for index, score in enumerate(keyword_scores) if score > 0),
        key=lambda index: keyword_scores[index], reverse=True,
    )

    # Reciprocal-rank fusion combines rankings without comparing the model's
    # cosine probabilities directly with BM25's unbounded scores.
    embedding_weight, keyword_weight, rank_constant = 0.65, 0.35, 60
    embedding_ranks = {index: rank for rank, index in enumerate(embedding_order, start=1)}
    keyword_ranks = {index: rank for rank, index in enumerate(keyword_order, start=1)}
    fused_scores = [
        embedding_weight / (rank_constant + embedding_ranks[index])
        + keyword_weight / (rank_constant + keyword_ranks[index])
        for index in range(len(symbols))
    ]
    selected = sorted(range(len(symbols)), key=lambda index: fused_scores[index], reverse=True)[:count]
    max_fused = max((fused_scores[index] for index in selected), default=1.0)
    return [{"ticker": symbols[i], "relevance_score": float(relevance[i].item()),
             "cosine_similarity": float(cosine[i].item()),
             "bm25_score": float(keyword_scores[i]),
             "hybrid_score": float(fused_scores[i] / max_fused) if max_fused else 0.0}
            for i in selected]


def _bm25_company_scores(text: str, symbols: Sequence[str], *, k1: float = 1.5,
                         b: float = 0.75) -> list[float]:
    """Score article terms against each configured ticker and company name."""
    def tokens(value: str) -> list[str]:
        # Keep class tickers such as BRK.B together; one-character terms are
        # handled separately because they are noisy in ordinary prose.
        return [token for token in re.findall(r"[a-z0-9]+(?:\.[a-z0-9]+)?", value.lower())
                if len(token) > 1]

    query = Counter(tokens(str(text or "")))
    query.update(symbol.lower() for symbol in re.findall(r"\$([A-Z])\b", str(text or ""), re.IGNORECASE))
    documents = []
    for symbol in symbols:
        document = tokens(f"{symbol} {SP100_COMPANIES.get(symbol, '')}")
        if len(symbol) == 1:
            document.append(symbol.lower())
        documents.append(document)
    if not query or not documents:
        return [0.0] * len(documents)
    frequencies = [Counter(document) for document in documents]
    document_frequency = Counter(term for counts in frequencies for term in counts)
    average_length = sum(map(len, documents)) / len(documents) or 1.0
    document_count = len(documents)
    scores = []
    for document, counts in zip(documents, frequencies):
        length = len(document)
        score = 0.0
        for term, query_frequency in query.items():
            term_frequency = counts.get(term, 0)
            if not term_frequency:
                continue
            df = document_frequency[term]
            inverse_frequency = math.log(1.0 + (document_count - df + 0.5) / (df + 0.5))
            denominator = term_frequency + k1 * (1.0 - b + b * length / average_length)
            score += inverse_frequency * (term_frequency * (k1 + 1.0) / denominator) * min(query_frequency, 3)
        scores.append(score)
    return scores


@torch.inference_mode()
def _encode_embeddings(model, tokenizer, texts, device, max_length, *, batch_size):
    rows=[]
    for start in range(0, len(texts), batch_size):
        batch=tokenizer(texts[start:start+batch_size], truncation=True, max_length=max_length,
                        padding=True, return_tensors="pt")
        batch={key:value.to(device) for key,value in batch.items() if key in {"input_ids","attention_mask","token_type_ids"}}
        output=model(**batch).last_hidden_state
        mask=batch["attention_mask"].unsqueeze(-1).to(output.dtype)
        pooled=(output*mask).sum(1)/mask.sum(1).clamp(min=1)
        rows.append(torch.nn.functional.normalize(pooled.float(),p=2,dim=-1).cpu())
    return torch.cat(rows,dim=0)


if __name__ == "__main__":
    print("Selected artifacts should be saved under:", Path(__file__).parent / "artifacts")
    print("Use save_selected_models(...) after training and selecting best validation checkpoints.")
