# -*- coding: utf-8 -*-

import pymongo
from .settings import conf
from .errors import KanpyConfigurationError


class Mongo:
    def __init__(self, board=None):
        """ Initializes the connection to the database

        :param int board: id number of the board
        """
        self.board = board
        self.query = {'BoardId': self.board} if board else {}
        try:
            mongo = conf['database']
            client = pymongo.MongoClient(mongo['ip'], mongo['port'])
            self.db = client.get_database(mongo['db'])
        except KeyError:
            raise KanpyConfigurationError("Database parameters not provided in configuration file")

    def get(self, collection, query={}, projection={}):
        """ Returns a collection from the database as a list

        :param str collection: name of the collection
        :param dict query: filtering parameters
        :param dict projection: projection
        """
        self.query.update(query)
        return [item for item in self.db[collection].find(self.query)]

    def get_dict(self, collection, query={}, projection={}, key='Id'):
        """ Returns a collection from the database as a dictionary

        :param str collection: name of the collection
        :param dict query: filtering parameters
        :param dict projection: projection
        :param str key: field of the document to be used as key for the dictionary
        """
        self.query.update(query)
        return {x[key]: x for x in get(collection, self.query, projection)}

    def update(self, collection, query, data):
        """ Takes an Id number or query dictionary and updates the
        matching documents from the corresponding collection """
        self.query.update(query)
        if isinstance(query, int):
            query = {'Id': query}
        return self.db[collection].update(self.query, {'$set': data})

    def events(self, card_id=None, event_type=None, from_date=None, to_date=None):
        """ Returns the history events for a given card.
        If no card id is provided, it returns all events.
        """
        self.query.update({})
        return self.db.events.find({"CardId": card_id}, {"_id": 0}).sort("DateTime")

