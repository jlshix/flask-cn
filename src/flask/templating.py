# -*- coding: utf-8 -*-
"""
    flask.templating
    ~~~~~~~~~~~~~~~~

    Implements the bridge to Jinja2.

    实现通往 Jinja2 的桥梁.

    :copyright: 2010 Pallets
    :license: BSD-3-Clause
"""
from jinja2 import BaseLoader
from jinja2 import Environment as BaseEnvironment
from jinja2 import TemplateNotFound

from .globals import _app_ctx_stack
from .globals import _request_ctx_stack
from .signals import before_render_template
from .signals import template_rendered


def _default_template_ctx_processor():
    """Default template context processor.  Injects `request`,
    `session` and `g`.

    默认模板上下文处理器. 注入 `request`, `session` 和 `g`.
    """
    reqctx = _request_ctx_stack.top
    appctx = _app_ctx_stack.top
    rv = {}
    if appctx is not None:
        rv["g"] = appctx.g
    if reqctx is not None:
        rv["request"] = reqctx.request
        rv["session"] = reqctx.session
    return rv


class Environment(BaseEnvironment):
    """Works like a regular Jinja2 environment but has some additional
    knowledge of how Flask's blueprint works so that it can prepend the
    name of the blueprint to referenced templates if necessary.

    可以像常规的 Jinja2 environment 工作, 但对于于 Flask 的蓝图如何工作有一些额外的
    了解, 所以在必要时可以将蓝图的名称放在引用的模板前面.
    """

    def __init__(self, app, **options):
        if "loader" not in options:
            options["loader"] = app.create_global_jinja_loader()
        BaseEnvironment.__init__(self, **options)
        self.app = app


class DispatchingJinjaLoader(BaseLoader):
    """A loader that looks for templates in the application and all
    the blueprint folders.

    一个加载器, 用于在应用和所有蓝图文件夹寻找模板.
    """

    def __init__(self, app):
        self.app = app

    def get_source(self, environment, template):
        if self.app.config["EXPLAIN_TEMPLATE_LOADING"]:
            return self._get_source_explained(environment, template)
        return self._get_source_fast(environment, template)

    def _get_source_explained(self, environment, template):
        attempts = []
        trv = None

        for srcobj, loader in self._iter_loaders(template):
            try:
                rv = loader.get_source(environment, template)
                if trv is None:
                    trv = rv
            except TemplateNotFound:
                rv = None
            attempts.append((loader, srcobj, rv))

        from .debughelpers import explain_template_loading_attempts

        explain_template_loading_attempts(self.app, template, attempts)

        if trv is not None:
            return trv
        raise TemplateNotFound(template)

    def _get_source_fast(self, environment, template):
        for _srcobj, loader in self._iter_loaders(template):
            try:
                return loader.get_source(environment, template)
            except TemplateNotFound:
                continue
        raise TemplateNotFound(template)

    def _iter_loaders(self, template):
        loader = self.app.jinja_loader
        if loader is not None:
            yield self.app, loader

        for blueprint in self.app.iter_blueprints():
            loader = blueprint.jinja_loader
            if loader is not None:
                yield blueprint, loader

    def list_templates(self):
        result = set()
        loader = self.app.jinja_loader
        if loader is not None:
            result.update(loader.list_templates())

        for blueprint in self.app.iter_blueprints():
            loader = blueprint.jinja_loader
            if loader is not None:
                for template in loader.list_templates():
                    result.add(template)

        return list(result)


def _render(template, context, app):
    """Renders the template and fires the signal

    渲染模板并发送信号.
    """

    before_render_template.send(app, template=template, context=context)
    rv = template.render(context)
    template_rendered.send(app, template=template, context=context)
    return rv


def render_template(template_name_or_list, **context):
    """Renders a template from the template folder with the given
    context.

    使用给定的上下文从模板文件夹渲染模板.

    :param template_name_or_list: the name of the template to be
                                  rendered, or an iterable with template names
                                  the first one existing will be rendered
    参数 template_name_or_list: 要进行渲染的模板名, 或一个模板名的迭代器, 将渲染第一个存在的模板.

    :param context: the variables that should be available in the
                    context of the template.
    参数 context: 在模板上下文中应当可用的变量.
    """
    ctx = _app_ctx_stack.top
    ctx.app.update_template_context(context)
    return _render(
        ctx.app.jinja_env.get_or_select_template(template_name_or_list),
        context,
        ctx.app,
    )


def render_template_string(source, **context):
    """Renders a template from the given template source string
    with the given context. Template variables will be autoescaped.

    根据给定的模板字符串和上下文渲染模板. 模板变量将自动转义.

    :param source: the source code of the template to be
                   rendered
    参数 source: 要渲染的模板源码.

    :param context: the variables that should be available in the
                    context of the template.
    参数 context: 在模板上下文中应当可用的变量.
    """
    ctx = _app_ctx_stack.top
    ctx.app.update_template_context(context)
    return _render(ctx.app.jinja_env.from_string(source), context, ctx.app)
