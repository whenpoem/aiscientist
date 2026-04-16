from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression


def build():
  X_train = [[0.0], [1.0]]
  y_train = [0, 1]
  model = Pipeline([
      ("scale", StandardScaler()),
      ("clf", LogisticRegression()),
  ])
  model.fit(X_train, y_train)
  return model

