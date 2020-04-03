# -*- coding: utf-8 -*-
"""
    flask.signals
    ~~~~~~~~~~~~~

    Implements signals based on blinker if available, otherwise
    falls silently back to a noop.

    基于 blinker 实现信号机制. 如果 blinker 不可用则什么都不做.

    :copyright: 2010 Pallets
    :license: BSD-3-Clause
"""
try:
    from blinker import Namespace

    signals_available = True
except ImportError:
    signals_available = False

    class Namespace(object):
        def signal(self, name, doc=None):
            return _FakeSignal(name, doc)

    class _FakeSignal(object):
        """If blinker is unavailable, create a fake class with the same
        interface that allows sending of signals but will fail with an
        error on anything else.  Instead of doing anything on send, it
        will just ignore the arguments and do nothing instead.

        如果 blinker 不可用, 创建一个接口一致的伪类, 可以实现信号的发送, 但会因为
        其他原因失败并报错. 这个伪类会在发送时忽略所有的参数, 什么都不做.
        """

        def __init__(self, name, doc=None):
            self.name = name
            self.__doc__ = doc

        def send(self, *args, **kwargs):
            pass

        def _fail(self, *args, **kwargs):
            raise RuntimeError(
                "Signalling support is unavailable because the blinker"
                " library is not installed."
            )

        connect = connect_via = connected_to = temporarily_connected_to = _fail
        disconnect = _fail
        has_receivers_for = receivers_for = _fail
        del _fail


# The namespace for code signals.  If you are not Flask code, do
# not put signals in here.  Create your own namespace instead.
#
# flask 信号的命名空间, 不是 flask 的信号请不要放置于此, 而应该另外创建命名空间.
_signals = Namespace()


# Core signals.  For usage examples grep the source code or consult
# the API documentation in docs/api.rst as well as docs/signals.rst
#
# 核心信号. 了解用法请在源码中进行查找或者查看 API 文档,
# 如 `docs/api.rst` 和 `docs/signals.rst`
template_rendered = _signals.signal("template-rendered")
before_render_template = _signals.signal("before-render-template")
request_started = _signals.signal("request-started")
request_finished = _signals.signal("request-finished")
request_tearing_down = _signals.signal("request-tearing-down")
got_request_exception = _signals.signal("got-request-exception")
appcontext_tearing_down = _signals.signal("appcontext-tearing-down")
appcontext_pushed = _signals.signal("appcontext-pushed")
appcontext_popped = _signals.signal("appcontext-popped")
message_flashed = _signals.signal("message-flashed")
