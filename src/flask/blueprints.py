# -*- coding: utf-8 -*-
"""
    flask.blueprints
    ~~~~~~~~~~~~~~~~

    Blueprints are the recommended way to implement larger or more
    pluggable applications in Flask 0.7 and later.

    Flask 0.7 及之后的版本, 推荐使用蓝图实现更大或更易可插拔的应用.

    :copyright: 2010 Pallets
    :license: BSD-3-Clause
"""
from functools import update_wrapper

from .helpers import _endpoint_from_view_func
from .helpers import _PackageBoundObject

# a singleton sentinel value for parameter defaults
# 一个单例标志, 用于默认参数
_sentinel = object()


class BlueprintSetupState(object):
    """Temporary holder object for registering a blueprint with the
    application.  An instance of this class is created by the
    :meth:`~flask.Blueprint.make_setup_state` method and later passed
    to all register callback functions.

    注册蓝图到应用时的临时持有对象. `flask.Blueprint.make_setup_state` 方法
    创建这个类的一个实例, 随后传递至所有的注册回调函数.
    """

    def __init__(self, blueprint, app, options, first_registration):
        #: a reference to the current application
        #
        # 指向当前应用
        self.app = app

        #: a reference to the blueprint that created this setup state.
        #
        # 指向创建此实例的蓝图
        self.blueprint = blueprint

        #: a dictionary with all options that were passed to the
        #: :meth:`~flask.Flask.register_blueprint` method.
        #
        # 存放所有传递至 `flask.Flask.register_blueprint` 方法的参数字典
        self.options = options

        #: as blueprints can be registered multiple times with the
        #: application and not everything wants to be registered
        #: multiple times on it, this attribute can be used to figure
        #: out if the blueprint was registered in the past already.
        #
        # 由于蓝图可以多次注册到应用, 但不是所有都需要多次注册, 此属性可以用于
        # 确认此蓝图是否已经注册过
        self.first_registration = first_registration

        subdomain = self.options.get("subdomain")
        if subdomain is None:
            subdomain = self.blueprint.subdomain

        #: The subdomain that the blueprint should be active for, ``None``
        #: otherwise.
        #
        # 此蓝图使用的子域名, 没有则为 None
        self.subdomain = subdomain

        url_prefix = self.options.get("url_prefix")
        if url_prefix is None:
            url_prefix = self.blueprint.url_prefix
        #: The prefix that should be used for all URLs defined on the
        #: blueprint.
        #
        # 蓝图定义的需要应用于所有 URL 的前缀
        self.url_prefix = url_prefix

        #: A dictionary with URL defaults that is added to each and every
        #: URL that was defined with the blueprint.
        #
        # 存放 URL 默认配置的字典, 将被添加到蓝图定义的每个 URL 中.
        self.url_defaults = dict(self.blueprint.url_values_defaults)
        self.url_defaults.update(self.options.get("url_defaults", ()))

    def add_url_rule(self, rule, endpoint=None, view_func=None, **options):
        """A helper method to register a rule (and optionally a view function)
        to the application.  The endpoint is automatically prefixed with the
        blueprint's name.

        注册一个规则(或视图函数)到应用的辅助方法. 自动使用蓝图的名称作为端点前缀.
        """
        if self.url_prefix is not None:
            if rule:
                rule = "/".join((self.url_prefix.rstrip("/"), rule.lstrip("/")))
            else:
                rule = self.url_prefix
        options.setdefault("subdomain", self.subdomain)
        if endpoint is None:
            endpoint = _endpoint_from_view_func(view_func)
        defaults = self.url_defaults
        if "defaults" in options:
            defaults = dict(defaults, **options.pop("defaults"))
        self.app.add_url_rule(
            rule,
            "%s.%s" % (self.blueprint.name, endpoint),
            view_func,
            defaults=defaults,
            **options
        )


class Blueprint(_PackageBoundObject):
    """Represents a blueprint, a collection of routes and other
    app-related functions that can be registered on a real application
    later.

    代表一个蓝图, 一个路由和其他应用相关函数的集合, 可以之后注册到一个真正的应用上.

    A blueprint is an object that allows defining application functions
    without requiring an application object ahead of time. It uses the
    same decorators as :class:`~flask.Flask`, but defers the need for an
    application by recording them for later registration.

    一个蓝图对象允许在没有提前创建应用对象的情况下定义应用函数. 蓝图对象使用和 `flask.Flask`
    类一致的装饰器, 但通过记录它们用于之后注册来推迟了对应用的要求.

    Decorating a function with a blueprint creates a deferred function
    that is called with :class:`~flask.blueprints.BlueprintSetupState`
    when the blueprint is registered on an application.

    使用蓝图装饰一个函数创建了一个延迟的函数, 在蓝图注册到应用时, 由
    `flask.blueprints.BlueprintSetupState` 调用.

    See :ref:`blueprints` for more information.
    查看蓝图文档以获取更多信息

    .. versionchanged:: 1.1.0
        Blueprints have a ``cli`` group to register nested CLI commands.
        The ``cli_group`` parameter controls the name of the group under
        the ``flask`` command.

    .. versionadded:: 0.7

    :param name: The name of the blueprint. Will be prepended to each
        endpoint name.
    参数 name: 蓝图名称, 作为每个端点的名称前缀

    :param import_name: The name of the blueprint package, usually
        ``__name__``. This helps locate the ``root_path`` for the
        blueprint.
    参数 import_name: 蓝图包名, 通常使用 `__name__`, 用于定位此蓝图的 `root_path`

    :param static_folder: A folder with static files that should be
        served by the blueprint's static route. The path is relative to
        the blueprint's root path. Blueprint static files are disabled
        by default.
    参数 static_folder: 放置静态文件的文件夹, 用于蓝图的静态路由. 此路径是此蓝图
        根路径的相对路径. 蓝图静态文件默认禁用.

    :param static_url_path: The url to serve static files from.
        Defaults to ``static_folder``. If the blueprint does not have
        a ``url_prefix``, the app's static route will take precedence,
        and the blueprint's static files won't be accessible.
    参数 static_url_path: 静态文件的 URL, 默认为 `static_folder`. 如果此蓝图
        没有 `url_prefix`, 将优先使用此应用的静态路由, 此蓝图的静态文件将不可访问.

    :param template_folder: A folder with templates that should be added
        to the app's template search path. The path is relative to the
        blueprint's root path. Blueprint templates are disabled by
        default. Blueprint templates have a lower precedence than those
        in the app's templates folder.
    参数 template_folder: 应当加入应用模板搜索路径的模板文件夹. 此路径是此蓝图
        根路径的相对路径. 蓝图模板默认禁用. 蓝图模板比应用模板文件夹的模板优先级低.

    :param url_prefix: A path to prepend to all of the blueprint's URLs,
        to make them distinct from the rest of the app's routes.
    参数 url_prefix: 作为此蓝图所有 URL 前缀的路径, 用于和此应用的其他路由做区分.

    :param subdomain: A subdomain that blueprint routes will match on by
        default.
    参数 subdomain: 蓝图路由默认匹配的子域名.

    :param url_defaults: A dict of default values that blueprint routes
        will receive by default.
    参数 url_defaults: 蓝图路由默认接收的参数字典.

    :param root_path: By default, the blueprint will automatically this
        based on ``import_name``. In certain situations this automatic
        detection can fail, so the path can be specified manually
        instead.
    参数 root_path: 默认情况下, 此蓝图将自动使用 `import_name` 指定的路径.
        在某些情况下, 自动检测会失败, 此时可手动指定.
    """

    warn_on_modifications = False
    _got_registered_once = False

    #: Blueprint local JSON decoder class to use.
    #: Set to ``None`` to use the app's :class:`~flask.app.Flask.json_encoder`.
    #
    # 蓝图本地使用的 JSON 编码器类. (注: 原文中的 decoder 应当是文档编写错误)
    # 设为 None 使用应用的 `flask.app.Flask.json_encoder`.
    json_encoder = None
    #: Blueprint local JSON decoder class to use.
    #: Set to ``None`` to use the app's :class:`~flask.app.Flask.json_decoder`.
    # 蓝图本地使用的 JSON 解码器类.
    # 设为 None 使用应用的 `flask.app.Flask.json_decoder`.
    json_decoder = None

    # TODO remove the next three attrs when Sphinx :inherited-members: works
    # https://github.com/sphinx-doc/sphinx/issues/741

    #: The name of the package or module that this app belongs to. Do not
    #: change this once it is set by the constructor.
    #
    # 蓝图包或模块的名字(注: 原文中的 app 应当是文档编写错误), 一旦构造函数设定了此值, 请不要修改.
    import_name = None

    #: Location of the template files to be added to the template lookup.
    #: ``None`` if templates should not be added.
    #
    # 加入模板搜索路径的模板文件位置. 设为 None 则不添加.
    template_folder = None

    #: Absolute path to the package on the filesystem. Used to look up
    #: resources contained in the package.
    #
    # 文件系统中此包的绝对路径. 用于搜索此包中包含的资源.
    root_path = None

    def __init__(
        self,
        name,
        import_name,
        static_folder=None,
        static_url_path=None,
        template_folder=None,
        url_prefix=None,
        subdomain=None,
        url_defaults=None,
        root_path=None,
        cli_group=_sentinel,
    ):
        _PackageBoundObject.__init__(
            self, import_name, template_folder, root_path=root_path
        )
        self.name = name
        self.url_prefix = url_prefix
        self.subdomain = subdomain
        self.static_folder = static_folder
        self.static_url_path = static_url_path
        self.deferred_functions = []
        if url_defaults is None:
            url_defaults = {}
        self.url_values_defaults = url_defaults
        self.cli_group = cli_group

    def record(self, func):
        """Registers a function that is called when the blueprint is
        registered on the application.  This function is called with the
        state as argument as returned by the :meth:`make_setup_state`
        method.

        蓝图注册到应用时调用此函数注册一个函数. 调用此函数时使用 `make_setup_state`
        方法返回的状态作为参数.
        """
        if self._got_registered_once and self.warn_on_modifications:
            from warnings import warn

            warn(
                Warning(
                    "The blueprint was already registered once "
                    "but is getting modified now.  These changes "
                    "will not show up."
                )
            )
        self.deferred_functions.append(func)

    def record_once(self, func):
        """Works like :meth:`record` but wraps the function in another
        function that will ensure the function is only called once.  If the
        blueprint is registered a second time on the application, the
        function passed is not called.

        类似 `record` 方法, 但使用另一个函数包裹此函数, 保证此函数只调用一次.
        如果蓝图多次注册到应用, 传入的函数不会调用.
        """

        def wrapper(state):
            if state.first_registration:
                func(state)

        return self.record(update_wrapper(wrapper, func))

    def make_setup_state(self, app, options, first_registration=False):
        """Creates an instance of :meth:`~flask.blueprints.BlueprintSetupState`
        object that is later passed to the register callback functions.
        Subclasses can override this to return a subclass of the setup state.

        创建一个 `flask.blueprints.BlueprintSetupState` 实例用于之后传递至注册回调函数.
        子类可重写此函数返回一个子类的示例.
        """
        return BlueprintSetupState(self, app, options, first_registration)

    def register(self, app, options, first_registration=False):
        """Called by :meth:`Flask.register_blueprint` to register all views
        and callbacks registered on the blueprint with the application. Creates
        a :class:`.BlueprintSetupState` and calls each :meth:`record` callback
        with it.

        由 `Flask.register_blueprint` 调用, 注册所有的视图和回调. 创建一个
        `BlueprintSetupState` 的实例并用它调用每个 `record` 方法.

        :param app: The application this blueprint is being registered with.
        参数 app: 此蓝图注册到的 app

        :param options: Keyword arguments forwarded from
            :meth:`~Flask.register_blueprint`.
        参数 options: 转发自 `Flask.register_blueprint` 的关键字参数

        :param first_registration: Whether this is the first time this
            blueprint has been registered on the application.
        参数 first_registration: 此蓝图是否第一次注册到此应用
        """
        self._got_registered_once = True
        state = self.make_setup_state(app, options, first_registration)

        if self.has_static_folder:
            state.add_url_rule(
                self.static_url_path + "/<path:filename>",
                view_func=self.send_static_file,
                endpoint="static",
            )

        for deferred in self.deferred_functions:
            deferred(state)

        cli_resolved_group = options.get("cli_group", self.cli_group)

        if not self.cli.commands:
            return

        if cli_resolved_group is None:
            app.cli.commands.update(self.cli.commands)
        elif cli_resolved_group is _sentinel:
            self.cli.name = self.name
            app.cli.add_command(self.cli)
        else:
            self.cli.name = cli_resolved_group
            app.cli.add_command(self.cli)

    def route(self, rule, **options):
        """Like :meth:`Flask.route` but for a blueprint.  The endpoint for the
        :func:`url_for` function is prefixed with the name of the blueprint.

        类似 `Flask.route` 但是用于蓝图. `url_for` 函数的端点使用蓝图名称作为前缀.
        """

        def decorator(f):
            endpoint = options.pop("endpoint", f.__name__)
            self.add_url_rule(rule, endpoint, f, **options)
            return f

        return decorator

    def add_url_rule(self, rule, endpoint=None, view_func=None, **options):
        """Like :meth:`Flask.add_url_rule` but for a blueprint.  The endpoint for
        the :func:`url_for` function is prefixed with the name of the blueprint.

        类似 `Flask.add_url_rule` 但是用于蓝图. `url_for` 函数的端点使用蓝图名称作为前缀.
        """
        if endpoint:
            assert "." not in endpoint, "Blueprint endpoints should not contain dots"
        if view_func and hasattr(view_func, "__name__"):
            assert (
                "." not in view_func.__name__
            ), "Blueprint view function name should not contain dots"
        self.record(lambda s: s.add_url_rule(rule, endpoint, view_func, **options))

    def endpoint(self, endpoint):
        """Like :meth:`Flask.endpoint` but for a blueprint.  This does not
        prefix the endpoint with the blueprint name, this has to be done
        explicitly by the user of this method.  If the endpoint is prefixed
        with a `.` it will be registered to the current blueprint, otherwise
        it's an application independent endpoint.

        类似 `Flask.endpoint` 但是用于蓝图. 端点不使用蓝图名称作为前缀, 必须由此方法的用户
        显式完成此操作. 如果以点号作为前缀, 将注册到当前蓝图, 否则为应用的独立端点.
        """

        def decorator(f):
            def register_endpoint(state):
                state.app.view_functions[endpoint] = f

            self.record_once(register_endpoint)
            return f

        return decorator

    def app_template_filter(self, name=None):
        """Register a custom template filter, available application wide.  Like
        :meth:`Flask.template_filter` but for a blueprint.

        注册一个自定义模板过滤器, 应用范围内可用. 类似 `Flask.template_filter`
        但是用于蓝图

        :param name: the optional name of the filter, otherwise the
                     function name will be used.
        参数 name: 此过滤器的可选名称, 否则使用函数名称.
        """

        def decorator(f):
            self.add_app_template_filter(f, name=name)
            return f

        return decorator

    def add_app_template_filter(self, f, name=None):
        """Register a custom template filter, available application wide.  Like
        :meth:`Flask.add_template_filter` but for a blueprint.  Works exactly
        like the :meth:`app_template_filter` decorator.

        注册一个自定义模板过滤器, 应用范围内可用. 类似 `Flask.template_filter`
        但是用于蓝图. 和 `app_template_filter` 方法功能一致.


        :param name: the optional name of the filter, otherwise the
                     function name will be used.
        参数 name: 此过滤器的可选名称, 否则使用函数名称.
        """

        def register_template(state):
            state.app.jinja_env.filters[name or f.__name__] = f

        self.record_once(register_template)

    def app_template_test(self, name=None):
        """Register a custom template test, available application wide.  Like
        :meth:`Flask.template_test` but for a blueprint.

        添加一个自定义模板测试, 应用范围内可用. 类似 `Flask.template_test` 但是用于蓝图.

        .. versionadded:: 0.10

        :param name: the optional name of the test, otherwise the
                     function name will be used.
        参数 name: 此测试的可选名称, 否则使用函数名称.
        """

        def decorator(f):
            self.add_app_template_test(f, name=name)
            return f

        return decorator

    def add_app_template_test(self, f, name=None):
        """Register a custom template test, available application wide.  Like
        :meth:`Flask.add_template_test` but for a blueprint.  Works exactly
        like the :meth:`app_template_test` decorator.

        注册一个自定义模板测试, 应用范围内可用. 类似 `Flask.add_template_test` 但是
        用于蓝图. 功能与 `app_template_test` 一致.

        .. versionadded:: 0.10

        :param name: the optional name of the test, otherwise the
                     function name will be used.
        参数 name: 此测试的可选名称, 否则使用函数名称.
        """

        def register_template(state):
            state.app.jinja_env.tests[name or f.__name__] = f

        self.record_once(register_template)

    def app_template_global(self, name=None):
        """Register a custom template global, available application wide.  Like
        :meth:`Flask.template_global` but for a blueprint.

        注册一个自定义模板全局, 应用范围内可用. 类似 `Flask.template_global` 但是用于蓝图.

        .. versionadded:: 0.10

        :param name: the optional name of the global, otherwise the
                     function name will be used.
        参数 name: 此全局的可选名称, 否则使用函数名称.
        """

        def decorator(f):
            self.add_app_template_global(f, name=name)
            return f

        return decorator

    def add_app_template_global(self, f, name=None):
        """Register a custom template global, available application wide.  Like
        :meth:`Flask.add_template_global` but for a blueprint.  Works exactly
        like the :meth:`app_template_global` decorator.

        注册一个自定义模板全局, 应用范围内可用. 类似 `Flask.template_global` 但是用于蓝图.
        功能与 `app_template_global` 一致.

        .. versionadded:: 0.10

        :param name: the optional name of the global, otherwise the
                     function name will be used.
        参数 name: 此全局的可选名称, 否则使用函数名称.
        """

        def register_template(state):
            state.app.jinja_env.globals[name or f.__name__] = f

        self.record_once(register_template)

    def before_request(self, f):
        """Like :meth:`Flask.before_request` but for a blueprint.  This function
        is only executed before each request that is handled by a function of
        that blueprint.

        类似 `Flask.before_request`, 但是用于蓝图. 此函数只在此蓝图处理的每个请求前执行.
        """
        self.record_once(
            lambda s: s.app.before_request_funcs.setdefault(self.name, []).append(f)
        )
        return f

    def before_app_request(self, f):
        """Like :meth:`Flask.before_request`.  Such a function is executed
        before each request, even if outside of a blueprint.

        类似 `Flask.before_request`. 此函数在每个请求前执行, 即使是蓝图外的请求.
        """
        self.record_once(
            lambda s: s.app.before_request_funcs.setdefault(None, []).append(f)
        )
        return f

    def before_app_first_request(self, f):
        """Like :meth:`Flask.before_first_request`.  Such a function is
        executed before the first request to the application.

        类似 `Flask.before_first_request`, 此函数在此应用的第一次请求前执行.
        """
        self.record_once(lambda s: s.app.before_first_request_funcs.append(f))
        return f

    def after_request(self, f):
        """Like :meth:`Flask.after_request` but for a blueprint.  This function
        is only executed after each request that is handled by a function of
        that blueprint.

        类似 `Flask.after_request`, 但是用于蓝图. 此函数只在此蓝图处理的每个请求后执行.
        """
        self.record_once(
            lambda s: s.app.after_request_funcs.setdefault(self.name, []).append(f)
        )
        return f

    def after_app_request(self, f):
        """Like :meth:`Flask.after_request` but for a blueprint.  Such a function
        is executed after each request, even if outside of the blueprint.

        类似 `Flask.after_request`, 但是用于蓝图. 此函数在每个请求后执行, 即使是蓝图外的请求.
        """
        self.record_once(
            lambda s: s.app.after_request_funcs.setdefault(None, []).append(f)
        )
        return f

    def teardown_request(self, f):
        """Like :meth:`Flask.teardown_request` but for a blueprint.  This
        function is only executed when tearing down requests handled by a
        function of that blueprint.  Teardown request functions are executed
        when the request context is popped, even when no actual request was
        performed.

        类似 `Flask.teardown_request`, 但是用于蓝图. 此函数只在此蓝图的请求拆解时执行.
        拆解请求函数是在请求上下文弹出时执行, 即使没有执行任何实际的请求.
        """
        self.record_once(
            lambda s: s.app.teardown_request_funcs.setdefault(self.name, []).append(f)
        )
        return f

    def teardown_app_request(self, f):
        """Like :meth:`Flask.teardown_request` but for a blueprint.  Such a
        function is executed when tearing down each request, even if outside of
        the blueprint.

        类似 `Flask.teardown_request`, 但是用于蓝图. 此函数在每个请求拆解时执行, 即使是
        蓝图外的请求.
        """
        self.record_once(
            lambda s: s.app.teardown_request_funcs.setdefault(None, []).append(f)
        )
        return f

    def context_processor(self, f):
        """Like :meth:`Flask.context_processor` but for a blueprint.  This
        function is only executed for requests handled by a blueprint.

        类似 `Flask.context_processor`, 但是用于蓝图. 此函数只在此蓝图处理请求时执行.
        """
        self.record_once(
            lambda s: s.app.template_context_processors.setdefault(
                self.name, []
            ).append(f)
        )
        return f

    def app_context_processor(self, f):
        """Like :meth:`Flask.context_processor` but for a blueprint.  Such a
        function is executed each request, even if outside of the blueprint.

        类似 `Flask.context_processor`, 但是用于蓝图. 此函数处理每个请求时都执行, 即使是
        蓝图外的请求.
        """
        self.record_once(
            lambda s: s.app.template_context_processors.setdefault(None, []).append(f)
        )
        return f

    def app_errorhandler(self, code):
        """Like :meth:`Flask.errorhandler` but for a blueprint.  This
        handler is used for all requests, even if outside of the blueprint.

        类似 `Flask.errorhandler`, 但是用于蓝图. 此处理器用于所有的请求, 即使是蓝图外的请求.
        """

        def decorator(f):
            self.record_once(lambda s: s.app.errorhandler(code)(f))
            return f

        return decorator

    def url_value_preprocessor(self, f):
        """Registers a function as URL value preprocessor for this
        blueprint.  It's called before the view functions are called and
        can modify the url values provided.

        注册一个函数作为此蓝图的 URL 值处理器. 在视图函数前调用, 并可以修改提供的 URL 值.
        """
        self.record_once(
            lambda s: s.app.url_value_preprocessors.setdefault(self.name, []).append(f)
        )
        return f

    def url_defaults(self, f):
        """Callback function for URL defaults for this blueprint.  It's called
        with the endpoint and values and should update the values passed
        in place.

        此蓝图的 URL 默认值回调函数. 以端点和应该更新的键值对作为参数.
        """
        self.record_once(
            lambda s: s.app.url_default_functions.setdefault(self.name, []).append(f)
        )
        return f

    def app_url_value_preprocessor(self, f):
        """Same as :meth:`url_value_preprocessor` but application wide.

        类似 `url_value_preprocessor` 但用于整个应用.
        """
        self.record_once(
            lambda s: s.app.url_value_preprocessors.setdefault(None, []).append(f)
        )
        return f

    def app_url_defaults(self, f):
        """Same as :meth:`url_defaults` but application wide.

        类似 `url_defaults` 但用于整个应用.
        """
        self.record_once(
            lambda s: s.app.url_default_functions.setdefault(None, []).append(f)
        )
        return f

    def errorhandler(self, code_or_exception):
        """Registers an error handler that becomes active for this blueprint
        only.  Please be aware that routing does not happen local to a
        blueprint so an error handler for 404 usually is not handled by
        a blueprint unless it is caused inside a view function.  Another
        special case is the 500 internal server error which is always looked
        up from the application.

        注册一个用于此蓝图的错误处理器. 请注意路由不在蓝图本地发生, 所以 404 的错误处理器
        通常不会被调用, 除非此错误在视图函数中发生. 另一个特殊情况是
        500 INTERNAL SERVER ERROR, 总是从应用中查找处理器.

        Otherwise works as the :meth:`~flask.Flask.errorhandler` decorator
        of the :class:`~flask.Flask` object.

        其他情况下和 `flask.Flask` 类对象的 `flask.Flask.errorhandler` 装饰器功能一致.
        """

        def decorator(f):
            self.record_once(
                lambda s: s.app._register_error_handler(self.name, code_or_exception, f)
            )
            return f

        return decorator

    def register_error_handler(self, code_or_exception, f):
        """Non-decorator version of the :meth:`errorhandler` error attach
        function, akin to the :meth:`~flask.Flask.register_error_handler`
        application-wide function of the :class:`~flask.Flask` object but
        for error handlers limited to this blueprint.

        非装饰器版本的 `errorhandler` 方法, 类似于 `flask.Flask` 对象的应用范围的
        `flask.Flask.register_error_handler` 方法, 但是只限于处理此蓝图的错误.

        .. versionadded:: 0.11
        """
        self.record_once(
            lambda s: s.app._register_error_handler(self.name, code_or_exception, f)
        )
