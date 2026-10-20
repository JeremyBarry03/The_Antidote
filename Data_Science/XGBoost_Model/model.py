"""Model B: ordinary CPU XGBoost, without degradation-aware features/training."""

from xgboost import XGBRegressor

from eta_baselines.configuration import TrainingConfig


def build_xgboost_regressor(
    config: TrainingConfig, depth: int, learning_rate: float,
) -> XGBRegressor:
    return XGBRegressor(
        objective="reg:squarederror",
        eval_metric="mae",
        tree_method="hist",
        device="cpu",
        max_depth=depth,
        learning_rate=learning_rate,
        n_estimators=config.xgboost_max_rounds,
        early_stopping_rounds=config.xgboost_early_stopping_rounds,
        random_state=config.seed,
        n_jobs=config.cpu_threads,
    )
