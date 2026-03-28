"""
Usage: python ahl_goalie.py  
Find each goalie in the db, find all saves and goals lets in by that goalie,
then calculate their delta and total xG
"""
import SQLDBconnect

if __name__ == "__main__":
    # CONNECT TO POSTGRES DB #
    connection, cursor = SQLDBconnect.connect(user = <insert username>,
                                    password = <insert password>,
                                    host = <insert sql server addr>,
                                    port = <insert sql server port number>,
                                    database = <insert database name>)

    #Create goalie table to store goalie stats
    #set the table name here
    table_name = "ahlGoaliexG"
    table_props = {"Goalie":"VARCHAR(80)",
                   "TotalxG":"FLOAT",
                   "SavedxG":"FLOAT",
                   "LetInxG":"FLOAT",
                   "TotalSaves":"INT",
                   "TotalGoals":"INT"}
    if not SQLDBconnect.drop_create_table(connection, cursor, table_name=table_name, table_properties=table_props):
        print(f"Error while creating PostgreSQL table: {table_name}")

    goalies_query = "SELECT DISTINCT Goalie FROM ahlxgfv2;"
    cursor.execute(goalies_query)
    #create list of goalies and format the string
    goalies = cursor.fetchall()
    goalies = [g[0] for g in goalies]
    goalies = [name.replace("'", "''") for name in goalies]
    for goalie in goalies:
        goalie_query = f"SELECT * FROM ahlxgfv2 WHERE Goalie = '{goalie}';"
        cursor.execute(goalie_query)
        records = cursor.fetchall()

        # For each goalie calculate their delta xG
        # Give goalie credit where they save a shot and penalize for letting a goal in
        total_saves = sum(1 for row in records if row[3] == False)
        total_goals = sum(1 for row in records if row[3] == True)
        saved_xG = sum(row[7] for row in records if row[3] == False)
        let_in_xG = sum(row[7] for row in records if row[3] == True)
        total_xG = saved_xG + let_in_xG
        
        query = f"INSERT INTO {table_name} (Goalie, TotalxG, SavedxG, LetInxG, TotalSaves, TotalGoals) VALUES (%s,%s,%s,%s,%s,%s)"
        cursor.execute(query, (goalie,total_xG,saved_xG,let_in_xG,total_saves,total_goals))
        connection.commit()

    #close connection to db
    if not SQLDBconnect.close_connection(connection=connection,cursor=cursor):
        print(f"Error when closing connection to {table_name}")