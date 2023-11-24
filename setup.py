import setuptools

with open('README.md', 'r') as fh:
    long_description = fh.read()

setuptools.setup(
    name='reloadserver',
    version='1.0.0',
    author='Densaugeo',
    author_email='author@example.com',
    description='HTTP(S) server with automatic refresh on file changes, based on Python\'s http.server',
    long_description=long_description,
    long_description_content_type='text/markdown',
    url='https://github.com/Densaugeo/reloadserver',
    packages=['reloadserver'],
    classifiers=[
        'Programming Language :: Python :: 3',
        'License :: OSI Approved :: MIT License',
        'Operating System :: OS Independent',
    ],
    python_requires='>=3.10',
    install_requires=[
        'watchdog',
    ],
    entry_points = {
        'console_scripts': ['reloadserver=reloadserver:main'],
    }
)
