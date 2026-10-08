from setuptools import setup

setup(
    name="nubra-workshop-relay",
    version="1.0.0",
    description="Drop-in workshop adapter for official Nubra Python SDK",
    author="Workshop Team",
    py_modules=["nubra_patch"],
    install_requires=[
        "nubra-sdk>=0.5.4"
    ],
    classifiers=[
        "Programming Language :: Python :: 3",
        "Operating System :: OS Independent",
    ],
    python_requires=">=3.9",
)
