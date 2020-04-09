# -*- coding: utf-8 -*-
"""
    flask.wrappers
    ~~~~~~~~~~~~~~

    Implements the WSGI wrappers (request and response).

    实现 WSGI 包装器 (请求和响应)

    :copyright: 2010 Pallets
    :license: BSD-3-Clause
"""
from werkzeug.exceptions import BadRequest
from werkzeug.wrappers import Request as RequestBase
from werkzeug.wrappers import Response as ResponseBase
from werkzeug.wrappers.json import JSONMixin as _JSONMixin

from . import json
from .globals import current_app


class JSONMixin(_JSONMixin):
    json_module = json

    def on_json_loading_failed(self, e):
        if current_app and current_app.debug:
            raise BadRequest("Failed to decode JSON object: {0}".format(e))

        raise BadRequest()


class Request(RequestBase, JSONMixin):
    """The request object used by default in Flask.  Remembers the
    matched endpoint and view arguments.

    Flask 默认使用的请求对象. 记录匹配的 endpoint 和视图参数.

    It is what ends up as :class:`~flask.request`.  If you want to replace
    the request object used you can subclass this and set
    :attr:`~flask.Flask.request_class` to your subclass.

    `flask.request` 以此结束. 如果你想替换请求对象, 可以继承此类并将
    `flask.Flask.request_class` 设为你编写的子类.

    The request object is a :class:`~werkzeug.wrappers.Request` subclass and
    provides all of the attributes Werkzeug defines plus a few Flask
    specific ones.

    请求对象是 `werkzeug.wrappers.Request` 这个类的子类, 提供所有 Werkzeug 定义的属性
    和一些 Flask 特性的属性.
    """

    #: The internal URL rule that matched the request.  This can be
    #: useful to inspect which methods are allowed for the URL from
    #: a before/after handler (``request.url_rule.methods``) etc.
    #: Though if the request's method was invalid for the URL rule,
    #: the valid list is available in ``routing_exception.valid_methods``
    #: instead (an attribute of the Werkzeug exception
    #: :exc:`~werkzeug.exceptions.MethodNotAllowed`)
    #: because the request was never internally bound.
    #
    # 匹配此请求的内部 URL 规则. 在检查请求前/请求后的 handler (`request.url_rule.methods`)
    # 等中允许使用 URL 的方法很有用. 虽然如果请求的方法对这个 URL 规则无效, 可用方法列表
    # 可使用 `routing_exception.valid_methods` (Werkzeug 异常
    # `werkzeug.exceptions.MethodNotAllowed` 的一个属性)访问. 因为请求从不内部绑定.
    #:
    #: .. versionadded:: 0.6
    url_rule = None

    #: A dict of view arguments that matched the request.  If an exception
    #: happened when matching, this will be ``None``.
    #
    # 匹配这个请求的视图参数字典. 若匹配时发生异常则为 `None`.
    view_args = None

    #: If matching the URL failed, this is the exception that will be
    #: raised / was raised as part of the request handling.  This is
    #: usually a :exc:`~werkzeug.exceptions.NotFound` exception or
    #: something similar.
    #
    # 若匹配 URL 失败, 这就是要作为请求处理一部分的抛出的异常. 通常是
    # `werkzeug.exceptions.NotFound` 或类似的异常.
    routing_exception = None

    @property
    def max_content_length(self):
        """Read-only view of the ``MAX_CONTENT_LENGTH`` config key.

        `MAX_CONTENT_LENGTH` 配置项的只读视图.
        """
        if current_app:
            return current_app.config["MAX_CONTENT_LENGTH"]

    @property
    def endpoint(self):
        """The endpoint that matched the request.  This in combination with
        :attr:`view_args` can be used to reconstruct the same or a
        modified URL.  If an exception happened when matching, this will
        be ``None``.

        匹配请求的 endpoint. 这与 `view_args` 属性可被用于重新创建一致或更改的 URL.
        若匹配时发生异常则为 `None`.
        """
        if self.url_rule is not None:
            return self.url_rule.endpoint

    @property
    def blueprint(self):
        """The name of the current blueprint

        当前蓝图的名称
        """
        if self.url_rule and "." in self.url_rule.endpoint:
            return self.url_rule.endpoint.rsplit(".", 1)[0]

    def _load_form_data(self):
        RequestBase._load_form_data(self)

        # In debug mode we're replacing the files multidict with an ad-hoc
        # subclass that raises a different error for key errors.
        #
        # debug 模式下我们使用一个临时子类替换文件 multidict.
        # 该子类会为键错误抛出不同的错误.
        if (
            current_app
            and current_app.debug
            and self.mimetype != "multipart/form-data"
            and not self.files
        ):
            from .debughelpers import attach_enctype_error_multidict

            attach_enctype_error_multidict(self)


class Response(ResponseBase, JSONMixin):
    """The response object that is used by default in Flask.  Works like the
    response object from Werkzeug but is set to have an HTML mimetype by
    default.  Quite often you don't have to create this object yourself because
    :meth:`~flask.Flask.make_response` will take care of that for you.

    FLask 默认使用的响应对象. 和 Werkzeug 的响应对象行为类似, 但将默认 mimetype 设为 HTML.
    你通常不必自行创建此对象, 因为 `flask.Flask.make_response` 方法将为你创建.

    If you want to replace the response object used you can subclass this and
    set :attr:`~flask.Flask.response_class` to your subclass.

    如果你想替换响应对象, 可以继承此类并将 `flask.Flask.response_class` 设为你编写的子类.



    .. versionchanged:: 1.0
        JSON support is added to the response, like the request. This is useful
        when testing to get the test client response data as JSON.

    .. versionchanged:: 1.0

        Added :attr:`max_cookie_size`.
    """

    default_mimetype = "text/html"

    def _get_data_for_json(self, cache):
        return self.get_data()

    @property
    def max_cookie_size(self):
        """Read-only view of the :data:`MAX_COOKIE_SIZE` config key.

        `MAX_COOKIE_SIZE` 配置项的只读视图.

        See :attr:`~werkzeug.wrappers.BaseResponse.max_cookie_size` in
        Werkzeug's docs.

        参见 Werkzeug 文档的 `werkzeug.wrappers.BaseResponse.max_cookie_size` 属性.
        """
        if current_app:
            return current_app.config["MAX_COOKIE_SIZE"]

        # return Werkzeug's default when not in an app context
        # 不在应用上下文中时返回 Werkzeug 默认值.
        return super(Response, self).max_cookie_size
