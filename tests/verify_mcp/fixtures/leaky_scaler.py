from sklearn.preprocessing import StandardScaler
import pandas as pd


def build():
  scaler = StandardScaler()
  X_train = pd.DataFrame({"x": [0.0, 1.0]})
  X_test = pd.DataFrame({"x": [2.0]})
  scaler.fit(pd.concat([X_train, X_test]))
  return scaler

