import requests
import tinys3
import csv
from lxml import html
from bs4 import BeautifulSoup

dataUrl='http://floodobservatory.colorado.edu/Archives/MasterListrev.htm'

def my_parse(html):
    records = []
    table2 = BeautifulSoup(html, "lxml").find_all('table')[0]
    for tr in table2.find_all('tr'):
        tds = tr.find_all('td')
        records.append([elem.text.encode('utf-8').replace("\r\n", "").replace("\xc2\xa0","").replace("#N/A","").replace("Centroid X","longitude").replace("Centroid Y","latitude") for elem in tds])
    return records


r = requests.get(dataUrl)
data = my_parse(r.content)
with open('flood_observatory.csv', 'wb') as f:
    writer = csv.writer(f)
    writer.writerows(data)

conn = tinys3.Connection(S3_ACCESS_KEY,S3_SECRET_KEY,bucket='my_bucket',headers={
            'x-amz-storage-class': 'REDUCED_REDUNDANCY', 'Content-Type':'application/csv'
            },tls=True)

# So we could skip the bucket parameter on every request

f = open('flood_observatory.csv','rb')
conn.upload('/flood_observatory.csv',f)
