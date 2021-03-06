from __future__ import unicode_literals

import os
import sys
import datetime
import logging
import subprocess
import eeUtil
import requests
from bs4 import BeautifulSoup
import urllib.request

# Sources for nrt data
SOURCE_URL = 'https://portal.nccs.nasa.gov/datashare/GlobalFWI/v2.0/fwiCalcs.GEOS-5/Default/GPM.LATE.v5/{year}/FWI.GPM.LATE.v5.Daily.Default.{date}.nc'

SDS_NAMES = ['NETCDF:"{fname}":GPM.LATE.v5_FWI', 'NETCDF:"{fname}":GPM.LATE.v5_BUI', 'NETCDF:"{fname}":GPM.LATE.v5_DC',
             'NETCDF:"{fname}":GPM.LATE.v5_DMC', 'NETCDF:"{fname}":GPM.LATE.v5_FFMC', 'NETCDF:"{fname}":GPM.LATE.v5_ISI']
FILENAME = 'for_012_fire_risk_{date}'
NODATA_VALUE = None
'''
GDAL: Assign a specified nodata value to output bands. Starting with GDAL 1.8.0, can be set to none to avoid setting
a nodata value to the output file if one exists for the source file. Note that, if the input dataset has a nodata 
value, this does not cause pixel values that are equal to that nodata value to be changed to the value specified 
with this option.
'''

DATA_DIR = 'data'
GS_FOLDER = 'for_012_fire_risk'
EE_COLLECTION = 'for_012_fire_risk'
CLEAR_COLLECTION_FIRST = False
DELETE_LOCAL = True

MAX_ASSETS = 7
DATE_FORMAT_NETCDF = '%Y%m%d'
DATE_FORMAT = '%Y%m%d'
TIMESTEP = {'days': 1}

LOG_LEVEL = logging.INFO
DATASET_ID = 'c56ee507-9a3b-41d3-90ac-1406bee32c32'
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

def getUrl(date):
    '''get source url from datestamp'''
    return SOURCE_URL.format(year=date[0:4], date=date)


def getAssetName(date):
    '''get asset name from datestamp'''# os.path.join('home', 'coming') = 'home/coming'
    return os.path.join(EE_COLLECTION, FILENAME.format(date=date))

def getFilename(date):
    '''get filename from datestamp CHECK FILE TYPE'''
    return os.path.join(DATA_DIR, '{}.nc'.format(
        FILENAME.format(date=date)))
        
def getDate(filename):
    '''get last 8 chrs of filename CHECK THIS'''
    return os.path.splitext(os.path.basename(filename))[0][-8:]

def getNewDates(exclude_dates):
    '''Get new dates excluding existing'''
    new_dates = []
    date = datetime.date.today()
    # if anything is in the collection, check back until last uploaded date
    if len(exclude_dates) > 0:
        while (date.strftime(DATE_FORMAT) not in exclude_dates):
            datestr = date.strftime(DATE_FORMAT_NETCDF)
            new_dates.append(datestr)  #add to new dates
            date -= datetime.timedelta(**TIMESTEP)
    #if the collection is empty, make list of most recent 10 days to check
    else:
        for i in range(10):
            datestr = date.strftime(DATE_FORMAT_NETCDF)
            new_dates.append(datestr)  #add to new dates
            date -= datetime.timedelta(**TIMESTEP)
    return new_dates

def convert(files):
    '''convert netcdfs to tifs'''
    tifs = []
    for f in files:
        band_tifs = []
        for sds_name in SDS_NAMES:
            # extract subdataset by name
            sds_path = sds_name.format(fname=f)
            band_tif = '{}_{}.tif'.format(os.path.splitext(f)[0], sds_name.split('_')[-1]) #naming tiffs
            cmd = ['gdal_translate','-q', '-a_nodata', str(NODATA_VALUE), '-a_srs', 'EPSG:4326', sds_path, band_tif] #'-q' means quiet so you don't see it
            logging.debug('Converting {} to {}'.format(f, band_tif))
            subprocess.call(cmd)
            band_tifs.append(band_tif)
        merged_tif = '{}.tif'.format(os.path.splitext(f)[0])  # naming tiffs
        merge_cmd = ['gdal_merge.py', '-seperate'] + band_tifs + ['-o', merged_tif]
        subprocess.call(merge_cmd)
        tifs.append(merged_tif)
    return tifs

def list_available_files(url, ext=''):
    page = requests.get(url).text
    soup = BeautifulSoup(page, 'html.parser')
    return [node.get('href') for node in soup.find_all('a') if type(node.get('href'))==str and node.get('href').endswith(ext)]

def fetch(new_dates):
    files = []
    for date in new_dates:
        # Setup the url of the folder to look for data, and the filename to download to if available
        url = getUrl(date)
        file_date = datetime.datetime.strptime(date, DATE_FORMAT_NETCDF).strftime(DATE_FORMAT)
        f = getFilename(file_date)
        file_name = os.path.split(url)[1]
        file_list = list_available_files(os.path.split(url)[0], ext='.nc')
        if file_name in file_list:
            logging.info('Retrieving {}'.format(file_name))
            try:
                urllib.request.urlretrieve(url, f)
                files.append(f)
                logging.info('Successfully retrieved {}'.format(f))
            except Exception as e:
                logging.error('Unable to retrieve data from {}'.format(url))
                logging.debug(e)
        else:
            logging.info('{} not available yet'.format(file_name))

    return files

def processNewData(existing_dates):
    '''fetch, process, upload, and clean new data'''
    # 1. Determine which files to fetch
    new_dates = getNewDates(existing_dates)

    # 2. Fetch new files
    logging.info('Fetching files')
    files = fetch(new_dates) #get list of locations of netcdfs in docker container

    if files: #if files is empty list do nothing, if something in, convert netcdfs
        # 3. Convert new files
        logging.info('Converting files')
        tifs = convert(files) # naming tiffs

        # 4. Upload new files
        logging.info('Uploading files')
        dates = [getDate(tif) for tif in tifs] #finding date for naming tiffs, returns string
        datestamps = [datetime.datetime.strptime(date, DATE_FORMAT) #list comprehension/for loop
                      for date in dates] #returns list of datetime object
        assets = [getAssetName(date) for date in dates] #create asset nema (imagecollect +tiffname)
        eeUtil.uploadAssets(tifs, assets, GS_FOLDER, datestamps) #puts on GEE

        # 5. Delete local files
        if DELETE_LOCAL:
            logging.info('Cleaning local files')
            for tif in tifs:
                os.remove(tif)
            for f in files:
                os.remove(f)

        return assets
    return []


def checkCreateCollection(collection):
    '''List assests in collection else create new collection'''
    if eeUtil.exists(collection):
        return eeUtil.ls(collection)
    else:
        logging.info('{} does not exist, creating'.format(collection))
        eeUtil.createFolder(collection, True, public=True)
        return []


def deleteExcessAssets(dates, max_assets):
    '''Delete assets if too many'''
    # oldest first
    dates.sort()
    if len(dates) > max_assets:
        for date in dates[:-max_assets]:
            eeUtil.removeAsset(getAssetName(date))


def main():
    '''Ingest new data into EE and delete old data'''
    logging.basicConfig(stream=sys.stderr, level=LOG_LEVEL)
    logging.info('STARTING')
    # Initialize eeUtil and clear collection in GEE if desired
    eeUtil.initJson()
    if CLEAR_COLLECTION_FIRST:
        if eeUtil.exists(EE_COLLECTION):
            eeUtil.removeAsset(EE_COLLECTION, recursive=True)
    # 1. Check if collection exists and create
    existing_assets = checkCreateCollection(EE_COLLECTION) #make image collection if doesn't have one
    existing_dates = [getDate(a) for a in existing_assets]
    # 2. Fetch, process, stage, ingest, clean
    new_assets = processNewData(existing_dates)
    new_dates = [getDate(a) for a in new_assets]
    # 3. Delete old assets
    existing_dates = existing_dates + new_dates
    logging.info('Existing assets: {}, new: {}, max: {}'.format(
        len(existing_dates), len(new_dates), MAX_ASSETS))
    deleteExcessAssets(existing_dates, MAX_ASSETS)
    # 4. Set last update date
    existing_assets = checkCreateCollection(EE_COLLECTION)  # make image collection if doesn't have one
    existing_dates = [getDate(a) for a in existing_assets]
    existing_dates.sort()
    most_recent_date = datetime.datetime.strptime(existing_dates[-1], DATE_FORMAT)
    lastUpdateDate(DATASET_ID, most_recent_date)
    logging.info('SUCCESS')
