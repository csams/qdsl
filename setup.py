import os
from setuptools import setup, find_packages

here = os.path.abspath(os.path.dirname(__file__))


runtime = set([
    "pyyaml",
])

develop = set([
    "coverage",
    "flake8",
    "pytest",
    "pytest-cov",
    "setuptools",
    "twine",
    "wheel",
])

docs = set([
    "Sphinx",
    "sphinx_rtd_theme",
])

optional = set([
    "IPython",
    "pandas",
])


if __name__ == "__main__":
    with open(os.path.join(here, "README.md")) as f:
        long_description = f.read()

    setup(
        name="qdsl",
        version="0.0.1",
        description="qdsl takes the tedium out of nested dicts and lists.",
        long_description=long_description,
        long_description_content_type="text/markdown",
        url="https://github.com/csams/qdsl",
        author="Christopher Sams",
        author_email="csams@gmail.com",
        packages=find_packages(),
        install_requires=list(runtime),
        package_data={"": ["LICENSE"]},
        license="Apache 2.0",
        extras_require={
            "develop": list(develop | docs | optional),
            "docs": list(docs),
            "optional": list(optional),
        },
        classifiers=[
            "Development Status :: 3 - Alpha",
            "Intended Audience :: Developers",
            "Natural Language :: English",
            "License :: OSI Approved :: Apache Software License",
            "Programming Language :: Python",
            "Programming Language :: Python :: 2.7",
            "Programming Language :: Python :: 3.6",
            "Programming Language :: Python :: 3.7",
            "Programming Language :: Python :: 3.8"
        ],
        include_package_data=True
    )
