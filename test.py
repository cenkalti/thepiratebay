from datetime import datetime

import app

api_base = 'http://127.0.0.1:5000/'


def test_date_conv() -> None:
    '''
    Tests date conversion from string to datetime.
    '''
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
        assert app.convert_to_date(s, now) == dt


def test_size_conv() -> None:
    '''
    Tests string to float conversions for sizes.
    '''
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
    url = app.BASE_URL + 'top/207/'
    items = app.parse_page(url)
    assert len(items) > 1
    t = items[0]

    # from pprint import pprint; pprint(t)

    assert t['category'] == 'Video'
    assert t['subcategory'] == 'HD - Movies'
    assert isinstance(t['title'], str)
    assert t['title'] != ''
    assert isinstance(t['magnet'], str)
    assert t['magnet'].startswith('magnet:')
    assert isinstance(t['uploader'], str)
    assert t['uploader'] != ''
    assert isinstance(t['upload_time'], datetime)
    assert isinstance(t['size'], float)
    assert t['size'] > 0
    assert isinstance(t['seeds'], int)
    assert t['seeds'] > 0
    assert isinstance(t['leeches'], int)
    assert t['leeches'] > 0
