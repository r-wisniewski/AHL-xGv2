"""
Find optimal hyperparameters for the xG calculation
"""

from sklearn.model_selection import GridSearchCV, train_test_split
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import PolynomialFeatures
from sklearn.pipeline import Pipeline
import SQLDBconnect, json
import pandas as pd
from pathlib import Path

PARAMS_FILE = "ahl_params.json"

def save_params(params, poly_degree, strength):
    """Save params to file"""
    with open(PARAMS_FILE, 'a') as f:
        entry = {"strength": strength, "params": params, "polydegree": poly_degree}
        f.write(json.dumps(entry) + '\n')

def gameint_to_string(st:int) -> str:
    match st:
        case -2 : return "3v5"
        case -1 : return "4v5"
        case 0 : return "Even"
        case 1 : return "5v4"
        case 2 : return "5v3"

if __name__ == "__main__":

    # CONNECT TO POSTGRES DB #
    connection = psycopg2.connect(user = <insert username>,
                                password = <insert password>,
                                host = <insert sql server addr>,
                                port = <insert sql server port number>,
                                database = <insert database name>)

    Path(PARAMS_FILE).unlink(missing_ok=True) #remove file if it exists

    # Degree of polynomial feature expansion for logistic regression.
    # degree=2 adds x^2, y^2, x*y terms (captures angle/distance non-linearity).
    # degree=1 is a plain linear logistic regression.
    poly_degree = 2

    # Define the grid
    param_grid = {
        'logreg__C': [0.1, 0.5, 1.0, 3.0, 5.0, 7.0, 9.0, 10.0, 12.0, 14.0, 20.0, 30.0, 50.0, 100.0],
        'logreg__l1_ratio': [0.0, 1.0],  # 0.0 = l2, 1.0 = l1
        'logreg__solver': ['saga']
    }

    # Build pipeline: polynomial feature expansion -> logistic regression
    pipeline = Pipeline([
        ('poly', PolynomialFeatures(degree=poly_degree, include_bias=False)),
        ('logreg', LogisticRegression(
            max_iter=10000,
            class_weight=None
        ))
    ])

    # Set the table name here
    table_name = "ahlxgfv2"
    # Query to get ALL shots for a given strength
    strength_query = f'''SELECT XLocation, YLocation, Goal FROM {table_name} WHERE Strength = %s;'''

    # Load all shots by strength and fit logistic regression models
    all_shots_by_strength = {}
    for strength_idx in range(-2, 3):  # strengths -2 to 2
        strength_idx = gameint_to_string(strength_idx)
        cursor.execute(strength_query, (strength_idx,))
        matching_records = cursor.fetchall()
        df = pd.DataFrame(matching_records, columns=['XLocation', 'YLocation', 'Goal'])
        all_shots_by_strength[strength_idx] = df
        print(f"Loaded {len(df)} shots for strength {strength_idx}")

    # Run GridSearchCV for each strength
    best_params_by_strength = {}
    for strength_idx in range(-2, 3):
        strength_idx = gameint_to_string(strength_idx)
        df = all_shots_by_strength[strength_idx]

        if df.empty:
            print(f"Skipping strength {strength_idx}: no data.")
            continue
        
        #set your inputs (x) and outputs (y)
        X = df[['XLocation', 'YLocation']].values
        y = df['Goal'].values

        #80/20 split between train and test
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, random_state=42, stratify=y
        )
        
        # n_jobs = -1 means use all processors
        grid_search = GridSearchCV(pipeline, param_grid, cv=5, scoring='roc_auc', n_jobs=-1)
        grid_search.fit(X_train, y_train)

        best_params_by_strength[strength_idx] = grid_search.best_params_
        print(f"Strength {strength_idx} | Best params: {grid_search.best_params_} | "
              f"Best CV AUC: {grid_search.best_score_:.4f} | "
              f"Test AUC: {grid_search.score(X_test, y_test):.4f}")
        save_params(grid_search.best_params_,poly_degree,strength_idx)

    print("\n=== Summary of best params by strength ===")
    for strength_idx, params in best_params_by_strength.items():
        print(f"  Strength {strength_idx}: {params}")