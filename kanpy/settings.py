#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import sys
import yaml


conf = {'environment': 'production', 'log': 0}

try:
    with open('conf.yml') as yml:
        conf.update(yaml.load(yml))
except FileNotFoundError:
    raise FileNotFoundError('Configuration file not found')
