from setuptools import setup, find_packages


def read_long_description(file_path):
    with open(file_path, encoding="utf-8") as f:
        return f.read()


setup(
    name="open_fdd",
    version="0.1.8",
    author="Ben Bartling",
    author_email="ben.bartling@gmail.com",
    description="A package for fault detection and diagnosis in HVAC systems",
    long_description=read_long_description("README.md"),
    long_description_content_type="text/markdown",
    url="https://github.com/bbartling/open-fdd",
    packages=find_packages(include=["open_fdd", "open_fdd.*"]),
    install_requires=[
        "pandas",
        "matplotlib",
        "pytest",
    ],
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    python_requires=">=3.6",
)
