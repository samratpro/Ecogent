import json
import traceback
import pandas as pd
from flaml import AutoML
from sklearn.model_selection import train_test_split

def run_flaml_automl(data_path: str, target_column: str, time_budget: int = 10, task: str = "classification") -> str:
    """
    Run FLAML AutoML on a local CSV dataset to train an ML model.

    Args:
        data_path: Path to the CSV file
        target_column: The name of the column to predict
        time_budget: The time budget for AutoML in seconds
        task: Either 'classification' or 'regression'

    Returns:
        JSON string containing the best model configuration and metrics.
    """
    try:
        df = pd.read_csv(data_path)
        if target_column not in df.columns:
            return json.dumps({"error": f"Target column '{target_column}' not found in data"})

        y = df.pop(target_column)
        X = df

        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

        automl = AutoML()
        automl_settings = {
            "time_budget": time_budget,
            "metric": "accuracy" if task == "classification" else "r2",
            "task": task,
            "log_file_name": "automl.log",
        }

        automl.fit(X_train=X_train, y_train=y_train, **automl_settings)

        # Evaluate
        train_metric = automl.score(X_train, y_train)
        test_metric = automl.score(X_test, y_test)

        result = {
            "best_estimator": automl.best_estimator,
            "best_config": automl.best_config,
            "best_loss": automl.best_loss,
            "train_score": train_metric,
            "test_score": test_metric,
            "metric_used": automl_settings["metric"]
        }
        return json.dumps(result, indent=2)

    except Exception as e:
        return json.dumps({"error": f"AutoML failed: {str(e)}", "traceback": traceback.format_exc()})
