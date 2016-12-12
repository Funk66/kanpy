# -*- coding: utf-8 -*-

import re

from .database import db
from .settings import timeutils, today


def singleton(method):
    def wrapper(self):
        attr = '__' + method.__name__ + '__'
        if not hasattr(self, attr):
            result = method(self)
            setattr(self, attr, result)
        return getattr(self, attr)
    return wrapper


class Converter:
    def __init__(self, data):
        for attr in data:
            setattr(self, self.snake_case(attr), data[attr])

    @staticmethod
    def snake_case(camelcase):
        camelcase = camelcase.replace('ID', '_id')
        if len(camelcase) > 1:
            camelcase = camelcase[0].lower() + camelcase[1:]
            return re.sub('([A-Z])', lambda match: '_' + match.group(1).lower(), camelcase)
        else:
            return camelcase.lower()


class User(Converter):
    def __init__(self, data, board):
        super(User, self).__init__(data)
        self.board = board

    def __repr__(self):
        return self.user_name


class CardType(Converter):
    def __init__(self, data, board):
        super(CardType, self).__init__(data)
        self.board = board

    def __repr__(self):
        return self.name


class ClassOfService(Converter):
    def __init__(self, data, board):
        super(ClassOfService, self).__init__(data)
        self.board = board

    def __repr__(self):
        return self.title


class Card(Converter):
    def __init__(self, data, board):
        super(Card, self).__init__(data)
        self.board = board
        self.type = board.card_types[self.type_id]
        self.history = []
        self._major_changes_ = False
        self._plan_ = {}
        self._estimation_ = {}
        self._achieved_ = {'working hours': {}, 'total hours': {}}

    def __repr__(self):
        return self.external_card_id or self.id

    @property
    def lane(self):
        """ Returns the current lane """
        return self.moves()[-1]['lane']

    @property
    def assigned_user(self):
        """ Returns the assigned user, if any """
        return self.board.users[self.assigned_user_id] if self.assigned_user_id else None

    @property
    def class_of_service(self):
        """ Returns the class of service, if any """
        return self.board.classes_of_service[self.class_of_service_id] if self.class_of_service_id else None

    @property
    def creation_date(self):
        for event in self.history:
            if event['Type'] == 'CardCreationEventDTO':
                return event['DateTime']

    @property
    def first_date(self):
        """ Date of the first event in the card's history """
        return self.history[0]['DateTime']

    @property
    def archived(self):
        """ Returns True if the card is in one of the archive lnaes """
        return self.lane.main_lane in self.board.archive_lanes

    @singleton
    def moves(self):
        """ Returns a list of card movements in chronological order """
        previous_time = self.creation_date or self.first_date
        current_time = None
        moves = []
        current_lane = self.board.lanes.get(self.history[0]['ToLaneId'])
        for event in self.history:
            if event['Type'] == 'CardMoveEventDTO':
                current_time = event['DateTime']
                moves.append({'lane': self.board.lanes.get(event['FromLaneId']),
                              'in': previous_time, 'out': current_time})
                previous_time = current_time
                current_lane = self.board.lanes.get(event['ToLaneId'])
        moves.append({'lane': current_lane, 'in': current_time or previous_time, 'out': None})
        return moves

    @singleton
    def timeline(self):
        """ Returns a list of card movements including the time elapsed among them """
        timeline = [move for move in self.moves() if move['out']]
        for move in timeline:
            move['time'] = (move['out'] - move['in']).total_seconds() / 3600
            move['trt'] = timeutils.working_hours(move['in'], move['out'])
        return timeline

    @singleton
    def lanes(self):
        """ Returns a dictionary containing the time data for the
        lanes the card has been through. Doesn't consider the
        time spent in the current one """
        lanes = {}
        for event in self.timeline():
            lane = event['lane']
            if lane in lanes:
                lanes[lane]['trt'] += event['trt']
                lanes[lane]['time'] += event['time']
                lanes[lane]['out'] = event['out']
                lanes[lane]['events'] += 1
            else:
                lanes[lane] = {'in': event['in'],
                               'out': event['out'],
                               'time': event['time'],
                               'trt': event['trt'],
                               'events': 1}
        return lanes

    @singleton
    def stations(self):
        """ Returns a dictionary containing the time data for the
        stations the card has been through. Doesn't consider the
        time spent in the current one """
        stations = {}
        for lane, data in self.lanes().items():
            station = lane.station if lane else None
            if station in stations:
                stations[station]['trt'] += data['trt']
                stations[station]['time'] += data['time']
                stations[station]['out'] = data['out']
                stations[station]['events'] += data['events']
            else:
                stations[station] = {'in': data['in'],
                                     'out': data['out'],
                                     'time': data['time'],
                                     'trt': data['trt'],
                                     'events': data['events']}
        return stations

    @singleton
    def phases(self):
        """ Returns a dictionary containing the time data for the
        phases the card has been through. Doesn't consider the
        time spent in the current one """
        phases = {}
        for station, data in self.stations().items():
            phase = station.phase if station else None
            if phase in phases:
                phases[phase]['trt'] += data['trt']
                phases[phase]['time'] += data['time']
                phases[phase]['out'] = data['out']
                phases[phase]['events'] += data['events']
            else:
                phases[phase] = {'in': data['in'],
                                 'out': data['out'],
                                 'time': data['time'],
                                 'trt': data['trt'],
                                 'events': data['events']}
        return phases

    @singleton
    def trt(self, hours=False):
        """ Total time the card has spent in all stations together """
        total = 0
        for move in self.moves():
            if move['lane'] and move['lane'].station:
                if hours:
                    total += timeutils.working_hours(move['in'], move['out'] or today())
                else:
                    total += ((move['out'] or today()) - move['in']).total_seconds() / 3600
        return total

    @property
    def tagset(self):
        """ Returns a list of tags """
        result = []
        for event in self.history:
            if event['Type'] == 'CardFieldsChangedEventDTO':
                for change in event['Changes']:
                    if change['FieldName'] == 'Tags':
                        old_tags = change['OldValue'].split(',') if change['OldValue'] else []
                        new_tags = change['NewValue'].split(',') if change['NewValue'] else []
                        if new_tags > old_tags:
                            diff = set(new_tags) - set(old_tags)
                            result.append({'tag': ','.join(diff), 'date': event['DateTime']})
        return result

    @property
    def comments(self):
        """ Returns a list of comments """
        result = []
        for event in self.history:
            if event['Type'] == 'CommentPostEventDTO':
                result.append({'text': event['CommentText'], 'date': event['DateTime'], 'user': event['UserName']})
        return result

    @property
    def start_date(self):
        """ Date in which the card was first moved into a station """
        for move in self.moves():
            if move['lane'] and move['lane'].station:
                start_date = move['in']
            elif move['lane'] and 'major changes' in move['lane'].title.lower():
                self._major_changes_ = True
                start_date = move['in']
        return start_date

    @property
    def major_changes(self):
        """ Returns True if the card has been to one of the 'major changes' lanes """
        self.start_date
        return self._major_changes_

    @property
    def station(self):
        """ Returns the current station """
        return self.lane.station

    @property
    def phase(self):
        """ Returns the current phase """
        if self.station:
            return self.station.phase

    def trt_lane(self, lane=None, hours=False):
        """ Returns the TRT for a given lane, including the current one

        :param int lane: Id number of the lane. Default to current lane
        :param bool hours: If True, returns the TRT in working hours
        """
        total = 0
        if not lane:
            lane = self.lane
        elif isinstance(lane, int):
            lane = self.board.lanes[lane]
        major_changes = self.major_changes
        for move in self.moves():
            if major_changes and move['in'] < major_changes:
                continue
            if move['lane'] and move['lane'].id == lane.id:
                if hours:
                    total += timeutils.working_hours(move['in'], move['out'] or today())
                else:
                    total += ((move['out'] or today()) - move['in']).total_seconds() / 3600
        return total

    def trt_station(self, station=None, hours=False):
        """ Returns the TRT for a given station, including the current one

        :param int station: Position of the station. Defaults to current station
        :param bool hours: If True, returns the TRT in working hours
        """
        if self.station:
            total = 0
            if not station:
                station = self.station
            elif isinstance(station, int):
                station = self.board.stations[station]
            for lane in station.lanes:
                total += self.trt_lane(lane.id, hours)
            return total

    def trt_phase(self, phase, hours=False):
        """ Returns the TRT for a given phase, including the current one

        :param int phase: Position of the phase
        :param bool hours: If True, returns the TRT in working hours
        """
        total = 0
        if isinstance(phase, int):
            phase = self.board.phases[phase]
        for station in phase.stations:
            total += self.trt_station(station.id, hours)
        return total

    def ect_station(self):
        """ Returns the estimated completion date for the current station """
        if self.station:
            remaining = self.station.target(self) - self.trt_station(self.station.id, hours=True)
            remaining = max(remaining, 0)
            return timeutils.due_date(remaining, today())

    def ect_phase(self):
        """ Returns the estimated completion date for the current phase """
        if self.station and self.station.phase:
            remaining = self.station.phase.target(self) - self.trt_phase(self.station.phase.id, hours=True)
            return timeutils.due_date(remaining, today())

    def target_station(self, station=None):
        """ Returns the target TRT for a given station

        :param int station: Position of the station. Defaults to current station
        """
        if self.station:
            if not station:
                station = self.station
            elif isinstance(station, int):
                station = self.board.stations[station]
            return station.target(self)

    def plan(self):
        """ Returns all the initially planned completion dates for each station """
        if not self._plan_:
            ect = self.start_date or today()
            for position in range(1, max(self.board.stations)+1):
                station = self.board.stations[position]
                target = station.target(self)
                ect = timeutils.due_date(target, ect)
                self._plan_[position] = {'station': station, 'target': target, 'ect': ect}
        return self._plan_

    def estimation(self):
        """ Returns all the predicted completion dates for each remaining station """
        # TODO: estimation from the last known lane
        if not self._estimation_:
            if self.station:
                consumed = self.trt_station(self.station.id, hours=True)
                target = self.station.target(self)
                ect = timeutils.due_date(target - consumed, today())
                self._estimation_[self.station.id] = {'station': self.station, 'target': target, 'ect': ect}
                for position in range(self.station.id+1, max(self.board.stations)+1):
                    station = self.board.stations[position]
                    target = station.target(self)
                    ect = timeutils.due_date(target, ect)
                    self._estimation_[position] = {'station': station, 'target': target, 'ect': ect}
        return self._estimation_

    def achieved(self, hours=False):
        """ Returns a list of completed stations """
        mode = 'working hours' if hours else 'total hours'
        data = self._achieved_[mode]
        if not data:
            for move in self.moves():
                if move['lane'] and move['lane'].station and move['out']:
                    if hours:
                        trt = timeutils.working_hours(move['in'], move['out'])
                    else:
                        trt = (move['out'] - move['in']).total_seconds() / 3600
                    station = move['lane'].station
                    if station.id in data:
                        data[station.id]['trt'] += trt
                        data[station.id]['out'] = move['out']
                    else:
                        data[station.id] = {'trt': trt, 'in': move['in'], 'out': move['out']}

            if self.station and self.station.id in data:
                del data[self.station.id]

        return data

    def ect(self):
        """ Returns the estimated completion time """
        if self.estimation():
            return self.estimation()[max(self.estimation())]['ect']

    def pct(self):
        """ Returns the planned completion time """
        return self.plan()[max(self.plan())]['ect']


class Lane(Converter):
    def __init__(self, data, board):
        super(Lane, self).__init__(data)
        self.board = board
        self.station = None
        self.groups = []

    def __repr__(self):
        return self.path

    @property
    def ascendants(self):
        """ Returns a list of all parent lanes sorted in ascending order """
        lanes = []
        lane = self.parent
        while lane:
            lanes.append(lane)
            lane = lane.parent
        return lanes

    @property
    def descendants(self):
        """ Returns a list of all child lanes sorted in descending order """
        def sublanes(lane, array):
            for child in lane.children:
                array.append(child)
                sublanes(child, array)
            return array

        return sublanes(self, [])

    @property
    def main_lane(self):
        return ([self] + self.ascendants)[-1]

    @property
    def children(self):
        return [self.board.lanes[lane_id] for lane_id in self.child_lane_ids]

    @property
    def siblings(self):
        return [self.board.lanes.get(lane) for lane in self.sibling_lane_ids]

    @property
    def parent(self):
        return self.board.lanes.get(self.parent_lane_id)

    @property
    def path(self):
        return '::'.join(reversed([self.title] + [lane.title for lane in self.ascendants]))

    @property
    def cards(self):
        return [card for card in self.board.cards.values() if card.lane == self]


class Bundle(Converter):
    def __init__(self, data, board):
        super(Bundle, self).__init__(data)
        self.board = board
        self.id = self.position
        self.lanes = [self.board.lanes[lane] for lane in self.lanes]
        self._cards_ = []
        self._moves_ = []

    def __repr__(self):
        return self.name

    def target(self, card):
        return self.size * card.size + self.card

    def cards(self, include={}, exclude={}):
        if not self._cards_:
            for card in self.board.deck(include, exclude):
                if card.lane in self.lanes:
                    self._cards_.append(card)
        return self._cards_


class Station(Bundle):
    def __init__(self, data, board):
        super(Station, self).__init__(data, board)
        self.board = board
        self.id = self.position
        self.phase = None
        self.group = None
        self.card = float(self.card)
        self.size = float(self.size)
        for lane in self.lanes:
            lane.station = self


class Phase(Bundle):
    def __init__(self, data, board):
        super(Phase, self).__init__(data, board)
        self.stations = [board.stations_by_id[s] for s in self.stations]
        for station in self.stations:
            station.phase = self

    def target(self, card):
        return sum([station.target(card) for station in self.stations])


class Group(Bundle):
    def __init__(self, data, board):
        super(Group, self).__init__(data, board)
        self.card = float(self.card)
        self.size = float(self.size)
        self._stats_ = None
        for lane in self.lanes:
            lane.groups.append(self)


class Board(Converter):
    def __init__(self, board_id=None, archive=False):
        # TODO: optionally load archived cards
        board_data = db.boards.find_one({'Id': board_id})
        assert board_data, "No board with id {} found".format(board_id)
        super(Board, self).__init__(board_data)
        self.card_types = {card_type['Id']: CardType(card_type, self) for card_type in db.card_types.find({'BoardId': board_id})}
        self.classes_of_service = {class_of_service['Id']: ClassOfService(class_of_service, self) for class_of_service in db.classes_of_service.find({'BoardId': board_id})}
        self.users = {user['Id']: User(user, self) for user in db.users.find({'BoardId': board_id})}
        self.lanes = {lane['Id']: Lane(lane, self) for lane in db.lanes.find({'BoardId': board_id})}
        self.cards = {card['Id']: Card(card, self) for card in db.cards.find({'BoardId': board_id})}
        self.stations = {station['Position']: Station(station, self) for station in db.stations.find({'BoardId': board_id})}
        self.phases = {phase['Position']: Phase(phase, self) for phase in db.phases.find({'BoardId': board_id})}
        self.groups = [Group(group, self) for group in db.groups.find({'BoardId': board_id})]

        # Load history
        # TODO: history has to be available on Card creation
        events = {}
        for event in db.events.find({'BoardId': board_id}):
            if event['CardId'] in events:
                events[event['CardId']].append(event)
            else:
                events[event['CardId']] = [event]

        assert len(self.cards) == len(events), 'Inconsistent number of events: {} - {}'.format(len(self.cards), len(events))

        for card_id in self.cards:
            self.cards[card_id].history = sorted(events[card_id], key=lambda event: event['Position'])

    def __repr__(self):
        return self.title

    def deck(self, include={}, exclude={}):
        """ Returns a list of cards matching the a given query.
        Defaults to all cards.

        :param dict include: attributes of the cards to be included
        :param dict exclude: attributes of the cards to be excluded
        """
        deck = []
        for card in self.cards.values():
            match = True
            for key, value in include.items():
                if getattr(card, key, None) != value:
                    match = False
            if match:
                deck.append(card)

        for card in deck[:]:
            for key, value in exclude.items():
                if getattr(card, key, None) == value:
                    deck.remove(card)
                    break

        return deck

    @property
    def sorted_lanes(self):
        lanes = []
        lanes += self.backlog_lanes
        for lane in self.top_level_lanes:
            lanes += [lane] + lane.descendants
        lanes += self.archive_lanes
        return lanes

    @property
    def backlog_lanes(self):
        backlog = self.lanes[self.backlog_top_level_lane_id]
        return [backlog] + backlog.descendants

    @property
    def archive_lanes(self):
        archive = self.lanes[self.archive_top_level_lane_id]
        return [archive] + archive.descendants

    @property
    def wip_lanes(self):
        return [lane for lane in self.lanes.values() if lane.area == 'wip']

    @property
    def top_level_lanes(self):
        return [self.lanes[lane_id] for lane_id in self.top_level_lane_ids]

