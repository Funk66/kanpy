# -*- coding: utf-8 -*-

import yaml
from os import path


conf_paths = ['conf.yaml', path.expanduser('~/.kanpy')]
conf_path = None
for conf_path in conf_paths:
    if path.exists(conf_path):
        break

with open(conf_path) as settings:
    conf = yaml.load(settings)

log = conf.get('log', {})
kanban = conf.get('kanban')
alerts = conf.get('alerts')
paths = conf.get('paths')
database = conf.get('database')
environment = conf.get('environment', 'production')

