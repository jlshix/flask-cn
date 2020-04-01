# -*- coding: utf-8 -*-
"""
    flask._compat
    ~~~~~~~~~~~~~

    Some py2/py3 compatibility support based on a stripped down
    version of six so we don't have to depend on a specific version
    of it.

    基于一个精简的 six 提供 python2 和 python3 的兼容,
    这样就不必依赖 six 的某个特定版本了.

    :copyright: 2010 Pallets
    :license: BSD-3-Clause
"""
import sys

PY2 = sys.version_info[0] == 2
_identity = lambda x: x

try:  # Python 2
    text_type = unicode
    string_types = (str, unicode)
    integer_types = (int, long)
except NameError:  # Python 3
    text_type = str
    string_types = (str,)
    integer_types = (int,)

if not PY2:
    iterkeys = lambda d: iter(d.keys())
    itervalues = lambda d: iter(d.values())
    iteritems = lambda d: iter(d.items())

    from inspect import getfullargspec as getargspec
    from io import StringIO
    import collections.abc as collections_abc

    def reraise(tp, value, tb=None):
        if value.__traceback__ is not tb:
            raise value.with_traceback(tb)
        raise value

    implements_to_string = _identity

else:
    iterkeys = lambda d: d.iterkeys()
    itervalues = lambda d: d.itervalues()
    iteritems = lambda d: d.iteritems()

    from inspect import getargspec
    from cStringIO import StringIO
    import collections as collections_abc

    exec("def reraise(tp, value, tb=None):\n raise tp, value, tb")

    def implements_to_string(cls):
        cls.__unicode__ = cls.__str__
        cls.__str__ = lambda x: x.__unicode__().encode("utf-8")
        return cls


def with_metaclass(meta, *bases):
    """Create a base class with a metaclass.

    用元类创建基类.
    """
    # This requires a bit of explanation: the basic idea is to make a
    # dummy metaclass for one level of class instantiation that replaces
    # itself with the actual metaclass.
    #
    # 这里需要解释一下: 基本的想法是为一个级别的类的实例化创建一个虚拟元类,
    # 用实际的元类替换自己
    class metaclass(type):
        def __new__(metacls, name, this_bases, d):
            return meta(name, bases, d)

    return type.__new__(metaclass, "temporary_class", (), {})


# Certain versions of pypy have a bug where clearing the exception stack
# breaks the __exit__ function in a very peculiar way.  The second level of
# exception blocks is necessary because pypy seems to forget to check if an
# exception happened until the next bytecode instruction?
#
# 某些版本的 pypy 有个 bug: 清空异常栈的时候会以某种方式中断 __exit__ 函数.
# 第二级异常块是必需的, 因为 pypy 似乎忘记了检查是否在下一条字节码指令之前发生了异常？
#
# Relevant PyPy bugfix commit:
# https://bitbucket.org/pypy/pypy/commits/77ecf91c635a287e88e60d8ddb0f4e9df4003301
# According to ronan on #pypy IRC, it is released in PyPy2 2.3 and later
# versions.
#
# 相关的 PyPy bugfix 提交:
# https://bitbucket.org/pypy/pypy/commits/77ecf91c635a287e88e60d8ddb0f4e9df4003301
# 根据 #pypy IRC 上的 ronan, 这个提交发布于 PyPy2 2.3 及之后的版本.
#
# Ubuntu 14.04 has PyPy 2.2.1, which does exhibit this bug.
#
# Ubuntu 14.04 安装的是 PyPy 2.2.1, 会有这个 bug.

BROKEN_PYPY_CTXMGR_EXIT = False
if hasattr(sys, "pypy_version_info"):

    class _Mgr(object):
        def __enter__(self):
            return self

        def __exit__(self, *args):
            if hasattr(sys, "exc_clear"):
                # Python 3 (PyPy3) doesn't have exc_clear
                # Python 3 (PyPy3) 没有 exc_clear 方法
                sys.exc_clear()

    try:
        try:
            with _Mgr():
                raise AssertionError()
        except:  # noqa: B001
            # We intentionally use a bare except here. See the comment above
            # regarding a pypy bug as to why.
            # 因为 pypy 的一个 bug, 我们在这里故意使用了一个空的 except.
            # 查看上面的注释了解更多信息.
            raise
    except TypeError:
        BROKEN_PYPY_CTXMGR_EXIT = True
    except AssertionError:
        pass


try:
    from os import fspath
except ImportError:
    # Backwards compatibility as proposed in PEP 0519:
    # 根据 PEP 0519 建议的向后兼容:
    # https://www.python.org/dev/peps/pep-0519/#backwards-compatibility
    def fspath(path):
        return path.__fspath__() if hasattr(path, "__fspath__") else path


class _DeprecatedBool(object):
    def __init__(self, name, version, value):
        self.message = "'{}' is deprecated and will be removed in version {}.".format(
            name, version
        )
        self.value = value

    def _warn(self):
        import warnings

        warnings.warn(self.message, DeprecationWarning, stacklevel=2)

    def __eq__(self, other):
        self._warn()
        return other == self.value

    def __ne__(self, other):
        self._warn()
        return other != self.value

    def __bool__(self):
        self._warn()
        return self.value

    __nonzero__ = __bool__


json_available = _DeprecatedBool("flask.json_available", "2.0.0", True)
