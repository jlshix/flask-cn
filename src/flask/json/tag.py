# -*- coding: utf-8 -*-
"""
Tagged JSON
~~~~~~~~~~~

A compact representation for lossless serialization of non-standard JSON types.
:class:`~flask.sessions.SecureCookieSessionInterface` uses this to serialize
the session data, but it may be useful in other places. It can be extended to
support other types.

无损序列化非标准 JSON 类型的一种简单表示. `flask.sessions.SecureCookieSessionInterface`
使用此类序列化 session 数据. 或许在其他地方也用得到. 也可以拓展它来支持其他类型.

.. autoclass:: TaggedJSONSerializer
    :members:

.. autoclass:: JSONTag
    :members:

Let's seen an example that adds support for :class:`~collections.OrderedDict`.
Dicts don't have an order in Python or JSON, so to handle this we will dump
the items as a list of ``[key, value]`` pairs. Subclass :class:`JSONTag` and
give it the new key ``' od'`` to identify the type. The session serializer
processes dicts first, so insert the new tag at the front of the order since
``OrderedDict`` must be processed before ``dict``. ::

我们来看一个添加对 OrderedDict 类型支持的例子. 字典在 python 和 JSON 中都是无序的, 所以
为了保留顺序我们将把每一项输出为 `[key, value]` 组成的列表.
定义一个 `JSONTag` 的子类, 定义类变量 key 为 ` od` 来标识这一类型. session 序列化先处理
dict, 所以应该在这个处理顺序的最前面插入一个新的 tag, 优先处理 `OrderedDict`

    from flask.json.tag import JSONTag

    class TagOrderedDict(JSONTag):
        __slots__ = ('serializer',)
        key = ' od'

        def check(self, value):
            return isinstance(value, OrderedDict)

        def to_json(self, value):
            return [[k, self.serializer.tag(v)] for k, v in iteritems(value)]

        def to_python(self, value):
            return OrderedDict(value)

    app.session_interface.serializer.register(TagOrderedDict, index=0)

:copyright: 2010 Pallets
:license: BSD-3-Clause
"""
from base64 import b64decode
from base64 import b64encode
from datetime import datetime
from uuid import UUID

from jinja2 import Markup
from werkzeug.http import http_date
from werkzeug.http import parse_date

from .._compat import iteritems
from .._compat import text_type
from ..json import dumps
from ..json import loads


class JSONTag(object):
    """Base class for defining type tags for :class:`TaggedJSONSerializer`.
    用于定义 `TaggedJSONSerializer` 的类型标记的基类.
    """

    __slots__ = ("serializer",)

    #: The tag to mark the serialized object with. If ``None``, this tag is
    #: only used as an intermediate step during tagging.
    # 用于标记序列化对象的 tag, 如果为 None, 这个 tag 仅在标记期间用作中间步骤.
    key = None

    def __init__(self, serializer):
        """Create a tagger for the given serializer.
        使用给定的 serializer 创建对象.
        """
        self.serializer = serializer

    def check(self, value):
        """Check if the given value should be tagged by this tag.
        检查给定值是否应该用这个标签标记.
        """
        raise NotImplementedError

    def to_json(self, value):
        """Convert the Python object to an object that is a valid JSON type.
        The tag will be added later.
        将 Python 对象转换为符合标准的 JSON 类型对象. 标签将稍后添加.
        """
        raise NotImplementedError

    def to_python(self, value):
        """Convert the JSON representation back to the correct type. The tag
        will already be removed.
        将 JSON 表示的值转换回原来的类型. 标签已经被移除.
        """
        raise NotImplementedError

    def tag(self, value):
        """Convert the value to a valid JSON type and add the tag structure
        around it.
        将值转换为符合标准的 JSON 类型, 并将标签结构加上.
        """
        return {self.key: self.to_json(value)}


class TagDict(JSONTag):
    """Tag for 1-item dicts whose only key matches a registered tag.
    只有一对键值对的字典的 Tag, 唯一的 key 匹配已经注册的标签.

    Internally, the dict key is suffixed with `__`, and the suffix is removed
    when deserializing.
    内部表示的时候, 字典的 key 以 `__` 作为后缀, 反序列化的时候移除这个后缀.
    """

    __slots__ = ()
    key = " di"

    def check(self, value):
        return (
            isinstance(value, dict)
            and len(value) == 1
            and next(iter(value)) in self.serializer.tags
        )

    def to_json(self, value):
        key = next(iter(value))
        return {key + "__": self.serializer.tag(value[key])}

    def to_python(self, value):
        key = next(iter(value))
        return {key[:-2]: value[key]}


class PassDict(JSONTag):
    __slots__ = ()

    def check(self, value):
        return isinstance(value, dict)

    def to_json(self, value):
        # JSON objects may only have string keys, so don't bother tagging the
        # key here.
        # JSON 对象可能只使用字符串作为 key, 所以不需要费心在这里为 key 做标记了
        return dict((k, self.serializer.tag(v)) for k, v in iteritems(value))

    tag = to_json


class TagTuple(JSONTag):
    __slots__ = ()
    key = " t"

    def check(self, value):
        return isinstance(value, tuple)

    def to_json(self, value):
        return [self.serializer.tag(item) for item in value]

    def to_python(self, value):
        return tuple(value)


class PassList(JSONTag):
    __slots__ = ()

    def check(self, value):
        return isinstance(value, list)

    def to_json(self, value):
        return [self.serializer.tag(item) for item in value]

    tag = to_json


class TagBytes(JSONTag):
    __slots__ = ()
    key = " b"

    def check(self, value):
        return isinstance(value, bytes)

    def to_json(self, value):
        return b64encode(value).decode("ascii")

    def to_python(self, value):
        return b64decode(value)


class TagMarkup(JSONTag):
    """Serialize anything matching the :class:`~flask.Markup` API by
    having a ``__html__`` method to the result of that method. Always
    deserializes to an instance of :class:`~flask.Markup`.

    序列化任何符合 `flask.Markup` API 的, 即含有 `__html__` 方法的对象.
    总是反序列化为一个 `flask.Markup` 的实例.
    """

    __slots__ = ()
    key = " m"

    def check(self, value):
        return callable(getattr(value, "__html__", None))

    def to_json(self, value):
        return text_type(value.__html__())

    def to_python(self, value):
        return Markup(value)


class TagUUID(JSONTag):
    __slots__ = ()
    key = " u"

    def check(self, value):
        return isinstance(value, UUID)

    def to_json(self, value):
        return value.hex

    def to_python(self, value):
        return UUID(value)


class TagDateTime(JSONTag):
    __slots__ = ()
    key = " d"

    def check(self, value):
        return isinstance(value, datetime)

    def to_json(self, value):
        return http_date(value)

    def to_python(self, value):
        return parse_date(value)


class TaggedJSONSerializer(object):
    """Serializer that uses a tag system to compactly represent objects that
    are not JSON types. Passed as the intermediate serializer to
    :class:`itsdangerous.Serializer`.

    使用标签系统简洁地呈现非 JSON 类型的序列化器. 作为中间序列化器传递给
    `itsdangerous.Serializer`.

    The following extra types are supported:
    支持以下额外的类型:

    * :class:`dict`
    * :class:`tuple`
    * :class:`bytes`
    * :class:`~flask.Markup`
    * :class:`~uuid.UUID`
    * :class:`~datetime.datetime`
    """

    __slots__ = ("tags", "order")

    #: Tag classes to bind when creating the serializer. Other tags can be
    #: added later using :meth:`~register`.
    # 创建序列化器时绑定的标签类. 其他标签之后也可以通过 `register` 方法加入.
    default_tags = [
        TagDict,
        PassDict,
        TagTuple,
        PassList,
        TagBytes,
        TagMarkup,
        TagUUID,
        TagDateTime,
    ]

    def __init__(self):
        self.tags = {}
        self.order = []

        for cls in self.default_tags:
            self.register(cls)

    def register(self, tag_class, force=False, index=None):
        """Register a new tag with this serializer.
        为此序列化器注册新的标签类.

        :param tag_class: tag class to register. Will be instantiated with this
            serializer instance.
        参数 tag_class: 注册的标签类. 将与此序列化器一同实例化.

        :param force: overwrite an existing tag. If false (default), a
            :exc:`KeyError` is raised.
        参数 force: 覆盖已经存在的标签. 如果为 False(默认), 抛出一个 `KeyError`.

        :param index: index to insert the new tag in the tag order. Useful when
            the new tag is a special case of an existing tag. If ``None``
            (default), the tag is appended to the end of the order.
        参数 index: 插入的新标签的序号. 当新的标签是已存在的标签的一个特殊情况时有用.
            如果为 None(默认), 这个标签将放在标签列表的最后.

        :raise KeyError: if the tag key is already registered and ``force`` is
            not true.
        抛出异常: KeyError: 如果标签的 key 已经注册过且 `force` 参数不为 True 时抛出.
        """
        tag = tag_class(self)
        key = tag.key

        if key is not None:
            if not force and key in self.tags:
                raise KeyError("Tag '{0}' is already registered.".format(key))

            self.tags[key] = tag

        if index is None:
            self.order.append(tag)
        else:
            self.order.insert(index, tag)

    def tag(self, value):
        """Convert a value to a tagged representation if necessary.
        如有必要, 将值转换为标记过的表示.
        """
        for tag in self.order:
            if tag.check(value):
                return tag.tag(value)

        return value

    def untag(self, value):
        """Convert a tagged representation back to the original type.
        将一个已标记的表示转换回其原来的类型.
        """
        if len(value) != 1:
            return value

        key = next(iter(value))

        if key not in self.tags:
            return value

        return self.tags[key].to_python(value[key])

    def dumps(self, value):
        """Tag the value and dump it to a compact JSON string.
        将值打标签并转换为简洁的 JSON 字符串.
        """
        return dumps(self.tag(value), separators=(",", ":"))

    def loads(self, value):
        """Load data from a JSON string and deserialized any tagged objects.
        从 JSON 字符串加载数据并反序列化为原来标记的对象.
        """
        return loads(value, object_hook=self.untag)
