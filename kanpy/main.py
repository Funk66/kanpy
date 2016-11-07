# -*- coding: utf-8 -*-

import re
import json
import time
import operator
import requests
from datetime import datetime



class Record(dict):
    """ A little dict subclass that adds attribute access to values. """

    def __hash__(self):
        return hash(repr(self))

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as e:
            raise AttributeError(e)

    def __setattr__(self, name, value):
        self[name] = value


class ResponseCodes:
    """ Enum listing all possible response codes from LeankitKanban API """
    NoData = 100
    DataRetrievalSuccess = 200
    DataInsertSuccess = 201
    DataUpdateSuccess = 202
    DataDeleteSuccess = 203
    SystemException = 500
    MinorException = 501
    UserException = 502
    FatalException = 503
    ThrottleWaitResponse = 800
    WipOverrideCommentRequired = 900
    ResendingEmailRequired = 902
    UnauthorizedAccess = 1000

    SUCCESS_CODES = [DataRetrievalSuccess,
                     DataInsertSuccess,
                     DataUpdateSuccess,
                     DataDeleteSuccess]
    EXPECTED_CODES = [DataRetrievalSuccess,
                      DataInsertSuccess,
                      DataUpdateSuccess,
                      DataDeleteSuccess,
                      NoData]


class Connector(object):
    def __init__(self, domain, username, password, throttle=0.1):
        host = 'https://' + domain + '.leankit.com'
        self.base_api_url = host + '/Kanban/Api'
        self.http = requests.sessions.Session()
        self.http.auth = (username, password)
        self.last_request_time = time.time() - throttle
        self.throttle = throttle

    def post(self, url, data, handle_errors=True):
        data = json.dumps(data)
        return self.do_request("POST", url, data, handle_errors)

    def get(self, url, handle_errors=True):
        return self.do_request("GET", url, None, handle_errors)

    def do_request(self, action, url, data=None, handle_errors=True):
        """ Make an HTTP request to the given url possibly POSTing some data. """
        assert self.http is not None, "HTTP connection should not be None"
        headers = {'Content-type': 'application/json'}

        # Throttle requests to Leankit to be no more than once per THROTTLE
        # seconds.
        now = time.time()
        delay = (self.last_request_time + self.throttle) - now
        if delay > 0:
            time.sleep(delay)
        self.last_request_time = time.time()
        try:
            request = self.http.request(
                method=action,
                url=self.base_api_url + url,
                data=data,
                auth=self.http.auth,
                headers=headers,
                verify=True)
        except Exception as e:
            raise IOError("Unable to make HTTP request: %s" % e.message)

        if request.status_code not in ResponseCodes.SUCCESS_CODES:
            raise IOError('Kanban error %d' % request.status_code)

        response = Record(request.json())

        if handle_errors and response.ReplyCode not in ResponseCodes.EXPECTED_CODES:
            raise IOError('Kanban error %d: %s' % (response.ReplyCode, response.ReplyText))
        return response


class Converter(object):
    """ Convert JSON returned by Leankit to Python classes.

    JSON returned by Leankit is in the form of a dict with CamelCase
    named values which are converted to lowercase underscore-separated
    class attributes.
    """
    attributes = []

    def __init__(self, raw_data, board):
        self.board = board
        self.raw_data = raw_data
        for attr in self.attributes:
            setattr(self, self.prettify_name(attr), raw_data.get(attr, ''))

    @staticmethod
    def prettify_name(camelcase):
        camelcase = camelcase.replace('ID', '_id')
        if len(camelcase) > 1:
            camelcase = camelcase[0].lower() + camelcase[1:]
            return re.sub('([A-Z])', lambda match: '_' + match.group(1).lower(), camelcase)
        else:
            return camelcase.lower()

    @staticmethod
    def to_camel_case(name):
        if len(name) > 1:
            name = name[0].upper() + name[1:]
            return re.sub('(_[a-z])', lambda match: match.group(1)[1:].upper(), name)
        else:
            return name.upper()

    def jsonify(self):
        data = {'LastUpdate': datetime.today()}
        for attr in self.attributes:
            data[attr] = self.raw_data[attr]
        if self.board:
            data['BoardId'] = self.board.id
        return data


class User(Converter):
    attributes = ['Id', 'UserName', 'FullName', 'EmailAddress',
                  'Enabled', 'IsDeleted', 'RoleName', 'GravatarLink']

    def __repr__(self):
        return self.user_name


class CardType(Converter):
    attributes = ['Id', 'Name', 'ColorHex']

    def __repr__(self):
        return self.name


class ClassOfService(Converter):
    attributes = ['Id', 'Title', 'ColorHex']

    def __repr__(self):
        return self.title


class OrganizationActivity(Converter):
    attributes = ['Id', 'Name']

    def __repr__(self):
        return self.name


class Card(Converter):
    attributes = ['Id', 'Title', 'Description', 'PriorityText',
                  'ClassOfServiceId', 'Tags', 'Color', 'Size',
                  'ExternalCardID', 'AssignedUserId', 'IsBlocked',
                  'BlockReason', 'Priority', 'TypeName', 'TypeId',
                  'ClassOfServiceTitle', 'AssignedUserName']

    def __init__(self, card_dict, lane, board):
        super(Card, self).__init__(card_dict, board)
        self.lane = lane
        self.date_archived_str = card_dict['DateArchived']
        self.last_move_str = card_dict['LastMove']
        self.last_activity_str = card_dict['LastActivity']
        self.due_date_str = card_dict['DueDate']
        self.archived = card_dict.get('Archived', False)
        self.history = self.raw_data.get('History', [])
        assert self.id not in self.board.cards, "Attempted to create duplicate card: {}".format(self.id)
        self.board.cards[self.id] = self

    def __repr__(self):
        return str(self.external_card_id or self.id)

    def jsonify(self):
        data = super(Card, self).jsonify()
        dates = ['LastActivity', 'LastMove', 'DateArchived', 'DueDate']
        for date in dates:
          data[date] = getattr(self, self.prettify_name(date))
        return data

    def get_history(self):
        history = self.board.kanban.connector.get("/Card/History/{board_id}/{card_id}".format(
            board_id=str(self.board.id), card_id=str(self.id))).ReplyData[0]

        for event in history:
            event['DateTime'] = datetime.strptime(event['DateTime'], '%d/%m/%Y at %I:%M:%S %p')
            event['Position'] = len(history) - history.index(event)

        self.history = list(reversed(history))

    def get_comments(self):
        self.comments = self.board.kanban.connector.get("/card/getcomments/{0.board.id}/{0.id}".format(self))['ReplyData'][0]

    @property
    def due_date(self):
        if self.due_date_str:
            return datetime.strptime(self.due_date_str, '%d/%m/%Y')
        else:
            return ''

    @property
    def last_move(self):
        if self.last_move_str:
            try:
                return datetime.strptime(self.last_move_str, '%d/%m/%Y %I:%M:%S %p')
            except ValueError:
                return datetime.strptime(self.last_move_str, '%d/%m/%Y')
        else:
            return ''

    @property
    def last_activity(self):
        if self.last_activity_str:
            return datetime.strptime(self.last_activity_str, '%d/%m/%Y %I:%M:%S %p')
        else:
            return ''

    @property
    def date_archived(self):
        if self.date_archived_str:
            return datetime.strptime(self.date_archived_str, '%d/%m/%Y')
        else:
            return ''


class Lane(Converter):
    attributes = ['Id', 'Title', 'Index', 'Orientation', 'ParentLaneId', 'ChildLaneIds',
                  'SiblingLaneIds', 'ActivityId', 'ActivityName', 'LaneState', 'Width']

    def __init__(self, lane_dict, board):
        super(Lane, self).__init__(lane_dict, board)
        self.cards = [Card(card_dict, self, board) for card_dict in lane_dict['Cards'] if card_dict['TypeId']]
        self.area = lane_dict.get('Area', 'wip')

    def __repr__(self):
        return self.path

    @property
    def path(self):
        return '::'.join(reversed([self.title] + [lane.title for lane in self.ascendants]))

    @property
    def main_lane(self):
        return ([self] + self.ascendants)[-1]

    @property
    def parent(self):
        return self.board.lanes.get(self.parent_lane_id)

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
    def children(self):
        return [self.board.lanes[lane_id] for lane_id in self.child_lane_ids]

    @property
    def role(self):
        return 'parent' if self.children else 'child'

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
    def parent_lane_ids(self):
        id_list = []
        lane = self
        while lane.id != 0:
            id_list.append(lane.id)
            lane = lane.parent
        return id_list

    def jsonify(self):
        data = super(Lane, self).jsonify()
        data['Area'] = self.area
        return data

    def propagate(self, key, value):
        setattr(self, key, value)
        for lane in self.descendants:
            setattr(lane, key, value)


class Board(Converter):
    attributes = ['Id', 'Title', 'Version', 'AvailableTags', 'BacklogTopLevelLaneId',
                  'ArchiveTopLevelLaneId', 'TopLevelLaneIds']

    def __init__(self, kanban, board_dict):
        super(Board, self).__init__(board_dict, None)

        self.kanban = kanban
        self.cards = {}
        self.lanes = self.populate('Lanes', Lane)
        self.users = self.populate('BoardUsers', User)
        self.card_types = self.populate('CardTypes', CardType)
        self.classes_of_service = self.populate('ClassesOfService', ClassOfService)
        self.organization_activities = self.populate('OrganizationActivities', OrganizationActivity)
        self._archive_lanes_ = []
        self._backlog_lanes_ = []

    def __repr__(self):
        return self.title

    @property
    def deck(self):
        return list(self.cards.values())

    @property
    def top_level_lanes(self):
        return [self.lanes[lane_id] for lane_id in self.top_level_lane_ids]

    @property
    def archive_lanes(self):
        if not self._archive_lanes_ and self.archive_top_level_lane_id in self.lanes:
            archive_lane = self.lanes[self.archive_top_level_lane_id]
            self._archive_lanes_ = [archive_lane] + archive_lane.descendants
        return self._archive_lanes_

    @property
    def backlog_lanes(self):
        if not self._backlog_lanes_ and self.backlog_top_level_lane_id in self.lanes:
            backlog_lane = self.lanes[self.backlog_top_level_lane_id]
            self._backlog_lanes_ = [backlog_lane] + backlog_lane.descendants
        return self._backlog_lanes_

    @property
    def sorted_lanes(self):
        lanes = []
        lanes += self.backlog_lanes
        for lane in self.top_level_lanes:
            lanes += [lane] + lane.descendants
        lanes += self.archive_lanes
        return lanes

    @property
    def history(self):
        for card in self.deck:
            for event in card.lanes:
                yield event

    def populate(self, key, element):
        items = {}
        for item in self.raw_data[key]:
            instance = element(item, self)
            items[instance.id] = instance
        return items

    def get_archive(self):
        archive = self.kanban.connector.get('/Board/{}/Archive'.format(str(self.id))).ReplyData[0][0]
        archive['Lane']['Area'] = 'archive'
        main_archive_lane = Lane(archive['Lane'], self)
        self.lanes[main_archive_lane.id] = main_archive_lane
        self.raw_data['Lanes'].append(archive['Lane'])
        for lane_dict in archive['ChildLanes']:
            lane_dict['Lane']['Area'] = 'archive'
            lane = Lane(lane_dict['Lane'], self)
            self.lanes[lane.id] = lane
            self.raw_data['Lanes'].append(lane_dict['Lane'])

    def get_backlog(self):
        backlog = self.kanban.connector.get("/Board/{}/Backlog".format(str(self.id))).ReplyData[0]
        for lane_dict in reversed(backlog):
            lane_dict['Area'] = 'backlog'
            lane = Lane(lane_dict, self)
            self.lanes[lane.id] = lane
            self.raw_data['Lanes'].append(lane_dict)

    def get_history(self):
        try:
            for card in self.deck:
                card.get_history()
        except KeyboardInterrupt:
            pass

    def get_card(self, card_id, history=True):
        card_dict = self.kanban.connector.get("/Board/{board_id}/GetCard/{card_id}".format(
                board_id=str(self.id), card_id=card_id)).ReplyData[0]

        if not card_dict:
            return

        assert self.lanes[card_dict['LaneId']], "Lane {} does not exist".format(card_dict['LaneId'])

        if card_id in self.cards:
            card = self.cards[card_id]
            card.lane.remove_card(card)

        lane = self.lanes[card_dict['LaneId']]
        card = Card(card_dict, lane, self)

        if history:
            card.get_history()
        lane.cards.append(card)
        lane.raw_data['Cards'].append(card.raw_data)
        self.cards[card.id] = card
        return card

    def find(self, array, attribute, value, mode='eq', case=True):
        matches = []
        for item in getattr(self, array).values():
            actual_value = getattr(item, attribute)
            if case and isinstance(attribute, str) and isinstance(actual_value, str):
                actual_value = actual_value.lower()
                value = value.lower()
            if getattr(operator, mode)(actual_value, value):
                matches.append(item)
        return matches[0] if len(matches) == 1 else matches


class Kanban:
    def __init__(self, domain, username, password):
        self.connector = Connector(domain, username, password)
        self.database = None
        self.boards = {}

    def get_board(self, board_id, backlog=True, archive=True):
        board_dict = self.connector.get('/Boards/{}'.format(board_id)).ReplyData[0]
        self.boards[board_id] = Board(self, board_dict)
        if archive:
            self.boards[board_id].get_archive()
        if backlog:
            self.boards[board_id].get_backlog()

    def check_updates(self, board_id, version):
        """ Downloads a board if a newer version number exists """
        board_dict = self.connector.get('/Board/{}/BoardVersion/{}/GetNewerIfExists'.format(board_id, version)).ReplyData[0]
        if board_dict:
            self.boards[board_id] = Board(self, board_dict)
            return True
        else:
            return False

