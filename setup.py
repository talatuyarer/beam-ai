from setuptools import setup, find_packages

with open("requirements.txt") as f:
  requirements = f.readlines()

setup(
    name="Apache Beam AI",
    version="0.1",
    description="English DSL for Apache Beam Framework.",
    author="Talat Uyarer",
    author_email="talat@apache.org",
    packages=find_packages(),
    install_requires=requirements,
)