# AHL-xGv2

# Purpose
An update to my previous work. I wanted to make a more robust scraper and a better prediction model.

# Getting started

Packages required and SQL DB setup.

## Prerequisites 
1. Install packages
```
pip install -r requirements.txt
```
2. A postgres [SQL Database](https://www.postgresql.org/download/linux/) is required.

## SQL DB Setup

Before you begin, step a SQL database. Note the lines 
```
    connection = psycopg2.connect(user = <insert username>,
                                  password = <insert password>,
                                  host = <insert sql server addr>,
                                  port = <insert sql server port number>,
                                  database = <insert database name>)
```
are commented out in the python scripts. Replace the angle brackets in the above statement with your SQL DB’s information.

# Usage

All four scripts can be run back to back
```
python ahl_xg_sql_scrape.py <latestGameID#>; python ahl_xg_param_tuning.py; python xg_regression.py; python ahl_goalie.py
```

# Results


# Future Work

I would greatly appreciate feedback regarding this code. This project is far from perfect and could definitely be fine tuned in many many ways. 

# Contact

Robin Wisniewski – [LinkedIn](https://www.linkedin.com/in/robin-wisniewski/) –  [wisniewski.ro@gmail.com](mailto:wisniewski.ro@gmail.com)
