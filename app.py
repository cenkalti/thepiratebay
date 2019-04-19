import os
import re
from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Union

import requests
from bs4 import BeautifulSoup
from flask import Flask, jsonify, Response
from flask_cors import CORS
from flask_caching import Cache


config = {
        'CACHE_TYPE': 'filesystem',
        'CACHE_DIR': '/tmp/thepiratebay',
}

app = Flask(__name__)
app.config.from_mapping(config)

CORS(app)
cache = Cache(app)

BASE_URL = os.getenv('BASE_URL', 'https://thepiratebay.org/')


@app.route('/top-movies', methods=['GET'])
def top_movies() -> Response:
    url = BASE_URL + 'top/207/'
    content = fetch_page(url)
    torrents = parse_page(content)
    return jsonify(torrents)


@cache.memoize(50)
def fetch_page(url: str) -> str:
    return requests.get(url).text


# TODO cache responses
# TODO parse imdb id
# TODO download posters and cache
# TODO return poster link
# TODO serve posters
def parse_page(url: str) -> List[Dict[str, Union[str, int, datetime]]]:
    '''
    This function parses the page and returns list of torrents
    '''
    data = requests.get(url).text
    soup = BeautifulSoup(data)
    table_present = soup.find('table', {'id': 'searchResult'})
    if table_present is None:
        return []

    titles = parse_titles(soup)
    magnets = parse_magnet_links(soup)
    times, sizes, uploaders = parse_description(soup)
    seeders, leechers = parse_seed_leech(soup)
    cat, subcat = parse_cat(soup)
    now = datetime.now()
    torrents = []
    for torrent in zip(titles, magnets, times, sizes, uploaders, seeders, leechers, cat, subcat):
        torrents.append({
            'title': torrent[0],
            'magnet': torrent[1],
            'upload_time': convert_to_date(torrent[2], now),
            'size': convert_to_bytes(torrent[3]),
            'uploader': torrent[4],
            'seeds': int(torrent[5]),
            'leeches': int(torrent[6]),
            'category': torrent[7],
            'subcategory': torrent[8],
        })

    return torrents


def parse_magnet_links(soup: BeautifulSoup) -> List[str]:
    '''
    Returns list of magnet links from soup
    '''
    magnets = soup.find('table', {'id': 'searchResult'}).find_all('a', href=True)
    magnets = [magnet['href'] for magnet in magnets if 'magnet' in magnet['href']]
    return magnets


def parse_titles(soup: BeautifulSoup) -> List[str]:
    '''
    Returns list of titles of torrents from soup
    '''
    titles = soup.find_all(class_='detLink')
    titles = [title.get_text() for title in titles]
    return titles


def parse_description(soup: BeautifulSoup) -> Tuple[List[str], List[str], List[str]]:
    '''
    Returns list of time, size and uploader from soup
    '''
    description = soup.find_all('font', class_='detDesc')
    description = [desc.get_text().split(',') for desc in description]
    times = [d[0].replace(u'\xa0', u' ').replace('Uploaded ', '') for d in description]
    sizes = [d[1].replace(u'\xa0', u' ').replace(' Size ', '') for d in description]
    uploaders = [d[2].replace(' ULed by ', '') for d in description]
    return times, sizes, uploaders


def parse_seed_leech(soup: BeautifulSoup) -> Tuple[str, str]:
    '''
    Returns list of numbers of seeds and leeches from soup
    '''
    slinfo = soup.find_all('td', {'align': 'right'})
    seeders = slinfo[::2]
    leechers = slinfo[1::2]
    seeders = [seeder.get_text() for seeder in seeders]
    leechers = [leecher.get_text() for leecher in leechers]
    return seeders, leechers


def parse_cat(soup: BeautifulSoup) -> Tuple[List[str], List[str]]:
    '''
    Returns list of category and subcategory
    '''
    cat_subcat = soup.find_all('center')
    cat_subcat = [c.get_text().replace('(', '').replace(')', '').split() for c in cat_subcat]
    cat = [cs[0] for cs in cat_subcat]
    subcat = [' '.join(cs[1:]) for cs in cat_subcat]
    return cat, subcat


def convert_to_bytes(size_str: str) -> int:
    '''
    Converts torrent sizes to a common count in bytes.
    '''
    size_data = size_str.split()

    multipliers = ['B', 'KiB', 'MiB', 'GiB', 'TiB', 'PiB', 'EiB']

    size_magnitude = float(size_data[0])
    multiplier_exp = multipliers.index(size_data[1])
    size_multiplier = 1024 ** multiplier_exp if multiplier_exp > 0 else 1

    return size_magnitude * size_multiplier


# TODO remove strptime conversion
def convert_to_date(date_str: str, now: datetime) -> datetime:
    '''
    Converts the dates into a proper standardized datetime.
    '''

    date_format = None

    if re.search('^[0-9]+ min(s)? ago$', date_str.strip()):
        minutes_delta = int(date_str.split()[0])
        torrent_dt = now - timedelta(minutes=minutes_delta)
        date_str = '{}-{}-{} {}:{}'.format(
                torrent_dt.year, torrent_dt.month, torrent_dt.day, torrent_dt.hour, torrent_dt.minute)
        date_format = '%Y-%m-%d %H:%M'

    elif re.search(r'^[0-9]*-[0-9]*\s[0-9]+:[0-9]+$', date_str.strip()):
        today = now.date()
        date_str = '{}-'.format(today.year) + date_str
        date_format = '%Y-%m-%d %H:%M'

    elif re.search(r'^Today\s[0-9]+\:[0-9]+$', date_str):
        today = now.date()
        date_str = date_str.replace('Today', '{}-{}-{}'.format(today.year, today.month, today.day))
        date_format = '%Y-%m-%d %H:%M'

    elif re.search(r'^Y-day\s[0-9]+\:[0-9]+$', date_str):
        today = now.date() - timedelta(days=1)
        date_str = date_str.replace('Y-day', '{}-{}-{}'.format(today.year, today.month, today.day))
        date_format = '%Y-%m-%d %H:%M'

    else:
        date_format = '%m-%d %Y'

    return datetime.strptime(date_str, date_format)


if __name__ == '__main__':
    app.run(debug=True)
