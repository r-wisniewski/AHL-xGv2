"""
Usage: python ahl_xgf_sql_smoothing_v5_regression.py
Take the ahlxgf database & table. Find the shots that are in the vicinity of
the datapoint. Use logistic regression to find the xG for each strength. Update the
same ahlxgf table rather than making new tables for each strength.

- Model is fit once per strength and cached, same as KDE approach
- xG is the predicted probability of a goal from the logistic regression model
"""

from datascience import Table
import SQLDBconnect
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import PolynomialFeatures
from sklearn.pipeline import Pipeline
import numpy as np
import pandas as pd
import json, os, itertools

CHECKPOINT_FILE = "xg_checkpoint.json"
PARAMS_FILE = "ahl_params.json"

# Logistic regression models will be cached per strength to avoid refitting repeatedly
_logreg_cache = {}

def calculate_xg_logreg(x, y, strength, all_strength_data, params, poly_degree):
    """
    Calculate xG using Logistic Regression fitted on entire dataset for a given strength.

    A polynomial feature expansion is applied before fitting so
    the decision boundary can capture non-linear spatial relationships (e.g. shot
    angle, distance from net) without manual feature engineering.

    Args:
        x, y:              Target coordinates (int/float)
        strength:          Game strength index (-2 to 2)
        all_strength_data: DataFrame with ALL shots for this strength
                           Required columns: ['XLocation', 'YLocation', 'Goal']
        poly_degree:       Degree for PolynomialFeatures expansion.

    Returns:
        xG (float): Predicted goal probability capped at 1.0, or 0.0 on failure.
    """
    coordinates = all_strength_data[['XLocation', 'YLocation']].values
    goals = all_strength_data['Goal'].values

    if len(coordinates) < 2:
        return 0.0

    # Need at least one positive and one negative example to fit
    if goals.sum() == 0 or goals.sum() == len(goals):
        # All same class — fall back to the raw shooting percentage
        return float(goals.mean())

    cache_key = strength
    tuned_params = params[strength]
    if cache_key not in _logreg_cache:
        # Build pipeline: polynomial feature expansion -> logistic regression
        pipeline = Pipeline([
            ('poly', PolynomialFeatures(degree=poly_degree, include_bias=False)),
            ('logreg', LogisticRegression(
                max_iter=1000,
                solver=tuned_params['logreg__solver'],
                C=tuned_params['logreg__C'],
                l1_ratio=tuned_params['logreg__l1_ratio'],   # Regularisation strength (inverse). Lower values smooth more. Higher values tighen fit to data.
                #class_weight='balanced'  # Compensates for class imbalance (few goals vs shots)
                class_weight=None
            ))
        ])
        pipeline.fit(coordinates, goals)
        _logreg_cache[cache_key] = pipeline
        print(f"  [Logistic Regression] Fitted model for strength: {strength} using C: {tuned_params['logreg__C']}"
              f" on {len(coordinates)} shots ({int(goals.sum())} goals)")
    else:
        pipeline = _logreg_cache[cache_key]

    # Predict probability of goal (class == 1) at target location
    target = np.array([[x, y]])
    xG = pipeline.predict_proba(target)[0][1]  # index 1 = P(goal)
    xG = min(1.0, float(xG)) 
    return xG

def load_params():
    """Load the params from file"""
    best_params = {}
    if os.path.exists(PARAMS_FILE):
        with open(PARAMS_FILE, 'r') as f:
            for line in f:
                entry = json.loads(line)
                best_params[entry['strength']] = entry['params']
                poly_degree = entry["polydegree"]
        return best_params, poly_degree
    return "No parameter file or parameter values exist" #default

def load_checkpoint():
    """Load the last processed point from checkpoint file"""
    if os.path.exists(CHECKPOINT_FILE):
        with open(CHECKPOINT_FILE, 'r') as f:
            return json.load(f)
    return {"row_index": 0} #default

def save_checkpoint(row_index, strength):
    """Save current progress to checkpoint file"""
    with open(CHECKPOINT_FILE, 'w') as f:
        json.dump({"row_index": row_index}, f)

if __name__ == "__main__":

        # CONNECT TO POSTGRES DB #
        connection, cursor = SQLDBconnect.connect(user = <insert username>,
                                    password = <insert password>,
                                    host = <insert sql server addr>,
                                    port = <insert sql server port number>,
                                    database = <insert database name>)

        # Locations to score
        locations = Table.read_table("input_simple.csv")

        # Load parameters
        tuned_parameters, poly_degree = load_params() #get parameters and poly_degree

        # Load checkpoint
        checkpoint = load_checkpoint()
        start_row = checkpoint["row_index"]

        # Set the table name here
        update_query = "UPDATE ahlxgfcomplete SET xG = %s WHERE XLocation = %s AND YLocation = %s AND Strength = %s;"
        # Query to get ALL shots for a given strength
        strength_query = '''SELECT XLocation, YLocation, Goal FROM ahlxgfv2 WHERE Strength = %s;'''
        updates = []

        # Pre-load all shots by strength and fit logistic regression models
        all_shots_by_strength = {}
        for strength_idx in range(-2,3): #strengths -2 to 2
            cursor.execute(strength_query, (strength_idx,))
            matching_records = cursor.fetchall()
            df = pd.DataFrame(matching_records, columns=['XLocation', 'YLocation', 'Goal'])
            all_shots_by_strength[strength_idx] = df
            print(f"Loaded {len(df)} shots for strength {strength_idx}")

            # Pre-fit the model now so the main loop doesn't stall on first hit
            if not df.empty:
                calculate_xg_logreg(0, 0, strength_idx, df, tuned_parameters, poly_degree)

        #Run all xG calcs on the logistic regression models
        for row_idx, row in enumerate(itertools.islice(locations.rows, start_row, None)):
            row_idx = row_idx + start_row  # Adjust index since islice shifts it

            x, y = int(row[0]), int(row[1]) #grab the x,y coords

            for i in range(-2, 3): #-2 to 2 are the strengths
                # Use pre-loaded shots for this strength
                df = all_shots_by_strength[i]

                if df.empty:
                    continue  # Skip xG calculation if df is empty
                
                # Calc xG using the tuned and prefit models
                xG = calculate_xg_logreg(x, y, i, df, tuned_parameters, poly_degree)

                print(f"Expected goals for ({x} , {y}) is {xG:.4f} at strength {i}")
                if xG != 0.0:
                    updates.append((xG, x, y, i))  # Only append where xG != 0.0

                if x % 10 == 0 and y == 150 and i == 0 and x > 0:  # Commit every 10 x's
                    cursor.executemany(update_query, updates)
                    connection.commit()
                    updates = []
                    # Save checkpoint after each write to the DB
                    save_checkpoint(row_idx, i)
                    print("Commit Successful")

        if updates:  # Finish writing any "left over" data
            cursor.executemany(update_query, updates)
            connection.commit()
            print("Commit Successful")

        if connection:  # Close connection
            SQLDBconnect.close_connection(connection, cursor)

        # Clear checkpoint on successful completion
        if os.path.exists(CHECKPOINT_FILE):
            os.remove(CHECKPOINT_FILE)