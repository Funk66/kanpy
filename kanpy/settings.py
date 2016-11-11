# -*- coding: utf-8 -*-

import yaml
from os import path


with open(os.path.expanduser('~/.kanpy')) as settings:
    conf = yaml.load(settings)

log = conf.get('log', 0)
kanban = conf.get('kanban')
alerts = conf.get('alerts')
paths = conf.get('paths')
database = conf.get('database')
environment = conf.get('environment', 'production')

