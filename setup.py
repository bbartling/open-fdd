from setuptools import setup, find_packages

setup(
    name="open_fdd",
    version="0.1.0",
    author="Ben Bartling",
    author_email="ben.bartling@gmail.com",
    description="A package for fault detection and diagnosis in HVAC systems",
    long_description=open('README.md').read(),
    long_description_content_type='text/markdown',
    url="https://github.com/bbartling/open-fdd",
    packages=find_packages(),
    install_requires=[
        "pandas",
        "matplotlib",
        "python-docx",
        "docutils",
        "docxcompose",
        "argparse",
        "pytest",
    ],
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    python_requires='>=3.6',
)
