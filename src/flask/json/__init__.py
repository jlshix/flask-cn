# -*- coding: utf-8 -*-
"""
flask.json
~~~~~~~~~~

:copyright: 2010 Pallets
:license: BSD-3-Clause
"""
import codecs
import io
import uuid
from datetime import date
from datetime import datetime
# 注: 导入了 itsdangerous 的 json 作为基础.
from itsdangerous import json as _json
from jinja2 import Markup
from werkzeug.http import http_date

from .._compat import PY2
from .._compat import text_type
from ..globals import current_app
from ..globals import request

try:
    # 注: 支持 python 3.7+ 的 数据类.
    # ref: https://docs.python.org/zh-cn/3/library/dataclasses.html
    import dataclasses
except ImportError:
    dataclasses = None

# Figure out if simplejson escapes slashes.  This behavior was changed
# from one version to another without reason.
# 确认 simplejson 是不是跳过了斜线.
# 从一个版本到另一个版本无故发生了这个行为变更.
_slash_escape = "\\/" not in _json.dumps("/")


__all__ = [
    "dump",
    "dumps",
    "load",
    "loads",
    "htmlsafe_dump",
    "htmlsafe_dumps",
    "JSONDecoder",
    "JSONEncoder",
    "jsonify",
]


def _wrap_reader_for_text(fp, encoding):
    if isinstance(fp.read(0), bytes):
        fp = io.TextIOWrapper(io.BufferedReader(fp), encoding)
    return fp


def _wrap_writer_for_text(fp, encoding):
    try:
        fp.write("")
    except TypeError:
        fp = io.TextIOWrapper(fp, encoding)
    return fp


class JSONEncoder(_json.JSONEncoder):
    """The default Flask JSON encoder. This one extends the default
    encoder by also supporting ``datetime``, ``UUID``, ``dataclasses``,
    and ``Markup`` objects.

    flask 默认的 JSON 编码器. 它拓展了 python 自带 json 模块的编码器, 并支持
    `datetime`, `UUID`, `dataclasses` 和 `Markup` 对象.

    ``datetime`` objects are serialized as RFC 822 datetime strings.
    This is the same as the HTTP date format.

    `datetime` 对象的序列化为 RFC 822 标准的 datetime 字符串, 和 HTTP 的时间格式一致.

    In order to support more data types, override the :meth:`default`
    method.

    如果需要支持更多的数据类型, 可重写 `default` 方法.
    """

    def default(self, o):
        """Implement this method in a subclass such that it returns a
        serializable object for ``o``, or calls the base implementation (to
        raise a :exc:`TypeError`).

        在子类中实现这个方法, 返回对象 `o` 序列化后的结果, 或者调用基类的实现
        (抛出 TypeError).

        For example, to support arbitrary iterators, you could implement
        default like this::

        例如, 为了支持任意的迭代器, 你可以这样实现 `default` 方法:

            def default(self, o):
                try:
                    iterable = iter(o)
                except TypeError:
                    pass
                else:
                    return list(iterable)
                return JSONEncoder.default(self, o)
        """
        if isinstance(o, datetime):
            return http_date(o.utctimetuple())
        if isinstance(o, date):
            return http_date(o.timetuple())
        if isinstance(o, uuid.UUID):
            return str(o)
        if dataclasses and dataclasses.is_dataclass(o):
            return dataclasses.asdict(o)
        if hasattr(o, "__html__"):
            return text_type(o.__html__())
        return _json.JSONEncoder.default(self, o)


class JSONDecoder(_json.JSONDecoder):
    """The default JSON decoder.  This one does not change the behavior from
    the default simplejson decoder.  Consult the :mod:`json` documentation
    for more information.  This decoder is not only used for the load
    functions of this module but also :attr:`~flask.Request`.

    flask 默认的 JSON 解码器. 行为和 simplejson 的解码器一致.
    如果想了解更多内容, 可以参考 python 自带 json 模块的文档.
    这个解码器不止用于此模块的加载函数, 也在 flask 的 `Request` 类中使用.
    """


def _dump_arg_defaults(kwargs, app=None):
    """Inject default arguments for dump functions.
    为 dump 函数注入默认参数
    """
    if app is None:
        app = current_app

    if app:
        bp = app.blueprints.get(request.blueprint) if request else None
        kwargs.setdefault(
            "cls", bp.json_encoder if bp and bp.json_encoder else app.json_encoder
        )

        if not app.config["JSON_AS_ASCII"]:
            kwargs.setdefault("ensure_ascii", False)

        kwargs.setdefault("sort_keys", app.config["JSON_SORT_KEYS"])
    else:
        kwargs.setdefault("sort_keys", True)
        kwargs.setdefault("cls", JSONEncoder)


def _load_arg_defaults(kwargs, app=None):
    """Inject default arguments for load functions.
    为 load 函数注入默认参数
    """
    if app is None:
        app = current_app

    if app:
        bp = app.blueprints.get(request.blueprint) if request else None
        kwargs.setdefault(
            "cls", bp.json_decoder if bp and bp.json_decoder else app.json_decoder
        )
    else:
        kwargs.setdefault("cls", JSONDecoder)


def detect_encoding(data):
    """Detect which UTF codec was used to encode the given bytes.

    检查给定的 bytes 是用哪种 UTF 编码得到的.

    The latest JSON standard (:rfc:`8259`) suggests that only UTF-8 is
    accepted. Older documents allowed 8, 16, or 32. 16 and 32 can be big
    or little endian. Some editors or libraries may prepend a BOM.

    最新的 JSON 标准(rfc 8259) 建议只使用 URF-8. 更旧的文档可以使用 8, 16 或 32.
    16 和 32 可能是大端字节序或小端字节序. 一些编辑器和库可能前置一个字节顺序标记.

    :param data: Bytes in unknown UTF encoding.
    参数 data: 未知 UTF 编码的 bytes
    :return: UTF encoding name
    返回: UTF 编码名
    """
    head = data[:4]

    if head[:3] == codecs.BOM_UTF8:
        return "utf-8-sig"

    if b"\x00" not in head:
        return "utf-8"

    if head in (codecs.BOM_UTF32_BE, codecs.BOM_UTF32_LE):
        return "utf-32"

    if head[:2] in (codecs.BOM_UTF16_BE, codecs.BOM_UTF16_LE):
        return "utf-16"

    if len(head) == 4:
        if head[:3] == b"\x00\x00\x00":
            return "utf-32-be"

        if head[::2] == b"\x00\x00":
            return "utf-16-be"

        if head[1:] == b"\x00\x00\x00":
            return "utf-32-le"

        if head[1::2] == b"\x00\x00":
            return "utf-16-le"

    if len(head) == 2:
        return "utf-16-be" if head.startswith(b"\x00") else "utf-16-le"

    return "utf-8"


def dumps(obj, app=None, **kwargs):
    """Serialize ``obj`` to a JSON-formatted string. If there is an
    app context pushed, use the current app's configured encoder
    (:attr:`~flask.Flask.json_encoder`), or fall back to the default
    :class:`JSONEncoder`.

    序列化 `obj` 为一个 json 格式字符串. 如果指定了应用上下文, 使用当前应用配置的
    编码器(Flask.json_encoder), 否则使用默认的编码器(JSONEncoder).

    Takes the same arguments as the built-in :func:`json.dumps`, and
    does some extra configuration based on the application. If the
    simplejson package is installed, it is preferred.

    接收的参数和内置 json 的 dumps 函数一致. 基于 app 做了一些额外的配置.
    如果安装了 simplejson, 优先使用 simplejson.

    :param obj: Object to serialize to JSON.
    参数 obj: 用于序列化的对象.

    :param app: App instance to use to configure the JSON encoder.
        Uses ``current_app`` if not given, and falls back to the default
        encoder when not in an app context.
    参数 app: app 实例, 用于配置 JSON 编码器. 若未指定, 使用 `current_app`,
        如果没有应用上下文, 使用默认的编码器.

    :param kwargs: Extra arguments passed to :func:`json.dumps`.
    参数 kwargs: 额外的参数, 和 json.dumps 一致.

    .. versionchanged:: 1.0.3

        ``app`` can be passed directly, rather than requiring an app
        context for configuration.
    """
    _dump_arg_defaults(kwargs, app=app)
    encoding = kwargs.pop("encoding", None)
    rv = _json.dumps(obj, **kwargs)
    if encoding is not None and isinstance(rv, text_type):
        rv = rv.encode(encoding)
    return rv


def dump(obj, fp, app=None, **kwargs):
    """Like :func:`dumps` but writes into a file object.
    和 dumps 类似, 但是把结果写入文件对象.
    """
    _dump_arg_defaults(kwargs, app=app)
    encoding = kwargs.pop("encoding", None)
    if encoding is not None:
        fp = _wrap_writer_for_text(fp, encoding)
    _json.dump(obj, fp, **kwargs)


def loads(s, app=None, **kwargs):
    """Deserialize an object from a JSON-formatted string ``s``. If
    there is an app context pushed, use the current app's configured
    decoder (:attr:`~flask.Flask.json_decoder`), or fall back to the
    default :class:`JSONDecoder`.

    从一个 json 格式字符串 `s` 反序列化得到一个对象.
    如果指定了应用上下文, 使用当前应用配置的解码器(Flask.json_decoder),
    否则使用默认的解码器(JSONDecoder).

    Takes the same arguments as the built-in :func:`json.loads`, and
    does some extra configuration based on the application. If the
    simplejson package is installed, it is preferred.

    接收的参数和内置 json 的 loads 函数一致. 基于 app 做了一些额外的配置.
    如果安装了 simplejson, 优先使用 simplejson.


    :param s: JSON string to deserialize.
    参数 s: 用于反序列化的 json 字符串.
    :param app: App instance to use to configure the JSON decoder.
        Uses ``current_app`` if not given, and falls back to the default
        encoder when not in an app context.
    参数 app: app 实例, 用于配置 JSON 解码器. 若未指定, 使用 `current_app`,
        如果没有应用上下文, 使用默认的编码器(注: 原文中的 encoder 应当是文档编写错误).

    :param kwargs: Extra arguments passed to :func:`json.dumps`.
    参数 kwargs: 额外的参数, 和 json.loads 一致(注: 原文中的 dumps 应当是文档编写错误).

    .. versionchanged:: 1.0.3

        ``app`` can be passed directly, rather than requiring an app
        context for configuration.
    """
    _load_arg_defaults(kwargs, app=app)
    if isinstance(s, bytes):
        encoding = kwargs.pop("encoding", None)
        if encoding is None:
            encoding = detect_encoding(s)
        s = s.decode(encoding)
    return _json.loads(s, **kwargs)


def load(fp, app=None, **kwargs):
    """Like :func:`loads` but reads from a file object.
    和 loads 类似, 但是是从文件中读取输入.
    """
    _load_arg_defaults(kwargs, app=app)
    if not PY2:
        fp = _wrap_reader_for_text(fp, kwargs.pop("encoding", None) or "utf-8")
    return _json.load(fp, **kwargs)


def htmlsafe_dumps(obj, **kwargs):
    """Works exactly like :func:`dumps` but is safe for use in ``<script>``
    tags.  It accepts the same arguments and returns a JSON string.  Note that
    this is available in templates through the ``|tojson`` filter which will
    also mark the result as safe.  Due to how this function escapes certain
    characters this is safe even if used outside of ``<script>`` tags.

    和 dumps 的作用类似, 可以在 `<script>` 标签中安全使用.
    和 dumps 接收的参数一致, 返回一个 json 格式的字符串.
    需要注意的是, 这个函数可以在模板以 `|tojson` 过滤器的方式使用, 也会同时将输出结果
    标记为安全. 由于此函数跳过某些特定字符的实现机制, 也可以在 `<script>` 标签外使用.

    The following characters are escaped in strings:
    在字符串中以下字符会被跳过

    -   ``<``
    -   ``>``
    -   ``&``
    -   ``'``

    This makes it safe to embed such strings in any place in HTML with the
    notable exception of double quoted attributes.  In that case single
    quote your attributes or HTML escape it in addition.
    这样可以将用双括号包含的属性安全嵌入这些字符串到 HTML 的任何位置, 出现异常也可以发现.
    那样的话, 可以使用单括号包含属性, 或者在 HTML 中避开.


    .. versionchanged:: 0.10
       This function's return value is now always safe for HTML usage, even
       if outside of script tags or if used in XHTML.  This rule does not
       hold true when using this function in HTML attributes that are double
       quoted.  Always single quote attributes if you use the ``|tojson``
       filter.  Alternatively use ``|tojson|forceescape``.
    """
    rv = (
        dumps(obj, **kwargs)
        .replace(u"<", u"\\u003c")
        .replace(u">", u"\\u003e")
        .replace(u"&", u"\\u0026")
        .replace(u"'", u"\\u0027")
    )
    if not _slash_escape:
        rv = rv.replace("\\/", "/")
    return rv


def htmlsafe_dump(obj, fp, **kwargs):
    """Like :func:`htmlsafe_dumps` but writes into a file object.
    类似于 htmlsafe_dumps, 但是把结果写入文件对象.
    """
    fp.write(text_type(htmlsafe_dumps(obj, **kwargs)))


def jsonify(*args, **kwargs):
    """This function wraps :func:`dumps` to add a few enhancements that make
    life easier.  It turns the JSON output into a :class:`~flask.Response`
    object with the :mimetype:`application/json` mimetype.  For convenience, it
    also converts multiple arguments into an array or multiple keyword arguments
    into a dict.  This means that both ``jsonify(1,2,3)`` and
    ``jsonify([1,2,3])`` serialize to ``[1,2,3]``.

    这个函数基于 dumps 做了一些增强, 使用更加方便. 它将 JSON 输出转换为 `flask.Response`
    对象, mimetype 默认为 `application/json`.
    为了使用方便, 也可以将多个参数转换为 list 或多个关键字参数转换为 dict.
    也就是说, `jsonify(1, 2, 3)` 和 `jsonify([1, 2, 3])` 都将序列化为 `[1,2,3]`

    For clarity, the JSON serialization behavior has the following differences
    from :func:`dumps`:
    为了清楚起见, JSON 序列化行为和 dumps 有以下几个不同之处:


    1. Single argument: Passed straight through to :func:`dumps`.
    1. 单个参数: 直接传入 `dumps`.

    2. Multiple arguments: Converted to an array before being passed to
       :func:`dumps`.
    2. 多个参数: 传入 `dumps` 之前转换为列表.

    3. Multiple keyword arguments: Converted to a dict before being passed to
       :func:`dumps`.
    3. 多个关键字参数: 传入 `dumps` 之前转换为字典.

    4. Both args and kwargs: Behavior undefined and will throw an exception.
    4. 位置参数和关键字参数: 未定义的行为都将抛出异常.

    Example usage::
    示例用法:

        from flask import jsonify

        @app.route('/_get_current_user')
        def get_current_user():
            return jsonify(username=g.user.username,
                           email=g.user.email,
                           id=g.user.id)

    This will send a JSON response like this to the browser::

        {
            "username": "admin",
            "email": "admin@localhost",
            "id": 42
        }


    .. versionchanged:: 0.11
       Added support for serializing top-level arrays. This introduces a
       security risk in ancient browsers. See :ref:`json-security` for details.

    This function's response will be pretty printed if the
    ``JSONIFY_PRETTYPRINT_REGULAR`` config parameter is set to True or the
    Flask app is running in debug mode. Compressed (not pretty) formatting
    currently means no indents and no spaces after separators.

    .. versionadded:: 0.2
    """

    indent = None
    separators = (",", ":")

    if current_app.config["JSONIFY_PRETTYPRINT_REGULAR"] or current_app.debug:
        indent = 2
        separators = (", ", ": ")

    if args and kwargs:
        raise TypeError("jsonify() behavior undefined when passed both args and kwargs")
    elif len(args) == 1:  # single args are passed directly to dumps()
        data = args[0]
    else:
        data = args or kwargs

    return current_app.response_class(
        dumps(data, indent=indent, separators=separators) + "\n",
        mimetype=current_app.config["JSONIFY_MIMETYPE"],
    )


def tojson_filter(obj, **kwargs):
    return Markup(htmlsafe_dumps(obj, **kwargs))
