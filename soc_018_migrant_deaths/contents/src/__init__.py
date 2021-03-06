import logging
import sys
import requests
import csv
from collections import OrderedDict
import datetime
import cartosql
import requests
import os

### Constants
SOURCE_URL = "https://missingmigrants.iom.int/global-figures/{year}/csv"
CLEAR_TABLE_FIRST = False
INPUT_DATE_FORMAT = '%B %d, %Y'
DATE_FORMAT = '%Y-%m-%d'
LOG_LEVEL = logging.INFO

### Table name and structure
CARTO_TABLE = 'soc_018_missing_migrants'
CARTO_SCHEMA = OrderedDict([
    ('the_geom', 'geometry'),
    ('uid', 'text'),
    ('Reported_Date', 'timestamp'),
    ('Region', 'text'),
    ('Number_Dead', 'numeric'),
    ('Minimum_Estimated_Number_of_Missing', 'numeric'),
    ('Total_Dead_and_Missing', 'numeric'),
    ('Number_of_Survivors', 'numeric'),
    ('Number_of_Females', 'numeric'),
    ('Number_of_Males', 'numeric'),
    ('Number_of_Children', 'numeric'),
    ('Cause_of_Death', 'text'),
    ('Location_Description', 'text'),
    ('Information_Source', 'text'),
    ('Migration_Route', 'text'),
    ('URL', 'text'),
    ('UNSD_Geographical_Grouping', 'text'),
    ('Source_Quality', 'text')
])
# this data source regularly alternates between names for 'Region'
# any time they use a new name, add it to the REGION_NAMES list
# this script uses whichever of these is in the table as the region so that we don't get an error
REGION_NAMES = ['Region', 'Region of Incident']
UID_FIELD = 'uid'
TIME_FIELD = 'Reported_Date'

# Table limits
MAX_ROWS = 500000
MAX_YEARS = 10
MAX_AGE = datetime.datetime.today() - datetime.timedelta(days=365*MAX_YEARS)

DATASET_ID = 'a0aecb8d-07ee-42e6-be3d-e5cabf12b0a9'
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

def formatDate(date):
    """ Parse input date string and write in output date format """
    return datetime.datetime.strptime(date, INPUT_DATE_FORMAT)\
                            .strftime(DATE_FORMAT)


def processData(existing_ids):
    """
    """
    num_new = 1
    year = datetime.datetime.today().year
    new_ids = []

    while year > MAX_AGE.year and num_new:
        logging.info("Fetching data for {}".format(year))
        res = requests.get(SOURCE_URL.format(year=year))
        csv_reader = csv.reader(res.iter_lines(decode_unicode=True))

        # Get headers as {'key':column#, ...} replacing spaces with underscores
        headers = next(csv_reader, None)
        idx = {}
        for v, k in enumerate(headers):
            if k in REGION_NAMES:
                for name in REGION_NAMES:
                    idx[name.replace(' ', '_')] = v
            else:
                idx[k.replace(' ', '_')] = v
        new_rows = []

        for row in csv_reader:
            if not len(row):
                break
            uid = row[idx['Web_ID']]
            if uid not in existing_ids and uid not in new_ids:
                new_ids.append(uid)
                new_row = []
                for field in CARTO_SCHEMA:
                    if field == UID_FIELD:
                        new_row.append(uid)
                    elif field == TIME_FIELD:
                        date = formatDate(row[idx[TIME_FIELD]])
                        new_row.append(date)
                    elif field == 'the_geom':
                        lon, lat = row[idx['Location_Coordinates']]\
                            .replace(' ', '').split(',')
                        geometry = {
                            'type': 'Point',
                            'coordinates': [float(lon), float(lat)]
                        }
                        new_row.append(geometry)
                    else:
                        v = None if row[idx[field]] == '' else row[idx[field]]
                        new_row.append(v)

                new_rows.append(new_row)

        num_new = len(new_rows)
        if num_new:
            logging.info("Inserting {} new rows".format(num_new))
            cartosql.insertRows(CARTO_TABLE, CARTO_SCHEMA.keys(),
                                CARTO_SCHEMA.values(), new_rows)

    return new_ids

###
## Carto code
###

def checkCreateTable(table, schema, id_field, time_field):
    '''Get existing ids or create table'''
    if cartosql.tableExists(table):
        logging.info('Fetching existing IDs')
        r = cartosql.getFields(id_field, table, f='csv')
        return r.text.split('\r\n')[1:-1]
    else:
        logging.info('Table {} does not exist, creating'.format(table))
        cartosql.createTable(table, schema)
        cartosql.createIndex(table, id_field, unique=True)
        cartosql.createIndex(table, time_field)
    return []


def deleteExcessRows(table, max_rows, time_field, max_age=''):
    '''Delete excess rows by age or count'''
    num_dropped = 0
    if isinstance(max_age, datetime.datetime):
        max_age = max_age.isoformat()

    # 1. delete by age
    if max_age:
        r = cartosql.deleteRows(table, "{} < '{}'".format(time_field, max_age))
        num_dropped = r.json()['total_rows']

    # 2. get sorted ids (old->new)
    r = cartosql.getFields('cartodb_id', table, order='{}'.format(time_field),
                           f='csv')
    ids = r.text.split('\r\n')[1:-1]

    # 3. delete excess
    if len(ids) > max_rows:
        r = cartosql.deleteRowsByIDs(table, ids[:-max_rows])
        num_dropped += r.json()['total_rows']
    if num_dropped:
        logging.info('Dropped {} old rows from {}'.format(num_dropped, table))

def get_most_recent_date(table):
    r = cartosql.getFields(TIME_FIELD, table, f='csv', post=True)
    dates = r.text.split('\r\n')[1:-1]
    dates.sort()
    most_recent_date = datetime.datetime.strptime(dates[-1], '%Y-%m-%d %H:%M:%S')
    return most_recent_date


def main():
    logging.basicConfig(stream=sys.stderr, level=LOG_LEVEL)
    logging.info('STARTING')

    # 1. Check if table exists and create table
    existing_ids = checkCreateTable(CARTO_TABLE, CARTO_SCHEMA, UID_FIELD,
                                    TIME_FIELD)

    # 2. Iterively fetch, parse and post new data
    new_ids = processData(existing_ids)

    new_count = len(new_ids)
    existing_count = new_count + len(existing_ids)
    logging.info('Total rows: {}, New: {}, Max: {}'.format(
        existing_count, new_count, MAX_ROWS))

    # 3. Remove old observations
    deleteExcessRows(CARTO_TABLE, MAX_ROWS, TIME_FIELD, MAX_AGE)

    # Get most recent update date
    if new_count>0:
        most_recent_date = datetime.datetime.utcnow()
        lastUpdateDate(DATASET_ID, most_recent_date)

    logging.info('SUCCESS')
