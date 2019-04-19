import os
import re
from datetime import datetime, timedelta

import requests
from bs4 import BeautifulSoup
from flask import Flask, jsonify
from flask_cors import CORS


app = Flask(__name__)
CORS(app)

BASE_URL = os.getenv('BASE_URL', 'https://thepiratebay.org/')


@app.route('/top/<int:cat>/', methods=['GET'])
def top_torrents(cat=0):
    if cat == 0:
        url = BASE_URL + 'top/' + 'all/'
    else:
        url = BASE_URL + 'top/' + str(cat) + '/'
    return jsonify(parse_page(url)), 200


@app.route('/search/', methods=['GET'])
@app.route('/search/<term>/', methods=['GET'])
@app.route('/search/<term>/<int:page>/', methods=['GET'])
def search_torrents(term=None, page=0):
    if term is None:
        return 'No search term entered<br/>Format for search: /search/search_term/page_no(optional)/', 404

    url = BASE_URL + 'search/' + str(term) + '/' + str(page) + '/'
    return jsonify(parse_page(url)), 200


def parse_page(url):
    '''
    This function parses the page and returns list of torrents
    '''
    data = requests.get(url).text
    soup = BeautifulSoup(data, 'lxml')
    table_present = soup.find('table', {'id': 'searchResult'})
    if table_present is None:
        return []
    titles = parse_titles(soup)
    magnets = parse_magnet_links(soup)
    times, sizes, uploaders = parse_description(soup)
    seeders, leechers = parse_seed_leech(soup)
    cat, subcat = parse_cat(soup)
    torrents = []
    for torrent in zip(titles, magnets, times, sizes, uploaders, seeders, leechers, cat, subcat):
        torrents.append({
            'title': torrent[0],
            'magnet': torrent[1],
            'time': convert_to_date(torrent[2]),
            'size': convert_to_bytes(torrent[3]),
            'uploader': torrent[4],
            'seeds': int(torrent[5]),
            'leeches': int(torrent[6]),
            'category': torrent[7],
            'subcat': torrent[8],
        })

    return torrents


def parse_magnet_links(soup):
    '''
    Returns list of magnet links from soup
    '''
    magnets = soup.find('table', {'id': 'searchResult'}).find_all('a', href=True)
    magnets = [magnet['href'] for magnet in magnets if 'magnet' in magnet['href']]
    return magnets


def parse_titles(soup):
    '''
    Returns list of titles of torrents from soup
    '''
    titles = soup.find_all(class_='detLink')
    titles[:] = [title.get_text() for title in titles]
    return titles


def parse_description(soup):
    '''
    Returns list of time, size and uploader from soup
    '''
    description = soup.find_all('font', class_='detDesc')
    description[:] = [desc.get_text().split(',') for desc in description]
    times, sizes, uploaders = map(list, zip(*description))
    times[:] = [time.replace(u'\xa0', u' ').replace('Uploaded ', '') for time in times]  # type: ignore
    sizes[:] = [size.replace(u'\xa0', u' ').replace(' Size ', '') for size in sizes]  # type: ignore
    uploaders[:] = [uploader.replace(' ULed by ', '') for uploader in uploaders]  # type: ignore
    return times, sizes, uploaders


def parse_seed_leech(soup):
    '''
    Returns list of numbers of seeds and leeches from soup
    '''
    slinfo = soup.find_all('td', {'align': 'right'})
    seeders = slinfo[::2]
    leechers = slinfo[1::2]
    seeders[:] = [seeder.get_text() for seeder in seeders]
    leechers[:] = [leecher.get_text() for leecher in leechers]
    return seeders, leechers


def parse_cat(soup):
    '''
    Returns list of category and subcategory
    '''
    cat_subcat = soup.find_all('center')
    cat_subcat[:] = [c.get_text().replace('(', '').replace(')', '').split() for c in cat_subcat]
    cat = [cs[0] for cs in cat_subcat]
    subcat = [' '.join(cs[1:]) for cs in cat_subcat]
    return cat, subcat


def convert_to_bytes(size_str):
    '''
    Converts torrent sizes to a common count in bytes.
    '''
    size_data = size_str.split()

    multipliers = ['B', 'KiB', 'MiB', 'GiB', 'TiB', 'PiB', 'EiB']

    size_magnitude = float(size_data[0])
    multiplier_exp = multipliers.index(size_data[1])
    size_multiplier = 1024 ** multiplier_exp if multiplier_exp > 0 else 1

    return size_magnitude * size_multiplier


def convert_to_date(date_str):
    '''
    Converts the dates into a proper standardized datetime.
    '''

    date_format = None

    if re.search('^[0-9]+ min(s)? ago$', date_str.strip()):
        minutes_delta = int(date_str.split()[0])
        torrent_dt = datetime.now() - timedelta(minutes=minutes_delta)
        date_str = '{}-{}-{} {}:{}'.format(
                torrent_dt.year, torrent_dt.month, torrent_dt.day, torrent_dt.hour, torrent_dt.minute)
        date_format = '%Y-%m-%d %H:%M'

    elif re.search(r'^[0-9]*-[0-9]*\s[0-9]+:[0-9]+$', date_str.strip()):
        today = datetime.today()
        date_str = '{}-'.format(today.year) + date_str
        date_format = '%Y-%m-%d %H:%M'

    elif re.search(r'^Today\s[0-9]+\:[0-9]+$', date_str):
        today = datetime.today()
        date_str = date_str.replace('Today', '{}-{}-{}'.format(today.year, today.month, today.day))
        date_format = '%Y-%m-%d %H:%M'

    elif re.search(r'^Y-day\s[0-9]+\:[0-9]+$', date_str):
        today = datetime.today() - timedelta(days=1)
        date_str = date_str.replace('Y-day', '{}-{}-{}'.format(today.year, today.month, today.day))
        date_format = '%Y-%m-%d %H:%M'

    else:
        date_format = '%m-%d %Y'

    return datetime.strptime(date_str, date_format)
