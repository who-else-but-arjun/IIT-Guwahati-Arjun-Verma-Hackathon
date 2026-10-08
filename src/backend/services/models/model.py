"""Reusable transformer backbones and task heads for financial text models.

Backbones are loaded from Hugging Face model repositories with ``transformers``.
The task heads are initialized locally and trained on the selected dataset.
"""

from __future__ import annotations

from typing import Callable, Iterable, Optional, Sequence

import torch
from torch import nn
from transformers import AutoModel


class ClassificationHead(nn.Module):
    """Shared MLP head for single-label classification."""

    def __init__(
        self,
        hidden_size: int,
        num_labels: int,
        dropout: float = 0.1,
        head_hidden_sizes: Sequence[int] = (256,),
    ) -> None:
        super().__init__()
        layers = []
        input_size = hidden_size
        for layer_size in head_hidden_sizes:
            layers.extend(
                [
                    nn.Linear(input_size, layer_size),
                    nn.LayerNorm(layer_size),
                    nn.GELU(),
                    nn.Dropout(dropout),
                ]
            )
            input_size = layer_size
        layers.append(nn.Linear(input_size, num_labels))
        self.network = nn.Sequential(*layers)

    def forward(self, pooled_output: torch.Tensor) -> torch.Tensor:
        return self.network(pooled_output)


class RegressionHead(nn.Module):
    """Shared MLP head for predicting one continuous value."""

    def __init__(
        self,
        hidden_size: int,
        dropout: float = 0.1,
        head_hidden_sizes: Sequence[int] = (256,),
    ) -> None:
        super().__init__()
        layers = []
        input_size = hidden_size
        for layer_size in head_hidden_sizes:
            layers.extend(
                [
                    nn.Linear(input_size, layer_size),
                    nn.LayerNorm(layer_size),
                    nn.GELU(),
                    nn.Dropout(dropout),
                ]
            )
            input_size = layer_size
        layers.append(nn.Linear(input_size, 1))
        self.network = nn.Sequential(*layers)

    def forward(self, pooled_output: torch.Tensor) -> torch.Tensor:
        return self.network(pooled_output).squeeze(-1)


class MultiLabelClassificationHead(nn.Module):
    """Shared MLP head for predicting a set of independent labels."""

    def __init__(
        self,
        hidden_size: int,
        num_labels: int,
        dropout: float = 0.2,
        head_hidden_sizes: Sequence[int] = (256,),
    ) -> None:
        super().__init__()
        layers = []
        input_size = hidden_size
        for layer_size in head_hidden_sizes:
            layers.extend(
                [
                    nn.Linear(input_size, layer_size),
                    nn.LayerNorm(layer_size),
                    nn.GELU(),
                    nn.Dropout(dropout),
                ]
            )
            input_size = layer_size
        layers.append(nn.Linear(input_size, num_labels))
        self.network = nn.Sequential(*layers)

    def forward(self, pooled_output: torch.Tensor) -> torch.Tensor:
        # Return logits; callers should use BCEWithLogitsLoss during training.
        return self.network(pooled_output)


class FinancialTransformerModel(nn.Module):
    """Composition base: a pretrained text encoder followed by a task head."""

    def __init__(
        self,
        model_name: str,
        head_factory: Callable[[int], nn.Module],
        **from_pretrained_kwargs,
    ) -> None:
        super().__init__()
        self.encoder = AutoModel.from_pretrained(model_name, **from_pretrained_kwargs)
        config = self.encoder.config
        hidden_size: Optional[int] = getattr(config, "hidden_size", None)
        if hidden_size is None:
            hidden_size = getattr(config, "dim", None) or getattr(config, "d_model", None)
        if hidden_size is None:
            raise ValueError(f"Could not infer hidden size for model {model_name!r}.")

        self.head = head_factory(int(hidden_size))
        self.model_name = model_name

    def forward(
        self,
        input_ids: torch.Tensor,
        attention_mask: Optional[torch.Tensor] = None,
        token_type_ids: Optional[torch.Tensor] = None,
    ) -> torch.Tensor:
        encoder_inputs = {"input_ids": input_ids, "attention_mask": attention_mask}
        if token_type_ids is not None:
            encoder_inputs["token_type_ids"] = token_type_ids
        outputs = self.encoder(**encoder_inputs)

        # BERT-like encoders may expose a pooler; RoBERTa/DistilBERT typically do not.
        pooled_output = getattr(outputs, "pooler_output", None)
        if pooled_output is None:
            pooled_output = outputs.last_hidden_state[:, 0]
        return self.head(pooled_output)

    def fit(
        self,
        train_loader: Iterable,
        *,
        optimizer: torch.optim.Optimizer,
        loss_fn: Callable,
        device: Optional[torch.device] = None,
        validation_fn: Optional[Callable] = None,
        scheduler=None,
        epochs: int = 1,
        patience: Optional[int] = None,
        maximize_metric: bool = False,
        on_improvement: Optional[Callable] = None,
    ) -> list[dict]:
        """Train with a caller-provided optimizer/loss and optional validation callback.

        Batches must be mappings containing model inputs plus ``labels`` (or a
        custom ``loss_fn`` may consume the whole batch). Validation callbacks
        receive ``(model, device)`` and return a scalar score. If supplied,
        ``on_improvement`` receives ``(model, score, epoch)`` after each best
        validation checkpoint, which is a convenient place to persist weights.
        """
        device = device or next(self.parameters()).device
        self.to(device)
        history: list[dict] = []
        best_score = float("-inf") if maximize_metric else float("inf")
        best_state = None
        stale = 0
        for epoch in range(1, epochs + 1):
            self.train()
            loss_total = 0.0
            examples = 0
            for batch in train_loader:
                batch = {k: (v.to(device) if torch.is_tensor(v) else v) for k, v in batch.items()}
                labels = batch.pop("labels", None)
                optimizer.zero_grad(set_to_none=True)
                output = self(**batch)
                loss = loss_fn(output, labels) if labels is not None else loss_fn(output, batch)
                loss.backward()
                torch.nn.utils.clip_grad_norm_(self.parameters(), 1.0)
                optimizer.step()
                if scheduler is not None:
                    scheduler.step()
                n = int(labels.shape[0]) if labels is not None else 1
                loss_total += float(loss.detach()) * n
                examples += n
            row = {"epoch": epoch, "train_loss": loss_total / max(examples, 1)}
            if validation_fn is not None:
                score = float(validation_fn(self, device))
                row["validation_score"] = score
                improved = score > best_score if maximize_metric else score < best_score
                if improved:
                    best_score = score
                    best_state = {k: v.detach().cpu().clone() for k, v in self.state_dict().items()}
                    stale = 0
                    if on_improvement:
                        on_improvement(self, score, epoch)
                else:
                    stale += 1
            history.append(row)
            if validation_fn is not None and patience is not None and stale >= patience:
                break
        if best_state is not None:
            self.load_state_dict(best_state)
        return history

    @torch.inference_mode()
    def infer(self, batch: dict[str, torch.Tensor], device: Optional[torch.device] = None) -> torch.Tensor:
        """Run inference on an already-tokenized batch and return raw head outputs."""
        device = device or next(self.parameters()).device
        self.to(device)
        self.eval()
        inputs = {k: v.to(device) for k, v in batch.items() if k in {"input_ids", "attention_mask", "token_type_ids"}}
        return self(**inputs)


class FinancialTextClassifier(FinancialTransformerModel):
    """Pretrained financial text encoder with a classification head."""

    def __init__(
        self,
        model_name: str,
        num_labels: int = 3,
        dropout: float = 0.1,
        head_hidden_sizes: Sequence[int] = (256,),
        **from_pretrained_kwargs,
    ) -> None:
        super().__init__(
            model_name=model_name,
            head_factory=lambda hidden_size: ClassificationHead(
                hidden_size, num_labels, dropout, head_hidden_sizes
            ),
            **from_pretrained_kwargs,
        )
        self.num_labels = num_labels
        self.dropout = dropout
        self.head_hidden_sizes = tuple(head_hidden_sizes)


class FinancialTextRegressor(FinancialTransformerModel):
    """Pretrained financial text encoder with a scalar regression head."""

    def __init__(
        self,
        model_name: str,
        dropout: float = 0.1,
        head_hidden_sizes: Sequence[int] = (256,),
        **from_pretrained_kwargs,
    ) -> None:
        super().__init__(
            model_name=model_name,
            head_factory=lambda hidden_size: RegressionHead(
                hidden_size, dropout, head_hidden_sizes
            ),
            **from_pretrained_kwargs,
        )
        self.dropout = dropout
        self.head_hidden_sizes = tuple(head_hidden_sizes)


class FinancialTextMultiLabelClassifier(FinancialTransformerModel):
    """Pretrained financial text encoder with independent sigmoid label outputs."""

    def __init__(
        self,
        model_name: str,
        num_labels: int,
        dropout: float = 0.2,
        head_hidden_sizes: Sequence[int] = (256,),
        **from_pretrained_kwargs,
    ) -> None:
        super().__init__(
            model_name=model_name,
            head_factory=lambda hidden_size: MultiLabelClassificationHead(
                hidden_size, num_labels, dropout, head_hidden_sizes
            ),
            **from_pretrained_kwargs,
        )
        self.num_labels = num_labels
        self.dropout = dropout
        self.head_hidden_sizes = tuple(head_hidden_sizes)
