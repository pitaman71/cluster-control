import setuptools

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setuptools.setup(
    name="cluster-control-pitaman71", # Replace with your own username
    version="0.0.1",
    author="Alan Pita",
    author_email="pitaman512@gmail.com",
    description="Self-contained cluster managment utility",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/pitaman71/cluster-control",
    project_urls={
        "Bug Tracker": "https://github.com/pitaman71/cluster-control/issues",
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    package_dir={"": "src"},
    packages=setuptools.find_packages(where="src"),
    python_requires=">=3.6",
)
