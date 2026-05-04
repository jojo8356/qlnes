"""build_cython.py — compile bench_cython.pyx to a CPython C extension.

Run with the same Python that will execute the benchmark:
    .venv-spike/bin/python build_cython.py build_ext --inplace
"""
from setuptools import setup
from Cython.Build import cythonize
from pathlib import Path

HERE = Path(__file__).parent

setup(
    name="bench_cython",
    ext_modules=cythonize(
        str(HERE / "bench_cython.pyx"),
        compiler_directives={
            "language_level": 3,
            "boundscheck": False,
            "wraparound": False,
            "cdivision": True,
        },
        annotate=False,
    ),
    script_args=["build_ext", "--inplace", "--build-temp", "/tmp/cython_build"],
)
