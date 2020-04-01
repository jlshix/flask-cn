# -*- coding: utf-8 -*-
"""
    flask.config
    ~~~~~~~~~~~~

    Implements the configuration related objects.

    配置相关对象的实现

    :copyright: 2010 Pallets
    :license: BSD-3-Clause
"""
import errno
import os
import types

from werkzeug.utils import import_string

from . import json
from ._compat import iteritems
from ._compat import string_types


class ConfigAttribute(object):
    """Makes an attribute forward to the config

    把属性转发至对象的 config.
    注: 在 app.Flask 的类变量中可以看到用法
    """

    def __init__(self, name, get_converter=None):
        self.__name__ = name
        self.get_converter = get_converter

    def __get__(self, obj, type=None):
        if obj is None:
            return self
        rv = obj.config[self.__name__]
        if self.get_converter is not None:
            rv = self.get_converter(rv)
        return rv

    def __set__(self, obj, value):
        obj.config[self.__name__] = value


class Config(dict):
    """Works exactly like a dict but provides ways to fill it from files
    or special dictionaries.  There are two common patterns to populate the
    config.

    作用和 dict 很像, 但提供了从文件或特定字典初始化的方法.
    有两种常见的模式来填充配置.


    Either you can fill the config from a config file::

    第一种是从一个配置文件中填充配置:

        app.config.from_pyfile('yourconfig.cfg')

    Or alternatively you can define the configuration options in the
    module that calls :meth:`from_object` or provide an import path to
    a module that should be loaded.  It is also possible to tell it to
    use the same module and with that provide the configuration values
    just before the call::

    或者你可以在某个模块中定义配置, 然后使用 `from_object` 方法或提供一个导入路径,
    从而加载这个模块中的配置. 也在定义配置的文件中调用, 在调用之前提供所有的配置项即可.

        DEBUG = True
        SECRET_KEY = 'development key'
        app.config.from_object(__name__)

    In both cases (loading from any Python file or loading from modules),
    only uppercase keys are added to the config.  This makes it possible to use
    lowercase values in the config file for temporary values that are not added
    to the config or to define the config keys in the same file that implements
    the application.

    在这两种方式(从任意 python 文件或模块中加载)中, 只有大写的属性才会被加载到配置文件中.
    这样可以在配置文件中使用小写的属性定义临时值, 这些小写的值不会被加到配置中. 甚至可以在
    同一文件中同时编写配置和 app.

    Probably the most interesting way to load configurations is from an
    environment variable pointing to a file::

    最有趣的方式应该是从环境变量指向的文件中加载配置:

        app.config.from_envvar('YOURAPPLICATION_SETTINGS')

    In this case before launching the application you have to set this
    environment variable to the file you want to use.  On Linux and OS X
    use the export statement::

    这种情况下, 在启动 app 之前必须先设定这个环境变量, 指向配置文件.
    在 Linux 和 OS X 使用 `export` 命令指定:

        export YOURAPPLICATION_SETTINGS='/path/to/config/file'

    On windows use `set` instead.

    在 windows 下使用 `set` 命令指定.

    :param root_path: path to which files are read relative from.  When the
                      config object is created by the application, this is
                      the application's :attr:`~flask.Flask.root_path`.
    参数 root_path: 读取文件的相对路径. 当配置对象由应用创建时,
                    这个值为 app 的 `root_path` 属性的值.

    :param defaults: an optional dictionary of default values
    参数 defaults: 可选的字典, 用于指定默认值.
    """

    def __init__(self, root_path, defaults=None):
        dict.__init__(self, defaults or {})
        self.root_path = root_path

    def from_envvar(self, variable_name, silent=False):
        """Loads a configuration from an environment variable pointing to
        a configuration file.  This is basically just a shortcut with nicer
        error messages for this line of code::

        从指向配置文件的环境变量中加载配置. 可以使用以下代码加载, 错误信息更友好:

            app.config.from_pyfile(os.environ['YOURAPPLICATION_SETTINGS'])

        :param variable_name: name of the environment variable
        参数 variable_name: 环境变量名.

        :param silent: set to ``True`` if you want silent failure for missing
                       files.
        参数 silent: 如果找不到文件的时候不报错可以设为 `True`.

        :return: bool. ``True`` if able to load config, ``False`` otherwise.
        返回一个布尔值, 可以加载配置返回 `True`, 不然返回 `False`.
        """
        rv = os.environ.get(variable_name)
        if not rv:
            if silent:
                return False
            raise RuntimeError(
                "The environment variable %r is not set "
                "and as such configuration could not be "
                "loaded.  Set this variable and make it "
                "point to a configuration file" % variable_name
            )
        return self.from_pyfile(rv, silent=silent)

    def from_pyfile(self, filename, silent=False):
        """Updates the values in the config from a Python file.  This function
        behaves as if the file was imported as module with the
        :meth:`from_object` function.

        从 python 文件中更新配置. 这个函数的行为和导入 python 文件作为一个模块后, 使用
        `from_object` 函数导入的行为是一致的.

        :param filename: the filename of the config.  This can either be an
                         absolute filename or a filename relative to the
                         root path.
        参数 filename: 配置的文件名. 可以是绝对路径, 也可以是项目根路径的相对路径.

        :param silent: set to ``True`` if you want silent failure for missing
                       files.
        参数 silent: 如果找不到文件的时候不报错可以设为 `True`.

        .. versionadded:: 0.7
           `silent` parameter.
        """
        filename = os.path.join(self.root_path, filename)
        d = types.ModuleType("config")
        d.__file__ = filename
        try:
            with open(filename, mode="rb") as config_file:
                exec(compile(config_file.read(), filename, "exec"), d.__dict__)
        except IOError as e:
            if silent and e.errno in (errno.ENOENT, errno.EISDIR, errno.ENOTDIR):
                return False
            e.strerror = "Unable to load configuration file (%s)" % e.strerror
            raise
        self.from_object(d)
        return True

    def from_object(self, obj):
        """Updates the values from the given object.  An object can be of one
        of the following two types:
        从给定的对象中加载配置. 对象可以是以下两种类型:

        -   a string: in this case the object with that name will be imported
        -   一个字符串: 这种情况下以这个字符串为名称的对象将被导入

        -   an actual object reference: that object is used directly
        -   一个真正的对象引用: 直接使用这个对象

        Objects are usually either modules or classes. :meth:`from_object`
        loads only the uppercase attributes of the module/class. A ``dict``
        object will not work with :meth:`from_object` because the keys of a
        ``dict`` are not attributes of the ``dict`` class.

        对象通常是模块或类. `from_object` 只加载模块或类大写的属性.
        对象不可以是 `dict` 的实例, 因为字典的键不是属性.

        Example of module-based configuration::
        基于模块的配置示例:

            app.config.from_object('yourapplication.default_config')
            from yourapplication import default_config
            app.config.from_object(default_config)

        Nothing is done to the object before loading. If the object is a
        class and has ``@property`` attributes, it needs to be
        instantiated before being passed to this method.

        加载对象前什么都没做. 如果对象是一个类, 并且有 `@property` 装饰的属性, 则
        需要在传入之前进行实例化.

        You should not use this function to load the actual configuration but
        rather configuration defaults.  The actual config should be loaded
        with :meth:`from_pyfile` and ideally from a location not within the
        package because the package might be installed system wide.

        你不应该使用这个函数加载实际的配置, 而是用来配置默认值.
        实际的配置应当使用 `from_pyfile` 方法加载. 最好这个文件不要在包目录里, 因为包
        可能会在系统范围内安装.


        See :ref:`config-dev-prod` for an example of class-based configuration
        using :meth:`from_object`.

        参见 config-dev-prod` 查看使用 `from_object` 加载基于类的配置的示例.

        :param obj: an import name or object
        参数 obj: 导入名或一个对象
        """
        if isinstance(obj, string_types):
            obj = import_string(obj)
        for key in dir(obj):
            if key.isupper():
                self[key] = getattr(obj, key)

    def from_json(self, filename, silent=False):
        """Updates the values in the config from a JSON file. This function
        behaves as if the JSON object was a dictionary and passed to the
        :meth:`from_mapping` function.

        从 JSON 文件更新配置. 这个函数的行为和将 JSON 文件转为字典后, 使用 `from_mapping`
        方法导入的行为是一致的.

        :param filename: the filename of the JSON file.  This can either be an
                         absolute filename or a filename relative to the
                         root path.
        参数 filename: JSON 文件名. 可以是绝对路径, 也可以是项目根路径的相对路径.

        :param silent: set to ``True`` if you want silent failure for missing
                       files.
        参数 silent: 如果找不到文件的时候不报错可以设为 `True`.

        .. versionadded:: 0.11
        """
        filename = os.path.join(self.root_path, filename)

        try:
            with open(filename) as json_file:
                obj = json.loads(json_file.read())
        except IOError as e:
            if silent and e.errno in (errno.ENOENT, errno.EISDIR):
                return False
            e.strerror = "Unable to load configuration file (%s)" % e.strerror
            raise
        return self.from_mapping(obj)

    def from_mapping(self, *mapping, **kwargs):
        """Updates the config like :meth:`update` ignoring items with non-upper
        keys.
        和 `update` 方法一样更新配置, 忽略非大写的键.

        .. versionadded:: 0.11
        """
        mappings = []
        if len(mapping) == 1:
            if hasattr(mapping[0], "items"):
                mappings.append(mapping[0].items())
            else:
                mappings.append(mapping[0])
        elif len(mapping) > 1:
            raise TypeError(
                "expected at most 1 positional argument, got %d" % len(mapping)
            )
        mappings.append(kwargs.items())
        for mapping in mappings:
            for (key, value) in mapping:
                if key.isupper():
                    self[key] = value
        return True

    def get_namespace(self, namespace, lowercase=True, trim_namespace=True):
        """Returns a dictionary containing a subset of configuration options
        that match the specified namespace/prefix. Example usage::

        返回一个包含配置项子集的字典. 其中的键匹配指定的命名空间或前缀. 示例用法:

            app.config['IMAGE_STORE_TYPE'] = 'fs'
            app.config['IMAGE_STORE_PATH'] = '/var/app/images'
            app.config['IMAGE_STORE_BASE_URL'] = 'http://img.website.com'
            image_store_config = app.config.get_namespace('IMAGE_STORE_')

        The resulting dictionary `image_store_config` would look like::

        结果字典 `image_store_config` 值为:

            {
                'type': 'fs',
                'path': '/var/app/images',
                'base_url': 'http://img.website.com'
            }

        This is often useful when configuration options map directly to
        keyword arguments in functions or class constructors.

        当配置选项直接映射到函数或类构造函数中的关键字参数时, 这通常很有用.

        :param namespace: a configuration namespace
        参数 namespace: 配置的命名空间

        :param lowercase: a flag indicating if the keys of the resulting
                          dictionary should be lowercase
        参数 lowercase: 结果字典中的 key 是否应转为小写

        :param trim_namespace: a flag indicating if the keys of the resulting
                          dictionary should not include the namespace
        参数 trim_namespace: 结果字典中的 key 是否应当去除命名空间

        .. versionadded:: 0.11
        """
        rv = {}
        for k, v in iteritems(self):
            if not k.startswith(namespace):
                continue
            if trim_namespace:
                key = k[len(namespace) :]
            else:
                key = k
            if lowercase:
                key = key.lower()
            rv[key] = v
        return rv

    def __repr__(self):
        return "<%s %s>" % (self.__class__.__name__, dict.__repr__(self))
