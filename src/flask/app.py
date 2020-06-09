# -*- coding: utf-8 -*-
"""
    flask.app
    ~~~~~~~~~

    This module implements the central WSGI application object.
    此模块实现核心 WSGI 应用对象.

    :copyright: 2010 Pallets
    :license: BSD-3-Clause
"""
import os
import sys
import warnings
from datetime import timedelta
from functools import update_wrapper
from itertools import chain
from threading import Lock

from werkzeug.datastructures import Headers
from werkzeug.datastructures import ImmutableDict
from werkzeug.exceptions import BadRequest
from werkzeug.exceptions import BadRequestKeyError
from werkzeug.exceptions import default_exceptions
from werkzeug.exceptions import HTTPException
from werkzeug.exceptions import InternalServerError
from werkzeug.exceptions import MethodNotAllowed
from werkzeug.routing import BuildError
from werkzeug.routing import Map
from werkzeug.routing import RequestRedirect
from werkzeug.routing import RoutingException
from werkzeug.routing import Rule
from werkzeug.wrappers import BaseResponse

from . import cli
from . import json
from ._compat import integer_types
from ._compat import reraise
from ._compat import string_types
from ._compat import text_type
from .config import Config
from .config import ConfigAttribute
from .ctx import _AppCtxGlobals
from .ctx import AppContext
from .ctx import RequestContext
from .globals import _request_ctx_stack
from .globals import g
from .globals import request
from .globals import session
from .helpers import _endpoint_from_view_func
from .helpers import _PackageBoundObject
from .helpers import find_package
from .helpers import get_debug_flag
from .helpers import get_env
from .helpers import get_flashed_messages
from .helpers import get_load_dotenv
from .helpers import locked_cached_property
from .helpers import url_for
from .json import jsonify
from .logging import create_logger
from .sessions import SecureCookieSessionInterface
from .signals import appcontext_tearing_down
from .signals import got_request_exception
from .signals import request_finished
from .signals import request_started
from .signals import request_tearing_down
from .templating import _default_template_ctx_processor
from .templating import DispatchingJinjaLoader
from .templating import Environment
from .wrappers import Request
from .wrappers import Response

# a singleton sentinel value for parameter defaults
# 一个单例标志, 用于默认参数
_sentinel = object()


def _make_timedelta(value):
    if not isinstance(value, timedelta):
        return timedelta(seconds=value)
    return value


def setupmethod(f):
    """Wraps a method so that it performs a check in debug mode if the
    first request was already handled.

    包裹一个方法以便在调试模式下进行检查, 确认第一个请求是否已经处理.
    """

    def wrapper_func(self, *args, **kwargs):
        if self.debug and self._got_first_request:
            raise AssertionError(
                "A setup function was called after the "
                "first request was handled.  This usually indicates a bug "
                "in the application where a module was not imported "
                "and decorators or other functionality was called too late.\n"
                "To fix this make sure to import all your view modules, "
                "database models and everything related at a central place "
                "before the application starts serving requests."
            )
        return f(self, *args, **kwargs)

    return update_wrapper(wrapper_func, f)


class Flask(_PackageBoundObject):
    """The flask object implements a WSGI application and acts as the central
    object.  It is passed the name of the module or package of the
    application.  Once it is created it will act as a central registry for
    the view functions, the URL rules, template configuration and much more.

    flask 对象实现了 WSGI 应用并作为核心对象. 传入模块或包的名称作为应用的初始化参数.
    一旦创建将作为视图函数, URL 规则和模板配置等等的注册中心.

    The name of the package is used to resolve resources from inside the
    package or the folder the module is contained in depending on if the
    package parameter resolves to an actual python package (a folder with
    an :file:`__init__.py` file inside) or a standard module (just a ``.py`` file).

    包的名称用于解析包内的资源或模块包含的文件夹, 取决于包参数解析为一个实际的 python 包
    (包含 `__init__.py` 的文件夹) 或一个标准的模块(只是一个 py 文件)

    For more information about resource loading, see :func:`open_resource`.
    查看 `open_resource` 函数的文档获取更多信息.

    Usually you create a :class:`Flask` instance in your main module or
    in the :file:`__init__.py` file of your package like this::

    通常情况下你可以通过以下方式在你的主模块或包的 `__init__.py` 文件中创建 `Flask` 类的实例:

        from flask import Flask
        app = Flask(__name__)

    .. admonition:: About the First Parameter
    警告: 关于第一个参数

        The idea of the first parameter is to give Flask an idea of what
        belongs to your application.  This name is used to find resources
        on the filesystem, can be used by extensions to improve debugging
        information and a lot more.

        第一个参数是为了让 Flask 确认你的应用实例中包含哪些资源. 这个名字用于查找文件
        系统上的资源, 可以用于拓展或改进调试信息以及更多作用.

        So it's important what you provide there.  If you are using a single
        module, `__name__` is always the correct value.  If you however are
        using a package, it's usually recommended to hardcode the name of
        your package there.

        所以你提供的这个参数很重要. 如果你使用一个单模块, `__name__` 一直是当前值. 如果你
        使用一个包, 推荐硬编码你使用的包名.



        For example if your application is defined in :file:`yourapplication/app.py`
        you should create it with one of the two versions below::

        举例来讲, 如果你的应用定义在 `yourapplication/app.py`, 你可以通过以下两种方式创建:

            app = Flask('yourapplication')
            app = Flask(__name__.split('.')[0])

        Why is that?  The application will work even with `__name__`, thanks
        to how resources are looked up.  However it will make debugging more
        painful.  Certain extensions can make assumptions based on the
        import name of your application.  For example the Flask-SQLAlchemy
        extension will look for the code in your application that triggered
        an SQL query in debug mode.  If the import name is not properly set
        up, that debugging information is lost.  (For example it would only
        pick up SQL queries in `yourapplication.app` and not
        `yourapplication.views.frontend`)

        为什么这样? 得益于资源的搜索机制, 这个应用即使使用 `__name__` 也可以工作. 但这样
        会使得调试变得更糟心. 某些拓展会基于导入名称假定. 例如 Flask-SQLAlchemy 拓展将
        在调试模式下查找应用中触发 SQL 查询的代码. 如果导入名称未设定好, 会丢失调试信息.
        (例如它将只提取 `yourapplication.app` 中发生的 SQL 查询, 而忽略
        `yourapplication.views.frontend` 中的查询)

    .. versionadded:: 0.7
       The `static_url_path`, `static_folder`, and `template_folder`
       parameters were added.

    .. versionadded:: 0.8
       The `instance_path` and `instance_relative_config` parameters were
       added.

    .. versionadded:: 0.11
       The `root_path` parameter was added.

    .. versionadded:: 1.0
       The ``host_matching`` and ``static_host`` parameters were added.

    .. versionadded:: 1.0
       The ``subdomain_matching`` parameter was added. Subdomain
       matching needs to be enabled manually now. Setting
       :data:`SERVER_NAME` does not implicitly enable it.

    :param import_name: the name of the application package
    参数 import_name: 应用包名

    :param static_url_path: can be used to specify a different path for the
                            static files on the web.  Defaults to the name
                            of the `static_folder` folder.
    参数 static_url_path: 可用于为静态文件指定不同的网络路径. 默认为 `static_folder`.

    :param static_folder: the folder with static files that should be served
                          at `static_url_path`.  Defaults to the ``'static'``
                          folder in the root path of the application.
    参数 static_folder: 使用 `static_url_path` 托管的静态文件夹. 默认为应用根路径的
        `static` 文件夹

    :param static_host: the host to use when adding the static route.
        Defaults to None. Required when using ``host_matching=True``
        with a ``static_folder`` configured.
    参数 static_host: 添加静态路由时使用的地址. 默认为 None. 当使用配置项
        `host_matching=True` 且配置了 `static_folder` 时不为 None

    :param host_matching: set ``url_map.host_matching`` attribute.
        Defaults to False.
    参数 host_matching: 设置 `url_map.host_matching` 属性. 默认为 None

    :param subdomain_matching: consider the subdomain relative to
        :data:`SERVER_NAME` when matching routes. Defaults to False.
    参数 subdomain_matching: 当匹配路由时考虑相对于 `SERVER_NAME` 的子域名

    :param template_folder: the folder that contains the templates that should
                            be used by the application.  Defaults to
                            ``'templates'`` folder in the root path of the
                            application.
    参数 template_folder: 存放应用使用的模板的文件夹. 默认为应用根路径的 `templates` 文件夹.

    :param instance_path: An alternative instance path for the application.
                          By default the folder ``'instance'`` next to the
                          package or module is assumed to be the instance
                          path.
    参数 instance_path: 可选的应用实例路径. 默认为应用所在包或模块同级的 `instance` 文件夹.

    :param instance_relative_config: if set to ``True`` relative filenames
                                     for loading the config are assumed to
                                     be relative to the instance path instead
                                     of the application root.
    参数 instance_relative_config: 若设为 `True`, 加载配置相关的文件名会相对于
        `instance_path` 而非应用根路径

    :param root_path: Flask by default will automatically calculate the path
                      to the root of the application.  In certain situations
                      this cannot be achieved (for instance if the package
                      is a Python 3 namespace package) and needs to be
                      manually defined.
    参数 root_path: Flask 默认自动计算应用根路径. 在某些情况下无法实现(例如包是一个
        python 3 命名空间包的情况), 需要手动指定.
    """

    #: The class that is used for request objects.  See :class:`~flask.Request`
    #: for more information.
    #
    # 请求对象的类. 查看 `flask.Request` 获取更多信息
    request_class = Request

    #: The class that is used for response objects.  See
    #: :class:`~flask.Response` for more information.
    #
    # 响应对象的类. 查看 `flask.Response` 获取更多信息
    response_class = Response

    #: The class that is used for the Jinja environment.
    #:
    #: .. versionadded:: 0.11
    #
    # Jinja 环境变量的类
    jinja_environment = Environment

    #: The class that is used for the :data:`~flask.g` instance.
    #:
    #: Example use cases for a custom class:
    #:
    #: 1. Store arbitrary attributes on flask.g.
    #: 2. Add a property for lazy per-request database connectors.
    #: 3. Return None instead of AttributeError on unexpected attributes.
    #: 4. Raise exception if an unexpected attr is set, a "controlled" flask.g.
    #:
    #: In Flask 0.9 this property was called `request_globals_class` but it
    #: was changed in 0.10 to :attr:`app_ctx_globals_class` because the
    #: flask.g object is now application context scoped.
    #:
    #: .. versionadded:: 0.10
    #
    # 全局对象 g 的类. 自定义类的使用举例:
    # 1. 存放任意属性于 flask.g
    # 2. 为每个惰性请求数据库连接添加一个属性
    # 3. 请求未期望的属性时返回 None 而不是抛出 AttributeError
    # 4. 如果设置了一个未期望的属性抛出异常, 是一个 "可控的" flask.g
    #
    # Flask 0.9 称其为 `request_globals_class`  但 0.10 改为 `app_ctx_globals_class`,
    # 因为 flask.g 对象现在是应用上下文范围的值.
    app_ctx_globals_class = _AppCtxGlobals

    #: The class that is used for the ``config`` attribute of this app.
    #: Defaults to :class:`~flask.Config`.
    #:
    #: Example use cases for a custom class:
    #:
    #: 1. Default values for certain config options.
    #: 2. Access to config values through attributes in addition to keys.
    #:
    #: .. versionadded:: 0.11
    #
    # 此应用中用于 config 属性的类. 默认为 `flask.Config`.
    # 自定义类的使用示例:
    # 1. 某些选项的默认值
    # 2. 除了使用 key, 也可用属性的形式访问设定值.
    config_class = Config

    #: The testing flag.  Set this to ``True`` to enable the test mode of
    #: Flask extensions (and in the future probably also Flask itself).
    #: For example this might activate test helpers that have an
    #: additional runtime cost which should not be enabled by default.
    #:
    #: If this is enabled and PROPAGATE_EXCEPTIONS is not changed from the
    #: default it's implicitly enabled.
    #:
    #: This attribute can also be configured from the config with the
    #: ``TESTING`` configuration key.  Defaults to ``False``.
    #
    # testing 标志. 设为 `True` 开启 Flask 拓展(后期可能也包括 Flask 本身)的测试模式.
    # 例如这或许会启用默认关闭的消耗额外运行时消耗的测试辅助工具
    #
    # 如果开启此项且 PROPAGATE_EXCEPTIONS 未更改, 则默认启用.
    #
    # 此属性也可以从配置中以 `TESTING` 作为 key 提取, 默认为 `False`.
    testing = ConfigAttribute("TESTING")

    #: If a secret key is set, cryptographic components can use this to
    #: sign cookies and other things. Set this to a complex random value
    #: when you want to use the secure cookie for instance.
    #:
    #: This attribute can also be configured from the config with the
    #: :data:`SECRET_KEY` configuration key. Defaults to ``None``.
    #
    # 如果设置了秘钥, 加密组件可以使用此秘钥对 cookie 或其他东西进行签名. 将此项设为复杂
    # 的随机字符串用于使用实例的安全 cookie.
    #
    # 此属性也可以从配置中以 `SECRET_KEY` 作为 key 提取, 默认为 `None`.
    secret_key = ConfigAttribute("SECRET_KEY")

    #: The secure cookie uses this for the name of the session cookie.
    #:
    #: This attribute can also be configured from the config with the
    #: ``SESSION_COOKIE_NAME`` configuration key.  Defaults to ``'session'``
    #
    # 安全 cookie 使用它作为会话 cookie 的名称.
    #
    # 此属性也可以从配置中以 `SESSION_COOKIE_NAME` 作为 key 提取, 默认为 `session`.
    session_cookie_name = ConfigAttribute("SESSION_COOKIE_NAME")

    #: A :class:`~datetime.timedelta` which is used to set the expiration
    #: date of a permanent session.  The default is 31 days which makes a
    #: permanent session survive for roughly one month.
    #:
    #: This attribute can also be configured from the config with the
    #: ``PERMANENT_SESSION_LIFETIME`` configuration key.  Defaults to
    #: ``timedelta(days=31)``
    #
    # 持久会话的过期时间, 是一个 timedelta 对象. 默认是 31 天, 约为一个月.
    #
    # 此属性也可以从配置中以 `PERMANENT_SESSION_LIFETIME` 作为 key 提取,
    # 默认为 `timedelta(days=31)`
    permanent_session_lifetime = ConfigAttribute(
        "PERMANENT_SESSION_LIFETIME", get_converter=_make_timedelta
    )

    #: A :class:`~datetime.timedelta` which is used as default cache_timeout
    #: for the :func:`send_file` functions. The default is 12 hours.
    #:
    #: This attribute can also be configured from the config with the
    #: ``SEND_FILE_MAX_AGE_DEFAULT`` configuration key. This configuration
    #: variable can also be set with an integer value used as seconds.
    #: Defaults to ``timedelta(hours=12)``
    #
    # `send_file` 函数缓存过期时间, 是一个 timedelta 对象, 默认是 12 小时.
    #
    # 此属性也可以从配置中以 `SEND_FILE_MAX_AGE_DEFAULT` 作为 key 提取,
    # 此配置变量可以使用整数值作为秒数进行设置, 默认为 `timedelta(hours=12)`
    send_file_max_age_default = ConfigAttribute(
        "SEND_FILE_MAX_AGE_DEFAULT", get_converter=_make_timedelta
    )

    #: Enable this if you want to use the X-Sendfile feature.  Keep in
    #: mind that the server has to support this.  This only affects files
    #: sent with the :func:`send_file` method.
    #:
    #: .. versionadded:: 0.2
    #:
    #: This attribute can also be configured from the config with the
    #: ``USE_X_SENDFILE`` configuration key.  Defaults to ``False``.
    #
    # 如果你想使用 X-Sendfile 特性, 请开启此选项. 需要服务器支持. 只影响使用 `send_file`
    # 方法发送的文件
    #
    # 此属性也可以从配置中以 `USE_X_SENDFILE` 作为 key 提取, 默认为 `False`
    use_x_sendfile = ConfigAttribute("USE_X_SENDFILE")

    #: The JSON encoder class to use.  Defaults to :class:`~flask.json.JSONEncoder`.
    #:
    #: .. versionadded:: 0.10
    #
    # 使用的 JSON 编码器类. 默认为 `flask.json.JSONEncoder`
    json_encoder = json.JSONEncoder

    #: The JSON decoder class to use.  Defaults to :class:`~flask.json.JSONDecoder`.
    #:
    #: .. versionadded:: 0.10
    #
    # 使用的 JSON 解码器类. 默认为 `flask.json.JSONDecoder`
    json_decoder = json.JSONDecoder

    #: Options that are passed to the Jinja environment in
    #: :meth:`create_jinja_environment`. Changing these options after
    #: the environment is created (accessing :attr:`jinja_env`) will
    #: have no effect.
    #:
    #: .. versionchanged:: 1.1.0
    #:     This is a ``dict`` instead of an ``ImmutableDict`` to allow
    #:     easier configuration.
    #:
    #
    # 在 `create_jinja_environment` 方法中传给 Jinja 环境的选项. 环境创建后再更改此项无效.
    jinja_options = {"extensions": ["jinja2.ext.autoescape", "jinja2.ext.with_"]}

    #: Default configuration parameters.
    #
    # 默认配置参数
    default_config = ImmutableDict(
        {
            "ENV": None,
            "DEBUG": None,
            "TESTING": False,
            "PROPAGATE_EXCEPTIONS": None,
            "PRESERVE_CONTEXT_ON_EXCEPTION": None,
            "SECRET_KEY": None,
            "PERMANENT_SESSION_LIFETIME": timedelta(days=31),
            "USE_X_SENDFILE": False,
            "SERVER_NAME": None,
            "APPLICATION_ROOT": "/",
            "SESSION_COOKIE_NAME": "session",
            "SESSION_COOKIE_DOMAIN": None,
            "SESSION_COOKIE_PATH": None,
            "SESSION_COOKIE_HTTPONLY": True,
            "SESSION_COOKIE_SECURE": False,
            "SESSION_COOKIE_SAMESITE": None,
            "SESSION_REFRESH_EACH_REQUEST": True,
            "MAX_CONTENT_LENGTH": None,
            "SEND_FILE_MAX_AGE_DEFAULT": timedelta(hours=12),
            "TRAP_BAD_REQUEST_ERRORS": None,
            "TRAP_HTTP_EXCEPTIONS": False,
            "EXPLAIN_TEMPLATE_LOADING": False,
            "PREFERRED_URL_SCHEME": "http",
            "JSON_AS_ASCII": True,
            "JSON_SORT_KEYS": True,
            "JSONIFY_PRETTYPRINT_REGULAR": False,
            "JSONIFY_MIMETYPE": "application/json",
            "TEMPLATES_AUTO_RELOAD": None,
            "MAX_COOKIE_SIZE": 4093,
        }
    )

    #: The rule object to use for URL rules created.  This is used by
    #: :meth:`add_url_rule`.  Defaults to :class:`werkzeug.routing.Rule`.
    #:
    #: .. versionadded:: 0.7
    #
    # 用于创建 URL 规则的对象. 由 `add_url_rule` 方法使用. 默认为 `werkzeug.routing.Rule`
    url_rule_class = Rule

    #: The map object to use for storing the URL rules and routing
    #: configuration parameters. Defaults to :class:`werkzeug.routing.Map`.
    #:
    #: .. versionadded:: 1.1.0
    #
    # 用于存储 URL 规则和路由配置参数的映射对象. 默认为 `werkzeug.routing.Map`
    url_map_class = Map

    #: the test client that is used with when `test_client` is used.
    #:
    #: .. versionadded:: 0.7
    #
    # 使用 `test_client` 时使用的类
    test_client_class = None

    #: The :class:`~click.testing.CliRunner` subclass, by default
    #: :class:`~flask.testing.FlaskCliRunner` that is used by
    #: :meth:`test_cli_runner`. Its ``__init__`` method should take a
    #: Flask app object as the first argument.
    #:
    #: .. versionadded:: 1.0
    #
    # `click.testing.CliRunner` 的子类, 默认为 `flask.testing.FlaskCliRunner`,
    # 由 `test_cli_runner` 方法使用. 其 `__init__` 方法接收应用对象作为第一个参数.
    test_cli_runner_class = None

    #: the session interface to use.  By default an instance of
    #: :class:`~flask.sessions.SecureCookieSessionInterface` is used here.
    #:
    #: .. versionadded:: 0.8
    #
    # 会话接口, 默认为 `flask.sessions.SecureCookieSessionInterface` 的实例.
    session_interface = SecureCookieSessionInterface()

    # TODO remove the next three attrs when Sphinx :inherited-members: works
    # https://github.com/sphinx-doc/sphinx/issues/741

    #: The name of the package or module that this app belongs to. Do not
    #: change this once it is set by the constructor.
    #
    # 应用所属的包或模块的名字. 创建后请不要修改此属性
    import_name = None

    #: Location of the template files to be added to the template lookup.
    #: ``None`` if templates should not be added.
    #
    # 加入模板文件搜索的路径. 如果不添加则为 None
    template_folder = None

    #: Absolute path to the package on the filesystem. Used to look up
    #: resources contained in the package.
    #
    # 包在文件系统上的绝对路径. 用于搜索包中包含的资源
    root_path = None

    def __init__(
        self,
        import_name,
        static_url_path=None,
        static_folder="static",
        static_host=None,
        host_matching=False,
        subdomain_matching=False,
        template_folder="templates",
        instance_path=None,
        instance_relative_config=False,
        root_path=None,
    ):
        _PackageBoundObject.__init__(
            self, import_name, template_folder=template_folder, root_path=root_path
        )

        self.static_url_path = static_url_path
        self.static_folder = static_folder

        if instance_path is None:
            instance_path = self.auto_find_instance_path()
        elif not os.path.isabs(instance_path):
            raise ValueError(
                "If an instance path is provided it must be absolute."
                " A relative path was given instead."
            )

        #: Holds the path to the instance folder.
        #:
        #: .. versionadded:: 0.8
        #
        # 持有实例文件夹的路径
        self.instance_path = instance_path

        #: The configuration dictionary as :class:`Config`.  This behaves
        #: exactly like a regular dictionary but supports additional methods
        #: to load a config from files.
        #
        # 配置字典, 是 `Config` 类的实例, 行为和普通字典一致, 支持额外的从文件加载配置的方法
        self.config = self.make_config(instance_relative_config)

        #: A dictionary of all view functions registered.  The keys will
        #: be function names which are also used to generate URLs and
        #: the values are the function objects themselves.
        #: To register a view function, use the :meth:`route` decorator.
        #
        # 存放所有注册的视图函数的字典. 键为函数名, 也用于生成 URL, 值为函数对象本身.
        # 用 `route` 装饰器注册一个视图函数
        self.view_functions = {}

        #: A dictionary of all registered error handlers.  The key is ``None``
        #: for error handlers active on the application, otherwise the key is
        #: the name of the blueprint.  Each key points to another dictionary
        #: where the key is the status code of the http exception.  The
        #: special key ``None`` points to a list of tuples where the first item
        #: is the class for the instance check and the second the error handler
        #: function.
        #:
        #: To register an error handler, use the :meth:`errorhandler`
        #: decorator.
        #
        # 存放所有错误处理器的字典. 键为 `None` 为全局活动的错误处理器, 其他键为蓝图名.
        # 每个键指向另一个字典, 键为 http 异常状态码, 特别的键为 `None` 指向
        # 由元组组成的列表, 元组的第一项为实例检查的类, 另一个是错误处理函数.
        self.error_handler_spec = {}

        #: A list of functions that are called when :meth:`url_for` raises a
        #: :exc:`~werkzeug.routing.BuildError`.  Each function registered here
        #: is called with `error`, `endpoint` and `values`.  If a function
        #: returns ``None`` or raises a :exc:`BuildError` the next function is
        #: tried.
        #:
        #: .. versionadded:: 0.9
        #
        # `url_for` 抛出 `werkzeug.routing.BuildError` 异常时的处理函数列表.
        # 每个函数接收 `error`. `endpoint` 和 `values` 作为参数. 如果一个函数返回
        # `None` 或抛出 `BuildError`, 尝试下一个函数
        self.url_build_error_handlers = []

        #: A dictionary with lists of functions that will be called at the
        #: beginning of each request. The key of the dictionary is the name of
        #: the blueprint this function is active for, or ``None`` for all
        #: requests. To register a function, use the :meth:`before_request`
        #: decorator.
        #
        # 存储每次请求开始时调用的函数列表的字典. 字典的键为对应蓝图名称, `None` 应用到
        # 所有请求. 使用 `before_request` 装饰器注册一个函数
        self.before_request_funcs = {}

        #: A list of functions that will be called at the beginning of the
        #: first request to this instance. To register a function, use the
        #: :meth:`before_first_request` decorator.
        #:
        #: .. versionadded:: 0.8
        #
        # 此实例第一个请求开始时调用的函数列表. 使用 `before_first_request` 装饰器
        # 注册一个函数
        self.before_first_request_funcs = []

        #: A dictionary with lists of functions that should be called after
        #: each request.  The key of the dictionary is the name of the blueprint
        #: this function is active for, ``None`` for all requests.  This can for
        #: example be used to close database connections. To register a function
        #: here, use the :meth:`after_request` decorator.
        #
        # 存储每次请求结束时调用的函数列表的字典. 字典的键为对应蓝图名称, `None` 应用到
        # 所有请求. 比如可以用于关闭数据库连接. 使用 `after_request` 装饰器注册一个函数
        self.after_request_funcs = {}

        #: A dictionary with lists of functions that are called after
        #: each request, even if an exception has occurred. The key of the
        #: dictionary is the name of the blueprint this function is active for,
        #: ``None`` for all requests. These functions are not allowed to modify
        #: the request, and their return values are ignored. If an exception
        #: occurred while processing the request, it gets passed to each
        #: teardown_request function. To register a function here, use the
        #: :meth:`teardown_request` decorator.
        #:
        #: .. versionadded:: 0.7
        #
        # 存储每次请求结束时调用的函数列表的字典, 发生异常也会调用. 字典的键为对应蓝图名称,
        # `None` 应用到所有请求. 不允许这些函数更改请求, 并忽略返回值. 若处理请求时发生异常,
        # 异常将被发送到每个函数. 使用 `teardown_request` 装饰器注册一个函数.
        self.teardown_request_funcs = {}

        #: A list of functions that are called when the application context
        #: is destroyed.  Since the application context is also torn down
        #: if the request ends this is the place to store code that disconnects
        #: from databases.
        #:
        #: .. versionadded:: 0.9
        #
        # 结束应用上下文时调用的函数列表. 请求结束后应用上下文也会结束, 所以可以放置与
        # 数据库断开连接的代码.
        self.teardown_appcontext_funcs = []

        #: A dictionary with lists of functions that are called before the
        #: :attr:`before_request_funcs` functions. The key of the dictionary is
        #: the name of the blueprint this function is active for, or ``None``
        #: for all requests. To register a function, use
        #: :meth:`url_value_preprocessor`.
        #:
        #: .. versionadded:: 0.7
        #
        # 存储每次 `before_request_funcs` 调用之前调用的函数列表的字典. 字典的键为对应
        # 蓝图名称, `None` 应用到所有请求. 使用 `url_value_preprocessor` 方法注册一个函数
        self.url_value_preprocessors = {}

        #: A dictionary with lists of functions that can be used as URL value
        #: preprocessors.  The key ``None`` here is used for application wide
        #: callbacks, otherwise the key is the name of the blueprint.
        #: Each of these functions has the chance to modify the dictionary
        #: of URL values before they are used as the keyword arguments of the
        #: view function.  For each function registered this one should also
        #: provide a :meth:`url_defaults` function that adds the parameters
        #: automatically again that were removed that way.
        #:
        #: .. versionadded:: 0.7
        #
        # 存储预处理 URL 值的函数列表的字典. 字典的键 `None` 作为应用范围的回调, 其他为
        # 蓝图名称. 每个函数都可以在 URL 值的字典作为关键字参数被视图函数调用之前对其更改.
        # 每个注册到这里的函数应提供一个 `url_defaults` 函数用于自动再次添加
        # 以这种方式删除的参数.
        self.url_default_functions = {}

        #: A dictionary with list of functions that are called without argument
        #: to populate the template context.  The key of the dictionary is the
        #: name of the blueprint this function is active for, ``None`` for all
        #: requests.  Each returns a dictionary that the template context is
        #: updated with.  To register a function here, use the
        #: :meth:`context_processor` decorator.
        #
        # 存储无参数的填充模板上下文的函数列表的字典. 字典的键为对应蓝图名称, `None` 应用到
        # 所有请求. 每个函数都返回一个字典, 用于更新模板上下文. 使用
        # `context_processor` 装饰器注册一个函数.
        self.template_context_processors = {None: [_default_template_ctx_processor]}

        #: A list of shell context processor functions that should be run
        #: when a shell context is created.
        #:
        #: .. versionadded:: 0.11
        #
        # 创建 shell 上下文时调用的处理 shell 上下文的函数列表
        self.shell_context_processors = []

        #: all the attached blueprints in a dictionary by name.  Blueprints
        #: can be attached multiple times so this dictionary does not tell
        #: you how often they got attached.
        #:
        #: .. versionadded:: 0.7
        #
        # 所有注册的蓝图字典, 以蓝图名作为键. 蓝图可以多次注册, 所以这个字典没有注册频率的信息.
        self.blueprints = {}
        self._blueprint_order = []

        #: a place where extensions can store application specific state.  For
        #: example this is where an extension could store database engines and
        #: similar things.  For backwards compatibility extensions should register
        #: themselves like this::
        #
        # 拓展可以存储应用特定状态的位置. 例如拓展可以存储数据库引擎和类似的东西. 为了向后兼容,
        # 拓展应该这样注册:
        #:
        #:      if not hasattr(app, 'extensions'):
        #:          app.extensions = {}
        #:      app.extensions['extensionname'] = SomeObject()
        #:
        #: The key must match the name of the extension module. For example in
        #: case of a "Flask-Foo" extension in `flask_foo`, the key would be
        #: ``'foo'``.
        #
        # 键名一定要和拓展模块名一致. 例如 `Flask-Foo` 拓展在 `flask_foo` 模块中,
        # 键名应该为 `'foo'`
        #:
        #: .. versionadded:: 0.7
        self.extensions = {}

        #: The :class:`~werkzeug.routing.Map` for this instance.  You can use
        #: this to change the routing converters after the class was created
        #: but before any routes are connected.  Example::
        #
        # `werkzeug.routing.Map` 的实例. 你可以在这个类创建后且连接建立前更改路由转换器.
        # 例如:
        #:
        #:    from werkzeug.routing import BaseConverter
        #:
        #:    class ListConverter(BaseConverter):
        #:        def to_python(self, value):
        #:            return value.split(',')
        #:        def to_url(self, values):
        #:            return ','.join(super(ListConverter, self).to_url(value)
        #:                            for value in values)
        #:
        #:    app = Flask(__name__)
        #:    app.url_map.converters['list'] = ListConverter
        self.url_map = self.url_map_class()

        self.url_map.host_matching = host_matching
        self.subdomain_matching = subdomain_matching

        # tracks internally if the application already handled at least one
        # request.
        # 应用是否已经至少处理了一个请求了
        self._got_first_request = False
        self._before_request_lock = Lock()

        # Add a static route using the provided static_url_path, static_host,
        # and static_folder if there is a configured static_folder.
        # Note we do this without checking if static_folder exists.
        # For one, it might be created while the server is running (e.g. during
        # development). Also, Google App Engine stores static files somewhere
        #
        # 使用给定的 `static_url_path`, `static_host` 和 `static_folder`
        # (如果配置了 `static_folder`) 添加静态路由. 注意此处未检查 `static_folder`
        # 是否存在. 因为可能在服务器运行时创建(如在部署时), 以及 Google App Engine 也会
        # 将静态文件放在某些地方
        if self.has_static_folder:
            assert (
                bool(static_host) == host_matching
            ), "Invalid static_host/host_matching combination"
            self.add_url_rule(
                self.static_url_path + "/<path:filename>",
                endpoint="static",
                host=static_host,
                view_func=self.send_static_file,
            )

        # Set the name of the Click group in case someone wants to add
        # the app's commands to another CLI tool.
        #
        # 设置 Click 组的名称以便有人想添加这个应用的命令到另一个命令行接口工具
        self.cli.name = self.name

    @locked_cached_property
    def name(self):
        """The name of the application.  This is usually the import name
        with the difference that it's guessed from the run file if the
        import name is main.  This name is used as a display name when
        Flask needs the name of the application.  It can be set and overridden
        to change the value.

        应用名称. 通常是导入名, 如果导入名是 main, 则与从运行文件中猜测的名称不同.
        当 Flask 需要应用名称时, 这个名字作为展示名. 可以设置或覆盖此值.

        .. versionadded:: 0.8
        """
        if self.import_name == "__main__":
            fn = getattr(sys.modules["__main__"], "__file__", None)
            if fn is None:
                return "__main__"
            return os.path.splitext(os.path.basename(fn))[0]
        return self.import_name

    @property
    def propagate_exceptions(self):
        """Returns the value of the ``PROPAGATE_EXCEPTIONS`` configuration
        value in case it's set, otherwise a sensible default is returned.

        返回设置项 `PROPAGATE_EXCEPTIONS` 的值, 如果未设置则返回默认值

        .. versionadded:: 0.7
        """
        rv = self.config["PROPAGATE_EXCEPTIONS"]
        if rv is not None:
            return rv
        return self.testing or self.debug

    @property
    def preserve_context_on_exception(self):
        """Returns the value of the ``PRESERVE_CONTEXT_ON_EXCEPTION``
        configuration value in case it's set, otherwise a sensible default
        is returned.

        返回设置项 `PRESERVE_CONTEXT_ON_EXCEPTION` 的值, 如果未设置则返回默认值

        .. versionadded:: 0.7
        """
        rv = self.config["PRESERVE_CONTEXT_ON_EXCEPTION"]
        if rv is not None:
            return rv
        return self.debug

    @locked_cached_property
    def logger(self):
        """A standard Python :class:`~logging.Logger` for the app, with
        the same name as :attr:`name`.

        一个标准的 Python `logging.Logger`, 名称和 `name` 属性相同.

        In debug mode, the logger's :attr:`~logging.Logger.level` will
        be set to :data:`~logging.DEBUG`.

        调试模式下, logger 的 `logging.Logger.level` 将设为 `logging.DEBUG`.

        If there are no handlers configured, a default handler will be
        added. See :doc:`/logging` for more information.

        如果未配置任何 handler, 添加默认 handler. 查看 `logging` 文档获取更多信息.

        .. versionchanged:: 1.1.0
            The logger takes the same name as :attr:`name` rather than
            hard-coding ``"flask.app"``.

        .. versionchanged:: 1.0.0
            Behavior was simplified. The logger is always named
            ``"flask.app"``. The level is only set during configuration,
            it doesn't check ``app.debug`` each time. Only one format is
            used, not different ones depending on ``app.debug``. No
            handlers are removed, and a handler is only added if no
            handlers are already configured.

        .. versionadded:: 0.3
        """
        return create_logger(self)

    @locked_cached_property
    def jinja_env(self):
        """The Jinja environment used to load templates.

        用于加载模板的 Jinja 环境.

        The environment is created the first time this property is
        accessed. Changing :attr:`jinja_options` after that will have no
        effect.

        第一次访问此属性时创建环境, 之后更改 `jinja_options` 属性无效.
        """
        return self.create_jinja_environment()

    @property
    def got_first_request(self):
        """This attribute is set to ``True`` if the application started
        handling the first request.

        如果应用开始处理第一个请求, 此属性设为 `True`

        .. versionadded:: 0.8
        """
        return self._got_first_request

    def make_config(self, instance_relative=False):
        """Used to create the config attribute by the Flask constructor.
        The `instance_relative` parameter is passed in from the constructor
        of Flask (there named `instance_relative_config`) and indicates if
        the config should be relative to the instance path or the root path
        of the application.

        Flask 构造函数调用, 用于创建 config 属性. 传入 `instance_relative` 参数
        (Flask 构造函数中名称为 `instance_relative_config`), 表示 config 是相对于
        实例路径还是根路径.

        .. versionadded:: 0.8
        """
        root_path = self.root_path
        if instance_relative:
            root_path = self.instance_path
        defaults = dict(self.default_config)
        defaults["ENV"] = get_env()
        defaults["DEBUG"] = get_debug_flag()
        return self.config_class(root_path, defaults)

    def auto_find_instance_path(self):
        """Tries to locate the instance path if it was not provided to the
        constructor of the application class.  It will basically calculate
        the path to a folder named ``instance`` next to your main file or
        the package.

        构造实例未给出实例路径时尝试定位实例路径. 会搜索和主文件或包同目录的
        名为 `instance` 的文件夹

        .. versionadded:: 0.8
        """
        prefix, package_path = find_package(self.import_name)
        if prefix is None:
            return os.path.join(package_path, "instance")
        return os.path.join(prefix, "var", self.name + "-instance")

    def open_instance_resource(self, resource, mode="rb"):
        """Opens a resource from the application's instance folder
        (:attr:`instance_path`).  Otherwise works like
        :meth:`open_resource`.  Instance resources can also be opened for
        writing.

        打开一个应用实例目录(`instance_path`)的资源. 否则作用和 `open_resource` 一致.
        实例资源也可以写模式打开.

        :param resource: the name of the resource.  To access resources within
                         subfolders use forward slashes as separator.
        参数 resource: 资源名称. 若访问子目录资源, 请使用正斜杠作为分隔符

        :param mode: resource file opening mode, default is 'rb'.
        参数 mode: 资源文件打开模式, 默认 `rb`
        """
        return open(os.path.join(self.instance_path, resource), mode)

    @property
    def templates_auto_reload(self):
        """Reload templates when they are changed. Used by
        :meth:`create_jinja_environment`.

        模板更改后自动重新加载. 由 `create_jinja_environment` 使用.

        This attribute can be configured with :data:`TEMPLATES_AUTO_RELOAD`. If
        not set, it will be enabled in debug mode.

        此属性可以由配置项 `TEMPLATES_AUTO_RELOAD` 设置. 若没有配置, 将在调试模式中启用.

        .. versionadded:: 1.0
            This property was added but the underlying config and behavior
            already existed.
        """
        rv = self.config["TEMPLATES_AUTO_RELOAD"]
        return rv if rv is not None else self.debug

    @templates_auto_reload.setter
    def templates_auto_reload(self, value):
        self.config["TEMPLATES_AUTO_RELOAD"] = value

    def create_jinja_environment(self):
        """Create the Jinja environment based on :attr:`jinja_options`
        and the various Jinja-related methods of the app. Changing
        :attr:`jinja_options` after this will have no effect. Also adds
        Flask-related globals and filters to the environment.

        基于 `jinja_options` 属性和各种 Jinja 相关方法创建 Jinja 环境.
        之后再更改 `jinja_options` 无效. 同时将 Flask 相关的全局变量和过滤器
        添加至环境中

        .. versionchanged:: 0.11
           ``Environment.auto_reload`` set in accordance with
           ``TEMPLATES_AUTO_RELOAD`` configuration option.

        .. versionadded:: 0.5
        """
        options = dict(self.jinja_options)

        if "autoescape" not in options:
            options["autoescape"] = self.select_jinja_autoescape

        if "auto_reload" not in options:
            options["auto_reload"] = self.templates_auto_reload

        rv = self.jinja_environment(self, **options)
        rv.globals.update(
            url_for=url_for,
            get_flashed_messages=get_flashed_messages,
            config=self.config,
            # request, session and g are normally added with the
            # context processor for efficiency reasons but for imported
            # templates we also want the proxies in there.
            #
            # 通常处于效率原因, 将 request, session 和 g 与上下文处理器一起添加.
            # 但导入的模板我们也想有一个代理
            request=request,
            session=session,
            g=g,
        )
        rv.filters["tojson"] = json.tojson_filter
        return rv

    def create_global_jinja_loader(self):
        """Creates the loader for the Jinja2 environment.  Can be used to
        override just the loader and keeping the rest unchanged.  It's
        discouraged to override this function.  Instead one should override
        the :meth:`jinja_loader` function instead.

        为 Jinja2 环境创建加载器. 可用于仅覆盖加载程序, 保持其他部分不变. 不推荐重写此函数.
        可以重写 `jinja_loader` 函数.

        The global loader dispatches between the loaders of the application
        and the individual blueprints.

        全局加载器在应用加载器和各个蓝图之间调度.

        .. versionadded:: 0.7
        """
        return DispatchingJinjaLoader(self)

    def select_jinja_autoescape(self, filename):
        """Returns ``True`` if autoescaping should be active for the given
        template name. If no template name is given, returns `True`.

        对于给定模板名, 若应该启用 `autoescaping` 则返回 `True`. 不给定文件名时返回 `True`

        .. versionadded:: 0.5
        """
        if filename is None:
            return True
        return filename.endswith((".html", ".htm", ".xml", ".xhtml"))

    def update_template_context(self, context):
        """Update the template context with some commonly used variables.
        This injects request, session, config and g into the template
        context as well as everything template context processors want
        to inject.  Note that the as of Flask 0.6, the original values
        in the context will not be overridden if a context processor
        decides to return a value with the same key.

        使用一些常用变量更新模板上下文. 这将注入 request, session, config 和 g
        到模板上下文, 还有模板上下文需要注入的所有东西. 注意 Flask 0.6 开始, 如果
        上下文处理器决定用相同的键返回值, 则上下文中的原始值将不会被覆盖

        :param context: the context as a dictionary that is updated in place
                        to add extra variables.
        参数 context: 作为字典的上下文, 用于添加其他变量
        """
        funcs = self.template_context_processors[None]
        reqctx = _request_ctx_stack.top
        if reqctx is not None:
            bp = reqctx.request.blueprint
            if bp is not None and bp in self.template_context_processors:
                funcs = chain(funcs, self.template_context_processors[bp])
        orig_ctx = context.copy()
        for func in funcs:
            context.update(func())
        # make sure the original values win.  This makes it possible to
        # easier add new variables in context processors without breaking
        # existing views.
        #
        # 确保原始值. 这可以更简单地在不破坏现有视图的情况下添加新变量到上下文处理器
        context.update(orig_ctx)

    def make_shell_context(self):
        """Returns the shell context for an interactive shell for this
        application.  This runs all the registered shell context
        processors.

        返回此应用的交互式 shell 的上下文. 返回所有已注册的 shell 上下文处理器
        .. versionadded:: 0.11
        """
        rv = {"app": self, "g": g}
        for processor in self.shell_context_processors:
            rv.update(processor())
        return rv

    #: What environment the app is running in. Flask and extensions may
    #: enable behaviors based on the environment, such as enabling debug
    #: mode. This maps to the :data:`ENV` config key. This is set by the
    #: :envvar:`FLASK_ENV` environment variable and may not behave as
    #: expected if set in code.
    #:
    #: **Do not enable development when deploying in production.**
    #:
    #: Default: ``'production'``
    #
    # 此应用的运行环境. Flask 和拓展可能根据环境不同启用不同的行为, 比如开启调试模式.
    # 这里映射到配置项 `ENV`. 使用环境变量 `FLASK_ENV` 进行配置, 若在代码中设置,
    # 可能与预期行为不一致.
    #
    # 注意: 不要在生产环境部署时开启 development
    #
    # 默认值 `'production'`
    env = ConfigAttribute("ENV")

    @property
    def debug(self):
        """Whether debug mode is enabled. When using ``flask run`` to start
        the development server, an interactive debugger will be shown for
        unhandled exceptions, and the server will be reloaded when code
        changes. This maps to the :data:`DEBUG` config key. This is
        enabled when :attr:`env` is ``'development'`` and is overridden
        by the ``FLASK_DEBUG`` environment variable. It may not behave as
        expected if set in code.

        调试模式是否打开. 使用 `flask run` 命令开启开发服务器, 一个交互式调试器将
        显示未处理的异常, 随后服务器将在代码发送变动时重新加载. 这个映射到配置项的 `DEBUG`.
        当 `env` 为 `development` 且被 `FLASK_DEBUG` 环境变量覆盖时开启.
        若在代码中设置, 可能与预期行为不一致.

        **Do not enable debug mode when deploying in production.**

        注意: 不要在生产环境部署时开启调试模式.

        Default: ``True`` if :attr:`env` is ``'development'``, or
        ``False`` otherwise.

        当 `env` 为 `development` 时默认为 `True`, 否则为 `False`
        """
        return self.config["DEBUG"]

    @debug.setter
    def debug(self, value):
        self.config["DEBUG"] = value
        self.jinja_env.auto_reload = self.templates_auto_reload

    def run(self, host=None, port=None, debug=None, load_dotenv=True, **options):
        """Runs the application on a local development server.

        在本地开发服务器运行应用.

        Do not use ``run()`` in a production setting. It is not intended to
        meet security and performance requirements for a production server.
        Instead, see :ref:`deployment` for WSGI server recommendations.

        不要在生产环境使用 `run()`. 并不能达到生产服务器的安全和性能要求. 相反, 请参考
        `deployment` 文档寻求 WSGI 服务器推荐.

        If the :attr:`debug` flag is set the server will automatically reload
        for code changes and show a debugger in case an exception happened.

        如果设置了 `debug` 属性标志, 将在代码发生变动时自动重新加载, 并在异常发生时展示调试器.

        If you want to run the application in debug mode, but disable the
        code execution on the interactive debugger, you can pass
        ``use_evalex=False`` as parameter.  This will keep the debugger's
        traceback screen active, but disable code execution.

        如果你想在调试模式下运行应用, 但是禁用交互式调试器的代码运行, 你可以传递参数
        `use_evalex=False`. 这将保持调试器的追溯页面启用, 但是禁用代码运行.

        It is not recommended to use this function for development with
        automatic reloading as this is badly supported.  Instead you should
        be using the :command:`flask` command line script's ``run`` support.

        不推荐使用此函数进行自动重新加载的开发, 因为支持很差. 相反, 你应该使用 `flask`
        命令行脚本的 `run` 支持.

        .. admonition:: Keep in Mind
        注意:

           Flask will suppress any server error with a generic error page
           unless it is in debug mode.  As such to enable just the
           interactive debugger without the code reloading, you have to
           invoke :meth:`run` with ``debug=True`` and ``use_reloader=False``.
           Setting ``use_debugger`` to ``True`` without being in debug mode
           won't catch any exceptions because there won't be any to
           catch.

            除非处于调试模式, Flask 将使用通用错误页面抑制任何服务器错误. 因此, 启用不带
            代码重载的交互式调试器, 需要在调用 `run` 方法时传入 `debug=True` 和
            `use_reloader=False`. 不在调试模式下将 `use_debugger` 设为 `True` 不会
            捕获任何异常因为没有异常可供捕获.

        :param host: the hostname to listen on. Set this to ``'0.0.0.0'`` to
            have the server available externally as well. Defaults to
            ``'127.0.0.1'`` or the host in the ``SERVER_NAME`` config variable
            if present.
        参数 host: 监听的主机名. 设为 `'0.0.0.0'` 让服务器可以从外部访问. 默认为
            `'127.0.0.1'` 或 `SERVER_NAME` 配置项的主机名.

        :param port: the port of the webserver. Defaults to ``5000`` or the
            port defined in the ``SERVER_NAME`` config variable if present.
        参数 port: 网络服务器的端口. 默认为 `5000` 或 `SERVER_NAME` 配置项的端口.

        :param debug: if given, enable or disable debug mode. See
            :attr:`debug`.
        参数 debug: 如果给了这个值, 启用或禁用调试模式, 参见 `debug` 属性.

        :param load_dotenv: Load the nearest :file:`.env` and :file:`.flaskenv`
            files to set environment variables. Will also change the working
            directory to the directory containing the first file found.
        参数 load_dotenv: 加载最近目录中的 `.env` 文件和 `.flaskenv` 文件来设定环境变量.
            同时也会将工作目录切换为找到的一个包含以上文件的目录.

        :param options: the options to be forwarded to the underlying Werkzeug
            server. See :func:`werkzeug.serving.run_simple` for more
            information.
        参数 options: 转发到底层 Werkzeug 服务器的选项. 参见
            `werkzeug.serving.run_simple` 函数的文档了解更多信息.

        .. versionchanged:: 1.0
            If installed, python-dotenv will be used to load environment
            variables from :file:`.env` and :file:`.flaskenv` files.

            If set, the :envvar:`FLASK_ENV` and :envvar:`FLASK_DEBUG`
            environment variables will override :attr:`env` and
            :attr:`debug`.

            Threaded mode is enabled by default.

        .. versionchanged:: 0.10
            The default port is now picked from the ``SERVER_NAME``
            variable.
        """
        # Change this into a no-op if the server is invoked from the
        # command line. Have a look at cli.py for more information.
        #
        # 如果从命令行调用服务器, 则将其更改为无操作. 请查看 cli.py 获取更多信息.
        if os.environ.get("FLASK_RUN_FROM_CLI") == "true":
            from .debughelpers import explain_ignored_app_run

            explain_ignored_app_run()
            return

        if get_load_dotenv(load_dotenv):
            cli.load_dotenv()

            # if set, let env vars override previous values
            # 如果设定了, 使用环境变量覆盖之前的值
            if "FLASK_ENV" in os.environ:
                self.env = get_env()
                self.debug = get_debug_flag()
            elif "FLASK_DEBUG" in os.environ:
                self.debug = get_debug_flag()

        # debug passed to method overrides all other sources
        # 传入的 debug 参数覆盖其他地方的设定
        if debug is not None:
            self.debug = bool(debug)

        _host = "127.0.0.1"
        _port = 5000
        server_name = self.config.get("SERVER_NAME")
        sn_host, sn_port = None, None

        if server_name:
            sn_host, _, sn_port = server_name.partition(":")

        host = host or sn_host or _host
        # pick the first value that's not None (0 is allowed)
        # 选择第一个不为 None 的值 (0 也可以)
        port = int(next((p for p in (port, sn_port) if p is not None), _port))

        options.setdefault("use_reloader", self.debug)
        options.setdefault("use_debugger", self.debug)
        options.setdefault("threaded", True)

        cli.show_server_banner(self.env, self.debug, self.name, False)

        from werkzeug.serving import run_simple

        try:
            run_simple(host, port, self, **options)
        finally:
            # reset the first request information if the development server
            # reset normally.  This makes it possible to restart the server
            # without reloader and that stuff from an interactive shell.
            #
            # 若开发服务器正常重设, 将首次请求信息重置. 这就可以在不使用重加载器的情况下
            # 重新启动服务器, 也无需重新启动交互式 shell 中的内容
            self._got_first_request = False

    def test_client(self, use_cookies=True, **kwargs):
        """Creates a test client for this application.  For information
        about unit testing head over to :ref:`testing`.

        为此应用创建一个测试客户端. 关于单元测试的更多信息, 请查看 `testing` 文档.

        Note that if you are testing for assertions or exceptions in your
        application code, you must set ``app.testing = True`` in order for the
        exceptions to propagate to the test client.  Otherwise, the exception
        will be handled by the application (not visible to the test client) and
        the only indication of an AssertionError or other exception will be a
        500 status code response to the test client.  See the :attr:`testing`
        attribute.  For example::

        注意如果你要测试断言或异常, 必须把 `app.test` 设为 `True`, 这样才可以将异常传递
        至测试客户端. 否则, 异常将被应用处理(对测试客户端不可见), 断言错误和其他异常的唯一
        表现就是传向测试客户端的 500 错误. 参见 `testing` 属性. 例如:

            app.testing = True
            client = app.test_client()

        The test client can be used in a ``with`` block to defer the closing down
        of the context until the end of the ``with`` block.  This is useful if
        you want to access the context locals for testing::

        测试客户端可以结合 `with` 语句使用, 语句块结束后上下文自动关闭. 在你想要访问上下文
        本地数据时很有用:

            with app.test_client() as c:
                rv = c.get('/?vodka=42')
                assert request.args['vodka'] == '42'

        Additionally, you may pass optional keyword arguments that will then
        be passed to the application's :attr:`test_client_class` constructor.
        For example::

        另外, 你可以传递可选的关键字参数, 将被转发到应用的 `test_client_class` 属性
        对应的类的构造函数. 例如:

            from flask.testing import FlaskClient

            class CustomClient(FlaskClient):
                def __init__(self, *args, **kwargs):
                    self._authentication = kwargs.pop("authentication")
                    super(CustomClient,self).__init__( *args, **kwargs)

            app.test_client_class = CustomClient
            client = app.test_client(authentication='Basic ....')

        See :class:`~flask.testing.FlaskClient` for more information.
        参见 `flask.testing.FlaskClient` 获取更多信息.

        .. versionchanged:: 0.4
           added support for ``with`` block usage for the client.

        .. versionadded:: 0.7
           The `use_cookies` parameter was added as well as the ability
           to override the client to be used by setting the
           :attr:`test_client_class` attribute.

        .. versionchanged:: 0.11
           Added `**kwargs` to support passing additional keyword arguments to
           the constructor of :attr:`test_client_class`.
        """
        cls = self.test_client_class
        if cls is None:
            from .testing import FlaskClient as cls
        return cls(self, self.response_class, use_cookies=use_cookies, **kwargs)

    def test_cli_runner(self, **kwargs):
        """Create a CLI runner for testing CLI commands.
        See :ref:`testing-cli`.

        创建一个命令行接口运行器以测试命令.

        Returns an instance of :attr:`test_cli_runner_class`, by default
        :class:`~flask.testing.FlaskCliRunner`. The Flask app object is
        passed as the first argument.

        返回一个 `test_cli_runner_class` 属性对应的类的实例, 默认类为
        `flask.testing.FlaskCliRunner`. Flask 应用作为第一个参数.

        .. versionadded:: 1.0
        """
        cls = self.test_cli_runner_class

        if cls is None:
            from .testing import FlaskCliRunner as cls

        return cls(self, **kwargs)

    def open_session(self, request):
        """Creates or opens a new session.  Default implementation stores all
        session data in a signed cookie.  This requires that the
        :attr:`secret_key` is set.  Instead of overriding this method
        we recommend replacing the :class:`session_interface`.

        创建或打开一个新的会话. 默认实现使用签名 cookie 存储所有会话数据. 这要求在配置文件中
        提前配置 `secret_key`. 与其重写此方法, 我们推荐替换 `session_interface` 对应的类

        .. deprecated: 1.0
            Will be removed in 1.1. Use ``session_interface.open_session``
            instead.

            将在 1.1 版本移除此方法, 使用 `session_interface.open_session` 代替.

        :param request: an instance of :attr:`request_class`.
        参数 request: `request_class` 的一个实例
        """

        warnings.warn(
            DeprecationWarning(
                '"open_session" is deprecated and will be removed in 1.1. Use'
                ' "session_interface.open_session" instead.'
            )
        )
        return self.session_interface.open_session(self, request)

    def save_session(self, session, response):
        """Saves the session if it needs updates.  For the default
        implementation, check :meth:`open_session`.  Instead of overriding this
        method we recommend replacing the :class:`session_interface`.

        如果会话需要更新, 保存会话. 默认实现检查 `open_session` 方法. 与其重写此方法,
        我们推荐替换 `session_interface` 对应的类

        .. deprecated: 1.0
            Will be removed in 1.1. Use ``session_interface.save_session``
            instead.

            将在 1.1 版本移除此方法, 使用 `session_interface.save_session` 代替.

        :param session: the session to be saved (a
                        :class:`~werkzeug.contrib.securecookie.SecureCookie`
                        object)
        参数 session: 要保存的会话(`werkzeug.contrib.securecookie.SecureCookie`
            类的实例)

        :param response: an instance of :attr:`response_class`
        参数 request: `request_class` 的一个实例
        """

        warnings.warn(
            DeprecationWarning(
                '"save_session" is deprecated and will be removed in 1.1. Use'
                ' "session_interface.save_session" instead.'
            )
        )
        return self.session_interface.save_session(self, session, response)

    def make_null_session(self):
        """Creates a new instance of a missing session.  Instead of overriding
        this method we recommend replacing the :class:`session_interface`.

        创建一个新的缺失会话的实例. 与其重写此方法, 我们推荐替换 `session_interface` 对应的类

        .. deprecated: 1.0
            Will be removed in 1.1. Use ``session_interface.make_null_session``
            instead.

            将在 1.1 版本移除此方法, 使用 `session_interface.make_null_session` 代替.

        .. versionadded:: 0.7
        """

        warnings.warn(
            DeprecationWarning(
                '"make_null_session" is deprecated and will be removed in 1.1. Use'
                ' "session_interface.make_null_session" instead.'
            )
        )
        return self.session_interface.make_null_session(self)

    @setupmethod
    def register_blueprint(self, blueprint, **options):
        """Register a :class:`~flask.Blueprint` on the application. Keyword
        arguments passed to this method will override the defaults set on the
        blueprint.

        注册一个蓝图, 传如的关键字参数将覆盖蓝图原本的默认值.

        Calls the blueprint's :meth:`~flask.Blueprint.register` method after
        recording the blueprint in the application's :attr:`blueprints`.

        把蓝图记录到应用本身的 `blueprints` 属性后, 调用蓝图的
        `flask.Blueprint.register` 方法

        :param blueprint: The blueprint to register.
        参数 blueprint: 注册的蓝图

        :param url_prefix: Blueprint routes will be prefixed with this.
        参数 url_prefix: 蓝图的路由将以此为前缀

        :param subdomain: Blueprint routes will match on this subdomain.
        参数 subdomain: 蓝图路由将匹配此子域名

        :param url_defaults: Blueprint routes will use these default values for
            view arguments.
        参数 url_defaults: 蓝图路由将使用这些默认值作为视图参数

        :param options: Additional keyword arguments are passed to
            :class:`~flask.blueprints.BlueprintSetupState`. They can be
            accessed in :meth:`~flask.Blueprint.record` callbacks.
        参数 options: 额外的传递给 `flask.blueprints.BlueprintSetupState` 的关键字参数,
            `flask.Blueprint.record` 回调方法可以访问

        .. versionadded:: 0.7
        """
        first_registration = False

        if blueprint.name in self.blueprints:
            assert self.blueprints[blueprint.name] is blueprint, (
                "A name collision occurred between blueprints %r and %r. Both"
                ' share the same name "%s". Blueprints that are created on the'
                " fly need unique names."
                % (blueprint, self.blueprints[blueprint.name], blueprint.name)
            )
        else:
            self.blueprints[blueprint.name] = blueprint
            self._blueprint_order.append(blueprint)
            first_registration = True

        blueprint.register(self, options, first_registration)

    def iter_blueprints(self):
        """Iterates over all blueprints by the order they were registered.
        按注册顺序迭代所有的蓝图.

        .. versionadded:: 0.11
        """
        return iter(self._blueprint_order)

    @setupmethod
    def add_url_rule(
        self,
        rule,
        endpoint=None,
        view_func=None,
        provide_automatic_options=None,
        **options
    ):
        """Connects a URL rule.  Works exactly like the :meth:`route`
        decorator.  If a view_func is provided it will be registered with the
        endpoint.

        添加一个路由规则. 和 `route` 装饰器功能一致. 如果提供了一个视图函数, 将以它的端点
        进行注册.

        Basically this example::

        例如:

            @app.route('/')
            def index():
                pass

        Is equivalent to the following::

        和如下等价:

            def index():
                pass
            app.add_url_rule('/', 'index', index)

        If the view_func is not provided you will need to connect the endpoint
        to a view function like so::

        如果未提供视图函数, 你需要这样把端点和视图函数联系起来:

            app.view_functions['index'] = index

        Internally :meth:`route` invokes :meth:`add_url_rule` so if you want
        to customize the behavior via subclassing you only need to change
        this method.

        内部方法 `route` 调用了 `add_url_rule`, 所以如果想通过子类自定义行为, 只需要
        重写此函数.

        For more information refer to :ref:`url-route-registrations`.
        请参阅 `url-route-registrations` 文档了解更多信息.

        .. versionchanged:: 0.2
           `view_func` parameter added.

        .. versionchanged:: 0.6
           ``OPTIONS`` is added automatically as method.

        :param rule: the URL rule as string
        参数 rule: 字符串表示的 URL 规则

        :param endpoint: the endpoint for the registered URL rule.  Flask
                         itself assumes the name of the view function as
                         endpoint
        参数 endpoint: 注册的 URL 规则的端点. Flask 默认将视图函数的名称作为端点

        :param view_func: the function to call when serving a request to the
                          provided endpoint
        参数 view_func: 当请求匹配到给定的端点时调用的视图函数

        :param provide_automatic_options: controls whether the ``OPTIONS``
            method should be added automatically. This can also be controlled
            by setting the ``view_func.provide_automatic_options = False``
            before adding the rule.
        参数 provide_automatic_options: 是否自动添加 `OPTIONS` 方法. 也可以在添加
            规则前设置 `view_func.provide_automatic_options = False` 来控制

        :param options: the options to be forwarded to the underlying
                        :class:`~werkzeug.routing.Rule` object.  A change
                        to Werkzeug is handling of method options.  methods
                        is a list of methods this rule should be limited
                        to (``GET``, ``POST`` etc.).  By default a rule
                        just listens for ``GET`` (and implicitly ``HEAD``).
                        Starting with Flask 0.6, ``OPTIONS`` is implicitly
                        added and handled by the standard request handling.
        参数 options: 转发到底层 `werkzeug.routing.Rule` 对象的配置. Werkzeug 的
            一个变动就是处理方法参数. `methods` 是一个此规则支持的请求方法列表(`GET`,
            `POST` 等等). 默认只监听 `GET` 方法(和隐式的 `HEAD` 方法). Flask 0.6 起,
            也隐式添加了 `OPTIONS` 方法, 并由标准请求处理器处理.
        """
        if endpoint is None:
            endpoint = _endpoint_from_view_func(view_func)
        options["endpoint"] = endpoint
        methods = options.pop("methods", None)

        # if the methods are not given and the view_func object knows its
        # methods we can use that instead.  If neither exists, we go with
        # a tuple of only ``GET`` as default.
        #
        # 如果未给出 methods 且视图函数本身指定了支持的 methods, 可以用后者代替.
        # 如果都未给出, 默认为只含 `GET` 的元组.
        if methods is None:
            methods = getattr(view_func, "methods", None) or ("GET",)
        if isinstance(methods, string_types):
            raise TypeError(
                "Allowed methods have to be iterables of strings, "
                'for example: @app.route(..., methods=["POST"])'
            )
        methods = set(item.upper() for item in methods)

        # Methods that should always be added
        # 应该添加的 methods
        required_methods = set(getattr(view_func, "required_methods", ()))

        # starting with Flask 0.8 the view_func object can disable and
        # force-enable the automatic options handling.
        #
        # Flask 0.8 起, 视图函数对象可以禁用或强制启用自动添加 OPTIONS 方法处理
        if provide_automatic_options is None:
            provide_automatic_options = getattr(
                view_func, "provide_automatic_options", None
            )

        if provide_automatic_options is None:
            if "OPTIONS" not in methods:
                provide_automatic_options = True
                required_methods.add("OPTIONS")
            else:
                provide_automatic_options = False

        # Add the required methods now.
        # 添加要求的请求方式.
        methods |= required_methods

        rule = self.url_rule_class(rule, methods=methods, **options)
        rule.provide_automatic_options = provide_automatic_options

        self.url_map.add(rule)
        if view_func is not None:
            old_func = self.view_functions.get(endpoint)
            if old_func is not None and old_func != view_func:
                raise AssertionError(
                    "View function mapping is overwriting an "
                    "existing endpoint function: %s" % endpoint
                )
            self.view_functions[endpoint] = view_func

    def route(self, rule, **options):
        """A decorator that is used to register a view function for a
        given URL rule.  This does the same thing as :meth:`add_url_rule`
        but is intended for decorator usage::

        为给定 URL 规则添加视图函数的装饰器. 和 `add_url_rule` 方法功能一致, 但用于装饰器:

            @app.route('/')
            def index():
                return 'Hello World'

        For more information refer to :ref:`url-route-registrations`.
        请查看 `url-route-registrations` 获取更多信息.

        :param rule: the URL rule as string
        cans rule: 字符串格式的 URL 规则

        :param endpoint: the endpoint for the registered URL rule.  Flask
                         itself assumes the name of the view function as
                         endpoint
        参数 endpoint: 注册的 URL 规则的端点. Flask 默认将视图函数的名称作为端点

        :param options: the options to be forwarded to the underlying
                        :class:`~werkzeug.routing.Rule` object.  A change
                        to Werkzeug is handling of method options.  methods
                        is a list of methods this rule should be limited
                        to (``GET``, ``POST`` etc.).  By default a rule
                        just listens for ``GET`` (and implicitly ``HEAD``).
                        Starting with Flask 0.6, ``OPTIONS`` is implicitly
                        added and handled by the standard request handling.
        参数 options: 转发到底层 `werkzeug.routing.Rule` 对象的配置. Werkzeug 的
            一个变动就是处理方法参数. `methods` 是一个此规则支持的请求方法列表(`GET`,
            `POST` 等等). 默认只监听 `GET` 方法(和隐式的 `HEAD` 方法). Flask 0.6 起,
            也隐式添加了 `OPTIONS` 方法, 并由标准请求处理器处理.
        """

        def decorator(f):
            endpoint = options.pop("endpoint", None)
            self.add_url_rule(rule, endpoint, f, **options)
            return f

        return decorator

    @setupmethod
    def endpoint(self, endpoint):
        """A decorator to register a function as an endpoint.
        把一个函数注册为端点的装饰器.

        Example::
        举例:

            @app.endpoint('example.endpoint')
            def example():
                return "example"

        :param endpoint: the name of the endpoint
        参数 endpoint: 端点名
        """

        def decorator(f):
            self.view_functions[endpoint] = f
            return f

        return decorator

    @staticmethod
    def _get_exc_class_and_code(exc_class_or_code):
        """Get the exception class being handled. For HTTP status codes
        or ``HTTPException`` subclasses, return both the exception and
        status code.

        获取处理的异常类. 如果是 HTTP 状态码或 `HTTPException` 的子类, 返回
        异常和状态码

        :param exc_class_or_code: Any exception class, or an HTTP status
            code as an integer.
        参数 exc_class_or_code: 任何异常类或作为 int 值的 HTTP 状态码
        """
        if isinstance(exc_class_or_code, integer_types):
            exc_class = default_exceptions[exc_class_or_code]
        else:
            exc_class = exc_class_or_code

        assert issubclass(exc_class, Exception)

        if issubclass(exc_class, HTTPException):
            return exc_class, exc_class.code
        else:
            return exc_class, None

    @setupmethod
    def errorhandler(self, code_or_exception):
        """Register a function to handle errors by code or exception class.

        通过状态码或异常类注册一个用于处理此异常的函数.

        A decorator that is used to register a function given an
        error code.  Example::

        用于注册一个函数处理对应的错误码, 例如:

            @app.errorhandler(404)
            def page_not_found(error):
                return 'This page does not exist', 404

        You can also register handlers for arbitrary exceptions::
        你也可以为任意异常注册处理器:

            @app.errorhandler(DatabaseError)
            def special_exception_handler(error):
                return 'Database connection failed', 500

        .. versionadded:: 0.7
            Use :meth:`register_error_handler` instead of modifying
            :attr:`error_handler_spec` directly, for application wide error
            handlers.

        .. versionadded:: 0.7
           One can now additionally also register custom exception types
           that do not necessarily have to be a subclass of the
           :class:`~werkzeug.exceptions.HTTPException` class.

        :param code_or_exception: the code as integer for the handler, or
                                  an arbitrary exception
        参数 code_or_exception: int 类型的代码或任意异常类
        """

        def decorator(f):
            self._register_error_handler(None, code_or_exception, f)
            return f

        return decorator

    @setupmethod
    def register_error_handler(self, code_or_exception, f):
        """Alternative error attach function to the :meth:`errorhandler`
        decorator that is more straightforward to use for non decorator
        usage.

        可选的错误连接函数, 不同于 `errorhandler` 方法以装饰器的形式使用,
        可以直接调用此函数进行注册.

        .. versionadded:: 0.7
        """
        self._register_error_handler(None, code_or_exception, f)

    @setupmethod
    def _register_error_handler(self, key, code_or_exception, f):
        """
        :type key: None|str
        key 的类型为 None 或 str

        :type code_or_exception: int|T<=Exception
        code_or_exception 的类型为 int 或 Exception 及其子类

        :type f: callable
        f 的类型为 callable
        """
        if isinstance(code_or_exception, HTTPException):  # old broken behavior     旧有的错误行为
            raise ValueError(
                "Tried to register a handler for an exception instance {0!r}."
                " Handlers can only be registered for exception classes or"
                " HTTP error codes.".format(code_or_exception)
            )

        try:
            exc_class, code = self._get_exc_class_and_code(code_or_exception)
        except KeyError:
            raise KeyError(
                "'{0}' is not a recognized HTTP error code. Use a subclass of"
                " HTTPException with that code instead.".format(code_or_exception)
            )

        handlers = self.error_handler_spec.setdefault(key, {}).setdefault(code, {})
        handlers[exc_class] = f

    @setupmethod
    def template_filter(self, name=None):
        """A decorator that is used to register custom template filter.
        You can specify a name for the filter, otherwise the function
        name will be used. Example::

        用于注册自定义模板筛选器的装饰器. 你可以为筛选器指定一个名称, 否则使用函数本身的名称:

          @app.template_filter()
          def reverse(s):
              return s[::-1]

        :param name: the optional name of the filter, otherwise the
                     function name will be used.
        参数 name: 筛选器的可选名称, 否则使用函数本身的名称
        """

        def decorator(f):
            self.add_template_filter(f, name=name)
            return f

        return decorator

    @setupmethod
    def add_template_filter(self, f, name=None):
        """Register a custom template filter.  Works exactly like the
        :meth:`template_filter` decorator.

        注册一个自定义模板过滤器. 和 `template_filter` 装饰器功能一致.

        :param name: the optional name of the filter, otherwise the
                     function name will be used.
        参数 name: 筛选器的可选名称, 否则使用函数本身的名称
        """
        self.jinja_env.filters[name or f.__name__] = f

    @setupmethod
    def template_test(self, name=None):
        """A decorator that is used to register custom template test.
        You can specify a name for the test, otherwise the function
        name will be used. Example::

        用于注册自定义模板测试的装饰器. 你可以为测试指定一个名称, 否则使用函数本身的名称:

          @app.template_test()
          def is_prime(n):
              if n == 2:
                  return True
              for i in range(2, int(math.ceil(math.sqrt(n))) + 1):
                  if n % i == 0:
                      return False
              return True

        .. versionadded:: 0.10

        :param name: the optional name of the test, otherwise the
                     function name will be used.
        参数 name: 测试的可选名称, 否则使用函数本身的名称
        """

        def decorator(f):
            self.add_template_test(f, name=name)
            return f

        return decorator

    @setupmethod
    def add_template_test(self, f, name=None):
        """Register a custom template test.  Works exactly like the
        :meth:`template_test` decorator.

        注册一个自定义模板测试. 和 `template_test` 装饰器功能一致.

        .. versionadded:: 0.10

        :param name: the optional name of the test, otherwise the
                     function name will be used.
        参数 name: 测试的可选名称, 否则使用函数本身的名称
        """
        self.jinja_env.tests[name or f.__name__] = f

    @setupmethod
    def template_global(self, name=None):
        """A decorator that is used to register a custom template global function.
        You can specify a name for the global function, otherwise the function
        name will be used. Example::

        用于注册自定义模板全局函数的装饰器. 你可以为全局函数指定一个名称, 否则使用函数本身的名称:

            @app.template_global()
            def double(n):
                return 2 * n

        .. versionadded:: 0.10

        :param name: the optional name of the global function, otherwise the
                     function name will be used.
        参数 name: 全局函数的可选名称, 否则使用函数本身的名称
        """

        def decorator(f):
            self.add_template_global(f, name=name)
            return f

        return decorator

    @setupmethod
    def add_template_global(self, f, name=None):
        """Register a custom template global function. Works exactly like the
        :meth:`template_global` decorator.

        注册一个自定义模板全局函数. 和 `template_global` 装饰器功能一致.

        .. versionadded:: 0.10

        :param name: the optional name of the global function, otherwise the
                     function name will be used.
        参数 name: 全局函数的可选名称, 否则使用函数本身的名称
        """
        self.jinja_env.globals[name or f.__name__] = f

    @setupmethod
    def before_request(self, f):
        """Registers a function to run before each request.

        注册一个函数, 使其在每次请求前运行.

        For example, this can be used to open a database connection, or to load
        the logged in user from the session.

        例如, 可以用于打开数据库连接, 或从会话中加载已登录的用户.

        The function will be called without any arguments. If it returns a
        non-None value, the value is handled as if it was the return value from
        the view, and further request handling is stopped.

        这个函数不接收任何参数. 如果返回一个非 None 的值, 这个值将作为视图函数的返回值,
        并停止进一步的请求处理.
        """
        self.before_request_funcs.setdefault(None, []).append(f)
        return f

    @setupmethod
    def before_first_request(self, f):
        """Registers a function to be run before the first request to this
        instance of the application.

        注册一个函数, 使其在此应用的首次请求前运行.

        The function will be called without any arguments and its return
        value is ignored.

        此函数不接收任何参数, 返回值将被忽略.

        .. versionadded:: 0.8
        """
        self.before_first_request_funcs.append(f)
        return f

    @setupmethod
    def after_request(self, f):
        """Register a function to be run after each request.

        注册一个函数, 使其在每次请求后运行.

        Your function must take one parameter, an instance of
        :attr:`response_class` and return a new response object or the
        same (see :meth:`process_response`).

        你的函数必须接收一个参数, 为 `response_class` 对应类的实例, 并返回一个新的
        响应对象或原本的响应对象(参见 `process_response`).

        As of Flask 0.7 this function might not be executed at the end of the
        request in case an unhandled exception occurred.

        Flask 0.7 之后, 当请求发生未处理的异常时, 请求结束时可能不会执行此函数.
        """
        self.after_request_funcs.setdefault(None, []).append(f)
        return f

    @setupmethod
    def teardown_request(self, f):
        """Register a function to be run at the end of each request,
        regardless of whether there was an exception or not.  These functions
        are executed when the request context is popped, even if not an
        actual request was performed.

        注册一个函数, 使其在每次请求最后, 无论是否发生异常都会执行.
        这些函数在请求上下文弹出时执行, 即使未执行实际的请求.

        Example::
        例如:

            ctx = app.test_request_context()
            ctx.push()
            ...
            ctx.pop()

        When ``ctx.pop()`` is executed in the above example, the teardown
        functions are called just before the request context moves from the
        stack of active contexts.  This becomes relevant if you are using
        such constructs in tests.

        以上的例子中, 当 `ctx.pop()` 执行时, 在请求上下文从活动上下文栈移除之前调用了
        这些函数. 如果你在测试中使用此类构造, 这些将变为相关操作.

        Generally teardown functions must take every necessary step to avoid
        that they will fail.  If they do execute code that might fail they
        will have to surround the execution of these code by try/except
        statements and log occurring errors.

        一般来讲, 请求结束时调用的函数应当使用各种方法避免执行失败. 如果必须要执行可能会
        失败的代码, 则需要使用 try/except 包裹相应代码并将错误记录到日志中.

        When a teardown function was called because of an exception it will
        be passed an error object.

        当发生异常时调用请求结束时的回调函数, 这些函数将接收错误对象作为参数.

        The return values of teardown functions are ignored.

        忽略这些函数的返回值.

        .. admonition:: Debug Note
        调试注意事项:

           In debug mode Flask will not tear down a request on an exception
           immediately.  Instead it will keep it alive so that the interactive
           debugger can still access it.  This behavior can be controlled
           by the ``PRESERVE_CONTEXT_ON_EXCEPTION`` configuration variable.

           在调试模式下 Flask 在发生异常时不会立即结束请求, 相反, 将保持请求以便交互式
           调试器可以访问其中的数据. 此行为可以通过 `PRESERVE_CONTEXT_ON_EXCEPTION`
           配置项来控制.
        """
        self.teardown_request_funcs.setdefault(None, []).append(f)
        return f

    @setupmethod
    def teardown_appcontext(self, f):
        """Registers a function to be called when the application context
        ends.  These functions are typically also called when the request
        context is popped.

        注册一个当应用上下文结束时调用的函数. 当请求上下文弹出时, 通常也会调用这些函数.

        Example::
        例如:

            ctx = app.app_context()
            ctx.push()
            ...
            ctx.pop()

        When ``ctx.pop()`` is executed in the above example, the teardown
        functions are called just before the app context moves from the
        stack of active contexts.  This becomes relevant if you are using
        such constructs in tests.

        以上例子中当调用 `ctx.pop()` 时, 这些函数会在应用上下文从栈顶移除前调用.
        如果你在测试中使用此类构造, 这些将变为相关操作.

        Since a request context typically also manages an application
        context it would also be called when you pop a request context.

        由于请求上下文通常管理一个应用上下文, 所以当弹出一个请求上下文时, 也会调用这些函数.

        When a teardown function was called because of an unhandled exception
        it will be passed an error object. If an :meth:`errorhandler` is
        registered, it will handle the exception and the teardown will not
        receive it.

        当由于一个未处理的异常发生而调用这些函数时, 将传入一个错误对象作为参数. 如果注册了一个
        `errorhandler` 来处理此异常, 那将不会将此异常传递到此处.

        The return values of teardown functions are ignored.

        忽略这些函数的返回值.

        .. versionadded:: 0.9
        """
        self.teardown_appcontext_funcs.append(f)
        return f

    @setupmethod
    def context_processor(self, f):
        """Registers a template context processor function.

        注册一个模板上下文处理函数.
        """
        self.template_context_processors[None].append(f)
        return f

    @setupmethod
    def shell_context_processor(self, f):
        """Registers a shell context processor function.

        注册一个 shell 上下文处理函数.

        .. versionadded:: 0.11
        """
        self.shell_context_processors.append(f)
        return f

    @setupmethod
    def url_value_preprocessor(self, f):
        """Register a URL value preprocessor function for all view
        functions in the application. These functions will be called before the
        :meth:`before_request` functions.

        注册一个应用到此应用的所有视图函数的 URL 值处理函数. 这些函数将在 `before_request`
        注册的函数之前调用.

        The function can modify the values captured from the matched url before
        they are passed to the view. For example, this can be used to pop a
        common language code value and place it in ``g`` rather than pass it to
        every view.

        这个函数可以修改从匹配的 url 中得到的值并在传入视图函数前修改. 例如, 可以用于弹出一个
        通用语言编码并将其放置于 `g`, 而不是传递到每个视图函数中.

        The function is passed the endpoint name and values dict. The return
        value is ignored.

        这个函数接收端点名, 以及值组成的字典作为参数, 忽略返回值.
        """
        self.url_value_preprocessors.setdefault(None, []).append(f)
        return f

    @setupmethod
    def url_defaults(self, f):
        """Callback function for URL defaults for all view functions of the
        application.  It's called with the endpoint and values and should
        update the values passed in place.

        应用到此应用的所有视图函数的 URL 默认值回调函数. 接收端点名, 以及应该更新的值组成
        的字典作为参数.
        """
        self.url_default_functions.setdefault(None, []).append(f)
        return f

    def _find_error_handler(self, e):
        """Return a registered error handler for an exception in this order:
        blueprint handler for a specific code, app handler for a specific code,
        blueprint handler for an exception class, app handler for an exception
        class, or ``None`` if a suitable handler is not found.

        返回一个注册的用于此错误的处理器, 按以下顺序查找: 蓝图用于处理特定状态码的, 应用用于处理
        特定状态码的, 蓝图用于处理一个特定的错误类, 应用用于处理一个特定的错误类. 如果找不到
        对应的处理器返回 `None`
        """
        exc_class, code = self._get_exc_class_and_code(type(e))

        for name, c in (
            (request.blueprint, code),
            (None, code),
            (request.blueprint, None),
            (None, None),
        ):
            handler_map = self.error_handler_spec.setdefault(name, {}).get(c)

            if not handler_map:
                continue

            for cls in exc_class.__mro__:
                handler = handler_map.get(cls)

                if handler is not None:
                    return handler

    def handle_http_exception(self, e):
        """Handles an HTTP exception.  By default this will invoke the
        registered error handlers and fall back to returning the
        exception as response.

        处理 HTTP 异常. 默认调用注册的错误处理器, 否则将异常作为响应返回.

        .. versionchanged:: 1.0.3
            ``RoutingException``, used internally for actions such as
             slash redirects during routing, is not passed to error
             handlers.

        .. versionchanged:: 1.0
            Exceptions are looked up by code *and* by MRO, so
            ``HTTPExcpetion`` subclasses can be handled with a catch-all
            handler for the base ``HTTPException``.

        .. versionadded:: 0.3
        """
        # Proxy exceptions don't have error codes.  We want to always return
        # those unchanged as errors
        #
        # 代理异常没有错误码. 我们想把这些依旧作为错误返回.
        if e.code is None:
            return e

        # RoutingExceptions are used internally to trigger routing
        # actions, such as slash redirects raising RequestRedirect. They
        # are not raised or handled in user code.
        #
        # 路由异常内部使用用于触发路由动作, 例如斜线重定向抛出 RequestRedirect.
        # 这些不以用户代码抛出或处理.
        if isinstance(e, RoutingException):
            return e

        handler = self._find_error_handler(e)
        if handler is None:
            return e
        return handler(e)

    def trap_http_exception(self, e):
        """Checks if an HTTP exception should be trapped or not.  By default
        this will return ``False`` for all exceptions except for a bad request
        key error if ``TRAP_BAD_REQUEST_ERRORS`` is set to ``True``.  It
        also returns ``True`` if ``TRAP_HTTP_EXCEPTIONS`` is set to ``True``.

        检查是否应该捕获 HTTP 异常. 对于所有的异常, 默认返回 `False` . 除非在
        `TRAP_BAD_REQUEST_ERRORS` 设为 `True` 的情况下的 bad request 键错误.
        如果 `TRAP_HTTP_EXCEPTIONS` 设为 `True` 也是设为 `True`.

        This is called for all HTTP exceptions raised by a view function.
        If it returns ``True`` for any exception the error handler for this
        exception is not called and it shows up as regular exception in the
        traceback.  This is helpful for debugging implicitly raised HTTP
        exceptions.

        所有的视图函数发生异常时都会调用此函数. 如果返回 `True`, 任何异常发生时, 不会
        调用处理此异常的的处理函数, 并在 traceback 中显示为一般错误. 这对于调试隐式
        引发的 HTTP 异常很有帮助.

        .. versionchanged:: 1.0
            Bad request errors are not trapped by default in debug mode.

        .. versionadded:: 0.8
        """
        if self.config["TRAP_HTTP_EXCEPTIONS"]:
            return True

        trap_bad_request = self.config["TRAP_BAD_REQUEST_ERRORS"]

        # if unset, trap key errors in debug mode
        # 如果未设置, 在调试模式下捕获键错误
        if (
            trap_bad_request is None
            and self.debug
            and isinstance(e, BadRequestKeyError)
        ):
            return True

        if trap_bad_request:
            return isinstance(e, BadRequest)

        return False

    def handle_user_exception(self, e):
        """This method is called whenever an exception occurs that
        should be handled. A special case is :class:`~werkzeug
        .exceptions.HTTPException` which is forwarded to the
        :meth:`handle_http_exception` method. This function will either
        return a response value or reraise the exception with the same
        traceback.

        当发生异常且应当被处理时调用此函数. 一个特例是 `werkzeug.exceptions.HTTPException`
        转发到 `handle_http_exception` 方法. 此函数将返回一个响应值或以同样的 traceback
        重新抛出异常.

        .. versionchanged:: 1.0
            Key errors raised from request data like ``form`` show the
            bad key in debug mode rather than a generic bad request
            message.

        .. versionadded:: 0.7
        """
        exc_type, exc_value, tb = sys.exc_info()
        assert exc_value is e
        # ensure not to trash sys.exc_info() at that point in case someone
        # wants the traceback preserved in handle_http_exception.  Of course
        # we cannot prevent users from trashing it themselves in a custom
        # trap_http_exception method so that's their fault then.
        #
        # 保证在那个时候不要丢弃 `sys.exc_info()`, 以防有人想将 traceback 保留到
        # `handle_http_exception` 中. 当然我们不能阻止用户使用自定义的 `trap_http_exception`
        # 方法自行丢弃, 因此这是他们的错误.

        if isinstance(e, BadRequestKeyError):
            if self.debug or self.config["TRAP_BAD_REQUEST_ERRORS"]:
                e.show_exception = True

                # Werkzeug < 0.15 doesn't add the KeyError to the 400
                # message, add it in manually.
                #
                # Werkzeug 0.15 以上版本不会将 KeyError 加入到 400 消息中,
                # 需要手动添加
                #
                # TODO: clean up once Werkzeug >= 0.15.5 is required
                if e.args[0] not in e.get_description():
                    e.description = "KeyError: '{}'".format(*e.args)
            elif not hasattr(BadRequestKeyError, "show_exception"):
                e.args = ()

        if isinstance(e, HTTPException) and not self.trap_http_exception(e):
            return self.handle_http_exception(e)

        handler = self._find_error_handler(e)

        if handler is None:
            reraise(exc_type, exc_value, tb)
        return handler(e)

    def handle_exception(self, e):
        """Handle an exception that did not have an error handler
        associated with it, or that was raised from an error handler.
        This always causes a 500 ``InternalServerError``.

        在一个没有对应处理器的异常发生时或者异常处理器发生异常时进行处理.
        这总是导致 500 `InternalServerError`.

        Always sends the :data:`got_request_exception` signal.

        总是发送 `got_request_exception` 信号.

        If :attr:`propagate_exceptions` is ``True``, such as in debug
        mode, the error will be re-raised so that the debugger can
        display it. Otherwise, the original exception is logged, and
        an :exc:`~werkzeug.exceptions.InternalServerError` is returned.

        如果 `propagate_exceptions` 属性值为 `True`, 例如在调试模式下, 将会
        重新抛出异常以便调试器可以展示. 否则, 日志记录原本的错误, 返回一个
        `werkzeug.exceptions.InternalServerError` 异常.

        If an error handler is registered for ``InternalServerError`` or
        ``500``, it will be used. For consistency, the handler will
        always receive the ``InternalServerError``. The original
        unhandled exception is available as ``e.original_exception``.

        如果一个错误处理器注册为处理 `InternalServerError` 或 `500`, 使用此函数.
        为了一致性, 处理器总是接收 `InternalServerError`. 原本的未处理的异常可以
        通过 `e.original_exception` 访问.


        .. note::
        注意:

            Prior to Werkzeug 1.0.0, ``InternalServerError`` will not
            always have an ``original_exception`` attribute. Use
            ``getattr(e, "original_exception", None)`` to simulate the
            behavior for compatibility.

            Werkzeug 1.0.0 前, `InternalServerError` 不一定总是有
            `original_exception` 属性. 使用
            `getattr(e, "original_exception", None)` 保证兼容.


        .. versionchanged:: 1.1.0
            Always passes the ``InternalServerError`` instance to the
            handler, setting ``original_exception`` to the unhandled
            error.

        .. versionchanged:: 1.1.0
            ``after_request`` functions and other finalization is done
            even for the default 500 response when there is no handler.

        .. versionadded:: 0.3
        """
        exc_type, exc_value, tb = sys.exc_info()
        got_request_exception.send(self, exception=e)

        if self.propagate_exceptions:
            # if we want to repropagate the exception, we can attempt to
            # raise it with the whole traceback in case we can do that
            # (the function was actually called from the except part)
            # otherwise, we just raise the error again
            #
            # 如果我们想重新传播这个异常, 我们可以尝试使用全部的 traceback 抛出.
            # (此函数实际上从 except 部分调用), 否则仅是重新抛出异常.
            if exc_value is e:
                reraise(exc_type, exc_value, tb)
            else:
                raise e

        self.log_exception((exc_type, exc_value, tb))
        server_error = InternalServerError()
        # TODO: pass as param when Werkzeug>=1.0.0 is required
        # TODO: also remove note about this from docstring and docs
        server_error.original_exception = e
        handler = self._find_error_handler(server_error)

        if handler is not None:
            server_error = handler(server_error)

        return self.finalize_request(server_error, from_error_handler=True)

    def log_exception(self, exc_info):
        """Logs an exception.  This is called by :meth:`handle_exception`
        if debugging is disabled and right before the handler is called.
        The default implementation logs the exception as error on the
        :attr:`logger`.

        记录一个异常. 如果禁用调试, 在处理器调用之前由 `handle_exception` 方法调用.
        默认实现是是将异常作为错误记录到 `logger` 属性.

        .. versionadded:: 0.8
        """
        self.logger.error(
            "Exception on %s [%s]" % (request.path, request.method), exc_info=exc_info
        )

    def raise_routing_exception(self, request):
        """Exceptions that are recording during routing are reraised with
        this method.  During debug we are not reraising redirect requests
        for non ``GET``, ``HEAD``, or ``OPTIONS`` requests and we're raising
        a different error instead to help debug situations.

        使用此方法引发在路由过程中记录的异常. 调试时不会针对非 `GET`, `HEAD`, `OPTIONS`
        请求重新引发重定向请求, 而是抛出不同的异常来帮助调试情况.

        :internal:
        """
        if (
            not self.debug
            or not isinstance(request.routing_exception, RequestRedirect)
            or request.method in ("GET", "HEAD", "OPTIONS")
        ):
            raise request.routing_exception

        from .debughelpers import FormDataRoutingRedirect

        raise FormDataRoutingRedirect(request)

    def dispatch_request(self):
        """Does the request dispatching.  Matches the URL and returns the
        return value of the view or error handler.  This does not have to
        be a response object.  In order to convert the return value to a
        proper response object, call :func:`make_response`.

        进行请求分发. 匹配 URL 返回视图或错误处理器的返回值. 不一定是响应对象. 为了将
        返回值转换为合适的响应对象, 调用 `make_response` 函数.

        .. versionchanged:: 0.7
           This no longer does the exception handling, this code was
           moved to the new :meth:`full_dispatch_request`.

           不再做异常处理, 移至新的 `full_dispatch_request` 方法.
        """
        req = _request_ctx_stack.top.request
        if req.routing_exception is not None:
            self.raise_routing_exception(req)
        rule = req.url_rule
        # if we provide automatic options for this URL and the
        # request came with the OPTIONS method, reply automatically
        #
        # 如果我们为此 URL 提供了自动的 OPTIONS 方法, 并且请求以 OPTIONS 方法
        # 发送, 自动回复.
        if (
            getattr(rule, "provide_automatic_options", False)
            and req.method == "OPTIONS"
        ):
            return self.make_default_options_response()
        # otherwise dispatch to the handler for that endpoint
        #
        # 否则根据端点分发到对应处理器
        return self.view_functions[rule.endpoint](**req.view_args)

    def full_dispatch_request(self):
        """Dispatches the request and on top of that performs request
        pre and postprocessing as well as HTTP exception catching and
        error handling.

        调度请求, 并在此之上执行请求的预处理和后处理, 以及 HTTP 异常捕获和错误处理.

        .. versionadded:: 0.7
        """
        self.try_trigger_before_first_request_functions()
        try:
            request_started.send(self)
            rv = self.preprocess_request()
            if rv is None:
                rv = self.dispatch_request()
        except Exception as e:
            rv = self.handle_user_exception(e)
        return self.finalize_request(rv)

    def finalize_request(self, rv, from_error_handler=False):
        """Given the return value from a view function this finalizes
        the request by converting it into a response and invoking the
        postprocessing functions.  This is invoked for both normal
        request dispatching as well as error handlers.

        给定视图函数的返回值, 此函数通过转换为响应对象并调用后处理函数. 普通请求
        调度和错误处理都会调用此函数.

        Because this means that it might be called as a result of a
        failure a special safe mode is available which can be enabled
        with the `from_error_handler` flag.  If enabled, failures in
        response processing will be logged and otherwise ignored.

        由于此函数可能在执行失败时调用, 所有有一个特别的安全模式可以通过 `from_error_handler`
        标志启用. 如果启用, 响应处理失败将被记录, 否则忽略.

        :internal:
        """
        response = self.make_response(rv)
        try:
            response = self.process_response(response)
            request_finished.send(self, response=response)
        except Exception:
            if not from_error_handler:
                raise
            self.logger.exception(
                "Request finalizing failed with an error while handling an error"
            )
        return response

    def try_trigger_before_first_request_functions(self):
        """Called before each request and will ensure that it triggers
        the :attr:`before_first_request_funcs` and only exactly once per
        application instance (which means process usually).

        每个请求前调用, 保证触发了 `before_first_request_funcs` 并且每个应用实例
        (通常意味着进程)只调用一次.

        :internal:
        """
        if self._got_first_request:
            return
        with self._before_request_lock:
            if self._got_first_request:
                return
            for func in self.before_first_request_funcs:
                func()
            self._got_first_request = True

    def make_default_options_response(self):
        """This method is called to create the default ``OPTIONS`` response.
        This can be changed through subclassing to change the default
        behavior of ``OPTIONS`` responses.

        调用此方法创建默认的 `OPTIONS` 响应. 可以通过在子类中重写此方法更改对 `OPTIONS`
        的默认响应行为.

        .. versionadded:: 0.7
        """
        adapter = _request_ctx_stack.top.url_adapter
        if hasattr(adapter, "allowed_methods"):
            methods = adapter.allowed_methods()
        else:
            # fallback for Werkzeug < 0.7
            methods = []
            try:
                adapter.match(method="--")
            except MethodNotAllowed as e:
                methods = e.valid_methods
            except HTTPException:
                pass
        rv = self.response_class()
        rv.allow.update(methods)
        return rv

    def should_ignore_error(self, error):
        """This is called to figure out if an error should be ignored
        or not as far as the teardown system is concerned.  If this
        function returns ``True`` then the teardown handlers will not be
        passed the error.

        调用此方法可以确定是否应该忽略拆解系统中的错误. 如果此函数返回 `True`, 不会将
        错误传递到处理函数.

        .. versionadded:: 0.10
        """
        return False

    def make_response(self, rv):
        """Convert the return value from a view function to an instance of
        :attr:`response_class`.

        将视图函数的返回值转变为 `response_class` 指向的类的实例.

        :param rv: the return value from the view function. The view function
            must return a response. Returning ``None``, or the view ending
            without returning, is not allowed. The following types are allowed
            for ``view_rv``:

        参数 rv: 视图函数的返回值. 视图函数必须返回响应. 不允许不返回或者返回 `None`.
            允许以下类型:

            ``str`` (``unicode`` in Python 2)
                A response object is created with the string encoded to UTF-8
                as the body.

            `str` (Python 2 的 `unicode`)
                使用此字符串编码为 UTF-8 作为 body 创建响应对象.

            ``bytes`` (``str`` in Python 2)
                A response object is created with the bytes as the body.

            `bytes` (Python 2 的 `str`)
                使用这些 bytes 作为 body 创建响应对象.

            ``dict``
                A dictionary that will be jsonify'd before being returned.

            `dict`
                返回之前调用 jsonify 生成响应.

            ``tuple``
                Either ``(body, status, headers)``, ``(body, status)``, or
                ``(body, headers)``, where ``body`` is any of the other types
                allowed here, ``status`` is a string or an integer, and
                ``headers`` is a dictionary or a list of ``(key, value)``
                tuples. If ``body`` is a :attr:`response_class` instance,
                ``status`` overwrites the exiting value and ``headers`` are
                extended.

            `tuple`
                可选的形式为 `(body, status, headers)`, `(body, status)`, 或
                `(body, headers)`. `body` 可以是之前提到的类型, `status` 为字符串或
                整数, `headers` 是一个字典或一个由 `(key, value)` 元组组成的列表.
                如果 `body` 为一个 `response_class` 属性指向的类的实例, `status` 覆盖
                当前的值, `headers` 拓展到当前的 headers.

            :attr:`response_class`
                The object is returned unchanged.

            属性 `response_class`
                以此对象返回, 不做更改.

            other :class:`~werkzeug.wrappers.Response` class
                The object is coerced to :attr:`response_class`.

            其他类 `werkzeug.wrappers.Response`:
                这个对象被强制为 `response_class`

            :func:`callable`
                The function is called as a WSGI application. The result is
                used to create a response object.

            函数 `callable`
                WSGI 应用调用的函数. 结果用于创建一个响应对象.

        .. versionchanged:: 0.9
           Previously a tuple was interpreted as the arguments for the
           response object.
        """

        status = headers = None

        # unpack tuple returns
        # 解包元组返回
        if isinstance(rv, tuple):
            len_rv = len(rv)

            # a 3-tuple is unpacked directly
            # 三个值的元组直接解包
            if len_rv == 3:
                rv, status, headers = rv
            # decide if a 2-tuple has status or headers
            # 确认两个值的元组包含 status 还是 headers
            elif len_rv == 2:
                if isinstance(rv[1], (Headers, dict, tuple, list)):
                    rv, headers = rv
                else:
                    rv, status = rv
            # other sized tuples are not allowed
            # 不允许其他长度的元组
            else:
                raise TypeError(
                    "The view function did not return a valid response tuple."
                    " The tuple must have the form (body, status, headers),"
                    " (body, status), or (body, headers)."
                )

        # the body must not be None
        # body 不能为 None
        if rv is None:
            raise TypeError(
                "The view function did not return a valid response. The"
                " function either returned None or ended without a return"
                " statement."
            )

        # make sure the body is an instance of the response class
        # 确保 body 是响应类的实例
        if not isinstance(rv, self.response_class):
            if isinstance(rv, (text_type, bytes, bytearray)):
                # let the response class set the status and headers instead of
                # waiting to do it manually, so that the class can handle any
                # special logic
                #
                # 让响应类设定 status 和 headers 而不是等待手动设定, 以便此类可以处理
                # 任何特定逻辑
                rv = self.response_class(rv, status=status, headers=headers)
                status = headers = None
            elif isinstance(rv, dict):
                rv = jsonify(rv)
            elif isinstance(rv, BaseResponse) or callable(rv):
                # evaluate a WSGI callable, or coerce a different response
                # class to the correct type
                #
                # 评估可调用的 WSGI, 或将其他响应类强制转为正确的类型
                try:
                    rv = self.response_class.force_type(rv, request.environ)
                except TypeError as e:
                    new_error = TypeError(
                        "{e}\nThe view function did not return a valid"
                        " response. The return type must be a string, dict, tuple,"
                        " Response instance, or WSGI callable, but it was a"
                        " {rv.__class__.__name__}.".format(e=e, rv=rv)
                    )
                    reraise(TypeError, new_error, sys.exc_info()[2])
            else:
                raise TypeError(
                    "The view function did not return a valid"
                    " response. The return type must be a string, dict, tuple,"
                    " Response instance, or WSGI callable, but it was a"
                    " {rv.__class__.__name__}.".format(rv=rv)
                )

        # prefer the status if it was provided
        # 优先使用传入的 status
        if status is not None:
            if isinstance(status, (text_type, bytes, bytearray)):
                rv.status = status
            else:
                rv.status_code = status

        # extend existing headers with provided headers
        # 使用提供的 headers 拓展已有的
        if headers:
            rv.headers.extend(headers)

        return rv

    def create_url_adapter(self, request):
        """Creates a URL adapter for the given request. The URL adapter
        is created at a point where the request context is not yet set
        up so the request is passed explicitly.

        为给定的请求创建 URL 适配器. URL 适配器在请求上下文还未设置完毕之前创建,
        所以显式传入请求.

        .. versionadded:: 0.6

        .. versionchanged:: 0.9
           This can now also be called without a request object when the
           URL adapter is created for the application context.

        .. versionchanged:: 1.0
            :data:`SERVER_NAME` no longer implicitly enables subdomain
            matching. Use :attr:`subdomain_matching` instead.
        """
        if request is not None:
            # If subdomain matching is disabled (the default), use the
            # default subdomain in all cases. This should be the default
            # in Werkzeug but it currently does not have that feature.
            #
            # 如果子域名匹配不可用(默认), 所有情况下使用默认子域名. 本应该是 Werkzeug
            # 默认的功能, 但目前没有此特性.
            subdomain = (
                (self.url_map.default_subdomain or None)
                if not self.subdomain_matching
                else None
            )
            return self.url_map.bind_to_environ(
                request.environ,
                server_name=self.config["SERVER_NAME"],
                subdomain=subdomain,
            )
        # We need at the very least the server name to be set for this
        # to work.
        #
        # 我们至少需要设置服务器名称才能使其正常工作
        if self.config["SERVER_NAME"] is not None:
            return self.url_map.bind(
                self.config["SERVER_NAME"],
                script_name=self.config["APPLICATION_ROOT"],
                url_scheme=self.config["PREFERRED_URL_SCHEME"],
            )

    def inject_url_defaults(self, endpoint, values):
        """Injects the URL defaults for the given endpoint directly into
        the values dictionary passed.  This is used internally and
        automatically called on URL building.

        将给定端点的 URL 默认值直接注入传递的值字典中. 这些操作是内部使用
        并且在 URL 构建时自动调用.

        .. versionadded:: 0.7
        """
        funcs = self.url_default_functions.get(None, ())
        if "." in endpoint:
            bp = endpoint.rsplit(".", 1)[0]
            funcs = chain(funcs, self.url_default_functions.get(bp, ()))
        for func in funcs:
            func(endpoint, values)

    def handle_url_build_error(self, error, endpoint, values):
        """Handle :class:`~werkzeug.routing.BuildError` on :meth:`url_for`.

        处理 `url_for` 抛出的 `werkzeug.routing.BuildError`
        """
        exc_type, exc_value, tb = sys.exc_info()
        for handler in self.url_build_error_handlers:
            try:
                rv = handler(error, endpoint, values)
                if rv is not None:
                    return rv
            except BuildError as e:
                # make error available outside except block (py3)
                # 使错误对象可以在 except 块外部访问 (python 3)
                error = e

        # At this point we want to reraise the exception.  If the error is
        # still the same one we can reraise it with the original traceback,
        # otherwise we raise it from here.
        #
        # 此处我们想重新抛出此异常. 如果错误还是原来的那个, 使用原来的 traceback 抛出,
        # 否则在此处抛出.
        if error is exc_value:
            reraise(exc_type, exc_value, tb)
        raise error

    def preprocess_request(self):
        """Called before the request is dispatched. Calls
        :attr:`url_value_preprocessors` registered with the app and the
        current blueprint (if any). Then calls :attr:`before_request_funcs`
        registered with the app and the blueprint.

        请求调度前调用. 调用应用和当前蓝图(如果有)注册的 `url_value_preprocessors`.
        然后调用应用和蓝图注册的 `before_request_funcs`.

        If any :meth:`before_request` handler returns a non-None value, the
        value is handled as if it was the return value from the view, and
        further request handling is stopped.

        如果任何 `before_request` 处理器返回一个不为 None 的值, 此值将视为视图函数的返回值,
        不再进行之后的操作.
        """

        bp = _request_ctx_stack.top.request.blueprint

        funcs = self.url_value_preprocessors.get(None, ())
        if bp is not None and bp in self.url_value_preprocessors:
            funcs = chain(funcs, self.url_value_preprocessors[bp])
        for func in funcs:
            func(request.endpoint, request.view_args)

        funcs = self.before_request_funcs.get(None, ())
        if bp is not None and bp in self.before_request_funcs:
            funcs = chain(funcs, self.before_request_funcs[bp])
        for func in funcs:
            rv = func()
            if rv is not None:
                return rv

    def process_response(self, response):
        """Can be overridden in order to modify the response object
        before it's sent to the WSGI server.  By default this will
        call all the :meth:`after_request` decorated functions.

        可以重写以便在发送到 WSGI 服务器前修改响应对象. 默认调用全部使用
        `after_request` 装饰器装饰的函数.

        .. versionchanged:: 0.5
           As of Flask 0.5 the functions registered for after request
           execution are called in reverse order of registration.

           Flask 0.5 后, 请求后调用的函数与注册顺序相反

        :param response: a :attr:`response_class` object.
        参数 response: 一个 `response_class` 类的对象.

        :return: a new response object or the same, has to be an
                 instance of :attr:`response_class`.
        返回: 一个新的响应对象或者原来的对象, 必须为 `response_class` 类的实例.
        """
        ctx = _request_ctx_stack.top
        bp = ctx.request.blueprint
        funcs = ctx._after_request_functions
        if bp is not None and bp in self.after_request_funcs:
            funcs = chain(funcs, reversed(self.after_request_funcs[bp]))
        if None in self.after_request_funcs:
            funcs = chain(funcs, reversed(self.after_request_funcs[None]))
        for handler in funcs:
            response = handler(response)
        if not self.session_interface.is_null_session(ctx.session):
            self.session_interface.save_session(self, ctx.session, response)
        return response

    def do_teardown_request(self, exc=_sentinel):
        """Called after the request is dispatched and the response is
        returned, right before the request context is popped.

        请求调度完毕且响应返回时, 在请求上下文弹出之前调用.

        This calls all functions decorated with
        :meth:`teardown_request`, and :meth:`Blueprint.teardown_request`
        if a blueprint handled the request. Finally, the
        :data:`request_tearing_down` signal is sent.

        调用所有使用 `teardown_request` 和 `Blueprint.teardown_request` 装饰器
        装饰的函数(如果这个请求由某个蓝图处理). 最后发送 `request_tearing_down` 信号.

        This is called by
        :meth:`RequestContext.pop() <flask.ctx.RequestContext.pop>`,
        which may be delayed during testing to maintain access to
        resources.

        此函数由 `RequestContext.pop() <flask.ctx.RequestContext.pop>` 方法调用,
        在测试期间可能因维持对资源的访问造成延迟.

        :param exc: An unhandled exception raised while dispatching the
            request. Detected from the current exception information if
            not passed. Passed to each teardown function.
        参数 exc: 调度请求时未处理的异常. 未传入则坚持当前异常信息, 将其传入每个 teardown
            函数.

        .. versionchanged:: 0.9
            Added the ``exc`` argument.
        """
        if exc is _sentinel:
            exc = sys.exc_info()[1]
        funcs = reversed(self.teardown_request_funcs.get(None, ()))
        bp = _request_ctx_stack.top.request.blueprint
        if bp is not None and bp in self.teardown_request_funcs:
            funcs = chain(funcs, reversed(self.teardown_request_funcs[bp]))
        for func in funcs:
            func(exc)
        request_tearing_down.send(self, exc=exc)

    def do_teardown_appcontext(self, exc=_sentinel):
        """Called right before the application context is popped.

        应用上下文弹出之前调用.

        When handling a request, the application context is popped
        after the request context. See :meth:`do_teardown_request`.

        处理请求时, 请求上下文结束后应用上下文也弹出. 参见函数 `do_teardown_request`.

        This calls all functions decorated with
        :meth:`teardown_appcontext`. Then the
        :data:`appcontext_tearing_down` signal is sent.

        调用所有用 `teardown_appcontext` 装饰器装饰的函数. 然后发送
        `appcontext_tearing_down` 信号.

        This is called by
        :meth:`AppContext.pop() <flask.ctx.AppContext.pop>`.

        此函数由 `AppContext.pop() <flask.ctx.AppContext.pop>` 方法调用.

        .. versionadded:: 0.9
        """
        if exc is _sentinel:
            exc = sys.exc_info()[1]
        for func in reversed(self.teardown_appcontext_funcs):
            func(exc)
        appcontext_tearing_down.send(self, exc=exc)

    def app_context(self):
        """Create an :class:`~flask.ctx.AppContext`. Use as a ``with``
        block to push the context, which will make :data:`current_app`
        point at this application.

        创建一个 `flask.ctx.AppContext` 对象. 使用 `with` 语句推入上下文,
        可以让 `current_app` 指向此应用.

        An application context is automatically pushed by
        :meth:`RequestContext.push() <flask.ctx.RequestContext.push>`
        when handling a request, and when running a CLI command. Use
        this to manually create a context outside of these situations.

        当处理请求或执行命令行接口命令时, 应用上下文由
        `RequestContext.push() <flask.ctx.RequestContext.push>` 方法自动推入,
        使用此方法在以上两种情况外手动创建一个上下文.

        ::

            with app.app_context():
                init_db()

        See :doc:`/appcontext`.
        参见文档 `/appcontext`.

        .. versionadded:: 0.9
        """
        return AppContext(self)

    def request_context(self, environ):
        """Create a :class:`~flask.ctx.RequestContext` representing a
        WSGI environment. Use a ``with`` block to push the context,
        which will make :data:`request` point at this request.

        创建一个 `flask.ctx.RequestContext` 对象代表 WSGI 环境. 使用 `with` 语句
        推入上下文, 可以让 `request` 指向此请求.

        See :doc:`/reqcontext`.
        参见文档 `/reqcontext`/

        Typically you should not call this from your own code. A request
        context is automatically pushed by the :meth:`wsgi_app` when
        handling a request. Use :meth:`test_request_context` to create
        an environment and context instead of this method.

        通常, 你不应该从自己的代码中调用它. 处理请求时, 请求上下文由 `wsgi_app` 方法
        自动推入. 使用 `test_request_context` 方法创建一个环境和上下文, 而不是
        使用此方法.

        :param environ: a WSGI environment
        参数 environ: WSGI 环境
        """
        return RequestContext(self, environ)

    def test_request_context(self, *args, **kwargs):
        """Create a :class:`~flask.ctx.RequestContext` for a WSGI
        environment created from the given values. This is mostly useful
        during testing, where you may want to run a function that uses
        request data without dispatching a full request.

        使用给定的值为 WSGI 环境创建一个 `flask.ctx.RequestContext` 类的对象.
        在测试时非常有用. 你可以用请求数据执行一个函数而不通过调度一个全量请求.

        See :doc:`/reqcontext`.
        参见 `/reqcontext` 文档.

        Use a ``with`` block to push the context, which will make
        :data:`request` point at the request for the created
        environment. ::

        使用 `with` 语句推入上下文, 可以让 `request` 指向此请求:

            with test_request_context(...):
                generate_report()

        When using the shell, it may be easier to push and pop the
        context manually to avoid indentation. ::

        使用 shell 时, 可以更方便地手动推入和弹出上下文以避免缩进.

            ctx = app.test_request_context(...)
            ctx.push()
            ...
            ctx.pop()

        Takes the same arguments as Werkzeug's
        :class:`~werkzeug.test.EnvironBuilder`, with some defaults from
        the application. See the linked Werkzeug docs for most of the
        available arguments. Flask-specific behavior is listed here.

        和 Werkzeug 的 `werkzeug.test.EnvironBuilder` 类使用相同的参数, 也使用
        一些来自应用的默认值. 查看关联的 Werkzeug 文档了解大部分可用参数.
        Flask 特定的行为列举如下.

        :param path: URL path being requested.
        参数 path: 请求的 URL 路径.

        :param base_url: Base URL where the app is being served, which
            ``path`` is relative to. If not given, built from
            :data:`PREFERRED_URL_SCHEME`, ``subdomain``,
            :data:`SERVER_NAME`, and :data:`APPLICATION_ROOT`.
        参数 base_url: 此应用服务的基础 URL, `path` 为其相对地址. 若未给出, 使用
            `PREFERRED_URL_SCHEME`, `subdomain`, `SERVER_NAME` 和 `APPLICATION_ROOT`
            进行构建

        :param subdomain: Subdomain name to append to
            :data:`SERVER_NAME`.
        参数 subdomain: 附加到 `SERVER_NAME` 的子域名.

        :param url_scheme: Scheme to use instead of
            :data:`PREFERRED_URL_SCHEME`.
        参数 url_scheme: 优先于 `PREFERRED_URL_SCHEME` 使用的 scheme.

        :param data: The request body, either as a string or a dict of
            form keys and values.
        参数 data: 请求体, 字符串或表单键值对组成的字典.

        :param json: If given, this is serialized as JSON and passed as
            ``data``. Also defaults ``content_type`` to
            ``application/json``.
        参数 json: 如果给定此参数, 序列化为 JSON 作为 `data`, 同时请求头的
            `content_type` 默认为 `application/json`.

        :param args: other positional arguments passed to
            :class:`~werkzeug.test.EnvironBuilder`.
        参数 args: 传入 `werkzeug.test.EnvironBuilder` 的其他位置参数.

        :param kwargs: other keyword arguments passed to
            :class:`~werkzeug.test.EnvironBuilder`.
        参数 kwargs: 传入 `werkzeug.test.EnvironBuilder` 的其他关键字参数.
        """
        from .testing import EnvironBuilder

        builder = EnvironBuilder(self, *args, **kwargs)

        try:
            return self.request_context(builder.get_environ())
        finally:
            builder.close()

    def wsgi_app(self, environ, start_response):
        """The actual WSGI application. This is not implemented in
        :meth:`__call__` so that middlewares can be applied without
        losing a reference to the app object. Instead of doing this::

        真正的 WSGI 应用. 未在 `__call__` 方法中实现, 因此可以在不丢失
        应用对象引用的情况下使用中间件. 而不是这样使用:

            app = MyMiddleware(app)

        It's a better idea to do this instead::
        更好的使用方式如下:

            app.wsgi_app = MyMiddleware(app.wsgi_app)

        Then you still have the original application object around and
        can continue to call methods on it.

        然后你依旧持有原来的应用对象, 可以继续在其上调用方法.

        .. versionchanged:: 0.7
            Teardown events for the request and app contexts are called
            even if an unhandled error occurs. Other events may not be
            called depending on when an error occurs during dispatch.
            See :ref:`callbacks-and-errors`.

        :param environ: A WSGI environment.
        参数 environ: WSGI 环境.

        :param start_response: A callable accepting a status code,
            a list of headers, and an optional exception context to
            start the response.
        参数 start_response: 一个可调用的函数, 接收状态码, headers 列表, 和
            可选的异常上下文来开始响应.
        """
        ctx = self.request_context(environ)
        error = None
        try:
            try:
                ctx.push()
                response = self.full_dispatch_request()
            except Exception as e:
                error = e
                response = self.handle_exception(e)
            except:  # noqa: B001
                error = sys.exc_info()[1]
                raise
            return response(environ, start_response)
        finally:
            if self.should_ignore_error(error):
                error = None
            ctx.auto_pop(error)

    def __call__(self, environ, start_response):
        """The WSGI server calls the Flask application object as the
        WSGI application. This calls :meth:`wsgi_app` which can be
        wrapped to applying middleware.

        WSGI 服务器调用 Flask 应用对象作为 WSGI 应用. 调用了 `wsgi` 方法,
        可以由中间件包裹.

        """
        return self.wsgi_app(environ, start_response)

    def __repr__(self):
        return "<%s %r>" % (self.__class__.__name__, self.name)
