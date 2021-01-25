# -*- coding: utf-8 -*-
"""
    flask.ctx
    ~~~~~~~~~

    Implements the objects required to keep the context.

    实现维持上下文所需的对象.

    :copyright: 2010 Pallets
    :license: BSD-3-Clause
"""
import sys
from functools import update_wrapper

from werkzeug.exceptions import HTTPException

from ._compat import BROKEN_PYPY_CTXMGR_EXIT
from ._compat import reraise
from .globals import _app_ctx_stack
from .globals import _request_ctx_stack
from .signals import appcontext_popped
from .signals import appcontext_pushed


# a singleton sentinel value for parameter defaults
# 一个单例标志, 用于默认参数
_sentinel = object()


class _AppCtxGlobals(object):
    """A plain object. Used as a namespace for storing data during an
    application context.

    一个普普通通的对象, 用作应用上下文期间存储数据的命名空间.

    Creating an app context automatically creates this object, which is
    made available as the :data:`g` proxy.

    创建应用上下文时自动创建此对象, 可以通过 `g` 这个代理来访问.

    .. describe:: 'key' in g

        Check whether an attribute is present.

        .. versionadded:: 0.10

    .. describe:: iter(g)

        Return an iterator over the attribute names.

        .. versionadded:: 0.10
    """

    def get(self, name, default=None):
        """Get an attribute by name, or a default value. Like
        :meth:`dict.get`.
        和字典的 `get` 方法类似, 根据名称获取值, 无结果时返回默认值.

        :param name: Name of attribute to get.
        参数 name: 需要获取的属性名称

        :param default: Value to return if the attribute is not present.
        参数 default: 找不到这个属性时返回的默认值

        .. versionadded:: 0.10
        """
        return self.__dict__.get(name, default)

    def pop(self, name, default=_sentinel):
        """Get and remove an attribute by name. Like :meth:`dict.pop`.
        和字典的 `pop` 方法类似, 根据名称获取并弹出一个属性.

        :param name: Name of attribute to pop.
        参数 name: 要弹出的属性名称.

        :param default: Value to return if the attribute is not present,
            instead of raise a ``KeyError``.
        参数 default: 找不到这个属性时返回的默认值, 而不是抛出 `KeyError` 异常.

        .. versionadded:: 0.11
        """
        if default is _sentinel:
            return self.__dict__.pop(name)
        else:
            return self.__dict__.pop(name, default)

    def setdefault(self, name, default=None):
        """Get the value of an attribute if it is present, otherwise
        set and return a default value. Like :meth:`dict.setdefault`.

        和字典的 `setdefault` 方法类似, 如果属性有值获取其值,
        不然就将默认值设置为其值并返回.

        :param name: Name of attribute to get.
        参数 name: 需要获取的属性名称.

        :param: default: Value to set and return if the attribute is not
            present.
        参数 default: 如果属性没有值, 就将这个默认值设为这个属性的值并返回.

        .. versionadded:: 0.11
        """
        return self.__dict__.setdefault(name, default)

    def __contains__(self, item):
        return item in self.__dict__

    def __iter__(self):
        return iter(self.__dict__)

    def __repr__(self):
        top = _app_ctx_stack.top
        if top is not None:
            return "<flask.g of %r>" % top.app.name
        return object.__repr__(self)


def after_this_request(f):
    """Executes a function after this request.  This is useful to modify
    response objects.  The function is passed the response object and has
    to return the same or a new one.

    此次请求后执行一个函数. 在更改返回数据时很有用. 这个参数以返回对象为参数, 可以返回
    同一个对象, 也可以创建新的对象返回.

    Example::

        @app.route('/')
        def index():
            @after_this_request
            def add_header(response):
                response.headers['X-Foo'] = 'Parachute'
                return response
            return 'Hello World!'

    This is more useful if a function other than the view function wants to
    modify a response.  For instance think of a decorator that wants to add
    some headers without converting the return value into a response object.

    当一个不为视图函数的函数想要更改返回数据时可以使用这个方法. 比如一个装饰器可以在不需要将
    返回值转换为返回对象的情况下修改一些 headers.

    .. versionadded:: 0.9
    """
    _request_ctx_stack.top._after_request_functions.append(f)
    return f


def copy_current_request_context(f):
    """A helper function that decorates a function to retain the current
    request context.  This is useful when working with greenlets.  The moment
    the function is decorated a copy of the request context is created and
    then pushed when the function is called.  The current session is also
    included in the copied request context.

    一个装饰器, 可帮助被装饰的函数维持当前的请求上下文. 在使用 greenlets 比较有用.
    函数被装饰时, 复制一份请求上下文, 在函数被调用时使用. 当前的 session 也同样包含在
    这份拷贝的请求上下文中.

    Example::

        import gevent
        from flask import copy_current_request_context

        @app.route('/')
        def index():
            @copy_current_request_context
            def do_some_work():
                # do some work here, it can access flask.request or
                # flask.session like you would otherwise in the view function.
                ...
            gevent.spawn(do_some_work)
            return 'Regular response'

    .. versionadded:: 0.10
    """
    top = _request_ctx_stack.top
    if top is None:
        raise RuntimeError(
            "This decorator can only be used at local scopes "
            "when a request context is on the stack.  For instance within "
            "view functions."
        )
    reqctx = top.copy()

    def wrapper(*args, **kwargs):
        with reqctx:
            return f(*args, **kwargs)

    return update_wrapper(wrapper, f)


def has_request_context():
    """If you have code that wants to test if a request context is there or
    not this function can be used.  For instance, you may want to take advantage
    of request information if the request object is available, but fail
    silently if it is unavailable.

    这个函数可以用于代码中检查当前是否存在请求上下文. 例如, 当请求上下文可用时, 获取其中的信息,
    不可用时则静默失败.
    ::

        class User(db.Model):

            def __init__(self, username, remote_addr=None):
                self.username = username
                if remote_addr is None and has_request_context():
                    remote_addr = request.remote_addr
                self.remote_addr = remote_addr

    Alternatively you can also just test any of the context bound objects
    (such as :class:`request` or :class:`g`) for truthness::

    或者你也可以直接检查绑定上下文的对象是否为 None, 如 `request` 和 `g`:

        class User(db.Model):

            def __init__(self, username, remote_addr=None):
                self.username = username
                if remote_addr is None and request:
                    remote_addr = request.remote_addr
                self.remote_addr = remote_addr

    .. versionadded:: 0.7
    """
    return _request_ctx_stack.top is not None


def has_app_context():
    """Works like :func:`has_request_context` but for the application
    context.  You can also just do a boolean check on the
    :data:`current_app` object instead.

    和 `has_request_context` 类似, 不过是用来检查应用上下文的.
    你也可以直接对 `current_app` 进行布尔检查.

    .. versionadded:: 0.9
    """
    return _app_ctx_stack.top is not None


class AppContext(object):
    """The application context binds an application object implicitly
    to the current thread or greenlet, similar to how the
    :class:`RequestContext` binds request information.  The application
    context is also implicitly created if a request context is created
    but the application is not on top of the individual application
    context.

    应用上下文隐式绑定到当前线程或 `greenlet` 的应用对象. 类似于 `RequestContext`
    绑定请求信息的实现方式. 如果请求上下文被创建, 应用上下文也隐式创建,
    但应用不在单个应用上下文的栈顶.
    """

    def __init__(self, app):
        self.app = app
        self.url_adapter = app.create_url_adapter(None)
        self.g = app.app_ctx_globals_class()

        # Like request context, app contexts can be pushed multiple times
        # but there a basic "refcount" is enough to track them.
        # 类似于请求上下文, 应用上下文也可以多次入栈, 但有一个 "引用计数" 就足够追踪了.
        self._refcnt = 0

    def push(self):
        """Binds the app context to the current context.
        将应用上下文绑定到当前上下文.
        """
        self._refcnt += 1
        if hasattr(sys, "exc_clear"):
            sys.exc_clear()
        _app_ctx_stack.push(self)
        appcontext_pushed.send(self.app)

    def pop(self, exc=_sentinel):
        """Pops the app context.
        应用上下文出栈.
        """
        try:
            self._refcnt -= 1
            if self._refcnt <= 0:
                if exc is _sentinel:
                    exc = sys.exc_info()[1]
                self.app.do_teardown_appcontext(exc)
        finally:
            rv = _app_ctx_stack.pop()
        assert rv is self, "Popped wrong app context.  (%r instead of %r)" % (rv, self)
        appcontext_popped.send(self.app)

    def __enter__(self):
        self.push()
        return self

    def __exit__(self, exc_type, exc_value, tb):
        self.pop(exc_value)

        if BROKEN_PYPY_CTXMGR_EXIT and exc_type is not None:
            reraise(exc_type, exc_value, tb)


class RequestContext(object):
    """The request context contains all request relevant information.  It is
    created at the beginning of the request and pushed to the
    `_request_ctx_stack` and removed at the end of it.  It will create the
    URL adapter and request object for the WSGI environment provided.

    请求上下文包含所有请求相关的信息. 请求开始时创建请求上下文, 推入 `_request_ctx_stack`,
    请求结束后出栈. 它将为提供的 WSGI 环境创建 URL 适配器和请求对象

    Do not attempt to use this class directly, instead use
    :meth:`~flask.Flask.test_request_context` and
    :meth:`~flask.Flask.request_context` to create this object.

    请不要直接使用此类, 而应当使用 `flask.Flask.test_request_context` 和
    `flask.Flask.request_context` 方法来创建实例.

    When the request context is popped, it will evaluate all the
    functions registered on the application for teardown execution
    (:meth:`~flask.Flask.teardown_request`).

    请求上下文出栈后, 它将评估所有注册到应用的函数以进行
    "请求拆除"(flask.Flask.teardown_request)

    The request context is automatically popped at the end of the request
    for you.  In debug mode the request context is kept around if
    exceptions happen so that interactive debuggers have a chance to
    introspect the data.  With 0.4 this can also be forced for requests
    that did not fail and outside of ``DEBUG`` mode.  By setting
    ``'flask._preserve_context'`` to ``True`` on the WSGI environment the
    context will not pop itself at the end of the request.  This is used by
    the :meth:`~flask.Flask.test_client` for example to implement the
    deferred cleanup functionality.

    请求结束后, 请求上下文将自动弹出. 在调试模式下, 请求上下文在发生异常时会继续保持,
    以便交互式的调试器可以拿到内省数据. 使用 0.4 版本时也可以强制未失败且处于
    调试模式之外的请求. 在 WSGI 环境下, 如果把 `flask._preserve_context`
    设为 `True`, 请求结束后不弹出上下文. 这种情况在 `flask.Flask.test_client`
    方法中使用, 例如实现延迟清理功能.

    You might find this helpful for unittests where you need the
    information from the context local around for a little longer.  Make
    sure to properly :meth:`~werkzeug.LocalStack.pop` the stack yourself in
    that situation, otherwise your unittests will leak memory.

    你会发现这在单元测试时很有用. 单元测试时需要上下文的信息多保留一段时间.
    在这种情况下一定要正确地自行通过 `werkzeug.LocalStack.pop` 方法弹出上下文,
    否则单元测试将会出现泄漏内存的情况.
    """

    def __init__(self, app, environ, request=None, session=None):
        self.app = app
        if request is None:
            request = app.request_class(environ)
        self.request = request
        self.url_adapter = None
        try:
            self.url_adapter = app.create_url_adapter(self.request)
        except HTTPException as e:
            self.request.routing_exception = e
        self.flashes = None
        self.session = session

        # Request contexts can be pushed multiple times and interleaved with
        # other request contexts.  Now only if the last level is popped we
        # get rid of them.  Additionally if an application context is missing
        # one is created implicitly so for each level we add this information
        #
        # 请求上下文可用被多次推入, 并与其他请求上下文交错. 只有最后一级弹出的时候才能摆脱.
        # 另外如果找不到应用上下文, 将会隐式创建一个, 所以每一级我们都加入这些信息
        self._implicit_app_ctx_stack = []

        # indicator if the context was preserved.  Next time another context
        # is pushed the preserved context is popped.
        #
        # 上下文被保留的标志. 下次其他上下文推入的时候, 保留的上下文就被弹出.
        self.preserved = False

        # remembers the exception for pop if there is one in case the context
        # preservation kicks in.
        #
        # 如果存在上下文保留的情况, 记住弹出的异常.
        self._preserved_exc = None

        # Functions that should be executed after the request on the response
        # object.  These will be called before the regular "after_request"
        # functions.
        #
        # 请求对象的请求完成以后应当执行的函数列表. 这些函数将在 "after_request" 装饰的
        # 函数之前调用.
        self._after_request_functions = []

    @property
    def g(self):
        return _app_ctx_stack.top.g

    @g.setter
    def g(self, value):
        _app_ctx_stack.top.g = value

    def copy(self):
        """Creates a copy of this request context with the same request object.
        This can be used to move a request context to a different greenlet.
        Because the actual request object is the same this cannot be used to
        move a request context to a different thread unless access to the
        request object is locked.

        使用相同的请求对象创建这个请求上下文的拷贝. 可以在将一个请求转移到不同的 greenlet 时
        使用. 因为真实的请求对象是一样的, 不能用于移动一个请求上下文到不同的线程中, 除非访问
        请求对象的过程是加锁的.

        .. versionadded:: 0.10

        .. versionchanged:: 1.1
           The current session object is used instead of reloading the original
           data. This prevents `flask.session` pointing to an out-of-date object.
        """
        return self.__class__(
            self.app,
            environ=self.request.environ,
            request=self.request,
            session=self.session,
        )

    def match_request(self):
        """Can be overridden by a subclass to hook into the matching
        of the request.
        可以由子类覆盖, 以钩入请求的匹配项中.
        """
        try:
            result = self.url_adapter.match(return_rule=True)
            self.request.url_rule, self.request.view_args = result
        except HTTPException as e:
            self.request.routing_exception = e

    def push(self):
        """Binds the request context to the current context.
        将请求上下文绑定到当前上下文.
        """
        # If an exception occurs in debug mode or if context preservation is
        # activated under exception situations exactly one context stays
        # on the stack.  The rationale is that you want to access that
        # information under debug situations.  However if someone forgets to
        # pop that context again we want to make sure that on the next push
        # it's invalidated, otherwise we run at risk that something leaks
        # memory.  This is usually only a problem in test suite since this
        # functionality is not active in production environments.
        #
        # 如果在调试模式下发生异常或在异常情况下激活了上下文保存, 则一个上下文留在栈中.
        # 在调试的情况下会想要访问这些信息, 这很合理. 但如果有人再次忘了弹出那个上下文,
        # 我们就想要保证下次推入是无效的了, 否则我们就要承担内存泄露的风险. 这通常只是一个
        # 测试套件中的问题, 因为此功能在生产环境中不会被激活.
        top = _request_ctx_stack.top
        if top is not None and top.preserved:
            top.pop(top._preserved_exc)

        # Before we push the request context we have to ensure that there
        # is an application context.
        #
        # 推入请求上下文前必须保证有应用上下文.
        app_ctx = _app_ctx_stack.top
        if app_ctx is None or app_ctx.app != self.app:
            app_ctx = self.app.app_context()
            app_ctx.push()
            self._implicit_app_ctx_stack.append(app_ctx)
        else:
            self._implicit_app_ctx_stack.append(None)

        if hasattr(sys, "exc_clear"):
            sys.exc_clear()

        _request_ctx_stack.push(self)

        # Open the session at the moment that the request context is available.
        # This allows a custom open_session method to use the request context.
        # Only open a new session if this is the first time the request was
        # pushed, otherwise stream_with_context loses the session.
        #
        # 在请求上下文可用时打开会话. 允许自定义的 open_session 方法使用应用上下文.
        # 只有第一次推入请求的时候才开启新的会话, 不然 stream_with_context 会丢失会话.
        if self.session is None:
            session_interface = self.app.session_interface
            self.session = session_interface.open_session(self.app, self.request)

            if self.session is None:
                self.session = session_interface.make_null_session(self.app)

        if self.url_adapter is not None:
            self.match_request()

    def pop(self, exc=_sentinel):
        """Pops the request context and unbinds it by doing that.  This will
        also trigger the execution of functions registered by the
        :meth:`~flask.Flask.teardown_request` decorator.

        弹出应用上下文并解绑. 同时也会触发由 `flask.Flask.teardown_request` 装饰的函数.

        .. versionchanged:: 0.9
           Added the `exc` argument.
        """
        app_ctx = self._implicit_app_ctx_stack.pop()

        try:
            clear_request = False
            if not self._implicit_app_ctx_stack:
                self.preserved = False
                self._preserved_exc = None
                if exc is _sentinel:
                    exc = sys.exc_info()[1]
                self.app.do_teardown_request(exc)

                # If this interpreter supports clearing the exception information
                # we do that now.  This will only go into effect on Python 2.x,
                # on 3.x it disappears automatically at the end of the exception
                # stack.
                #
                # 如果解释器支持清除异常信息就立即执行清除. 只有在 Python 2.X 有效.
                # 3.X 在异常栈结束后自动清除.
                if hasattr(sys, "exc_clear"):
                    sys.exc_clear()

                request_close = getattr(self.request, "close", None)
                if request_close is not None:
                    request_close()
                clear_request = True
        finally:
            rv = _request_ctx_stack.pop()

            # get rid of circular dependencies at the end of the request
            # so that we don't require the GC to be active.
            # 在请求的最后摆脱循环依赖, 所以我们不要求启动垃圾回收.
            if clear_request:
                rv.request.environ["werkzeug.request"] = None

            # Get rid of the app as well if necessary.
            # 如果有必要, 同样弹出 app
            if app_ctx is not None:
                app_ctx.pop(exc)

            assert rv is self, "Popped wrong request context. (%r instead of %r)" % (
                rv,
                self,
            )

    def auto_pop(self, exc):
        if self.request.environ.get("flask._preserve_context") or (
            exc is not None and self.app.preserve_context_on_exception
        ):
            self.preserved = True
            self._preserved_exc = exc
        else:
            self.pop(exc)

    def __enter__(self):
        self.push()
        return self

    def __exit__(self, exc_type, exc_value, tb):
        # do not pop the request stack if we are in debug mode and an
        # exception happened.  This will allow the debugger to still
        # access the request object in the interactive shell.  Furthermore
        # the context can be force kept alive for the test client.
        # See flask.testing for how this works.
        #
        # 当调试模式下发生异常时, 不要弹出请求栈. 这样做将允许调试器在交互式 shell 中
        # 继续访问请求对象. 参见 `flask.testing` 了解如何工作的.
        self.auto_pop(exc_value)

        if BROKEN_PYPY_CTXMGR_EXIT and exc_type is not None:
            reraise(exc_type, exc_value, tb)

    def __repr__(self):
        return "<%s '%s' [%s] of %s>" % (
            self.__class__.__name__,
            self.request.url,
            self.request.method,
            self.app.name,
        )
