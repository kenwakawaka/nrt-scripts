import os
import logging
import sys
import requests
from collections import OrderedDict
import cartosql
import datetime
import hashlib
import requests

logging.basicConfig(stream=sys.stderr, level=logging.INFO)

### Constants
DATA_DIR = 'data'
# max page size = 10000
DATA_URL = 'https://api.openaq.org/v1/measurements?limit=10000&include_fields=attribution&page={page}'
# always check first 10 pages
MIN_PAGES = 10
MAX_PAGES = 20

# asserting table structure rather than reading from input
PARAMS = ('pm25', 'pm10', 'so2', 'no2', 'o3', 'co', 'bc')
CARTO_TABLES = {
    'pm25':'cit_003a_air_quality_pm25',
    'pm10':'cit_003b_air_quality_pm10',
    'so2':'cit_003c_air_quality_so2',
    'no2':'cit_003d_air_quality_no2',
    'o3':'cit_003e_air_quality_o3',
    'co':'cit_003f_air_quality_co',
    'bc':'cit_003g_air_quality_bc'
}
CARTO_SCHEMA = OrderedDict([
    ("the_geom", "geometry"),
    ("_UID", "text"),
    ("utc", "timestamp"),
    ("value", "numeric"),
    ("parameter", "text"),
    ("location", "text"),
    ("city", "text"),
    ("country", "text"),
    ("unit", "text"),
    ("attribution", "text"),
    ("ppm", "numeric")
])
CARTO_GEOM_TABLE = 'cit_003loc_air_quality'
CARTO_GEOM_SCHEMA = OrderedDict([
    ("the_geom", "geometry"),
    ("_UID", "text"),
    ("location", "text"),
    ("city", "text"),
    ("country", "text")
])


UID_FIELD = '_UID'
TIME_FIELD = 'utc'

CARTO_USER = os.environ.get('CARTO_USER')
CARTO_KEY = os.environ.get('CARTO_KEY')

# Limit to 5M rows / 30 days
MAXROWS = 500000
MAXAGE = datetime.datetime.now() - datetime.timedelta(days=30)

# conversions
UGM3 = ["\u00b5g/m\u00b3", "ug/m3"]
MOL_WEIGHTS = {
    'so2': 64,
    'no2': 46,
    'o3': 48,
    'co': 28
}

DATASET_ID = {
    'pm25':'ae7227d1-8779-4ca4-a2ce-3c87d53c63f6',
    'pm10':'7c36dbb7-6685-4dc7-b285-7476db05cd5e',
    'so2':'764318db-bb4b-442c-b533-8a3c38768a0c',
    'no2':'5b5c7d9b-baf3-4fdf-a41c-e10506b72770',
    'o3':'9d17e2eb-cc26-4743-a2d6-abf1ebc56376',
    'co':'51861c34-f67a-4662-b0b6-1b7f265c6d23',
    'bc':'0c3ed5b9-94b4-4fc5-9208-bf749f0a5052'
}

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

def convert(param, unit, value):
    if param in MOL_WEIGHTS.keys() and unit in UGM3:
        return convert_ugm3_ppm(value, MOL_WEIGHTS[param])
    return value


def convert_ugm3_ppm(ugm3, mol, T=0, P=101.325):
    # ideal gas conversion
    K = 273.15    # 0C
    Atm = 101.325 # kPa
    return float(ugm3)/mol * 22.414 * (T+K)/K * Atm/P / 1000


# Generate UID
def genUID(obs):
    # location should be unique, plus measurement timestamp
    id_str = '{}_{}'.format(obs['location'], obs['date']['utc'])
    return hashlib.md5(id_str.encode('utf8')).hexdigest()


# Generate UID for location
def genLocID(obs):
    return hashlib.md5(obs['location'].encode('utf8')).hexdigest()


# Parse OpenAQ fields
def parseFields(obs, uid, fields):
    row = []
    for field in fields:
        if field == 'the_geom':
            # construct geojson
            if 'coordinates' in obs:
                geom = {
                    "type": "Point",
                    "coordinates": [
                        obs['coordinates']['longitude'],
                        obs['coordinates']['latitude']
                    ]
                }
                row.append(geom)
            else:
                row.append(None)
        elif field == UID_FIELD:
            row.append(uid)
        elif field == TIME_FIELD:
            row.append(obs['date'][TIME_FIELD])
        elif field == 'attribution':
            try:
                obs['attribution']
            except KeyError:
                row_value='NA'
            else:
                row_value = str(obs['attribution'])
            row.append(row_value)
        elif field == 'ppm':
            ppm = convert(obs['parameter'], obs['unit'], obs['value'])
            row.append(ppm)
        else:
            row.append(obs[field])
    return row


def checkCreateTable(table, schema, id_field, time_field=''):
    '''Get existing ids or create table'''
    if cartosql.tableExists(table):
        logging.info('Fetching existing IDs')
        r = cartosql.getFields(id_field, table, f='csv', post=True)
        return r.text.split('\r\n')[1:-1]
    else:
        logging.info('Table {} does not exist, creating'.format(table))
        cartosql.createTable(table, schema)
        cartosql.createIndex(table, id_field, unique=True)
        if time_field:
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

def get_most_recent_date(param):
    r = cartosql.getFields(TIME_FIELD, CARTO_TABLES[param], f='csv', post=True)
    dates = r.text.split('\r\n')[1:-1]
    dates.sort()
    most_recent_date = datetime.datetime.strptime(dates[-1], '%Y-%m-%d %H:%M:%S')
    return most_recent_date

def main():
    logging.info('BEGIN')

    # 1. Get existing uids, if none create tables
    existing_ids = {}
    for param in PARAMS:
        existing_ids[param] = checkCreateTable(CARTO_TABLES[param],
                                               CARTO_SCHEMA, UID_FIELD,
                                               TIME_FIELD)
    # 1.1 Get separate location table uids
    loc_ids = checkCreateTable(CARTO_GEOM_TABLE, CARTO_GEOM_SCHEMA, UID_FIELD)

    # 2. Iterively fetch, parse and post new data
    # this is done all together because OpenAQ endpoint filter by parameter
    # doesn't work
    new_counts = dict(((param, 0) for param in PARAMS))
    new_count = 1
    page = 1
    retries = 0
    # get and parse each page
    # read at least 10 pages; stop when no new results or 100 pages
    while page <= MIN_PAGES or new_count and page < MAX_PAGES:
        logging.info("Fetching page {}".format(page))
        r = requests.get(DATA_URL.format(page=page))
        page += 1
        new_count = 0


        # separate row lists per param
        rows = dict(((param, []) for param in PARAMS))
        loc_rows = []

        # 2.1 parse data excluding existing observations
        try:
            results = r.json()['results']
            for obs in results:
                param = obs['parameter']
                uid = genUID(obs)
                if uid not in existing_ids[param]:
                    existing_ids[param].append(uid)
                    rows[param].append(parseFields(obs, uid, CARTO_SCHEMA.keys()))

                    # 2.2 Check if new locations
                    loc_id = genLocID(obs)
                    if loc_id not in loc_ids and 'coordinates' in obs:
                        loc_ids.append(loc_id)
                        loc_rows.append(parseFields(obs, loc_id,
                                                    CARTO_GEOM_SCHEMA.keys()))

            # 2.3 insert new locations
            if len(loc_rows):
                logging.info('Pushing {} new locations'.format(len(loc_rows)))
                cartosql.insertRows(CARTO_GEOM_TABLE, CARTO_GEOM_SCHEMA.keys(),
                                    CARTO_GEOM_SCHEMA.values(), loc_rows)

            # 2.4 insert new rows
            for param in PARAMS:
                count = len(rows[param])
                if count:
                    logging.info('Pushing {} new {} rows'.format(count, param))
                    cartosql.insertRows(CARTO_TABLES[param], CARTO_SCHEMA.keys(),
                                        CARTO_SCHEMA.values(), rows[param], blocksize=500)
                    new_count += count
                new_counts[param] += count

        # failed to read ['results']
        except Exception as e:
            logging.info("Failed to read results")
            retries += 1
            page -= 1
            if retries > 3:
                raise(e)

    # 3. Remove old observations
    for param in PARAMS:
        logging.info('Total rows: {}, New: {}, Max: {}'.format(
            len(existing_ids[param]), new_counts[param], MAXROWS))
        deleteExcessRows(CARTO_TABLES[param], MAXROWS, TIME_FIELD, MAXAGE)

    for param in PARAMS:
        dataset = DATASET_ID[param]
        most_recent_date = get_most_recent_date(param)
        lastUpdateDate(dataset, most_recent_date)

    logging.info('SUCCESS')
