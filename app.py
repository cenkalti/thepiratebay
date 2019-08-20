from gevent.monkey import patch_all; patch_all()  # noqa
from gevent.pywsgi import WSGIServer

import os
import re
import time
import pickle
import hashlib
import logging
from threading import Thread, Event, Lock
from urllib.parse import urljoin
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
from typing import List, Union, NoReturn, Match, Set, Callable, Any, Dict, DefaultDict
from functools import update_wrapper
from collections import defaultdict

from requests import Session
from bs4 import BeautifulSoup
from flask import Flask, jsonify, Response, make_response
from flask.json import JSONEncoder
from diskcache import Cache
from imdb import IMDb

logger = logging.getLogger('thepiratebay')

# These variables can be set via environment variables.
HOST = os.getenv('HOST', '0.0.0.0')
PORT = int(os.getenv('PORT', 5000))
TPB_BASE_URL = os.getenv('TPB_BASE_URL', 'https://thepiratebay.org/')
TMDB_KEY = os.getenv('TMDB_KEY', '')

UPDATE_INTERVAL = 60

TPB_PAGE_REQUEST_TIMEOUT = 30
TPB_PAGE_CACHE_STALE = 60 * 60
TPB_PAGE_CACHE_EXPIRE = 60 * 60 * 24
TPB_PAGE_CACHE_BACKOFF = 60 * 10

TMDB_API_REQUEST_TIMEOUT = 30
TMDB_CONFIG_CACHE_STALE = 60 * 60 * 24
TMDB_CONFIG_CACHE_EXPIRE = 60 * 60 * 24 * 3
TMDB_CONFIG_CACHE_BACKOFF = 60 * 60
TMDB_POSTER_CACHE_STALE = 60 * 60
TMDB_POSTER_CACHE_EXPIRE = 60 * 60 * 24 * 3
TMDB_POSTER_CACHE_BACKOFF = 60 * 10

IMDB_API_REQUEST_TIMEOUT = 30
IMDB_API_CACHE_STALE = 60 * 60
IMDB_API_CACHE_EXPIRE = 60 * 60 * 24 * 3
IMDB_API_CACHE_BACKOFF = 60 * 10

CACHE_READY_WAIT_TIMEOUT = 30
CACHE_DIR = '/tmp/thepiratebay'

LIMIT_NUM_TORRENTS = int(os.getenv('LIMIT_NUM_TORRENTS', '40'))
LIMIT_NUM_MOVIES = int(os.getenv('LIMIT_NUM_MOVIES', '20'))
RETRY_AFTER = 30


# To be able to serialize datetime objects in ISO format.
class CustomJSONEncoder(JSONEncoder):
    def default(self, obj):  # type: ignore
        if isinstance(obj, datetime):
            return obj.isoformat()

        return super().default(obj)


app = Flask(__name__)
app.json_encoder = CustomJSONEncoder

# Fetched pages from TPB and API responses from TMDB are saved in disk cache.
cache = Cache(CACHE_DIR)

# The movie list is empty at first run.
# This event will be set after all torrents, imdb ids and poster links are fetched.
cache_ready = Event()

# Make requests from the same session to be able to reuse HTTP connections.
session = Session()


# Data structure to return in top-movies response
@dataclass
class Torrent:
    title: str
    magnet: str
    upload_time: datetime
    size: int
    seeds: int
    leeches: int
    detail_page: str
    imdb_id: Union[str, None] = None
    imdb_rating: Union[float, None] = None
    poster_url: Union[str, None] = None


# Global list for fetched movies.
# `update` function updates this list at interval.
# `/top-movies` handler reads from this list.
_top_movies: List[Torrent] = []

# This lock is held when reading and updating `_top_movies` list.
_lock = Lock()


# Contains failure info for cache item in order to decide whether to retry operation or return cached exception.
@dataclass
class CacheInfo:
    last_failure: float = 0.0
    last_exception: Union[Exception, None] = None


# Keep last success time along with the value to decide whether the item is stale and needs refresh.
@dataclass
class CacheItem:
    value: Any
    last_success: float


cache_infos: DefaultDict[bytes, CacheInfo] = defaultdict(CacheInfo)


# Our custom cache decorator for coping with unreliable and slow sources.
# Values are considered stale after `stale` seconds and will be refreshed.
# Values expire after `expire` seconds.
# During the period between `stale` and `expire`, exceptions will not raised, instead stale value is returned.
# To reduce number of requests made when the function is raising an exception,
# a `backoff` period is applied and cached exception will be returned.
def stalecache(key: str, stale: float, expire: float, backoff: float) -> Callable:
    class CachedFunction:
        def __init__(self, f: Callable) -> None:
            self.f = f
            update_wrapper(self, f)

        def _make_key(self, args: List[Any], kwargs: Dict[str, Any]) -> bytes:
            m = hashlib.sha1()
            m.update(key.encode())
            m.update(pickle.dumps(args))
            m.update(pickle.dumps(kwargs))
            return m.digest()

        def __call__(self, *args, **kwargs):  # type: ignore
            _key = self._make_key(args, kwargs)
            info = cache_infos[_key]
            _notset = object()  # to distinguish between `None` value and "not in cache"
            now = time.time()
            value, expire_time = cache.get(_key, default=_notset, expire_time=True)

            if value is _notset or now > value.last_success + stale:  # is stale?
                if info.last_exception and (now < info.last_failure + backoff):  # backing off?
                    if value is _notset:
                        raise info.last_exception

                    return value.value  # stale value

                try:
                    value = CacheItem(value=self.f(*args, **kwargs), last_success=now)
                except Exception as e:
                    logger.exception('exception in cached function: %s', self.f.__name__)

                    info.last_failure = now
                    info.last_exception = e

                    if value is _notset:
                        raise

                    return value.value  # stale value

                cache.set(_key, value, expire=expire)
                info.last_failure = 0.0
                info.last_exception = None

            return value.value
    return CachedFunction


@stalecache('get_tmdb_base_url', TMDB_CONFIG_CACHE_STALE, TMDB_CONFIG_CACHE_EXPIRE, TMDB_CONFIG_CACHE_BACKOFF)
def get_tmdb_base_url() -> str:
    CONFIG_PATTERN = 'http://api.themoviedb.org/3/configuration?api_key={key}'
    url = CONFIG_PATTERN.format(key=TMDB_KEY)
    logger.info('getting tmdb config')
    r = session.get(url, timeout=TMDB_API_REQUEST_TIMEOUT)
    config = r.json()
    return config['images']['base_url']


@stalecache('get_tmdb_poster_url', TMDB_POSTER_CACHE_STALE, TMDB_POSTER_CACHE_EXPIRE, TMDB_POSTER_CACHE_BACKOFF)
def get_tmdb_poster_url(imdb_id: str) -> Union[str, None]:
    if not TMDB_KEY:
        return None

    logger.info('getting poster for imdb id: %s', imdb_id)
    CONFIG_PATTERN = 'http://api.themoviedb.org/3/movie/{id}/images?api_key={key}'
    url = CONFIG_PATTERN.format(key=TMDB_KEY, id=imdb_id)
    r = session.get(url, timeout=TMDB_API_REQUEST_TIMEOUT)
    response = r.json()
    posters = response.get('posters')
    if not posters:
        logger.warning('no poster found for: %s', imdb_id)
        return None

    return urljoin(get_tmdb_base_url(), 'original') + posters[0]['file_path']


@stalecache('fetch_tpb_page', TPB_PAGE_CACHE_STALE, TPB_PAGE_CACHE_EXPIRE, TPB_PAGE_CACHE_BACKOFF)
def fetch_tpb_page(url: str) -> str:
    logger.info("fetching tpb page: %s", url)
    return session.get(url, timeout=TPB_PAGE_REQUEST_TIMEOUT).text


ia = IMDb(timeout=IMDB_API_REQUEST_TIMEOUT)


@stalecache('get_imdb_rating', IMDB_API_CACHE_STALE, IMDB_API_CACHE_EXPIRE, IMDB_API_CACHE_BACKOFF)
def get_imdb_rating(imdb_id: str) -> Union[str, None]:
    logger.info("getting imdb rating of: %s", imdb_id)
    imdb_id = imdb_id.lstrip('t')
    movie = ia.get_movie(imdb_id)
    return movie['rating']


# This function runs forever and keep `_top_movies` list up to date.
def update() -> NoReturn:
    global _top_movies
    while True:
        try:
            torrents = fetch_and_parse()
            with _lock:
                _top_movies = torrents

            cache_ready.set()
        except Exception:
            logger.exception('exception in update function')

            with _lock:
                _top_movies = []
        finally:
            time.sleep(UPDATE_INTERVAL)


# Starts `update` function in a daemon thread.
# Must be called before starting to serve requests.
def start() -> None:
    Thread(target=update, daemon=True).start()


def fetch_and_parse() -> List[Torrent]:
    logger.info("fetching top movies...")
    url = urljoin(TPB_BASE_URL, 'top/207/')
    content = fetch_tpb_page(url)
    torrents = parse_page(content)
    fill_imdb_ids(torrents)
    seen_ids: Set[str] = set()
    imdb_torrents: List[Torrent] = []
    for torrent in torrents:
        if torrent.imdb_id:
            if torrent.imdb_id not in seen_ids:
                imdb_torrents.append(torrent)
                seen_ids.add(torrent.imdb_id)

    fill_poster_urls(imdb_torrents)
    fill_ratings(imdb_torrents)
    logger.info("fetched top movies.")
    return imdb_torrents[:LIMIT_NUM_MOVIES]


def fill_poster_urls(torrents: List[Torrent]) -> None:
    for torrent in torrents:
        try:
            torrent.poster_url = get_tmdb_poster_url(torrent.imdb_id)
        except Exception:
            logger.exception('exception while getting poster url')
            continue


def fill_ratings(torrents: List[Torrent]) -> None:
    for torrent in torrents:
        try:
            torrent.imdb_rating = get_imdb_rating(torrent.imdb_id)
        except Exception:
            logger.exception('exception while getting imdb rating')
            continue


def fill_imdb_ids(torrents: List[Torrent]) -> None:
    for torrent in torrents:
        try:
            torrent.imdb_id = get_imdb_id(torrent.detail_page)
        except Exception:
            logger.exception('exception while getting imdb id')
            continue


def get_imdb_id(detail_url: str) -> Union[str, None]:
    detail_url = urljoin(TPB_BASE_URL, detail_url)
    content = fetch_tpb_page(detail_url)
    imdb_id = parse_imdb_id(content)
    if not imdb_id:
        logger.warning('no imdb id found for: %s', detail_url)

    return imdb_id


def parse_imdb_id(content: str) -> Union[str, None]:
    soup = BeautifulSoup(content, 'html.parser')
    items = soup.find('div', id='details')
    links = items.find_all('a', title='IMDB')
    if links:
        m = re.search(r'imdb.com\/title\/(tt\d+)\/', links[0]['href'])
        if m:
            return m.groups()[0]

    return None


def parse_page(content: str) -> List[Torrent]:
    soup = BeautifulSoup(content, 'html.parser')
    rows = soup.find('table', id='searchResult').find_all('tr')[:LIMIT_NUM_TORRENTS + 1]

    now = datetime.utcnow()
    torrents = []
    for row in rows:
        if 'header' not in row.get('class', []):
            torrent = parse_row(row, now)
            torrents.append(torrent)

    return torrents


def parse_row(row: BeautifulSoup, now: datetime) -> Torrent:
    detlink = row.find('a', class_='detLink', href=True)
    detdesc = row.find('font', class_='detDesc')
    desc = [s.strip() for s in detdesc.get_text().replace('\xa0', ' ').split(',')]
    slinfo = row.find_all('td', align='right', recursive=False)
    return Torrent(
            title=detlink.get_text(),
            detail_page=detlink['href'],
            magnet=row.find('a', title='Download this torrent using magnet', href=True)['href'],
            upload_time=convert_to_date(desc[0].split(' ', maxsplit=1)[1], now),
            size=convert_to_bytes(desc[1].split(' ', maxsplit=1)[1]),
            seeds=int(slinfo[0].get_text()),
            leeches=int(slinfo[1].get_text()),
    )


def convert_to_bytes(size_str: str) -> int:
    size_data = size_str.split()
    multipliers = ['B', 'KiB', 'MiB', 'GiB', 'TiB', 'PiB', 'EiB']
    size_magnitude = float(size_data[0])
    multiplier_exp = multipliers.index(size_data[1])
    size_multiplier = 1024 ** multiplier_exp if multiplier_exp > 0 else 1
    return int(size_magnitude * size_multiplier)


def _parse_date_mins_ago(m: Match, now: datetime) -> datetime:
    g = [int(s) for s in m.groups()]
    return now - timedelta(minutes=g[0])


def _parse_date_this_year(m: Match, now: datetime) -> datetime:
    g = [int(s) for s in m.groups()]
    return datetime(now.date().year, g[0], g[1], g[2], g[3])


def _parse_date_today(m: Match, now: datetime) -> datetime:
    g = [int(s) for s in m.groups()]
    return datetime(now.year, now.month, now.day, g[0], g[1])


def _parse_date_yesterday(m: Match, now: datetime) -> datetime:
    yesterday = now.date() - timedelta(days=1)
    g = [int(s) for s in m.groups()]
    return datetime(yesterday.year, yesterday.month, yesterday.day, g[0], g[1])


def _parse_date_default(m: Match, now: datetime) -> datetime:
    g = [int(s) for s in m.groups()]
    return datetime(g[2], g[0], g[1])


_date_patterns = [
        (r'^([0-9]+) mins? ago$', _parse_date_mins_ago),
        (r'^([0-9]*)-([0-9]*)\s([0-9]+):([0-9]+)$', _parse_date_this_year),
        (r'^Today\s([0-9]+)\:([0-9]+)$', _parse_date_today),
        (r'^Y-day\s([0-9]+)\:([0-9]+)$', _parse_date_yesterday),
        (r'^([0-9]*)-([0-9]*)\s([0-9]+)$', _parse_date_default),
]


def convert_to_date(date_str: str, now: datetime) -> datetime:
    for pattern, parser in _date_patterns:
        m = re.search(pattern, date_str.strip())
        if m:
            return parser(m, now)

    raise Exception('cannot parse date: %s' % date_str)


@app.route('/top-movies', methods=['GET'])
def top_movies() -> Response:
    with _lock:
        top_movies = _top_movies

    if not top_movies:
        ready = cache_ready.wait(CACHE_READY_WAIT_TIMEOUT)
        if not ready:
            response = make_response()
            response.status_code = 503
            response.headers.set('retry-after', str(RETRY_AFTER))
            return response

        with _lock:
            top_movies = _top_movies

    return jsonify([asdict(t) for t in top_movies])


if __name__ == '__main__':
    formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(name)s:%(lineno)s - %(message)s')

    handler = logging.StreamHandler()
    handler.setLevel(logging.INFO)
    handler.setFormatter(formatter)

    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

    start()
    server = WSGIServer((HOST, PORT), app)
    server.serve_forever()
