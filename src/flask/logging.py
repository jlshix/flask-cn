# -*- coding: utf-8 -*-
"""
flask.logging
~~~~~~~~~~~~~

:copyright: 2010 Pallets
:license: BSD-3-Clause
"""
from __future__ import absolute_import

import logging
import sys
import warnings

from werkzeug.local import LocalProxy

from .globals import request


@LocalProxy
def wsgi_errors_stream():
    """Find the most appropriate error stream for the application. If a request
    is active, log to ``wsgi.errors``, otherwise use ``sys.stderr``.

    为 app 找到最合适的 error stream. 如果一个请求活动中, 日志打到 `wsgi.errors`,
    否则打到 `sys.stderr`.

    If you configure your own :class:`logging.StreamHandler`, you may want to
    use this for the stream. If you are using file or dict configuration and
    can't import this directly, you can refer to it as
    ``ext://flask.logging.wsgi_errors_stream``.

    如果你配置了自己的 `logging.StreamHandler`, 你或许想用这个获取错误流. 如果你使用文件
    或字典进行配置, 无法直接导入, 你可以使用 `ext://flask.logging.wsgi_errors_stream`.
    """
    return request.environ["wsgi.errors"] if request else sys.stderr


def has_level_handler(logger):
    """Check if there is a handler in the logging chain that will handle the
    given logger's :meth:`effective level <~logging.Logger.getEffectiveLevel>`.

    检查日志链上是否有处理给定 logger 的 `effective level` 的 handler.
    """
    level = logger.getEffectiveLevel()
    current = logger

    while current:
        if any(handler.level <= level for handler in current.handlers):
            return True

        if not current.propagate:
            break

        current = current.parent

    return False


#: Log messages to :func:`~flask.logging.wsgi_errors_stream` with the format
#: ``[%(asctime)s] %(levelname)s in %(module)s: %(message)s``.
#
# 以 `[%(asctime)s] %(levelname)s in %(module)s: %(message)s` 的格式
# 打印消息到 `flask.logging.wsgi_errors_stream`.
default_handler = logging.StreamHandler(wsgi_errors_stream)
default_handler.setFormatter(
    logging.Formatter("[%(asctime)s] %(levelname)s in %(module)s: %(message)s")
)


def _has_config(logger):
    """Decide if a logger has direct configuration applied by checking
    its properties against the defaults.

    通过检查其属性是否为默认属性, 确认一个 logger 是否直接应用了配置.

    :param logger: The :class:`~logging.Logger` to inspect.
    参数 logger: 要检查的 `logging.Logger` 类实例.
    """
    return (
        logger.level != logging.NOTSET
        or logger.handlers
        or logger.filters
        or not logger.propagate
    )


def create_logger(app):
    """Get the the Flask apps's logger and configure it if needed.

    获取 Flask app 的 logger, 如果有需要则进行配置.

    The logger name will be the same as
    :attr:`app.import_name <flask.Flask.name>`.

    logger 的名字和 `app.import_name` 一致.

    When :attr:`~flask.Flask.debug` is enabled, set the logger level to
    :data:`logging.DEBUG` if it is not set.

    当 `flask.Flask.debug` 启用且未设置日志等级时, 将日志等级设为 `logging.DEBUG`.

    If there is no handler for the logger's effective level, add a
    :class:`~logging.StreamHandler` for
    :func:`~flask.logging.wsgi_errors_stream` with a basic format.

    如果这个 logger 的有效日志等级没有可用的 handler, 以一个基本日志格式为
    `flask.logging.wsgi_errors_stream` 添加一个 `logging.StreamHandler`.
    """
    logger = logging.getLogger(app.name)

    # 1.1.0 changes name of logger, warn if config is detected for old
    # name and not new name
    #
    # 1.1.0 版本更改了 logger 的名字, 发现配置了旧的名称时给出警告.
    for old_name in ("flask.app", "flask"):
        old_logger = logging.getLogger(old_name)

        if _has_config(old_logger) and not _has_config(logger):
            warnings.warn(
                "'app.logger' is named '{name}' for this application,"
                " but configuration was found for '{old_name}', which"
                " no longer has an effect. The logging configuration"
                " should be moved to '{name}'.".format(name=app.name, old_name=old_name)
            )
            break

    if app.debug and not logger.level:
        logger.setLevel(logging.DEBUG)

    if not has_level_handler(logger):
        logger.addHandler(default_handler)

    return logger
