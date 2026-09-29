from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import joblib
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression

from encoder.base import DecisionAdapter
from encoder.models import DecisionExample, DecisionPrediction


class TFIDFLRAdapter(DecisionAdapter):
    """Deterministic baseline adapter combining TF-IDF and Logistic Regression."""

    kind = "tfidf_lr"
    probability_kind = "distribution"

    def __init__(self, name: str = "tfidf_lr", c_param: float = 1.0) -> None:
        self.name = name
        self.c_param = c_param
        self.vectorizer: TfidfVectorizer | None = None
        self.classifier: LogisticRegression | None = None
        self.classes_: list[str] = []

    def fit(
        self,
        train_examples: Sequence[DecisionExample],
        val_examples: Sequence[DecisionExample] | None = None,
        epochs: int = 3,
        batch_size: int = 8,
        learning_rate: float = 5e-5,
    ) -> None:
        """Fit TF-IDF vectorizer and Logistic Regression classifier."""
        texts = [ex.text for ex in train_examples]
        intents = [ex.intent for ex in train_examples]

        self.vectorizer = TfidfVectorizer(
            ngram_range=(1, 2),
            min_df=1,
            sublinear_tf=True,
            strip_accents="unicode",
        )
        x_train = self.vectorizer.fit_transform(texts)

        self.classifier = LogisticRegression(
            C=self.c_param,
            max_iter=1000,
            class_weight="balanced",
            random_state=42,
        )
        self.classifier.fit(x_train, intents)
        self.classes_ = list(self.classifier.classes_)

    def predict(
        self,
        texts: Sequence[str],
        candidate_intents: Sequence[str] | None = None,
        candidate_slots: Sequence[str] | None = None,
    ) -> list[DecisionPrediction]:
        """Predict intent and confidence for texts."""
        if not texts:
            return []

        if self.vectorizer is None or self.classifier is None:
            raise RuntimeError(
                f"TFIDFLRAdapter '{self.name}' must be fitted before predict"
            )

        x_features = self.vectorizer.transform(texts)
        proba_matrix = self.classifier.predict_proba(x_features)

        results: list[DecisionPrediction] = []
        for row in proba_matrix:
            best_idx = int(np.argmax(row))
            best_intent = str(self.classes_[best_idx])
            confidence = float(row[best_idx])
            prob_dict = {
                cls_name: float(p)
                for cls_name, p in zip(self.classes_, row, strict=True)
            }
            results.append(
                DecisionPrediction(
                    intent=best_intent,
                    confidence=confidence,
                    slots=[],  # Lexical baseline does not perform entity extraction
                    probabilities=prob_dict,
                )
            )
        return results

    def save(self, path: str | Path) -> None:
        """Save vectorizer and classifier to disk."""
        target_path = Path(path)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(
            {
                "name": self.name,
                "vectorizer": self.vectorizer,
                "classifier": self.classifier,
                "classes": self.classes_,
            },
            target_path,
        )

    def load(self, path: str | Path) -> None:
        """Load vectorizer and classifier from disk."""
        target_path = Path(path)
        if not target_path.exists():
            raise FileNotFoundError(f"Weights file not found: {target_path}")
        data = joblib.load(target_path)
        self.name = data.get("name", self.name)
        self.vectorizer = data["vectorizer"]
        self.classifier = data["classifier"]
        self.classes_ = data["classes"]
