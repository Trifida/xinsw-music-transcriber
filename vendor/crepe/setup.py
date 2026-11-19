from setuptools import setup, find_packages

# Minimal local packaging patch for upstream CREPE 0.0.16.
# Upstream setup.py downloads all five capacities at build time. MusicMaster's
# default path uses only "full"; prepare_crepe_model.py provisions that asset.
setup(
    name="crepe",
    version="0.0.16",
    description="CREPE pitch tracker (MusicMaster isolated vendor build)",
    packages=find_packages(),
    package_data={"crepe": ["model-full.h5"]},
    include_package_data=True,
    license="MIT",
    python_requires=">=3.8",
)
