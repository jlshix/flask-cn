# -*- coding: utf-8 -*-
"""
    flask.__main__
    ~~~~~~~~~~~~~~

    Alias for flask.run for the command line.

    命令行工具中 flask.run 的别名

    :copyright: 2010 Pallets
    :license: BSD-3-Clause
"""

if __name__ == "__main__":
    from .cli import main

    main(as_module=True)
