"""
Usage: python ahl_xgf_sql_scrape_v2_improved.py <latest game ID>

V2 is updated to populate the ahlxgfv2 postgresql database with the shot data, shooter name, goalie name.

IMPROVEMENTS:
- Error handling for failed requests with retry logic
- Robust JSON parsing
- Event validation to catch missing data
- Detailed logging for debugging missed events
- Thread-safe logging
"""

from urllib import request
import requests
import json
import psycopg2
import sys
import numpy as np
from requests.sessions import Session
from concurrent.futures import ThreadPoolExecutor
from threading import local, Lock
from tqdm import tqdm
import logging
from time import sleep

# Configure logging
log = logging.getLogger(__name__)
log.setLevel(logging.INFO)

# File handler - logs everything at INFO level and above
file_handler = logging.FileHandler('scraper.log')
file_handler.setLevel(logging.INFO)
file_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
file_handler.setFormatter(file_formatter)

log.addHandler(file_handler)

def make_url_list() -> list:
    url_list = []
    for n in range(first_game_id, last_game + 1, 1):
        fullurl = f"{url}{n}{end}"
        url_list.append(fullurl)
    return url_list

def request_all(url_list: list) -> None:
    with ThreadPoolExecutor(max_workers=10) as executor:
        executor.map(request_url, url_list)

def get_session() -> Session:
    if not hasattr(thread_local, 'session'):
        thread_local.session = requests.Session()
    return thread_local.session

def extract_json_from_jsonp(resp_text, game_id):
    """Extract JSON from JSONP response (angular.callbacks._8(JSON);)"""
    if not resp_text:
        log.error(f"Game {game_id}: Empty response")
        return None
    
    resp_text = resp_text.rstrip(';').strip()
    
    # Find the JSON content between parentheses
    json_start = resp_text.find('(')
    json_end = resp_text.rfind(')')
    
    if json_start == -1 or json_end == -1:
        log.error(f"Game {game_id}: JSONP format not found. Response starts with: {resp_text[:100]}")
        return None
    
    json_str = resp_text[json_start + 1:json_end]
    
    try:
        json_data = json.loads(json_str)
    except json.JSONDecodeError as e:
        log.error(f"Game {game_id}: JSON parse error - {str(e)}")
        return None
    
    if not isinstance(json_data, list):
        log.warning(f"Game {game_id}: JSON is not a list, got {type(json_data)}")
        return None
    
    return json_data

def request_url(url: str) -> None:
    """Fetch and process a single game URL"""
    game_id = int(url.split('game_id=')[1].split('&')[0])
    max_retries = 3
    retry_count = 0
    
    while retry_count < max_retries:
        try:
            session = get_session()
            resp = session.get(url, timeout=15)
            resp.raise_for_status()
            
            json_data = extract_json_from_jsonp(resp.text, game_id)
            if json_data is None:
                bar.update(1)
                return
            
            # Process the game data
            process_game_events(json_data, game_id)
            bar.update(1)
            return
            
        except requests.exceptions.Timeout:
            retry_count += 1
            if retry_count < max_retries:
                log.warning(f"Game {game_id}: Timeout (attempt {retry_count}/{max_retries}), retrying...")
                sleep(2 ** retry_count)  # Exponential backoff
            else:
                log.error(f"Game {game_id}: Failed after {max_retries} timeout attempts")
                bar.update(1)
                
        except requests.exceptions.RequestException as e:
            log.error(f"Game {game_id}: Request failed - {str(e)}")
            bar.update(1)
            return
            
        except Exception as e:
            log.error(f"Game {game_id}: Unexpected error - {str(e)}")
            bar.update(1)
            return

def safe_get(obj, *keys, default=None):
    """Safely navigate nested dictionaries"""
    current = obj
    for key in keys:
        if isinstance(current, dict):
            current = current.get(key)
        else:
            return default
    return current if current is not None else default

def process_game_events(json_data, game_id):
    """Process all events from a single game"""
    try:
        # Find the two teams from goalie_change events
        team = []
        events_processed = 0
        
        for i in json_data:
            event = safe_get(i, 'event')
            if event == "goalie_change":
                team_id = safe_get(i, 'details', 'team_id')
                if team_id:
                    team.append(team_id)
        
        if len(team) < 2:
            log.warning(f"Game {game_id}: Could not find 2 teams. Found {len(team)}")
            return
        
        Team1 = int(team[0])
        Team2 = int(team[1])
        log.info(f"Game {game_id}: Processing with Team1={Team1}, Team2={Team2}")
        
        # Create strength array
        gametime = np.arange(0, 9999)
        zero_array = np.zeros(9999)
        strengths = np.vstack((gametime, zero_array)).T
        
        # First pass: calculate strength changes from penalties and PP goals
        last_penalty_time = 0
        for event_obj in json_data:
            try:
                event = safe_get(event_obj, 'event')
                
                if event == "penalty":
                    time_raw = safe_get(event_obj, 'details', 'time')
                    if not time_raw:
                        log.warning(f"Game {game_id}: Penalty missing time")
                        continue
                    
                    period = safe_get(event_obj, 'details', 'period', 'id')
                    minutes = safe_get(event_obj, 'details', 'minutes')
                    against_team = safe_get(event_obj, 'details', 'againstTeam', 'id')
                    
                    if not all([period, minutes, against_team]):
                        log.warning(f"Game {game_id}: Penalty missing fields")
                        continue
                    
                    period = int(period)
                    time_parts = time_raw.split(":")
                    if len(time_parts) != 2:
                        log.warning(f"Game {game_id}: Invalid time format in penalty: {time_raw}")
                        continue
                    
                    time = ((period - 1) * 20 * 60) + (int(time_parts[0]) * 60) + int(time_parts[1])
                    length = int(minutes.split(".")[0])
                    against_team = int(against_team)
                    
                    # Team1 goes on the PP
                    if against_team == Team2:
                        last_penalty_time = time + (length * 60)
                        penalty_end = min(time + (length * 60) + 1, 9999)
                        for j in range(time, penalty_end):
                            if int(strengths[j, 1]) < 2:
                                strengths[j, 1] += 1
                    
                    # Team1 goes on the PK
                    elif against_team == Team1:
                        last_penalty_time = time + (length * 60)
                        penalty_end = min(time + (length * 60) + 1, 9999)
                        for j in range(time, penalty_end):
                            if int(strengths[j, 1]) > -2:
                                strengths[j, 1] -= 1
                
                elif event == "goal":
                    pp_goal = safe_get(event_obj, 'details', 'properties', 'isPowerPlay')
                    team_id = safe_get(event_obj, 'details', 'team', 'id')
                    
                    if pp_goal and int(pp_goal) == 1 and team_id:
                        time_raw = safe_get(event_obj, 'details', 'time')
                        period = safe_get(event_obj, 'details', 'period', 'id')
                        
                        if time_raw and period:
                            period = int(period)
                            time_parts = time_raw.split(":")
                            if len(time_parts) == 2:
                                time_of_goal = ((period - 1) * 20 * 60) + (int(time_parts[0]) * 60) + int(time_parts[1])
                                team_id = int(team_id)
                                
                                if team_id == Team1:
                                    for j in range(min(time_of_goal + 1, 9999), min(last_penalty_time + 1, 9999)):
                                        if int(strengths[j, 1]) > -2:
                                            strengths[j, 1] -= 1
                                elif team_id == Team2:
                                    for j in range(min(time_of_goal + 1, 9999), min(last_penalty_time + 1, 9999)):
                                        if int(strengths[j, 1]) < 2:
                                            strengths[j, 1] += 1
            
            except Exception as e:
                log.warning(f"Game {game_id}: Error processing penalty/goal event - {str(e)}")
                continue
        
        # Second pass: Process shots and goals
        shots_processed = 0
        for event_obj in json_data:
            try:
                event = safe_get(event_obj, 'event')
                if event not in ["shot", "goal"]:
                    continue
                
                # Validate all required fields exist
                x_loc = safe_get(event_obj, 'details', 'xLocation')
                y_loc = safe_get(event_obj, 'details', 'yLocation')
                is_goal = safe_get(event_obj, 'details', 'isGoal')
                time_raw = safe_get(event_obj, 'details', 'time')
                period = safe_get(event_obj, 'details', 'period', 'id')
                
                if not all([x_loc is not None, y_loc is not None, is_goal is not None, time_raw, period]):
                    log.debug(f"Game {game_id}: {event} missing location/time/goal data")
                    continue
                
                # Get shooter/goalie
                shooter = safe_get(event_obj, 'details', 'shooter')
                goalie = safe_get(event_obj, 'details', 'goalie')
                
                if not shooter or not goalie:
                    log.debug(f"Game {game_id}: {event} missing shooter/goalie")
                    continue
                
                shooter_name = str(shooter.get('firstName', '')) + ' ' + str(shooter.get('lastName', ''))
                goalie_name = str(goalie.get('firstName', '')) + ' ' + str(goalie.get('lastName', ''))
                
                if not shooter_name.strip() or not goalie_name.strip():
                    log.debug(f"Game {game_id}: Invalid shooter/goalie names")
                    continue
                
                # Get team ID
                if event == "goal":
                    team_id = safe_get(event_obj, 'details', 'team', 'id')
                elif event == "shot":
                    team_id = safe_get(event_obj, 'details', 'shooterTeamId')
                
                if not team_id:
                    log.debug(f"Game {game_id}: {event} missing team ID")
                    continue
                
                # Calculate coordinates
                #xLocation is distance from the net
                xLocation = int(x_loc)
                if xLocation > 593 / 2: #if the goal is for the "other" team
                    xLocation = 593 - xLocation
                
                #yLocation is the distance from the right corner of the boards
                #yLocation = 300 - float(y_loc)
                yLocation = int(y_loc)

                # Get event time
                period = int(period)
                time_parts = time_raw.split(":")
                if len(time_parts) != 2:
                    log.debug(f"Game {game_id}: Invalid time format")
                    continue
                
                event_time = ((period - 1) * 20 * 60) + (int(time_parts[0]) * 60) + int(time_parts[1])
                
                if event_time < 0: #no max set in case its a multiple OT playoff game
                    log.warning(f"Game {game_id}: Event time out of range: {event_time}")
                    continue
                
                # Get strength
                team_id = int(team_id)
                if team_id == Team1:
                    event_strength = int(strengths[event_time, 1])
                else:
                    event_strength = -int(strengths[event_time, 1])
                
                # Insert into database
                values = """INSERT INTO ahlxgfv2 (GameID, XLocation, YLocation, Goal, Strength, Shooter, Goalie, xG) 
                           VALUES (%s,%s,%s,%s,%s,%s,%s,0.0)"""
                
                mutex.acquire()
                try:
                    cursor.execute(values, (game_id, xLocation, yLocation, is_goal, event_strength, shooter_name, goalie_name))
                    connection.commit()
                    shots_processed += 1
                finally:
                    mutex.release()
                    
            except Exception as e:
                log.warning(f"Game {game_id}: Error processing {event} event - {str(e)}")
                continue
        
        log.info(f"Game {game_id}: Successfully processed {shots_processed} shot/goal events")
    
    except Exception as e:
        log.error(f"Game {game_id}: Unexpected error in process_game_events - {str(e)}")

if __name__ == "__main__":
    # Configuration
    first_game_id = 1017122 #from Friday, October 06, 2017
    url = 'https://lscluster.hockeytech.com/feed/index.php?feed=statviewfeed&view=gameCenterPlayByPlay&game_id='
    end = '&key=50c2cd9b5e18e390&client_code=ahl&lang=en&league_id=&callback=angular.callbacks._8'
    
    thread_local = local()
    mutex = Lock()
    
    # Connect to database
    try:
        connection = psycopg2.connect(user = <insert username>,
                                    password = <insert password>,
                                    host = <insert sql server addr>,
                                    port = <insert sql server port number>,
                                    database = <insert database name>)
        cursor = connection.cursor()
        cursor.execute("SELECT version();")
        record = cursor.fetchone()
        log.info(f"Connected to database: {record}")
    except (Exception, psycopg2.Error) as error:
        log.error(f"Error connecting to database: {error}")
        sys.exit(1)
    
    if len(sys.argv) < 2:
        log.error("Error: Please supply the most recent game number")
        sys.exit(1)
    else:
        last_game = int(sys.argv[1])
    
    # Recreate table
    try:
        cursor.execute("DROP TABLE IF EXISTS ahlxgfv2;")
        connection.commit()
        log.info("Dropped existing ahlxgfv2 table")
    except Exception as error:
        log.error(f"Error dropping table: {error}")
    
    try:
        create_table = '''CREATE TABLE ahlxgfv2 ( 
            GameID INT,
            XLocation INT,
            YLocation INT,
            Goal BOOL,
            Strength INT,
            Shooter VARCHAR(80),
            Goalie VARCHAR(80),
            xG FLOAT)'''
        cursor.execute(create_table)
        connection.commit()
        log.info("Created new ahlxgfv2 table")
    except Exception as error:
        log.error(f"Error creating table: {error}")
        sys.exit(1)
    
    # Scrape data
    log.info(f"Starting scrape from game {first_game_id} to {last_game}")
    bar = tqdm(desc="Progress", total=(last_game - first_game_id))
    
    url_list = make_url_list()
    request_all(url_list)
    
    bar.close()
    log.info("Scrape complete")
    
    # Cleanup
    try:
        sql_delete_query = "DELETE FROM ahlxgfv2 WHERE Goal IS NULL"
        cursor.execute(sql_delete_query)
        connection.commit()
        log.info("Cleaned up NULL entries")
    except Exception as error:
        log.error(f"Error during cleanup: {error}")
    
    # Close connection
    cursor.close()
    connection.close()
    log.info("Database connection closed")