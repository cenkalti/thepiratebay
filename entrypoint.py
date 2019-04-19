#!/usr/bin/env python
from gevent.monkey import patch_all; patch_all()  # noqa
from gevent.pywsgi import WSGIServer

import os
from app import app

server = WSGIServer(('0.0.0.0', int(os.environ.get("PORT", 5000))), app)
server.serve_forever()
