#!/usr/bin/python
# -*- coding: utf-8 -*-

import logging
import logging.handlers
from os import path

from .settings import conf
from .errors import KanpyConfigurationError


class TlsSMTPHandler(logging.handlers.SMTPHandler):
    def emit(self, record):
        try:
            import smtplib
            import string
            try:
                from email.utils import formatdate
            except ImportError:
                formatdate = self.date_time
            port = self.mailport
            if not port:
                port = smtplib.SMTP_PORT
            smtp = smtplib.SMTP(self.mailhost, port)
            msg = self.format(record)
            msg = "From: %s\r\nTo: %s\r\nSubject: %s\r\nDate: %s\r\n\r\n%s" % (
                            self.fromaddr,
                            string.join(self.toaddrs, ","),
                            self.getSubject(record),
                            formatdate(), msg)
            if self.username:
                smtp.ehlo()
                smtp.starttls()
                smtp.ehlo()
                smtp.login(self.username, self.password)
            smtp.sendmail(self.fromaddr, self.toaddrs, msg)
            smtp.quit()
        except (KeyboardInterrupt, SystemExit):
            raise
        except:
            self.handleError(record)


def set_level(level, stream=None, name=None):
    if isinstance(level, str):
        try:
            level = logging.__getattribute__(level.upper())
        except AttributeError:
            raise ValueError("{} is not a valid log level".format(level))
    if stream:
        stream.setLevel(level)
    elif name:
        logger = logging.getLogger(name)
        logger.setLevel(level)
    else:
        raise ValueError("Must provide stream or name")


def log_file(name, level='info', format_str='%(asctime)s | %(levelname)-7s | %(message)s'):
    """ Activate logging to a file

    :param str name: name of the log file to write
    :param level: amount of logging info (see set_level)
    """
    file_path = path.join(conf['paths']['logs'], '{}.log'.format(name))
    rotating_handler = logging.handlers.RotatingFileHandler(file_path, maxBytes=10**7, backupCount=2)
    set_level(level, rotating_handler)
    log_format = logging.Formatter(format_str)
    rotating_handler.setFormatter(log_format)
    log.addHandler(rotating_handler)


def runtime_log(level):
    """ Activates the log output to the terminal

    :param int level: logging level
    """
    stream_handler = logging.StreamHandler()
    set_level(level, stream_handler)
    formatter = logging.Formatter('%(message)s')
    stream_handler.setFormatter(formatter)
    log.addHandler(stream_handler)


def email_alerts():
    try:
        alerts = conf['alerts']
    except KeyError:
        raise KanpyConfigurationError('Email alerts parameters not provided in configuration file')
    if alerts:
        smtp_handler = TlsSMTPHandler(mailhost=(alerts['server'], alerts['port']),
                                      fromaddr=alerts['from'],
                                      toaddrs=alerts['to'],
                                      credentials=(alerts['from'], alerts['password']),
                                      subject=alerts['subject'])
        smtp_handler.setLevel(40)
        log.addHandler(smtp_handler)


log = logging.getLogger('kanban')
log.setLevel(10)

if conf['log']:
    runtime_log(conf['log'])
