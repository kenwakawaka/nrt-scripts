from __future__ import unicode_literals

import os
import sys
import urllib
import datetime
import logging
import subprocess
import eeUtil
import urllib.request
from http.cookiejar import CookieJar
from ftplib import FTP

# Sources for nrt data
SOURCE_URL = 'ftp://ftp.nccs.nasa.gov/v2.0/fwiCalcs.GEOS-5/Default/GPM.EARLY/{year}/FWI.GPM.EARLY.Daily.Default.{date}.nc'
#SOURCE_URL = 'ftp://GlobalFWI@ftp.nccs.nasa.gov/v2.0/fwiCalcs.GEOS-5/Default/GPM.EARLY/{year}/FWI.GPM.EARLY.Daily.Default.{date}.nc'

SDS_NAME = 'NETCDF:"{fname}":GPM.EARLY_FWI'
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

MAX_ASSETS = 1
DATE_FORMAT_NETCDF = '%Y%m%d'
DATE_FORMAT = '%Y%m%d'
TIMESTEP = {'days': 1}

LOG_LEVEL = logging.INFO

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
    #Old value for 8 day dataset
    #for i in range(MAX_ASSETS*8): #because only updates every 8 days
    for i in range(MAX_ASSETS*1): #because updates every day
        date -= datetime.timedelta(**TIMESTEP) #subtraction and assignments in one step
        datestr = date.strftime(DATE_FORMAT_NETCDF)#of NETCDF because looking for new data in old format
        if date.strftime(DATE_FORMAT) not in exclude_dates:
            new_dates.append(datestr) #add to new dates if have not already seen
    return new_dates
	

#https://gis.stackexchange.com/questions/6669/converting-projected-geotiff-to-wgs84-with-gdal-and-python
def convert(files):
    '''convert netcdfs to tifs'''
    tifs = []
    for f in files:
        # extract subdataset by name
        sds_path = SDS_NAME.format(fname=f)
        tif = '{}.tif'.format(os.path.splitext(f)[0]) #naming tiffs
        #os.path.splitext gets rids of .nc because it makes a list of file name[0] and ext [1]
        #and only takes the file name (splits on last period)
        cmd = ['gdal_translate','-q', '-a_nodata', str(NODATA_VALUE), '-a_srs', 'EPSG:4326', sds_path, tif] #'-q' means quiet so you don't see it
        logging.debug('Converting {} to {}'.format(f, tif))
        subprocess.call(cmd) #using the gdal from command line from inside python
        tifs.append(tif)
    return tifs





def fetch(new_dates):
	# 1. Set up authentication with the urllib.request library
	# not needed here
    username = 'GlobalFWI'
    password = ''

    # 2. Loop over the new dates, check if there is data available, and attempt to download the hdfs
    files = []
    for date in new_dates:
        # Setup the url of the folder to look for data, and the filename to download to if available
        url = getUrl(date)
        file_name = url[-39:]
        #starts as string, strptime changes to datetime object, strfttime reformats into string)
        f = getFilename(date)
        #f = 'C:/Users/amelia.snyder/Github/amsnyder/test/for_012_fire_risk_'+date+'.nc'
        try:
            ftp = FTP('ftp.nccs.nasa.gov', user=username, passwd=password)
            ftp.set_debuglevel(2)
            #ftp.login(user=username, passwd=password)
            logging.info("ftp login successful")
            ftp.cwd('v2.0/fwiCalcs.GEOS-5/Default/GPM.EARLY/'+date[0:4])
            logging.info("navigated to correct directory")
            local_file = open(f, 'wb')
            logging.info("opened local file")
            ftp.retrbinary('RETR '+file_name, local_file.write)
            logging.info("transferred file")
            local_file.close()
            logging.info("closed file")
            ftp.quit()
            logging.info("quit ftp")
            files.append(f)
            logging.info("appended file")
            logging.info('Successfully retrieved {}'.format(f))# gives us "Successully retrieved file name"
        except Exception as e:
            #logging.error('Unable to retrieve data from {}'.format(url))
            logging.info(e)
            logging.info('Unable to retrieve data from {}'.format(url))
            logging.debug(e)
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
    logging.info('SUCCESS')