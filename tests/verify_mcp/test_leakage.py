from __future__ import annotations

from pathlib import Path


def _rules(result: dict) -> set[str]:
    return {finding["rule"] for finding in result["findings"]}


def test_leakage_detector_flags_concatenated_fit(workspace):
    impl = workspace["verify_mcp.impl"]
    fixture = Path(__file__).with_name("fixtures") / "leaky_scaler.py"

    result = impl.leakage_check(script_path=str(fixture))

    assert result["clean"] is False
    assert "fit_on_concatenated" in _rules(result)


def test_leakage_detector_flags_reserved_heldout_access(workspace):
    impl = workspace["verify_mcp.impl"]

    result = impl.leakage_check(
        script_text="""
from pathlib import Path

def load():
    return open(Path.home() / ".research-agent" / "held_out" / "eval.csv").read()
"""
    )

    assert result["clean"] is False
    assert "heldout_access" in _rules(result)


def test_leakage_detector_flags_fit_on_eval_split(workspace):
    impl = workspace["verify_mcp.impl"]

    result = impl.leakage_check(
        script_text="""
from sklearn.linear_model import LogisticRegression

def train(X_test, y_test):
    model = LogisticRegression()
    model.fit(X_test, y_test)
    return model
"""
    )

    assert result["clean"] is False
    assert "fit_on_eval_split" in _rules(result)


def test_leakage_detector_flags_split_after_global_transform(workspace):
    impl = workspace["verify_mcp.impl"]

    result = impl.leakage_check(
        script_text="""
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler

def prepare(X, y):
    X_scaled = StandardScaler().fit_transform(X)
    return train_test_split(X_scaled, y, test_size=0.2, random_state=0)
"""
    )

    assert result["clean"] is False
    assert "split_after_global_transform" in _rules(result)


def test_leakage_detector_flags_target_in_features(workspace):
    impl = workspace["verify_mcp.impl"]

    result = impl.leakage_check(
        script_text="""
from sklearn.ensemble import RandomForestClassifier

def train(train_df):
    model = RandomForestClassifier()
    model.fit(train_df, train_df["label"])
    return model
"""
    )

    assert result["clean"] is False
    assert "target_in_features" in _rules(result)


def test_leakage_detector_accepts_clean_pipeline(workspace):
    impl = workspace["verify_mcp.impl"]
    fixture = Path(__file__).with_name("fixtures") / "clean_pipeline.py"

    result = impl.leakage_check(script_path=str(fixture))

    assert result == {"clean": True, "findings": []}


def test_leakage_detector_allows_autoencoder_fit_on_same_tensor(workspace):
    impl = workspace["verify_mcp.impl"]

    result = impl.leakage_check(
        script_text="""
class AutoEncoder:
    def fit(self, X, y):
        return self

def train(X):
    model = AutoEncoder()
    model.fit(X, X)
    return model
"""
    )

    assert result == {"clean": True, "findings": []}
