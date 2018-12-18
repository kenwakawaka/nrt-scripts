import logging
import sys
import os
import requests as req
import datetime
import pandas as pd
import cartoframes
import requests


### Constants
SOURCE_URL = "https://ngdc.noaa.gov/nndc/struts/results?type_0=Exact&query_0=$ID&t=101650&s=69&d=59&dfn=tsevent.txt"

DATE_FORMAT = '%Y-%m-%dT%H:%M:%SZ'
LOG_LEVEL = logging.INFO

### Table name and structure
CARTO_TABLE = 'dis_009_tsunamis'
DATASET_ID = '2fb159b3-e613-40ec-974c-21b22c930ce4'
def lastUpdateDate(dataset, date):
   apiUrl = 'http://api.resourcewatch.org/v1/dataset/{0}'.format(dataset)
   headers = {
   'Content-Type': 'application/json',
   'Authorization': os.getenv('apiToken')
   }
   body = {
       "dataLastUpdated": date.isoformat()
   }
   try:
       r = requests.patch(url = apiUrl, json = body, headers = headers)
       logging.info('[lastUpdated]: SUCCESS, '+ date.isoformat() +' status code '+str(r.status_code))
       return 0
   except Exception as e:
       logging.error('[lastUpdated]: '+str(e))

DATASET_ID =  '2fb159b3-e613-40ec-974c-21b22c930ce4'

def lastUpdateDate(dataset, date):
    apiUrl = 'http://api.resourcewatch.org/v1/dataset/{0}'.format(dataset)
    headers = {
    'Content-Type': 'application/json',
    'Authorization': os.getenv('apiToken')
    }
    body = {
        "dataLastUpdated": date.isoformat()
    }
    try:
        r = requests.patch(url = apiUrl, json = body, headers = headers)
        logging.info('[lastUpdated]: SUCCESS, '+ date.isoformat() +' status code '+str(r.status_code))
        return 0
    except Exception as e:
        logging.error('[lastUpdated]: '+str(e))

###
## Accessing remote data
###

def create_date(year, month, day, hour, minute, second):
    if year:
        try:
            year = int(year)
            month = int(month) if month else 1
            day = int(day) if day else 1
            hour = int(hour) if hour else 1
            minute = int(minute) if minute else 1
            second = int(float(second)) if second else 1
            return datetime(year, month, day, hour, minute, second).strftime(DATE_FORMAT)
        except Exception as e:
            pass
            #logging.error(year, month, day, hour, minute, second)
            #logging.error(e)
    else:
        pass
        #logging.error('No year!')

def processData():
    """
    Inputs: SOURCE_URL where data is stored
    Actions: Retrives data, creates date column, and returns dataframe
    Output: Dataframe with data
    """

    data = req.get(SOURCE_URL).text
    data = data.split('\n')
    lines = [line.split('\t') for line in data]
    header = lines[0]
    rows = lines[1:]
    df = pd.DataFrame(rows)
    df.columns = header
    df['datetime'] = list(map(lambda dates: create_date(*dates), zip(df['YEAR'],df['MONTH'], df['DAY'], df['HOUR'], df['MINUTE'], df['SECOND'])))

    return(df)

###
## Application code
###

def main():
    logging.basicConfig(stream=sys.stderr, level=LOG_LEVEL)

    ### 1. Authenticate to Carto
    CARTO_USER = os.environ.get('CARTO_USER')
    CARTO_KEY = os.environ.get('CARTO_KEY')


    cc = cartoframes.CartoContext(base_url='https://{}.carto.com/'.format(CARTO_USER),
                                  api_key=CARTO_KEY)

    ### 2. Fetch data from FTP, dedupe, process
    df = processData()

    num_rows = df.shape[0]

    cc.write(df, CARTO_TABLE, overwrite=True, privacy='public')

    lastDate = df.sort_values(by=['datetime'], ascending=False)['datetime'][0]
    lastUpdateDate(DATASET_ID, datetime.datetime.utcnow())
    ### 3. Notify results
    logging.info('Existing rows: {}'.format(num_rows))
    logging.info("SUCCESS")
