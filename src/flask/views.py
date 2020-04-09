# -*- coding: utf-8 -*-
"""
    flask.views
    ~~~~~~~~~~~

    This module provides class-based views inspired by the ones in Django.

    此模块提供基于类的视图, 灵感来自 Django.

    :copyright: 2010 Pallets
    :license: BSD-3-Clause
"""
from ._compat import with_metaclass
from .globals import request


http_method_funcs = frozenset(
    ["get", "post", "head", "options", "delete", "put", "trace", "patch"]
)


class View(object):
    """Alternative way to use view functions.  A subclass has to implement
    :meth:`dispatch_request` which is called with the view arguments from
    the URL routing system.  If :attr:`methods` is provided the methods
    do not have to be passed to the :meth:`~flask.Flask.add_url_rule`
    method explicitly::

    使用视图函数的可选方式. 子类需实现 `dispatch_request` 方法. URL 路由系统会传入
    视图参数调用此方法. 如果提供了 `methods` 属性, 则请求方法不会显式传递给
    `flask.Flask.add_url_rule` 方法:

        class MyView(View):
            methods = ['GET']

            def dispatch_request(self, name):
                return 'Hello %s!' % name

        app.add_url_rule('/hello/<name>', view_func=MyView.as_view('myview'))

    When you want to decorate a pluggable view you will have to either do that
    when the view function is created (by wrapping the return value of
    :meth:`as_view`) or you can use the :attr:`decorators` attribute::

    当你想装饰一个可插拔的视图时, 你需要在视图函数创建时(通过包装 `as_view` 方法的返回值)或
    使用 `decorators` 属性:

        class SecretView(View):
            methods = ['GET']
            decorators = [superuser_required]

            def dispatch_request(self):
                ...

    The decorators stored in the decorators list are applied one after another
    when the view function is created.  Note that you can *not* use the class
    based decorators since those would decorate the view class and not the
    generated view function!

    存储在装饰器列表中的装饰器在视图函数创建后会按先后顺序进行应用. 注意你不可用使用类装饰器,
    因为是用于装饰视图类而不是视图函数的.
    """

    #: A list of methods this view can handle.
    # 这个视图可以处理的请求方法.
    methods = None

    #: Setting this disables or force-enables the automatic options handling.
    # 设置此选项用于禁用或强制启用自动选项处理.
    provide_automatic_options = None

    #: The canonical way to decorate class-based views is to decorate the
    #: return value of as_view().  However since this moves parts of the
    #: logic from the class declaration to the place where it's hooked
    #: into the routing system.
    #
    # 装饰基于类的视图的规范方法是装饰 `as_view()` 的返回值. 但这样会将一部分逻辑
    # 从类的声明移到挂接到路由系统的地方.
    #:
    #: You can place one or more decorators in this list and whenever the
    #: view function is created the result is automatically decorated.
    #
    # 你可以在这个列表中放置一到多个装饰器, 当视图函数创建时, 会自动装饰结果.
    #:
    #: .. versionadded:: 0.8
    decorators = ()

    def dispatch_request(self):
        """Subclasses have to override this method to implement the
        actual view function code.  This method is called with all
        the arguments from the URL rule.

        子类必须重写此方法实现真正的路由函数代码. 这个方法使用 URL 规则所有的参数调用.
        """
        raise NotImplementedError()

    @classmethod
    def as_view(cls, name, *class_args, **class_kwargs):
        """Converts the class into an actual view function that can be used
        with the routing system.  Internally this generates a function on the
        fly which will instantiate the :class:`View` on each request and call
        the :meth:`dispatch_request` method on it.

        将类转化成路由系统可以使用的真正的视图函数. 内部会动态生成一个函数, 在每个请求上
        实例化 View 并调用其 `dispatch_request` 方法.

        The arguments passed to :meth:`as_view` are forwarded to the
        constructor of the class.

        传递给 `as_view` 方法的参数将转发给类的构造函数.

        """

        def view(*args, **kwargs):
            self = view.view_class(*class_args, **class_kwargs)
            return self.dispatch_request(*args, **kwargs)

        if cls.decorators:
            view.__name__ = name
            view.__module__ = cls.__module__
            for decorator in cls.decorators:
                view = decorator(view)

        # We attach the view class to the view function for two reasons:
        # first of all it allows us to easily figure out what class-based
        # view this thing came from, secondly it's also used for instantiating
        # the view class so you can actually replace it with something else
        # for testing purposes and debugging.
        #
        # 我们把视图类附加到视图函数有两个原因: 首先我们可以很容易地弄清楚这个是从
        # 什么样的基于类的视图转化而来的, 然后也用于实例化视图类, 所以你可以在测试或调试
        # 的时候使用其他的类进行替换.
        view.view_class = cls
        view.__name__ = name
        view.__doc__ = cls.__doc__
        view.__module__ = cls.__module__
        view.methods = cls.methods
        view.provide_automatic_options = cls.provide_automatic_options
        return view


class MethodViewType(type):
    """Metaclass for :class:`MethodView` that determines what methods the view
    defines.

    `MethodView` 的元类, 指定视图定义了什么请求方法.
    """

    def __init__(cls, name, bases, d):
        super(MethodViewType, cls).__init__(name, bases, d)

        if "methods" not in d:
            methods = set()

            for base in bases:
                if getattr(base, "methods", None):
                    methods.update(base.methods)

            for key in http_method_funcs:
                if hasattr(cls, key):
                    methods.add(key.upper())

            # If we have no method at all in there we don't want to add a
            # method list. This is for instance the case for the base class
            # or another subclass of a base method view that does not introduce
            # new methods.
            #
            # 如果这里没有任何请求方法, 我们不想添加一个请求方法列表. 例如, 对于不引入
            # 新方法的基本方法视图的基类或另一个子类, 就是这种情况.
            if methods:
                cls.methods = methods


class MethodView(with_metaclass(MethodViewType, View)):
    """A class-based view that dispatches request methods to the corresponding
    class methods. For example, if you implement a ``get`` method, it will be
    used to handle ``GET`` requests. ::

    一个基于类的视图, 分发请求方法到相关的类方法中. 例如, 如果你实现一个 `get` 方法, 这个方法
    将用于处理 `GET` 请求:

        class CounterAPI(MethodView):
            def get(self):
                return session.get('counter', 0)

            def post(self):
                session['counter'] = session.get('counter', 0) + 1
                return 'OK'

        app.add_url_rule('/counter', view_func=CounterAPI.as_view('counter'))
    """

    def dispatch_request(self, *args, **kwargs):
        meth = getattr(self, request.method.lower(), None)

        # If the request method is HEAD and we don't have a handler for it
        # retry with GET.
        #
        # 如果请求方法是 HEAD, 无需进行处理, 会使用 GET 重试.
        if meth is None and request.method == "HEAD":
            meth = getattr(self, "get", None)

        assert meth is not None, "Unimplemented method %r" % request.method
        return meth(*args, **kwargs)
