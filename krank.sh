#!/bin/bash
export LD_LIBRARY_PATH="/opt/intel/compilers_and_libraries_2019.1.144/linux/mkl/lib/intel64_lin:/usr/local/lib:$LD_LIBRARY_PATH"
klipReduce "$@"