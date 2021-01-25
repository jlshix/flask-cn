# -*- coding: utf-8 -*-
"""
    flask.helpers
    ~~~~~~~~~~~~~

    Implements various helpers.
    各种帮助函数的实现

    :copyright: 2010 Pallets
    :license: BSD-3-Clause
"""
import io
import mimetypes
import os
import pkgutil
import posixpath
import socket
import sys
import unicodedata
from functools import update_wrapper
from threading import RLock
from time import time
from zlib import adler32

from jinja2 import FileSystemLoader
from werkzeug.datastructures import Headers
from werkzeug.exceptions import BadRequest
from werkzeug.exceptions import NotFound
from werkzeug.exceptions import RequestedRangeNotSatisfiable
from werkzeug.routing import BuildError
from werkzeug.urls import url_quote
from werkzeug.wsgi import wrap_file

from ._compat import fspath
from ._compat import PY2
from ._compat import string_types
from ._compat import text_type
from .globals import _app_ctx_stack
from .globals import _request_ctx_stack
from .globals import current_app
from .globals import request
from .globals import session
from .signals import message_flashed

# sentinel
# 参数缺失的标志
_missing = object()


# what separators does this operating system provide that are not a slash?
# this is used by the send_from_directory function to ensure that nobody is
# able to access files from outside the filesystem.
#
# 操作系统提供的除斜线 ("/") 以外的分隔符有哪些?
# 在 `send_from_directory` 函数中使用, 可以保证没有人可以访问文件系统之外的文件.
_os_alt_seps = list(
    sep for sep in [os.path.sep, os.path.altsep] if sep not in (None, "/")
)


def get_env():
    """Get the environment the app is running in, indicated by the
    :envvar:`FLASK_ENV` environment variable. The default is
    ``'production'``.

    获取 app 执行的环境, 以环境变量 `FLASK_ENV` 的值来确定. 默认为 `production`.
    """
    return os.environ.get("FLASK_ENV") or "production"


def get_debug_flag():
    """Get whether debug mode should be enabled for the app, indicated
    by the :envvar:`FLASK_DEBUG` environment variable. The default is
    ``True`` if :func:`.get_env` returns ``'development'``, or ``False``
    otherwise.

    确定是否在 debug 模式下执行 app, 以环境变量 `FLASK_DEBUG` 的值来确定. 如果
    `get_env` 返回 `deployment` 则默认为 `True`, 否则为 False.
    """
    val = os.environ.get("FLASK_DEBUG")

    if not val:
        return get_env() == "development"

    return val.lower() not in ("0", "false", "no")


def get_load_dotenv(default=True):
    """Get whether the user has disabled loading dotenv files by setting
    :envvar:`FLASK_SKIP_DOTENV`. The default is ``True``, load the
    files.

    确定用户是否加载以点号 (".") 开头的文件, 以环境变量 `FLASK_SKIP_DOTENV` 的值
    来确定. 默认为 `True`, 加载点号开头的文件.

    :param default: What to return if the env var isn't set.
    参数 default: 如果未设定这个环境变量, 返回默认值.
    """
    val = os.environ.get("FLASK_SKIP_DOTENV")

    if not val:
        return default

    return val.lower() in ("0", "false", "no")


def _endpoint_from_view_func(view_func):
    """Internal helper that returns the default endpoint for a given
    function.  This always is the function name.

    内部使用的帮助函数, 返回给定视图函数的默认 endpoint. 这个值总是函数的名字.
    """
    assert view_func is not None, "expected view func if endpoint is not provided."
    return view_func.__name__


def stream_with_context(generator_or_function):
    """Request contexts disappear when the response is started on the server.
    This is done for efficiency reasons and to make it less likely to encounter
    memory leaks with badly written WSGI middlewares.  The downside is that if
    you are using streamed responses, the generator cannot access request bound
    information any more.

    当服务的返回开始时, 请求上下文就会消失. 这样做是为了效率, 也是为了在 WSGI 中间件有问题
    的时候更少发生内存泄露. 问题是如果用了流式返回, 这个生成器就无法访问请求绑定的信息了.

    This function however can help you keep the context around for longer::

    这个函数可以帮助你将这个上下文维持更长时间:

        from flask import stream_with_context, request, Response

        @app.route('/stream')
        def streamed_response():
            @stream_with_context
            def generate():
                yield 'Hello '
                yield request.args['name']
                yield '!'
            return Response(generate())

    Alternatively it can also be used around a specific generator::

    你也可以不作为装饰器使用, 直接将函数或生成器作为参数:

        from flask import stream_with_context, request, Response

        @app.route('/stream')
        def streamed_response():
            def generate():
                yield 'Hello '
                yield request.args['name']
                yield '!'
            return Response(stream_with_context(generate()))

    .. versionadded:: 0.9
    """
    try:
        gen = iter(generator_or_function)
    except TypeError:

        def decorator(*args, **kwargs):
            gen = generator_or_function(*args, **kwargs)
            return stream_with_context(gen)

        return update_wrapper(decorator, generator_or_function)

    def generator():
        ctx = _request_ctx_stack.top
        if ctx is None:
            raise RuntimeError(
                "Attempted to stream with context but "
                "there was no context in the first place to keep around."
            )
        with ctx:
            # Dummy sentinel.  Has to be inside the context block or we're
            # not actually keeping the context around.
            #
            # 虚拟哨兵. 必须在上下文块内, 否则实际上不会保留上下文.
            yield None

            # The try/finally is here so that if someone passes a WSGI level
            # iterator in we're still running the cleanup logic.  Generators
            # don't need that because they are closed on their destruction
            # automatically.
            #
            # 这个 try/finally 块保证即使传入了 WSGI 级别的迭代器, 依然可以执行清理逻辑.
            # 生成器不需要, 因为在析构的时候自动执行了关闭操作.
            try:
                for item in gen:
                    yield item
            finally:
                if hasattr(gen, "close"):
                    gen.close()

    # The trick is to start the generator.  Then the code execution runs until
    # the first dummy None is yielded at which point the context was already
    # pushed.  This item is discarded.  Then when the iteration continues the
    # real generator is executed.
    #
    # 使用这种方式启动生成器. 然后代码执行, 直到生成完毕第一个虚拟哨兵. 这时候上下文已经推入了.
    # 丢弃此项. 然后迭代继续, 执行了真正的生成器.
    wrapped_g = generator()
    next(wrapped_g)
    return wrapped_g


def make_response(*args):
    """Sometimes it is necessary to set additional headers in a view.  Because
    views do not have to return response objects but can return a value that
    is converted into a response object by Flask itself, it becomes tricky to
    add headers to it.  This function can be called instead of using a return
    and you will get a response object which you can use to attach headers.

    有时候有必要在一个视图上添加额外的返回头数据. 因为视图函数不返回响应对象, 而是返回一个
    值, 由 Flask 本身转换为响应对象. 要想加上额外的返回头就有点麻烦了. 可以调用这个函数
    代替原来的返回值, 这样就可以获取一个响应对象, 在这个对象上就可以添加额外的返回头了.

    If view looked like this and you want to add a new header::

    如果视图函数就像这样, 并且你想加个新的返回头:

        def index():
            return render_template('index.html', foo=42)

    You can now do something like this::

    你可以这样做:

        def index():
            response = make_response(render_template('index.html', foo=42))
            response.headers['X-Parachutes'] = 'parachutes are cool'
            return response

    This function accepts the very same arguments you can return from a
    view function.  This for example creates a response with a 404 error
    code::

    这个函数接收的参数和你在视图函数返回的值非常相似. 以下的例子是创建一个返回 404 错误
    的例子:

        response = make_response(render_template('not_found.html'), 404)

    The other use case of this function is to force the return value of a
    view function into a response which is helpful with view
    decorators::

    其他的使用情景包括强制把视图函数的返回值包含到响应中. 在视图装饰器时很有用.

        response = make_response(view_function())
        response.headers['X-Parachutes'] = 'parachutes are cool'

    Internally this function does the following things:

    这个函数内部做了以下工作:

    -   if no arguments are passed, it creates a new response argument
    -   如果未传入任何参数, 将创建一个新的响应参数

    -   if one argument is passed, :meth:`flask.Flask.make_response`
        is invoked with it.
    -   如果传入一个参数, 将使用这个参数触发 `flask.Flask.make_response`

    -   if more than one argument is passed, the arguments are passed
        to the :meth:`flask.Flask.make_response` function as tuple.
    -   如果传入不止一个参数, 这些参数将被作为一个元组传入 `flask.Flask.make_response`.

    .. versionadded:: 0.6
    """
    if not args:
        return current_app.response_class()
    if len(args) == 1:
        args = args[0]
    return current_app.make_response(args)


def url_for(endpoint, **values):
    """Generates a URL to the given endpoint with the method provided.

    根据提供的方法名生成一个指向 endpoint 的 URL

    Variable arguments that are unknown to the target endpoint are appended
    to the generated URL as query arguments.  If the value of a query argument
    is ``None``, the whole pair is skipped.  In case blueprints are active
    you can shortcut references to the same blueprint by prefixing the
    local endpoint with a dot (``.``).

    目标 endpoint 未知的变量参数将作为查询参数附加到生成的 URL 中. 跳过值为 `None` 的
    键值对. 使用蓝图时可以在前面直接加点号 (".") 来指向同一蓝图的 endpoint.


    This will reference the index function local to the current blueprint::

    以下示例指向当前蓝图的 index 函数:

        url_for('.index')

    For more information, head over to the :ref:`Quickstart <url-building>`.

    了解更多, 请参见 `快速开始: 组建 URL`.

    Configuration values ``APPLICATION_ROOT`` and ``SERVER_NAME`` are only used when
    generating URLs outside of a request context.

    配置值 `APPLICATION_ROOT` 和 `SERVER_NAME` 只在生成请求上下文外的 URL 时使用.

    To integrate applications, :class:`Flask` has a hook to intercept URL build
    errors through :attr:`Flask.url_build_error_handlers`.  The `url_for`
    function results in a :exc:`~werkzeug.routing.BuildError` when the current
    app does not have a URL for the given endpoint and values.  When it does, the
    :data:`~flask.current_app` calls its :attr:`~Flask.url_build_error_handlers` if
    it is not ``None``, which can return a string to use as the result of
    `url_for` (instead of `url_for`'s default to raise the
    :exc:`~werkzeug.routing.BuildError` exception) or re-raise the exception.

    为了应用集成, `Flask` 类有一个通过 `Flask.url_build_error_handlers` 属性监听
    URL 组建失败的钩子. 当前 app 没有一个给定 endpoint 指向的 URL 时, `url_for` 函数会
    抛出 `werkzeug.routing.BuildError`. 当这个异常抛出且 `Flask.url_build_error_handlers`
    不为 `None` 时, `current_app` 将调用其自身的 `Flask.url_build_error_handlers`
    中注册的函数. 然后返回一个字符串作为 `url_for` 的返回, 而不是让 `url_for` 抛出
    `werkzeug.routing.BuildError` 异常或重新抛出.

    An example::
    例如:


        def external_url_handler(error, endpoint, values):
            "Looks up an external URL when `url_for` cannot build a URL."
            # This is an example of hooking the build_error_handler.
            # Here, lookup_url is some utility function you've built
            # which looks up the endpoint in some external URL registry.
            url = lookup_url(endpoint, **values)
            if url is None:
                # External lookup did not have a URL.
                # Re-raise the BuildError, in context of original traceback.
                exc_type, exc_value, tb = sys.exc_info()
                if exc_value is error:
                    raise exc_type, exc_value, tb
                else:
                    raise error
            # url_for will use this result, instead of raising BuildError.
            return url

        app.url_build_error_handlers.append(external_url_handler)

    Here, `error` is the instance of :exc:`~werkzeug.routing.BuildError`, and
    `endpoint` and `values` are the arguments passed into `url_for`.  Note
    that this is for building URLs outside the current application, and not for
    handling 404 NotFound errors.

    这里的 `error` 是 `werkzeug.routing.BuildError` 的实例, `endpoint` 和 `values`
    是传入 `url_for` 的参数. 注意这里是为了组建当前 app 之外的 URL, 不是为了处理 404 错误.

    .. versionadded:: 0.10
       The `_scheme` parameter was added.

    .. versionadded:: 0.9
       The `_anchor` and `_method` parameters were added.

    .. versionadded:: 0.9
       Calls :meth:`Flask.handle_build_error` on
       :exc:`~werkzeug.routing.BuildError`.

    :param endpoint: the endpoint of the URL (name of the function)
    参数 endpoint: URL 的 endpoint (函数的名字)

    :param values: the variable arguments of the URL rule
    参数 values: URL 规则的变量参数

    :param _external: if set to ``True``, an absolute URL is generated. Server
      address can be changed via ``SERVER_NAME`` configuration variable which
      falls back to the `Host` header, then to the IP and port of the request.
    参数 _external: 如果设为 `True`, 将生成一个绝对路径的 URL. 服务器地址按优先级
        可以被替换为 `SERVER_NAME` 配置的值, 请求 headers 中 `Host` 的值或者 IP 和端口.

    :param _scheme: a string specifying the desired URL scheme. The `_external`
      parameter must be set to ``True`` or a :exc:`ValueError` is raised. The default
      behavior uses the same scheme as the current request, or
      ``PREFERRED_URL_SCHEME`` from the :ref:`app configuration <config>` if no
      request context is available. As of Werkzeug 0.10, this also can be set
      to an empty string to build protocol-relative URLs.
    参数 _scheme: 指定期望的 URL 模式. `_external` 参数必须设为 `True` 否则将抛出
        `ValueError`. 默认的模式和当前请求的一致, 如果当前上下文不可用, 使用配置中指定的
        `PREFERRED_URL_SCHEME`. 对于 Werkzeug 0.10, 可以设为空字符串, 来构建协议相关的 URL.

    :param _anchor: if provided this is added as anchor to the URL.
    参数 _anchor: 如果提供了这个参数, 将作为锚点加到 URL 中.

    :param _method: if provided this explicitly specifies an HTTP method.
    参数 _method: 如果提供了这个参数, 将指定 HTTP 请求方式.
    """
    appctx = _app_ctx_stack.top
    reqctx = _request_ctx_stack.top

    if appctx is None:
        raise RuntimeError(
            "Attempted to generate a URL without the application context being"
            " pushed. This has to be executed when application context is"
            " available."
        )

    # If request specific information is available we have some extra
    # features that support "relative" URLs.
    #
    # 如果有请求指定信息, 我们有额外特性支持 "相对" URL.
    if reqctx is not None:
        url_adapter = reqctx.url_adapter
        blueprint_name = request.blueprint

        if endpoint[:1] == ".":
            if blueprint_name is not None:
                endpoint = blueprint_name + endpoint
            else:
                endpoint = endpoint[1:]

        external = values.pop("_external", False)

    # Otherwise go with the url adapter from the appctx and make
    # the URLs external by default.
    #
    # 否则使用应用上下文的 URL 适配器, 默认使用外部 URL.
    else:
        url_adapter = appctx.url_adapter

        if url_adapter is None:
            raise RuntimeError(
                "Application was not able to create a URL adapter for request"
                " independent URL generation. You might be able to fix this by"
                " setting the SERVER_NAME config variable."
            )

        external = values.pop("_external", True)

    anchor = values.pop("_anchor", None)
    method = values.pop("_method", None)
    scheme = values.pop("_scheme", None)
    appctx.app.inject_url_defaults(endpoint, values)

    # This is not the best way to deal with this but currently the
    # underlying Werkzeug router does not support overriding the scheme on
    # a per build call basis.
    #
    # 这不是解决此问题的最佳方法. 但是当前底层的 Werkzeug 路由不支持在每个构建调用的
    # 基础上覆盖模式.
    old_scheme = None
    if scheme is not None:
        if not external:
            raise ValueError("When specifying _scheme, _external must be True")
        old_scheme = url_adapter.url_scheme
        url_adapter.url_scheme = scheme

    try:
        try:
            rv = url_adapter.build(
                endpoint, values, method=method, force_external=external
            )
        finally:
            if old_scheme is not None:
                url_adapter.url_scheme = old_scheme
    except BuildError as error:
        # We need to inject the values again so that the app callback can
        # deal with that sort of stuff.
        #
        # 我们需要再次注入这些值, 以便 app 回调处理.
        values["_external"] = external
        values["_anchor"] = anchor
        values["_method"] = method
        values["_scheme"] = scheme
        return appctx.app.handle_url_build_error(error, endpoint, values)

    if anchor is not None:
        rv += "#" + url_quote(anchor)
    return rv


def get_template_attribute(template_name, attribute):
    """Loads a macro (or variable) a template exports.  This can be used to
    invoke a macro from within Python code.  If you for example have a
    template named :file:`_cider.html` with the following contents:

    加载一个模板输出的宏(或者变量). 可以在 Python 代码中调用宏. 例如你有一个模板叫做
    `_cider.html`, 包含以下内容:

    .. sourcecode:: html+jinja

       {% macro hello(name) %}Hello {{ name }}!{% endmacro %}

    You can access this from Python code like this::

    你可以在 Python 代码中这样访问:

        hello = get_template_attribute('_cider.html', 'hello')
        return hello('World')

    .. versionadded:: 0.2

    :param template_name: the name of the template
    参数 template_name: 模板名

    :param attribute: the name of the variable of macro to access
    参数 attribute: 要访问的变量或宏的名字
    """
    return getattr(current_app.jinja_env.get_template(template_name).module, attribute)


def flash(message, category="message"):
    """Flashes a message to the next request.  In order to remove the
    flashed message from the session and to display it to the user,
    the template has to call :func:`get_flashed_messages`.

    在下一个请求里展示提示消息. 为了在会话中移除已经展示的消息并展示给用户, 模板必须
    调用 `get_flashed_messages` 函数.

    .. versionchanged:: 0.3
       `category` parameter added.

    :param message: the message to be flashed.
    参数 message: 要展示的消息.

    :param category: the category for the message.  The following values
                     are recommended: ``'message'`` for any kind of message,
                     ``'error'`` for errors, ``'info'`` for information
                     messages and ``'warning'`` for warnings.  However any
                     kind of string can be used as category.
    参数 category: 消息类别. 建议使用以下值: 任何消息都可以使用 `message`, 错误消息使用
        `error`, 提示信息使用 `info`, 警告信息使用 `warning`. 当然任何值都可以作为类别
        的名字, 不限于以上推荐的几个.
    """
    # Original implementation:
    #
    # 原来的实现方式:
    #
    #     session.setdefault('_flashes', []).append((category, message))
    #
    # This assumed that changes made to mutable structures in the session are
    # always in sync with the session object, which is not true for session
    # implementations that use external storage for keeping their keys/values.
    #
    # 这种方式假定可变结构所做的更改始终与会话对象同步, 这不适用于使用外部存储保留键值对的
    # 会话实现.
    flashes = session.get("_flashes", [])
    flashes.append((category, message))
    session["_flashes"] = flashes
    message_flashed.send(
        current_app._get_current_object(), message=message, category=category
    )


def get_flashed_messages(with_categories=False, category_filter=()):
    """Pulls all flashed messages from the session and returns them.
    Further calls in the same request to the function will return
    the same messages.  By default just the messages are returned,
    but when `with_categories` is set to ``True``, the return value will
    be a list of tuples in the form ``(category, message)`` instead.

    从会话中拿到所有已展示的消息并返回. 在统一请求中进一步调用此函数将返回相同的信息.
    默认返回的就是这些信息, 当 `with_categories` 设为 `True` 时, 返回值将是
    由元组组成的列表, 每一项为 `(category, message)`.

    Filter the flashed messages to one or more categories by providing those
    categories in `category_filter`.  This allows rendering categories in
    separate html blocks.  The `with_categories` and `category_filter`
    arguments are distinct:

    使用 `category_filter` 传入的元组过滤已经展示的消息. 可以实现在单独的 html 块中
    展示类别. with_categories` 和 `category_filter` 不同:

    * `with_categories` controls whether categories are returned with message
      text (``True`` gives a tuple, where ``False`` gives just the message text).
    * `with_categories` 控制返回的消息中是否带有分类.
      (每一项在设为 `True` 时是元组, `False` 时是消息文本)

    * `category_filter` filters the messages down to only those matching the
      provided categories.
    * `category_filter` 筛选符合给定类别的消息.

    See :ref:`message-flashing-pattern` for examples.
    参见 `message-flashing-pattern` 获取示例.

    .. versionchanged:: 0.3
       `with_categories` parameter added.

    .. versionchanged:: 0.9
        `category_filter` parameter added.

    :param with_categories: set to ``True`` to also receive categories.
    参数 with_categories: 设为 `True` 同时接收类别信息.

    :param category_filter: whitelist of categories to limit return values
    参数 category_filter: 限制返回消息类别的白名单.
    """
    flashes = _request_ctx_stack.top.flashes
    if flashes is None:
        _request_ctx_stack.top.flashes = flashes = (
            session.pop("_flashes") if "_flashes" in session else []
        )
    if category_filter:
        flashes = list(filter(lambda f: f[0] in category_filter, flashes))
    if not with_categories:
        return [x[1] for x in flashes]
    return flashes


def send_file(
    filename_or_fp,
    mimetype=None,
    as_attachment=False,
    attachment_filename=None,
    add_etags=True,
    cache_timeout=None,
    conditional=False,
    last_modified=None,
):
    """Sends the contents of a file to the client.  This will use the
    most efficient method available and configured.  By default it will
    try to use the WSGI server's file_wrapper support.  Alternatively
    you can set the application's :attr:`~Flask.use_x_sendfile` attribute
    to ``True`` to directly emit an ``X-Sendfile`` header.  This however
    requires support of the underlying webserver for ``X-Sendfile``.

    将文件内容发送到客户端. 将使用可用的最有效的方法并进行配置. 默认尝试 WSGI 服务器的
    file_wrapper 支持. 你也可以配置应用的 `Flask.use_x_sendfile` 属性为 `True`
    直接发出一个 `X-Sendfile` header. 当然这样要求底层的 webserver 支持
    `X-Sendfile`.

    By default it will try to guess the mimetype for you, but you can
    also explicitly provide one.  For extra security you probably want
    to send certain files as attachment (HTML for instance).  The mimetype
    guessing requires a `filename` or an `attachment_filename` to be
    provided.

    此方法默认(根据文件类型)尝试猜测 mimetype, 也可以直接提供一个. 额外为了安全你或许
    想发送某些文件作为附件(例如 HTML). mimetype 猜测需要提供一个 `filename` 或者
    `attachment_filename`.

    ETags will also be attached automatically if a `filename` is provided. You
    can turn this off by setting `add_etags=False`.

    如果提供了 `filename`, etags 也会自动添加. 你可以通过设置 `add_etags=False` 关闭此功能.

    If `conditional=True` and `filename` is provided, this method will try to
    upgrade the response stream to support range requests.  This will allow
    the request to be answered with partial content response.

    如果 `conditional=True` 并提供了 `filename`, 这个方法将尝试为响应流升级以支持范围请求.
    这将允许以部分内容响应请求.

    Please never pass filenames to this function from user sources;
    you should use :func:`send_from_directory` instead.

    请一定不要将用户输入的文件名传入此函数; 而是使用 `send_from_directory`.

    .. versionadded:: 0.2

    .. versionadded:: 0.5
       The `add_etags`, `cache_timeout` and `conditional` parameters were
       added.  The default behavior is now to attach etags.

    .. versionchanged:: 0.7
       mimetype guessing and etag support for file objects was
       deprecated because it was unreliable.  Pass a filename if you are
       able to, otherwise attach an etag yourself.  This functionality
       will be removed in Flask 1.0

    .. versionchanged:: 0.9
       cache_timeout pulls its default from application config, when None.

    .. versionchanged:: 0.12
       The filename is no longer automatically inferred from file objects. If
       you want to use automatic mimetype and etag support, pass a filepath via
       `filename_or_fp` or `attachment_filename`.

    .. versionchanged:: 0.12
       The `attachment_filename` is preferred over `filename` for MIME-type
       detection.

    .. versionchanged:: 1.0
        UTF-8 filenames, as specified in `RFC 2231`_, are supported.

    .. _RFC 2231: https://tools.ietf.org/html/rfc2231#section-4

    .. versionchanged:: 1.0.3
        Filenames are encoded with ASCII instead of Latin-1 for broader
        compatibility with WSGI servers.

    .. versionchanged:: 1.1
        Filename may be a :class:`~os.PathLike` object.

    .. versionadded:: 1.1
        Partial content supports :class:`~io.BytesIO`.

    :param filename_or_fp: the filename of the file to send.
                           This is relative to the :attr:`~Flask.root_path`
                           if a relative path is specified.
                           Alternatively a file object might be provided in
                           which case ``X-Sendfile`` might not work and fall
                           back to the traditional method.  Make sure that the
                           file pointer is positioned at the start of data to
                           send before calling :func:`send_file`.
    参数 filename_or_fp: 发送的文件名或文件. 如果指定相对路径, 则是相对 `Flask.root_path`
        指定的路径. 当指定请求头 `X-Sendfile` 时也可以传入文件对象, 如果不成功则回退到传统
        方式. 确认文件指针在调用 `send_file` 前指向文件数据的开头.

    :param mimetype: the mimetype of the file if provided. If a file path is
                     given, auto detection happens as fallback, otherwise an
                     error will be raised.
    参数 mimetype: 如果提供就作为文件的 mimetype. 如果给定文件路径, 自动检测作为后备选项,
        否则抛出异常.

    :param as_attachment: set to ``True`` if you want to send this file with
                          a ``Content-Disposition: attachment`` header.
    参数 as_attachment: 设为 `True` 时以返回头 `Content-Disposition: attachment` 返回.

    :param attachment_filename: the filename for the attachment if it
                                differs from the file's filename.
    参数 attachment_filename: 附件的文件名, 和文件名不一致时指定.

    :param add_etags: set to ``False`` to disable attaching of etags.
    参数 add_tags: 设为 `False` 禁用附加 etags.

    :param conditional: set to ``True`` to enable conditional responses.
    参数 conditional: 设为 `True` 启用条件回应.

    :param cache_timeout: the timeout in seconds for the headers. When ``None``
                          (default), this value is set by
                          :meth:`~Flask.get_send_file_max_age` of
                          :data:`~flask.current_app`.
    参数 cache_timeout: 返回头的超时秒数. 默认 `None`, 使用当前 app 的
        `Flask.get_send_file_max_age`.

    :param last_modified: set the ``Last-Modified`` header to this value,
        a :class:`~datetime.datetime` or timestamp.
        If a file was passed, this overrides its mtime.
    参数 last_modified: 设置返回头 `Last-Modified`, 值类型为 `datetime.datetime` 或
        时间戳. 如果传入一个文件, 覆盖其 mtime.
    """
    mtime = None
    fsize = None

    if hasattr(filename_or_fp, "__fspath__"):
        filename_or_fp = fspath(filename_or_fp)

    if isinstance(filename_or_fp, string_types):
        filename = filename_or_fp
        if not os.path.isabs(filename):
            filename = os.path.join(current_app.root_path, filename)
        file = None
        if attachment_filename is None:
            attachment_filename = os.path.basename(filename)
    else:
        file = filename_or_fp
        filename = None

    if mimetype is None:
        if attachment_filename is not None:
            mimetype = (
                mimetypes.guess_type(attachment_filename)[0]
                or "application/octet-stream"
            )

        if mimetype is None:
            raise ValueError(
                "Unable to infer MIME-type because no filename is available. "
                "Please set either `attachment_filename`, pass a filepath to "
                "`filename_or_fp` or set your own MIME-type via `mimetype`."
            )

    headers = Headers()
    if as_attachment:
        if attachment_filename is None:
            raise TypeError("filename unavailable, required for sending as attachment")

        if not isinstance(attachment_filename, text_type):
            attachment_filename = attachment_filename.decode("utf-8")

        try:
            attachment_filename = attachment_filename.encode("ascii")
        except UnicodeEncodeError:
            filenames = {
                "filename": unicodedata.normalize("NFKD", attachment_filename).encode(
                    "ascii", "ignore"
                ),
                "filename*": "UTF-8''%s" % url_quote(attachment_filename, safe=b""),
            }
        else:
            filenames = {"filename": attachment_filename}

        headers.add("Content-Disposition", "attachment", **filenames)

    if current_app.use_x_sendfile and filename:
        if file is not None:
            file.close()
        headers["X-Sendfile"] = filename
        fsize = os.path.getsize(filename)
        headers["Content-Length"] = fsize
        data = None
    else:
        if file is None:
            file = open(filename, "rb")
            mtime = os.path.getmtime(filename)
            fsize = os.path.getsize(filename)
            headers["Content-Length"] = fsize
        elif isinstance(file, io.BytesIO):
            try:
                fsize = file.getbuffer().nbytes
            except AttributeError:
                # Python 2 doesn't have getbuffer
                # Python 2 没有 getbuffer
                fsize = len(file.getvalue())
            headers["Content-Length"] = fsize
        data = wrap_file(request.environ, file)

    rv = current_app.response_class(
        data, mimetype=mimetype, headers=headers, direct_passthrough=True
    )

    if last_modified is not None:
        rv.last_modified = last_modified
    elif mtime is not None:
        rv.last_modified = mtime

    rv.cache_control.public = True
    if cache_timeout is None:
        cache_timeout = current_app.get_send_file_max_age(filename)
    if cache_timeout is not None:
        rv.cache_control.max_age = cache_timeout
        rv.expires = int(time() + cache_timeout)

    if add_etags and filename is not None:
        from warnings import warn

        try:
            rv.set_etag(
                "%s-%s-%s"
                % (
                    os.path.getmtime(filename),
                    os.path.getsize(filename),
                    adler32(
                        filename.encode("utf-8")
                        if isinstance(filename, text_type)
                        else filename
                    )
                    & 0xFFFFFFFF,
                )
            )
        except OSError:
            warn(
                "Access %s failed, maybe it does not exist, so ignore etags in "
                "headers" % filename,
                stacklevel=2,
            )

    if conditional:
        try:
            rv = rv.make_conditional(request, accept_ranges=True, complete_length=fsize)
        except RequestedRangeNotSatisfiable:
            if file is not None:
                file.close()
            raise
        # make sure we don't send x-sendfile for servers that
        # ignore the 304 status code for x-sendfile.
        #
        # 确认对于忽略 x-sendfile 的 304 状态码的服务器, 不发送 x-sendfile.
        if rv.status_code == 304:
            rv.headers.pop("x-sendfile", None)
    return rv


def safe_join(directory, *pathnames):
    """Safely join `directory` and zero or more untrusted `pathnames`
    components.

    安全地连接文件夹和 0 到多个不受信任的路径名

    Example usage::

        @app.route('/wiki/<path:filename>')
        def wiki_page(filename):
            filename = safe_join(app.config['WIKI_FOLDER'], filename)
            with open(filename, 'rb') as fd:
                content = fd.read()  # Read and process the file content...

    :param directory: the trusted base directory.
    参数 directory: 受信任的文件夹名

    :param pathnames: the untrusted pathnames relative to that directory.
    参数 pathnames: 不受信任的相对于文件夹的路径名

    :raises: :class:`~werkzeug.exceptions.NotFound` if one or more passed
            paths fall out of its boundaries.
    异常: 如果一个或多个路径超出其边界, 抛出 `werkzeug.exceptions.NotFound`
    """

    parts = [directory]

    for filename in pathnames:
        if filename != "":
            filename = posixpath.normpath(filename)

        if (
            any(sep in filename for sep in _os_alt_seps)
            or os.path.isabs(filename)
            or filename == ".."
            or filename.startswith("../")
        ):
            raise NotFound()

        parts.append(filename)

    return posixpath.join(*parts)


def send_from_directory(directory, filename, **options):
    """Send a file from a given directory with :func:`send_file`.  This
    is a secure way to quickly expose static files from an upload folder
    or something similar.

    从给定的目录使用 `send_file` 函数发送文件. 这是一个快速显示上传文件夹中静态文件
    或者其他类似操作的安全方法.

    Example usage::

    使用示例:

        @app.route('/uploads/<path:filename>')
        def download_file(filename):
            return send_from_directory(app.config['UPLOAD_FOLDER'],
                                       filename, as_attachment=True)

    .. admonition:: Sending files and Performance

       It is strongly recommended to activate either ``X-Sendfile`` support in
       your webserver or (if no authentication happens) to tell the webserver
       to serve files for the given path on its own without calling into the
       web application for improved performance.

    .. versionadded:: 0.5

    :param directory: the directory where all the files are stored.
    参数 directory: 存放所有文件的文件夹.

    :param filename: the filename relative to that directory to
                     download.
    参数 filename: 要下载的文件与那个文件夹相对路径的文件名.

    :param options: optional keyword arguments that are directly
                    forwarded to :func:`send_file`.
    参数 options: 可选的关键字参数, 直接发送给 `send_file` 函数.
    """
    filename = fspath(filename)
    directory = fspath(directory)
    filename = safe_join(directory, filename)
    if not os.path.isabs(filename):
        filename = os.path.join(current_app.root_path, filename)
    try:
        if not os.path.isfile(filename):
            raise NotFound()
    except (TypeError, ValueError):
        raise BadRequest()
    options.setdefault("conditional", True)
    return send_file(filename, **options)


def get_root_path(import_name):
    """Returns the path to a package or cwd if that cannot be found.  This
    returns the path of a package or the folder that contains a module.

    返回包的路径, 如果找不到返回当前工作目录. 这个函数返回包或包含模块的文件夹路径.

    Not to be confused with the package path returned by :func:`find_package`.

    不要与 `find_package` 返回的包路径混淆.
    """
    # Module already imported and has a file attribute.  Use that first.
    #
    # 模块已经导入并包含 `__file__` 属性, 优先使用这个.
    mod = sys.modules.get(import_name)
    if mod is not None and hasattr(mod, "__file__"):
        return os.path.dirname(os.path.abspath(mod.__file__))

    # Next attempt: check the loader.
    #
    # 然后尝试检查加载器.
    loader = pkgutil.get_loader(import_name)

    # Loader does not exist or we're referring to an unloaded main module
    # or a main module without path (interactive sessions), go with the
    # current working directory.
    #
    # 加载器不存在或者指向未加载的主模块或者主模块不包含路径(交互会话), 返回当前工作目录.
    if loader is None or import_name == "__main__":
        return os.getcwd()

    # For .egg, zipimporter does not have get_filename until Python 2.7.
    # Some other loaders might exhibit the same behavior.
    #
    # 对于 .egg, zipimporter 直到 Python 2.7 前都没有 get_filename 方法.
    # 一些其他加载器或许会展现同样的行为.
    if hasattr(loader, "get_filename"):
        filepath = loader.get_filename(import_name)
    else:
        # Fall back to imports.
        #
        # 回退到导入
        __import__(import_name)
        mod = sys.modules[import_name]
        filepath = getattr(mod, "__file__", None)

        # If we don't have a filepath it might be because we are a
        # namespace package.  In this case we pick the root path from the
        # first module that is contained in our package.
        #
        # 如果没有文件路径, 或许因为是一个命名空间包. 这种情况下我们从包中包含的
        # 第一个模块中选择根路径.
        if filepath is None:
            raise RuntimeError(
                "No root path can be found for the provided "
                'module "%s".  This can happen because the '
                "module came from an import hook that does "
                "not provide file name information or because "
                "it's a namespace package.  In this case "
                "the root path needs to be explicitly "
                "provided." % import_name
            )

    # filepath is import_name.py for a module, or __init__.py for a package.
    # 模块文件路径是 import_name.py, 包的导入名是 __init__.py.
    return os.path.dirname(os.path.abspath(filepath))


def _matching_loader_thinks_module_is_package(loader, mod_name):
    """Given the loader that loaded a module and the module this function
    attempts to figure out if the given module is actually a package.

    给定加载器已加载一个模块. 这个函数试图确定这个模块是不是一个包.
    """
    # If the loader can tell us if something is a package, we can
    # directly ask the loader.
    #
    # 如果加载器提供判断是否为包的方法, 我们可以直接调用
    if hasattr(loader, "is_package"):
        return loader.is_package(mod_name)
    # importlib's namespace loaders do not have this functionality but
    # all the modules it loads are packages, so we can take advantage of
    # this information.
    #
    # importlib 的命名空间加载器没有提供这个方法但所有加载的模块都作为包, 我们可以利用这一点.
    elif (
        loader.__class__.__module__ == "_frozen_importlib"
        and loader.__class__.__name__ == "NamespaceLoader"
    ):
        return True
    # Otherwise we need to fail with an error that explains what went
    # wrong.
    #
    # 否则抛出异常, 给出解释信息.
    raise AttributeError(
        (
            "%s.is_package() method is missing but is required by Flask of "
            "PEP 302 import hooks.  If you do not use import hooks and "
            "you encounter this error please file a bug against Flask."
        )
        % loader.__class__.__name__
    )


def _find_package_path(root_mod_name):
    """Find the path where the module's root exists in
    查找模块的根目录路径.
    """
    if sys.version_info >= (3, 4):
        import importlib.util

        try:
            spec = importlib.util.find_spec(root_mod_name)
            if spec is None:
                raise ValueError("not found")
        # ImportError: the machinery told us it does not exist
        # ValueError:
        #    - the module name was invalid
        #    - the module name is __main__
        #    - *we* raised `ValueError` due to `spec` being `None`
        #
        # ImportError: 导入机制告诉我们路径不存在
        # ValueError:
        #    - 模块名不合法
        #    - 模块名为 __main__
        #    - `spec` 为 `None` 的时候手动抛出
        except (ImportError, ValueError):
            pass  # handled below
                  # 在下面处理
        else:
            # namespace package
            # 命名空间包
            if spec.origin in {"namespace", None}:
                return os.path.dirname(next(iter(spec.submodule_search_locations)))
            # a package (with __init__.py)
            # 一个包 (包含 __init__.py)
            elif spec.submodule_search_locations:
                return os.path.dirname(os.path.dirname(spec.origin))
            # just a normal module
            # 普通的模块
            else:
                return os.path.dirname(spec.origin)

    # we were unable to find the `package_path` using PEP 451 loaders
    # 使用 PEP451 加载器无法找到 `package_path`
    loader = pkgutil.get_loader(root_mod_name)
    if loader is None or root_mod_name == "__main__":
        # import name is not found, or interactive/main module
        # 找不到导入名, 或者为交互环境或主模块.
        return os.getcwd()
    else:
        # For .egg, zipimporter does not have get_filename until Python 2.7.
        # 对于 egg 文件, Python 2.7 前 zipimporter 没有 get_filename 方法.
        if hasattr(loader, "get_filename"):
            filename = loader.get_filename(root_mod_name)
        elif hasattr(loader, "archive"):
            # zipimporter's loader.archive points to the .egg or .zip
            # archive filename is dropped in call to dirname below.
            #
            # zipimporter 的 loader.archive 指向 egg 或 zip 归档文件名,
            # 在下面的 dirname 调用中被删除.
            filename = loader.archive
        else:
            # At least one loader is missing both get_filename and archive:
            # Google App Engine's HardenedModulesHook
            #
            # 至少一个加载器同时缺少 get_filename 和 archive:
            # Google App Engine 的 HardenedModulesHook
            #
            # Fall back to imports.
            # 回退到导入
            __import__(root_mod_name)
            filename = sys.modules[root_mod_name].__file__
        package_path = os.path.abspath(os.path.dirname(filename))

        # In case the root module is a package we need to chop of the
        # rightmost part.  This needs to go through a helper function
        # because of python 3.3 namespace packages.
        #
        # 如果根模块是包, 我们需要分解最右边的部分. 由于 python 3.3 命名空间包的原因,
        # 需要借助一个辅助函数实现.
        if _matching_loader_thinks_module_is_package(loader, root_mod_name):
            package_path = os.path.dirname(package_path)

    return package_path


def find_package(import_name):
    """Finds a package and returns the prefix (or None if the package is
    not installed) as well as the folder that contains the package or
    module as a tuple.  The package path returned is the module that would
    have to be added to the pythonpath in order to make it possible to
    import the module.  The prefix is the path below which a UNIX like
    folder structure exists (lib, share etc.).

    查找一个包并以元组的方式返回前缀(如果未安装这个包返回 None)和包含这个包的文件夹.
    返回的包路径是必须添加到 PYTHONPATH 中的模块, 以便可以导入该模块. 前缀是存在
    类似 UNIX 文件夹结构的路径(例如 lib, share 等).
    """
    root_mod_name, _, _ = import_name.partition(".")
    package_path = _find_package_path(root_mod_name)
    site_parent, site_folder = os.path.split(package_path)
    py_prefix = os.path.abspath(sys.prefix)
    if package_path.startswith(py_prefix):
        return py_prefix, package_path
    elif site_folder.lower() == "site-packages":
        parent, folder = os.path.split(site_parent)
        # Windows like installations
        # 类似 Windows 的安装
        if folder.lower() == "lib":
            base_dir = parent
        # UNIX like installations
        # 类似 UNIX 的安装
        elif os.path.basename(parent).lower() == "lib":
            base_dir = os.path.dirname(parent)
        else:
            base_dir = site_parent
        return base_dir, package_path
    return None, package_path


class locked_cached_property(object):
    """A decorator that converts a function into a lazy property.  The
    function wrapped is called the first time to retrieve the result
    and then that calculated result is used the next time you access
    the value.  Works like the one in Werkzeug but has a lock for
    thread safety.
    一个把函数转换为懒加载属性的装饰器. 被装饰的函数第一次调用时, 保存调用结果, 再次
    调用时这个结果就作为下次访问的返回, 不再进行计算. 和 Werkzeug 中的一个装饰器
    类似, 但有一个锁保证线程安全.
    """

    def __init__(self, func, name=None, doc=None):
        self.__name__ = name or func.__name__
        self.__module__ = func.__module__
        self.__doc__ = doc or func.__doc__
        self.func = func
        self.lock = RLock()

    def __get__(self, obj, type=None):
        if obj is None:
            return self
        with self.lock:
            value = obj.__dict__.get(self.__name__, _missing)
            if value is _missing:
                value = self.func(obj)
                obj.__dict__[self.__name__] = value
            return value


class _PackageBoundObject(object):
    #: The name of the package or module that this app belongs to. Do not
    #: change this once it is set by the constructor.
    #
    # 这个 app 所属的包名或模块名, 初始化后不应进行修改.
    import_name = None

    #: Location of the template files to be added to the template lookup.
    #: ``None`` if templates should not be added.
    #
    # 要添加的模板文件位置, 如果不添加则设为 `None`
    template_folder = None

    #: Absolute path to the package on the filesystem. Used to look up
    #: resources contained in the package.
    #
    # 文件系统指向这个包的的绝对路径. 用于查找包中的资源文件.
    root_path = None

    def __init__(self, import_name, template_folder=None, root_path=None):
        self.import_name = import_name
        self.template_folder = template_folder

        if root_path is None:
            root_path = get_root_path(self.import_name)

        self.root_path = root_path
        self._static_folder = None
        self._static_url_path = None

        # circular import
        # 循环导入
        from .cli import AppGroup

        #: The Click command group for registration of CLI commands
        #: on the application and associated blueprints. These commands
        #: are accessible via the :command:`flask` command once the
        #: application has been discovered and blueprints registered.
        #
        # 用于在 app 和相关蓝图上注册 CLI 命令的 Click 命令组. 在 app 发现且
        # 蓝图注册完毕后, 这些命令可以通过 `flask` 命令调用.
        self.cli = AppGroup()

    @property
    def static_folder(self):
        """The absolute path to the configured static folder.
        指向已配置的静态文件文件夹的绝对路径.
        """
        if self._static_folder is not None:
            return os.path.join(self.root_path, self._static_folder)

    @static_folder.setter
    def static_folder(self, value):
        self._static_folder = value

    @property
    def static_url_path(self):
        """The URL prefix that the static route will be accessible from.

        可以访问静态路由的 URL 前缀.

        If it was not configured during init, it is derived from
        :attr:`static_folder`.

        如果在初始化时未设定, 则通过 `static_folder` 属性派生.
        """
        if self._static_url_path is not None:
            return self._static_url_path

        if self.static_folder is not None:
            basename = os.path.basename(self.static_folder)
            return ("/" + basename).rstrip("/")

    @static_url_path.setter
    def static_url_path(self, value):
        if value is not None:
            value = value.rstrip("/")

        self._static_url_path = value

    @property
    def has_static_folder(self):
        """This is ``True`` if the package bound object's container has a
        folder for static files.

        如果这个对象的容器有放置静态文件的文件夹则返回 `True`

        .. versionadded:: 0.5
        """
        return self.static_folder is not None

    @locked_cached_property
    def jinja_loader(self):
        """The Jinja loader for this package bound object.

        这个对象的 Jinja 加载器.

        .. versionadded:: 0.5
        """
        if self.template_folder is not None:
            return FileSystemLoader(os.path.join(self.root_path, self.template_folder))

    def get_send_file_max_age(self, filename):
        """Provides default cache_timeout for the :func:`send_file` functions.

        为 `send_file` 函数提供默认的缓存超时时长.

        By default, this function returns ``SEND_FILE_MAX_AGE_DEFAULT`` from
        the configuration of :data:`~flask.current_app`.

        这个函数默认返回 `current_app` 配置中的 `SEND_FILE_MAX_AGE_DEFAULT`.

        Static file functions such as :func:`send_from_directory` use this
        function, and :func:`send_file` calls this function on
        :data:`~flask.current_app` when the given cache_timeout is ``None``. If a
        cache_timeout is given in :func:`send_file`, that timeout is used;
        otherwise, this method is called.

        静态文件相关的函数例如 `send_from_directory` 使用这个函数, 并且函数 `send_file`
        在参数 `cache_timeout` 为 `None` 时调用 `current_app` 的此函数. 不为 `None`
        时使用给定的超时时长, 不然就调用此函数.

        This allows subclasses to change the behavior when sending files based
        on the filename.  For example, to set the cache timeout for .js files
        to 60 seconds::

        允许子类重写此函数, 实现基于文件名发送文件时更改行为. 例如, 将 js 文件的缓存超时时长
        设为 60s:

            class MyFlask(flask.Flask):
                def get_send_file_max_age(self, name):
                    if name.lower().endswith('.js'):
                        return 60
                    return flask.Flask.get_send_file_max_age(self, name)

        .. versionadded:: 0.9
        """
        return total_seconds(current_app.send_file_max_age_default)

    def send_static_file(self, filename):
        """Function used internally to send static files from the static
        folder to the browser.

        内部使用的函数, 用于从静态文件文件夹发送文件到浏览器.

        .. versionadded:: 0.5
        """
        if not self.has_static_folder:
            raise RuntimeError("No static folder for this object")
        # Ensure get_send_file_max_age is called in all cases.
        # Here, we ensure get_send_file_max_age is called for Blueprints.
        #
        # 确保任何情况下都调用 get_send_file_max_age.
        # 这里我们确保为蓝图调用了 get_send_file_max_age.
        cache_timeout = self.get_send_file_max_age(filename)
        return send_from_directory(
            self.static_folder, filename, cache_timeout=cache_timeout
        )

    def open_resource(self, resource, mode="rb"):
        """Opens a resource from the application's resource folder.  To see
        how this works, consider the following folder structure::

        从 app 的资源文件夹打开资源文件. 若要查看其工作原理, 考虑以下文件夹结构:

            /myapplication.py
            /schema.sql
            /static
                /style.css
            /templates
                /layout.html
                /index.html

        If you want to open the :file:`schema.sql` file you would do the
        following::

        如果你想打开 `schema.sql` 文件, 你可以这样做:

            with app.open_resource('schema.sql') as f:
                contents = f.read()
                do_something_with(contents)

        :param resource: the name of the resource.  To access resources within
                         subfolders use forward slashes as separator.
        参数 resource: 资源名. 若要访问子文件夹中的资源, 使用斜线 `/` 作为分隔符.

        :param mode: Open file in this mode. Only reading is supported,
            valid values are "r" (or "rt") and "rb".
        参数 mode: 以这个模式打开文件. 只支持读模式, 合法取值为 "r"(或 "rt") 和 "rb"
        """
        if mode not in {"r", "rt", "rb"}:
            raise ValueError("Resources can only be opened for reading")

        return open(os.path.join(self.root_path, resource), mode)


def total_seconds(td):
    """Returns the total seconds from a timedelta object.
    返回 timedelta 对象的秒数.

    :param timedelta td: the timedelta to be converted in seconds
    参数 timedelta td: 要被转换为秒数的 timedelta

    :returns: number of seconds
    返回: 秒数

    :rtype: int
    返回类型: int
    """
    return td.days * 60 * 60 * 24 + td.seconds


def is_ip(value):
    """Determine if the given string is an IP address.
    确认给定的字符串是不是 IP 地址.

    Python 2 on Windows doesn't provide ``inet_pton``, so this only
    checks IPv4 addresses in that environment.

    Windows 平台的 Python 2 未提供 `inet_pton`, 所以在此环境下只检查 IPv4 地址.

    :param value: value to check
    参数 value: 检查的值

    :type value: str
    参数类型 value: str

    :return: True if string is an IP address
    返回 如果字符串是 IP 地址返回 `True`

    :rtype: bool
    返回类型: bool
    """
    if PY2 and os.name == "nt":
        try:
            socket.inet_aton(value)
            return True
        except socket.error:
            return False

    for family in (socket.AF_INET, socket.AF_INET6):
        try:
            socket.inet_pton(family, value)
        except socket.error:
            pass
        else:
            return True

    return False
