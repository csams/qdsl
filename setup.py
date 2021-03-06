import os
from setuptools import setup, find_packages

here = os.path.abspath(os.path.dirname(__file__))


entry_points = {
    "console_scripts": [
        "qry = qdsl.cli:main"
    ]
}

runtime = set([
    "IPython",
    "pandas",
    "pyyaml",
    "requests",
])

develop = set([
    "coverage",
    "flake8",
    "pytest",
    "pytest-cov",
    "setuptools",
    "Sphinx",
    "sphinx_rtd_theme",
    "twine",
    "wheel",
])

if __name__ == "__main__":
    with open(os.path.join(here, "README.md")) as f:
        long_description = f.read()

    setup(
        name="qdsl",
        version="0.2.4",
        description="qdsl takes the tedium out of nested dicts and lists.",
        long_description=long_description,
        long_description_content_type="text/markdown",
        url="https://github.com/csams/qdsl",
        author="Christopher Sams",
        author_email="cwsams@gmail.com",
        packages=find_packages(),
        install_requires=list(runtime),
        package_data={"": ["LICENSE"]},
        license="Apache 2.0",
        extras_require={
            "develop": list(develop),
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
        include_package_data=True,
        entry_points=entry_points
    )
