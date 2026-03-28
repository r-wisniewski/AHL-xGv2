import psycopg2, logging
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

logging.basicConfig(level=logging.INFO)

#This class is a context manager for connecting to a PostgreSQL database.
#It handles the connection and cursor creation, and ensures that the connection is closed properly.
class SQLDBconnect:
    #initialize the credentials and db info
    def __init__(self, db_name:str, usr:str, pwd:str, port:str="5432", host:str="127.0.0.1"):
        self.db_name = db_name
        self.usr = usr
        self.pwd = pwd
        self.port = port
        self.host = host

    #create a context manager to handle the connection and cursor
    def __enter__(self):
        self.connection, self.cursor = connect(self.usr, self.pwd, self.db_name)
        return self.connection, self.cursor
    
    #end of context manager
    def __exit__(self, exc_type, exc_val, exc_tb):
        close_connection(self.connection, self.cursor)

#Create a new database
def create_db(db_name:str,usr:str,pwd:str,port:str="5432", host:str="127.0.0.1"):
    con = psycopg2.connect(user = usr,
                                    password = pwd,
                                    host = host,
                                    port = port,
                                    database = "postgres")
    con.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT) 
    cursor = con.cursor()
    db_string = f"CREATE DATABASE {db_name}"
    cursor.execute(db_string)


def connect(user:str,pwd:str,db:str,port:str="5432", host:str="127.0.0.1"):
    # CONNECT TO POSTGRES DB #
    try:
        connection = psycopg2.connect(user = user,
                                    password = pwd,
                                    host = host,
                                    port = port,
                                    database = db)
        #Create cursor object. This will allow us to interact with the database and execute commands
        cursor = connection.cursor()
        # Print PostgreSQL version
        cursor.execute("SELECT version();")
        record = cursor.fetchone()
        print(f"You are connected to - {record}")
    except (Exception, psycopg2.Error) as error :
        logging.error(f"Error while connecting to PostgreSQL {error}")
    
    #return connection and cursor objects
    return connection, cursor

#return true upon success, false upon failure
def create_table(connection, cursor, table_name:str, table_properties:dict) -> bool:
    #Build the create_table string
    create_table = f"CREATE TABLE {table_name} ("
    #Format => key is column name, value is the data type
    for key, value in table_properties.items():
        temp_str = f"{key} {value},\n"
        create_table += temp_str
    #strip off trailing new line & comma
    create_table = create_table[:-2]
    create_table += ")"
    try:
        cursor.execute(create_table)
        connection.commit()
        return True
    except (Exception, psycopg2.DatabaseError) as error :
        logging.error(f"Error while creating PostgreSQL table {error}")
        return False

#return true upon success, false upon failure
def drop_create_table(connection, cursor, table_name:str, table_properties:dict) -> bool:
    #drop previous table if it exists
    try:
        query = f"DROP TABLE IF EXISTS {table_name};"
        cursor.execute(query)
        connection.commit()
        logging.info(f"Table {table_name} has been dropped")
    except (Exception, psycopg2.DatabaseError) as error :
        logging.error(f"An error was encountered dropping the table: {error}")

    #Build the create_table string
    create_table = f"CREATE TABLE {table_name} ("
    #Format => key is column name, value is the data type
    for key, value in table_properties.items():
        temp_str = f"{key} {value},\n"
        create_table += temp_str
    #strip off trailing new line & comma
    create_table = create_table[:-2]
    create_table += ")"
    try:
        cursor.execute(create_table)
        connection.commit()
        return True
    except (Exception, psycopg2.DatabaseError) as error :
        logging.error(f"Error while creating PostgreSQL table {error}")
        return False

#close database connection.
def close_connection(connection, cursor):
    if(connection):
        cursor.close()
        connection.close()
        logging.info("PostgreSQL connection is closed")
        return True
    #return false if no connection exists
    else:
        return False
    
def insert_into_table(cursor, table_name:str, columns:list, *args):
    """Inserts data into the specified table."""
    placeholder = ', '.join(['%s'] * len(args))
    column_str = ', '.join(columns)
    values = f"INSERT INTO {table_name} ({column_str}) VALUES ({placeholder})"
    cursor.execute(values, args)