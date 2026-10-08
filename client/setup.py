from pathlib import Path
from setuptools import setup, find_packages

this_directory = Path(__file__).parent
readme_path = this_directory / "README.md"
long_description = readme_path.read_text(encoding="utf-8") if readme_path.exists() else ""

setup(
    name="nubra_workshop",
    version="1.0.0",
    description="Drop-in workshop adapter for official Nubra Python SDK",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="Workshop Team",
    packages=["nubra_workshop"],
    py_modules=["nubra_patch"],
    package_data={
        "nubra_workshop": ["../nubra_workshop.pth"],
    },
    include_package_data=True,
    install_requires=[
        "nubra-sdk>=0.5.4",
    ],
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    python_requires=">=3.9",
)
