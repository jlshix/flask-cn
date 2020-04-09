# -*- coding: utf-8 -*-
"""
    flask.sessions
    ~~~~~~~~~~~~~~

    Implements cookie based sessions based on itsdangerous.

    基于 itsdangerous, 实现基于 cookie 的会话.


    :copyright: 2010 Pallets
    :license: BSD-3-Clause
"""
import hashlib
import warnings
from datetime import datetime

from itsdangerous import BadSignature
from itsdangerous import URLSafeTimedSerializer
from werkzeug.datastructures import CallbackDict

from ._compat import collections_abc
from .helpers import is_ip
from .helpers import total_seconds
from .json.tag import TaggedJSONSerializer


class SessionMixin(collections_abc.MutableMapping):
    """Expands a basic dictionary with session attributes.
    拓展基本字典类型, 添加会话属性.
    """

    @property
    def permanent(self):
        """This reflects the ``'_permanent'`` key in the dict.
        这个属性反映字典中的 `'_permanent'`.
        """
        return self.get("_permanent", False)

    @permanent.setter
    def permanent(self, value):
        self["_permanent"] = bool(value)

    #: Some implementations can detect whether a session is newly
    #: created, but that is not guaranteed. Use with caution. The mixin
    # default is hard-coded ``False``.
    #
    # 一些实现会检查会话是不是新建的, 但不能保证. 小心使用. 默认硬编码为 `False`.
    new = False

    #: Some implementations can detect changes to the session and set
    #: this when that happens. The mixin default is hard coded to
    #: ``True``.
    #
    # 一些实现会检查会话变动并在发生变动时将此键设为 `True`. 默认硬编码为 `True`.
    modified = True

    #: Some implementations can detect when session data is read or
    #: written and set this when that happens. The mixin default is hard
    #: coded to ``True``.
    #
    # 一些实现会检查会话数据的读写并在发生读写时将此键设为 `True`. 默认硬编码为 `True`.
    accessed = True


class SecureCookieSession(CallbackDict, SessionMixin):
    """Base class for sessions based on signed cookies.

    基于签名 cookie 的会话基类.

    This session backend will set the :attr:`modified` and
    :attr:`accessed` attributes. It cannot reliably track whether a
    session is new (vs. empty), so :attr:`new` remains hard coded to
    ``False``.

    这个会话后端将设置 `modified` 属性和 `accessed` 属性. 并不能可靠地追踪
    一个会话是不是新建的(或空的), 所以 `new` 属性仍硬编码为 `False`.
    """

    #: When data is changed, this is set to ``True``. Only the session
    #: dictionary itself is tracked; if the session contains mutable
    #: data (for example a nested dict) then this must be set to
    #: ``True`` manually when modifying that data. The session cookie
    #: will only be written to the response if this is ``True``.
    #
    # 会话字典被追踪的情况下, 数据发生变动时设为 `True`. 如果会话包含可变数据(如内嵌字典),
    # 当更改数据时必须手动设为 `True`. 会话 cookie 只有在值为 `True` 时才写入返回数据.
    modified = False

    #: When data is read or written, this is set to ``True``. Used by
    # :class:`.SecureCookieSessionInterface` to add a ``Vary: Cookie``
    #: header, which allows caching proxies to cache different pages for
    #: different users.
    #
    # 当数据被读取或写入时设为 `True`. `SecureCookieSessionInterface` 类使用时
    # 加入一个 `Vary: Cookie` 的 header 数据, 允许缓存代理为不同用户缓存不同的页面.
    accessed = False

    def __init__(self, initial=None):
        def on_update(self):
            self.modified = True
            self.accessed = True

        super(SecureCookieSession, self).__init__(initial, on_update)

    def __getitem__(self, key):
        self.accessed = True
        return super(SecureCookieSession, self).__getitem__(key)

    def get(self, key, default=None):
        self.accessed = True
        return super(SecureCookieSession, self).get(key, default)

    def setdefault(self, key, default=None):
        self.accessed = True
        return super(SecureCookieSession, self).setdefault(key, default)


class NullSession(SecureCookieSession):
    """Class used to generate nicer error messages if sessions are not
    available.  Will still allow read-only access to the empty session
    but fail on setting.

    当会话不可用时, 此类用于生成更易读的错误信息.
    """

    def _fail(self, *args, **kwargs):
        raise RuntimeError(
            "The session is unavailable because no secret "
            "key was set.  Set the secret_key on the "
            "application to something unique and secret."
        )

    __setitem__ = __delitem__ = clear = pop = popitem = update = setdefault = _fail
    del _fail


class SessionInterface(object):
    """The basic interface you have to implement in order to replace the
    default session interface which uses werkzeug's securecookie
    implementation.  The only methods you have to implement are
    :meth:`open_session` and :meth:`save_session`, the others have
    useful defaults which you don't need to change.

    需要实现的基本接口, 用于替换默认的使用 werkzeug 的 securecookie 实现的会话接口.
    只需要实现 `open_session` 和 `save_session`, 其他的则具有有用的默认值, 无需修改.

    The session object returned by the :meth:`open_session` method has to
    provide a dictionary like interface plus the properties and methods
    from the :class:`SessionMixin`.  We recommend just subclassing a dict
    and adding that mixin::

    由 `open_session` 返回的会话对象需要提供类似字典的接口以及来自 `SessionMixin` 的属性
    和方法. 我们推荐直接将 dict 和 SessionMixin 作为父类继承:

        class Session(dict, SessionMixin):
            pass

    If :meth:`open_session` returns ``None`` Flask will call into
    :meth:`make_null_session` to create a session that acts as replacement
    if the session support cannot work because some requirement is not
    fulfilled.  The default :class:`NullSession` class that is created
    will complain that the secret key was not set.

    若 `open_session` 返回 None, Flask 将调用 `make_null_session` 创建一个会话,
    如果有些要求未满足而无法支持会话, 则该会话将充当替换会话. 创建的默认 `NullSession`
    类将提示未设置秘钥.

    To replace the session interface on an application all you have to do
    is to assign :attr:`flask.Flask.session_interface`::

    替换会话接口只需要设定 `flask.Flask.session_interface` 属性:

        app = Flask(__name__)
        app.session_interface = MySessionInterface()

    .. versionadded:: 0.8
    """

    #: :meth:`make_null_session` will look here for the class that should
    #: be created when a null session is requested.  Likewise the
    #: :meth:`is_null_session` method will perform a typecheck against
    #: this type.
    #
    # `make_null_session` 方法将在此处寻找当请求空会话时应当创建的类.
    # 同样 `is_null_session` 方法将对这个类型进行类型检查.
    null_session_class = NullSession

    #: A flag that indicates if the session interface is pickle based.
    #: This can be used by Flask extensions to make a decision in regards
    #: to how to deal with the session object.
    #:
    #
    # 指示会话接口是否基于 pickle 的标志. 可以被 Flask 拓展用于确定如何处理会话对象.
    #
    #: .. versionadded:: 0.10
    pickle_based = False

    def make_null_session(self, app):
        """Creates a null session which acts as a replacement object if the
        real session support could not be loaded due to a configuration
        error.  This mainly aids the user experience because the job of the
        null session is to still support lookup without complaining but
        modifications are answered with a helpful error message of what
        failed.

        当真正的会话支持由于配置错误无法加载时创建一个空会话作为替换会话. 主要用于提升用户体验,
        因为空会话的主要作用是在无提示的情况下继续支持查询, 但更改和应答就返回有用的错误信息,
        提示错误原因.

        This creates an instance of :attr:`null_session_class` by default.

        默认创建一个 `null_session_class` 属性指向的类的实例.
        """
        return self.null_session_class()

    def is_null_session(self, obj):
        """Checks if a given object is a null session.  Null sessions are
        not asked to be saved.

        检查一个给定的对象是否为空会话. 空会话不要求保存.

        This checks if the object is an instance of :attr:`null_session_class`
        by default.

        默认检查这个对象是不是 `null_session_class` 属性所指向的类的实例.
        """
        return isinstance(obj, self.null_session_class)

    def get_cookie_domain(self, app):
        """Returns the domain that should be set for the session cookie.

        返回应为会话 cookie 设置的域名.

        Uses ``SESSION_COOKIE_DOMAIN`` if it is configured, otherwise
        falls back to detecting the domain based on ``SERVER_NAME``.

        如果配置了 `SESSION_COOKIE_DOMAIN`, 返回其值, 否则回退到根据 `SERVER_NAME`
        检测域名.

        Once detected (or if not set at all), ``SESSION_COOKIE_DOMAIN`` is
        updated to avoid re-running the logic.

        一旦检测到(或根本没设置), 更新 `SESSION_COOKIE_DOMAIN` 的值避免重新执行检测逻辑.
        """

        rv = app.config["SESSION_COOKIE_DOMAIN"]

        # set explicitly, or cached from SERVER_NAME detection
        # if False, return None
        #
        # 明确设置, 或从 SERVER_NAME 检测缓存, 若为 False 则返回 None
        if rv is not None:
            return rv if rv else None

        rv = app.config["SERVER_NAME"]

        # server name not set, cache False to return none next time
        # SERVER_NAME 未设置, 缓存 False, 下次直接返回 None
        if not rv:
            app.config["SESSION_COOKIE_DOMAIN"] = False
            return None

        # chop off the port which is usually not supported by browsers
        # remove any leading '.' since we'll add that later
        #
        # 去除浏览器一般不支持的端口, 去除任何前缀的点号("."), 因为之后会加上.
        rv = rv.rsplit(":", 1)[0].lstrip(".")

        if "." not in rv:
            # Chrome doesn't allow names without a '.'
            # this should only come up with localhost
            # hack around this by not setting the name, and show a warning
            #
            # Chrome 不允许不含 '.' 的名称, 这将只在本地出现,
            # 通过不设置名称来解决这个问题, 并显示警告.
            warnings.warn(
                '"{rv}" is not a valid cookie domain, it must contain a ".".'
                " Add an entry to your hosts file, for example"
                ' "{rv}.localdomain", and use that instead.'.format(rv=rv)
            )
            app.config["SESSION_COOKIE_DOMAIN"] = False
            return None

        ip = is_ip(rv)

        if ip:
            warnings.warn(
                "The session cookie domain is an IP address. This may not work"
                " as intended in some browsers. Add an entry to your hosts"
                ' file, for example "localhost.localdomain", and use that'
                " instead."
            )

        # if this is not an ip and app is mounted at the root, allow subdomain
        # matching by adding a '.' prefix
        #
        # 如果不是 ip 且 app 挂载在根目录, 通过添加 '.' 作为前缀允许子域名匹配
        if self.get_cookie_path(app) == "/" and not ip:
            rv = "." + rv

        app.config["SESSION_COOKIE_DOMAIN"] = rv
        return rv

    def get_cookie_path(self, app):
        """Returns the path for which the cookie should be valid.  The
        default implementation uses the value from the ``SESSION_COOKIE_PATH``
        config var if it's set, and falls back to ``APPLICATION_ROOT`` or
        uses ``/`` if it's ``None``.

        返回 cookie 应该有效的路径. 默认实现是使用 `SESSION_COOKIE_PATH` 的值, 若未设置,
        回退到 `APPLICATION_ROOT`, 若仍未设置, 返回 `None` 使用 `/`
        """
        return app.config["SESSION_COOKIE_PATH"] or app.config["APPLICATION_ROOT"]

    def get_cookie_httponly(self, app):
        """Returns True if the session cookie should be httponly.  This
        currently just returns the value of the ``SESSION_COOKIE_HTTPONLY``
        config var.

        会话 cookie 应当为 httponly 时返回 `True`. 当前直接返回配置项
        `SESSION_COOKIE_HTTPONLY` 的值
        """
        return app.config["SESSION_COOKIE_HTTPONLY"]

    def get_cookie_secure(self, app):
        """Returns True if the cookie should be secure.  This currently
        just returns the value of the ``SESSION_COOKIE_SECURE`` setting.

        cookie 应当加密时返回 `True`. 当前直接返回配置项 `SESSION_COOKIE_SECURE` 的值.
        """
        return app.config["SESSION_COOKIE_SECURE"]

    def get_cookie_samesite(self, app):
        """Return ``'Strict'`` or ``'Lax'`` if the cookie should use the
        ``SameSite`` attribute. This currently just returns the value of
        the :data:`SESSION_COOKIE_SAMESITE` setting.

        cookie 应当使用 `SameSite` 属性时返回 `'Strict'` 或 `'Lax'`. 当前直接返回
        配置项 `SESSION_COOKIE_SAMESITE` 的值.
        """
        return app.config["SESSION_COOKIE_SAMESITE"]

    def get_expiration_time(self, app, session):
        """A helper method that returns an expiration date for the session
        or ``None`` if the session is linked to the browser session.  The
        default implementation returns now + the permanent session
        lifetime configured on the application.

        一个辅助方法, 用于返回会话的过期时间, 若会话链接到浏览器会话则返回 `None`.
        默认实现是返回当前时间和 app 配置的持久化会话生存时长的总和.
        """
        if session.permanent:
            return datetime.utcnow() + app.permanent_session_lifetime

    def should_set_cookie(self, app, session):
        """Used by session backends to determine if a ``Set-Cookie`` header
        should be set for this session cookie for this response. If the session
        has been modified, the cookie is set. If the session is permanent and
        the ``SESSION_REFRESH_EACH_REQUEST`` config is true, the cookie is
        always set.

        由会话后端使用, 用于确认在是否应该为会话 cookie 在此次返回的 header 中添加
        `Set-Cookie`. 如果会话修改了, 设置 cookie. 若会话持久化了且配置项
        `SESSION_REFRESH_EACH_REQUEST` 为 True, 则总是设置 cookie.

        This check is usually skipped if the session was deleted.

        如果会话被删除, 此检查通常会跳过.

        .. versionadded:: 0.11
        """

        return session.modified or (
            session.permanent and app.config["SESSION_REFRESH_EACH_REQUEST"]
        )

    def open_session(self, app, request):
        """This method has to be implemented and must either return ``None``
        in case the loading failed because of a configuration error or an
        instance of a session object which implements a dictionary like
        interface + the methods and attributes on :class:`SessionMixin`.

        必须实现此方法. 因配置错误加载失败时返回 `None`, 或者返回一个实现了字典接口和
        `SessionMixin` 的对象.
        """
        raise NotImplementedError()

    def save_session(self, app, session, response):
        """This is called for actual sessions returned by :meth:`open_session`
        at the end of the request.  This is still called during a request
        context so if you absolutely need access to the request you can do
        that.

        请求结束时, 由 `open_session` 返回的实际会话会调用此方法. 在请求上下文期间仍会调用
        此方法, 所以如果你一定需要访问改请求, 则可以执行此操作.
        """
        raise NotImplementedError()


session_json_serializer = TaggedJSONSerializer()


class SecureCookieSessionInterface(SessionInterface):
    """The default session interface that stores sessions in signed cookies
    through the :mod:`itsdangerous` module.

    默认会话接口, 使用基于 `itsdangerous` 模块的签名 cookie 实现的会话存储.
    """

    #: the salt that should be applied on top of the secret key for the
    #: signing of cookie based sessions.
    #
    # 基于 cookie 的会话签名秘钥上应加的盐(噪声).
    salt = "cookie-session"
    #: the hash function to use for the signature.  The default is sha1
    # 签名使用的散列函数. 默认 sha1
    digest_method = staticmethod(hashlib.sha1)
    #: the name of the itsdangerous supported key derivation.  The default
    #: is hmac.
    #
    # itsdangerous 支持的秘钥派生名称. 默认 hmac.
    key_derivation = "hmac"
    #: A python serializer for the payload.  The default is a compact
    #: JSON derived serializer with support for some extra Python types
    #: such as datetime objects or tuples.
    #
    # 用于有效负载的 python 序列化器. 默认是一个简单的由 JSON 派生的序列化器, 并
    # 支持一些额外的 Python 类型, 例如 datetime 和元组.
    serializer = session_json_serializer
    session_class = SecureCookieSession

    def get_signing_serializer(self, app):
        if not app.secret_key:
            return None
        signer_kwargs = dict(
            key_derivation=self.key_derivation, digest_method=self.digest_method
        )
        return URLSafeTimedSerializer(
            app.secret_key,
            salt=self.salt,
            serializer=self.serializer,
            signer_kwargs=signer_kwargs,
        )

    def open_session(self, app, request):
        s = self.get_signing_serializer(app)
        if s is None:
            return None
        val = request.cookies.get(app.session_cookie_name)
        if not val:
            return self.session_class()
        max_age = total_seconds(app.permanent_session_lifetime)
        try:
            data = s.loads(val, max_age=max_age)
            return self.session_class(data)
        except BadSignature:
            return self.session_class()

    def save_session(self, app, session, response):
        domain = self.get_cookie_domain(app)
        path = self.get_cookie_path(app)

        # If the session is modified to be empty, remove the cookie.
        # If the session is empty, return without setting the cookie.
        #
        # 若会话修改为空, 移除 cookie. 若会话为空, 返回时不设置 cookie.
        if not session:
            if session.modified:
                response.delete_cookie(
                    app.session_cookie_name, domain=domain, path=path
                )

            return

        # Add a "Vary: Cookie" header if the session was accessed at all.
        # 如果完全访问了会话, 添加 header "Vary: Cookie"
        if session.accessed:
            response.vary.add("Cookie")

        if not self.should_set_cookie(app, session):
            return

        httponly = self.get_cookie_httponly(app)
        secure = self.get_cookie_secure(app)
        samesite = self.get_cookie_samesite(app)
        expires = self.get_expiration_time(app, session)
        val = self.get_signing_serializer(app).dumps(dict(session))
        response.set_cookie(
            app.session_cookie_name,
            val,
            expires=expires,
            httponly=httponly,
            domain=domain,
            path=path,
            secure=secure,
            samesite=samesite,
        )
