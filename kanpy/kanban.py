# -*- coding: utf-8 -*-

import re
import datetime

from kanpy import database
from kanpy.utils import date as dateutils


today = datetime.datetime.today


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
        return self.name


class Card(Converter):
    def __init__(self, data, board):
        super(Card, self).__init__(data)
        self.board = board
        self.type = board.card_types[self.type_id]
        self.history = []
        self._moves_ = []
        self._major_changes_ = None
        self._plan_ = {}
        self._estimation_ = {}
        self._achieved_ = {}

    def __repr__(self):
        return self.external_card_id or self.id

    @property
    def assigned_user(self):
        if self.assigned_user_id:
            return self.board.users[self.assigned_user_id]
        else:
            return None

    @property
    def class_of_service(self):
        if self.class_of_service_id:
            return self.board.classes_of_service[self.class_of_service_id]
        else:
            return None

    @property
    def creation_date(self):
        for event in self.history:
            if event['Type'] == 'CardCreationEventDTO':
                return event['DateTime']

    @property
    def first_date(self):
        return self.history[0]['DateTime']

    @property
    def moves(self):
        if not self._moves_:
            previous_time = self.creation_date or self.first_date
            current_time = None
            self._moves_ = []
            current_lane = self.board.lanes.get(self.history[0]['ToLaneId'])
            for event in self.history:
                if event['Type'] == 'CardMoveEventDTO':
                    current_time = event['DateTime']
                    self._moves_.append({'lane': self.board.lanes.get(event['FromLaneId']),
                                  'in': previous_time, 'out': current_time})
                    previous_time = current_time
                    current_lane = self.board.lanes.get(event['ToLaneId'])
            self._moves_.append({'lane': current_lane, 'in': current_time or previous_time, 'out': None})
        return self._moves_

    def trt(self, hours=False):
        """ Total time the card has spent in all stations together """
        total = 0
        for move in self.moves:
            if move['lane'] and move['lane'].station:
                if hours:
                    total += dateutils.working_hours(move['in'], move['out'] or today())
                else:
                    total += ((move['out'] or today()) - move['in']).total_seconds() / 3600
        return total


    @property
    def lane(self):
        """ Returns the current lane """
        return self.moves[-1]['lane']

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
                result.append({'comment': event['CommentText'], 'date': event['DateTime'], 'user': event['UserName']})
        return result

    @property
    def start_date(self):
        """ Date in which the card was first moved into a station """
        if self.major_changes:
            return self.major_changes
        else:
            for move in self.moves:
                if move['lane'] and move['lane'].station:
                    return move['in']

    @property
    def major_changes(self):
        if not self._major_changes_:
            for move in self.moves:
                if move['lane'] and 'major changes' in move['lane'].title.lower():
                    self._major_changes_ = move['in']
        return self._major_changes_

    @property
    def station(self):
        return self.lane.station

    @property
    def phase(self):
        """ Returns the current phase """
        if self.lane.station:
            return self.lane.station.phase
        else:
            return None

    def trt_lane(self, lane, hours=False):
        """ Returns the TRT for a given lane, including the current one
        :param int lane: Id number of the lane
        :param bool hours: If True, returns the TRT in working hours
        """
        total = 0
        if isinstance(lane, int):
            lane = self.board.lanes[lane]
        major_changes = self.major_changes
        for move in self.moves:
            if major_changes and move['in'] < major_changes:
                continue
            if move['lane'] and move['lane'].id == lane.id:
                if hours:
                    total += dateutils.working_hours(move['in'], move['out'] or today())
                else:
                    total += ((move['out'] or today()) - move['in']).total_seconds() / 3600
        return total

    def trt_station(self, station, hours=False):
        """ Returns the TRT for a given station, including the current one
        :param int station: Position of the station
        :param bool hours: If True, returns the TRT in working hours
        """
        total = 0
        if isinstance(station, int):
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
            remaining = self.station.target(self) - self.trt_station(self.station.id)
            return dateutils.hours_to_date(today(), remaining)
        else:
            return None

    def plan(self):
        """ Returns all the initially planned completion dates for each station """
        if not self._plan_:
            ect = self.start_date or today()
            for position in range(1, max(self.board.stations)+1):
                station = self.board.stations[position]
                target = station.target(self)
                ect = dateutils.hours_to_date(ect, target)
                self._plan_[position] = {'station': station, 'target': target, 'ect': ect}
        return self._plan_

    def estimation(self):
        """ Returns all the predicted completion dates for each remaining station """
        # TODO: estimation from the last known lane
        if not self._estimation_:
            if self.station:
                consumed = self.trt_station(self.station.id, hours=True)
                target = self.station.target(self)
                ect = dateutils.hours_to_date(today(), target - consumed)
                self._estimation_[self.station.id] = {'station': self.station, 'target': target, 'ect': ect}
                for position in range(self.station.id+1, max(self.board.stations)+1):
                    station = self.board.stations[position]
                    target = station.target(self)
                    ect = dateutils.hours_to_date(ect, target)
                    self._estimation_[position] = {'station': station, 'target': target, 'ect': ect}
        return self._estimation_

    def achieved(self, hours=False):
        """ Returns a list of completed stations """
        if not self._achieved_:
            for move in self.moves:
                if move['lane'].station and move['out']:
                    if hours:
                        trt = dateutils.working_hours(move['in'], move['out'])
                    else:
                        trt = (move['out'] - move['in']).total_seconds() / 3600
                    station = move['lane'].station
                    if station.id in self._achieved_:
                        self._achieved_[station.id]['trt'] += trt
                        self._achieved_[station.id]['date'] = move['out']
                    else:
                        self._achieved_[station.id] = {'trt': trt, 'date': move['out'], 'station': station}

            if self.station.id in self._achieved_:
                del self._achieved_[self.station.id]

        return self._achieved_

    def ect(self):
        """ Returns the estimated completion time """
        if self.estimation():
            return self._estimation_[max(self._estimation_)]['ect']

    def pct(self):
        """ Returns the planned completion time """
        return self._plan_[max(self._plan_)]['ect']

class Lane(Converter):
    def __init__(self, data, board):
        super(Lane, self).__init__(data)
        self.board = board

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


class Station(Converter):
    def __init__(self, data, board):
        super(Station, self).__init__(data)
        self.board = board
        self.id = self.position
        self.lanes = []

    def __repr__(self):
        return self.name

    def target(self, card):
        return self.size * card.size + self.card


class Phase(Converter):
    def __init__(self, data, board):
        super(Phase, self).__init__(data)
        self.board = board
        self.id = self.position
        self.stations = [board.stations_by_id[s] for s in self.stations]
        for station in self.stations:
            station.phase = self

    def __repr__(self):
        return self.name

    def target(self, card):
        return sum([station.target(card) for station in self.stations])


class Board(Converter):
    def __init__(self, board_id=None):
        super(Board, self).__init__(database.get('board')[0])  # TODO: filter for {'Id': board_id}
        self.card_types = {card_type['Id']: CardType(card_type, self) for card_type in database.get('card_types')}
        self.classes_of_service = {class_of_service['Id']: ClassOfService(class_of_service, self) for class_of_service in database.get('classes_of_service')}
        self.users = {user['Id']: User(user, self) for user in database.get('users')}
        self.lanes = {lane['Id']: Lane(lane, self) for lane in database.get('lanes')}  # TODO: filter for {'Board': self.id}
        self.cards = {card['Id']: Card(card, self) for card in database.get('cards')}
        self.stations = {station['Position']: Station(station, self) for station in database.get('stations')}
        self.stations_by_id = {s._id: s for s in self.stations.values()}
        self.phases = {phase['Position']: Phase(phase, self) for phase in database.get('phases')}

        # Load history
        # TODO: history has to be available on Card creation
        events = {}
        for event in database.get('events'):
            if event['CardId'] in events:
                events[event['CardId']].append(event)
            else:
                events[event['CardId']] = [event]

        assert len(self.cards) == len(events), 'Inconsistent number of events: {} - {}'.format(len(self.cards), len(events))

        for card_id in self.cards:
            self.cards[card_id].history = sorted(events[card_id], key=lambda event: event['Position'])

        # Get stations right
        for lane in self.lanes.values():
            if hasattr(lane, 'station'):
                lane.station = self.stations_by_id[lane.station]
                lane.station.lanes.append(lane)
            else:
                lane.station = None


    def __repr__(self):
        return self.title

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

