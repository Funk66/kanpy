from distutils.core import setup

setup(
    name = 'kanpy',
    packages = ['kanpy'],
    version = '0.1.0',
    description = 'Kanban wrapper',
    author = 'Guillermo Guirao Aguilar',
    author_email = 'contact@guillermoguiraoaguilar.com',
    url = 'https://github.com/Funk66/kanpy.git',
    keywords = ['kanban'],
    install_requires = ['requests', 'pymongo', 'pyyaml']
)
