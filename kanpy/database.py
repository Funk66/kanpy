# -*- coding: utf-8 -*-

import pymongo

from . import settings


client = pymongo.MongoClient(settings.database)
db = client.get_default_database()

