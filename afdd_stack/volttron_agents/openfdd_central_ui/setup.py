"""Installable VOLTTRON agent: serve Open-FDD React build at /openfdd/ on the platform web service."""

from setuptools import find_packages, setup

setup(
    name="openfddcentralui",
    version="0.1.0",
    description="Open-F-DD static UI for VOLTTRON platform web (registers /openfdd/)",
    packages=find_packages(),
    zip_safe=False,
    install_requires=[],
)
