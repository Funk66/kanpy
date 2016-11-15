# -*- coding: utf-8 -*-

import os
import time
import pymongo
import logging
from logging import handlers

from . import api
from . import settings
from .database import db


log = logging.getLogger(__name__)


class Worker:
    def __init__(self, throttle=60):
        self.kanban = api.Kanban()
        self.boards = {}
        self.throttle = throttle
        self.last_update = time.time()
        self.boards = {board_id: self.load(board_id) for board_id in settings.kanban['boards']}
        self.collections = ['lanes', 'cards', 'users', 'card_types', 'classes_of_service']

    def load(self, board_id):
        return db.boards.find_one({'Id': board_id})

    def find(self, collection, board_id, query={}):
        query.update({'BoardId': board_id})
        return {item['Id']: item for item in db[collection].find(query)}

    def reset(self):
        for collection in self.collections:
            db[collection].drop()
            db[collection].create_index([('Id', pymongo.ASCENDING)], unique=True)
            db[collection].create_index([('BoardId', pymongo.ASCENDING)])

        db.events.drop()
        db.events.create_index([('CardId', pymongo.ASCENDING), ('BoardId', pymongo.ASCENDING)])
        db.boards.drop()

    def populate(self, board_id):
        log.info('Populating board {}'.format(board_id))
        self.kanban.get_board(board_id)
        board = self.kanban.boards[board_id]
        board.get_history()
        db.boards.insert_one(board.jsonify())
        for collection in self.collections:
            db[collection].remove({'BoardId': board_id})
            items = [item.jsonify() for item in getattr(board, collection).values()]
            if items:
                db[collection].insert_many(items)
        db.events.remove({'BoardId': board_id})
        events = [event for card in board.cards.values() for event in card.history]
        db.events.insert_many(events)
        self.boards[board_id] = self.load(board_id)

    def check(self, board_id):
        if self.boards[board_id]:
            version = self.boards[board_id]['Version']
            if self.kanban.check_updates(board_id, version):
                board = self.kanban.boards[board_id]
                log.debug('Updating {} from v{} to v{}'.format(board.title, version, board.version))
                self.update(board_id)
        else:
            self.populate(board_id)

    def update(self, board_id):
        board = self.kanban.boards[board_id]
        board.get_backlog()
        board.get_archive()  # TODO: get recent archive

        cards = self.find('cards', board_id, {'InCabinet': {'$ne': True}})
        for card in board.cards.values():
            if card.id in cards:
                assert card.last_activity >= cards[card.id]['LastActivity'], \
                        'Card {} has invalid LastActivity: {} --> {}'.format(card.id, card.last_activity, cards[card.id]['LastActivity'])
                if card.last_activity > cards[card.id]['LastActivity']:
                    log.info('Card updated: {}'.format(card.id))
                    card.get_history()
                    last_event = [result for result in db.events.find({'CardId': card.id}).sort('Position', -1).limit(1)][0]
                    for position in range(last_event['Position'], len(card.history)):
                        db.events.insert(card.history[position])
                    db.cards.update({'Id': card.id}, card.jsonify())
            else:
                log.info('Card created: {}'.format(card.id))
                card.get_history()
                db.events.insert_many(card.history)
                db.cards.insert_one(card.jsonify())

        # Check for archived and deleted cards
        for card_id in cards:
            if card_id not in board.cards:
                missing_card = board.get_card(card_id)
                if missing_card:
                    log.info("Card archived: {}".format(card_id))
                    db.cards.update({'CardId': card_id}, {'InCabinet': True})
                else:
                    log.info("Card deleted: {}".format(card_id))
                    db.cards.remove({'Id': card_id})
                    db.events.remove({'CardId': card_id})

        # Update other databases
        for collection in ['lanes', 'users', 'card_types', 'classes_of_service']:
            items = self.find(collection, board_id)
            for item_id, item in getattr(board, collection).items():
                if item_id not in items:
                    # New item
                    db[collection].insert_one(item.jsonify())
                    log.info("{} ({}) added to {} database".format(item.prettify_name(type(item).__name__), item.id, collection))
                else:
                    # Compare dicts
                    stored = items[item_id]
                    downloaded = item.jsonify()
                    downloaded['LastUpdate'] = stored['LastUpdate']
                    for key, value in downloaded.items():
                        if stored.get(key) != value:
                            # Item updated
                            db[collection].update({'Id': item_id}, item.jsonify())
                            log.info("{} ({}) updated in {} database".format(item.prettify_name(type(item).__name__), item.id, collection))

        # Update board data
        db.boards.update({'Id': board_id}, board.jsonify())
        self.boards[board_id] = board.jsonify()


    def run(self):
        while True:
            try:
                self.last_update = time.time()
                for board_id in self.boards:
                    self.check(board_id)
                elapsed = time.time() - self.last_update
                if elapsed < self.throttle:
                    time.sleep(self.throttle - elapsed)
            except ConnectionError:
                self.kanban = api.Kanban()
            except KeyboardInterrupt:
                log.info("Stopped by the user")
                break

