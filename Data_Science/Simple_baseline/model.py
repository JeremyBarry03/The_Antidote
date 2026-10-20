"""Model A: degree-two polynomial regression with ridge regularization."""

from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import PolynomialFeatures, StandardScaler


def build_quadratic_regressor(alpha: float) -> Pipeline:
    return Pipeline([
        ("scale", StandardScaler()),
        ("quadratic", PolynomialFeatures(degree=2, include_bias=False)),
        ("ridge", Ridge(alpha=alpha)),
    ])
