import time
from datetime import datetime

import app

api_base = 'http://127.0.0.1:5000/'


def test_date_conv() -> None:
    now = datetime(2019, 4, 19, 12, 00, 00)
    test_strings = [
        ('01-01 10:00', datetime(now.year, 1, 1, 10, 00, 00)),
        ('Today 10:00', datetime(2019, 4, 19, 10, 00, 00)),
        ('1 min ago', datetime(2019, 4, 19, 11, 59, 00)),
        ('3 mins ago', datetime(2019, 4, 19, 11, 57, 00)),
        ('01-01 2016', datetime(2016, 1, 1)),
        ('Y-day 10:00', datetime(2019, 4, 18, 10, 00, 00)),
    ]

    for s, dt in test_strings:
        # print('testing date: %s' % s)
        assert app.convert_to_date(s, now) == dt


def test_size_conv() -> None:
    test_strings = [
        ('4.3 EiB', 4.3 * (2**60)),
        ('50 PiB', 50 * 2**50),
        ('45 TiB', 45 * 2**40),
        ('1.0 GiB', 2**30),
        ('100 MiB', 100 * (2**20)),
        ('50 KiB', 50 * (2**10)),
        ('5 B', 5),
    ]

    for s, i in test_strings:
        assert app.convert_to_bytes(s) == i


def test_parse_page() -> None:
    app.cache.clear()

    url = app.TPB_BASE_URL + 'top/207/'
    content = app.fetch_tpb_page(url)
    items = app.parse_page(content)
    assert len(items) > 1
    t = items[0]

    # print(t)

    assert isinstance(t.title, str)
    assert t.title != ''
    assert isinstance(t.magnet, str)
    assert t.magnet.startswith('magnet:')
    assert isinstance(t.upload_time, datetime)
    assert isinstance(t.size, int)
    assert t.size > 0
    assert isinstance(t.seeds, int)
    assert t.seeds > 0
    assert isinstance(t.leeches, int)
    assert t.leeches > 0


def test_parse_imdb_id() -> None:
    app.cache.clear()

    url = app.TPB_BASE_URL + 'torrent/31086814/Glass.2019.1080p.WEBRip.x264-MP4'
    content = app.fetch_tpb_page(url)
    imdb_id = app.parse_imdb_id(content)
    assert imdb_id.startswith('tt')


def test_stalecache() -> None:
    app.cache.clear()

    i = 0
    raise_exc = False

    @app.stalecache('f', 1, 2, 0.2)
    def f() -> int:
        nonlocal i
        i += 1

        if raise_exc:
            raise Exception(i)

        return i

    # first call
    assert f() == 1
    # assert f.last_success
    # assert f.last_failure == 0.0
    # assert f.last_exception is None
    # assert not f.is_stale()
    # assert not f.is_backing_off()

    # return from cache
    time.sleep(0.1)
    # assert not f.is_stale()
    # assert not f.is_backing_off()
    assert f() == 1
    # assert f.last_success
    # assert f.last_failure == 0.0
    # assert f.last_exception is None

    # return cached value in case of exception
    raise_exc = True
    # assert not f.is_stale()
    # assert not f.is_backing_off()
    assert f() == 1
    # assert f.last_success
    # assert f.last_failure == 0.0
    # assert not f.last_exception
    # assert not f.is_backing_off()

    # value is stale, raises exception, return cached value
    time.sleep(1)
    # assert f.is_stale()
    # assert not f.is_backing_off()
    assert f() == 1
    # assert f.last_success == 0.0
    # assert f.last_failure
    # assert f.last_exception
    # assert f.is_backing_off()

    # value is stale but last retry is too close
    # assert f.is_stale()
    # assert f.is_backing_off()
    assert f() == 1
    # assert f.last_success == 0.0
    # assert f.last_failure
    # assert f.last_exception
    # assert f.is_backing_off()

    # can retry now, but still fails, returns cached value
    time.sleep(0.2)
    # assert f.is_stale()
    # assert not f.is_backing_off()
    assert f() == 1
    # assert f.last_success == 0.0
    # assert f.last_failure
    # assert f.last_exception
    # assert f.is_backing_off()

    # backing off, returning cached value
    raise_exc = False
    # assert f.is_stale()
    # assert f.is_backing_off()
    assert f() == 1
    # assert f.last_success == 0.0
    # assert f.last_failure
    # assert f.last_exception
    # assert f.is_backing_off()

    # retry after backoff
    time.sleep(0.2)
    # assert f.is_stale()
    # assert not f.is_backing_off()
    assert f() == 4
    # assert f.last_success
    # assert f.last_failure == 0.0
    # assert not f.last_exception
    # assert not f.is_backing_off()
