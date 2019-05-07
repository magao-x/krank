FROM centos:6.10@sha256:b4c3fe75b135ca1c26ef6feb8153aade8a31c4e3e763376529c1088de7e973f4
USER root
RUN yum -y update
RUN yum -y install centos-release-scl
RUN yum -y install devtoolset-7
RUN echo "if tty -s; then source /opt/rh/devtoolset-7/enable; fi" | tee /etc/profile.d/devtoolset-7.sh
RUN echo "/usr/local/lib" | tee /etc/ld.so.conf.d/local.conf
RUN yum -y install gsl gsl-devel wget
RUN yum -y clean all

# Install MKL
# http://registrationcenter-download.intel.com/akdlm/irc_nas/tec/14895/l_mkl_2019.1.144.tgz
ENV MKL_VERSION "2019.1.144"
ENV MKL_MAGIC_NUMBER "14895"
ENV MKL_DOWNLOAD "l_mkl_$MKL_VERSION"
RUN source /opt/rh/devtoolset-7/enable && cd /tmp && \
  curl -L http://registrationcenter-download.intel.com/akdlm/irc_nas/tec/$MKL_MAGIC_NUMBER/$MKL_DOWNLOAD.tgz | \
  tar -xvz && \
  cd $MKL_DOWNLOAD && \
  sed -i 's/ACCEPT_EULA=decline/ACCEPT_EULA=accept/g' silent.cfg && \
  ./install.sh -s silent.cfg && \
  cd && \
  rm -rf /tmp/*
ENV MKLROOT /opt/intel/compilers_and_libraries_$MKL_VERSION/linux/mkl
RUN echo "$MKLROOT/lib" > /etc/ld.so.conf.d/mkl.conf
# Install a more up-to-date Boost
ENV BOOST_VERSION "1_68_0"
RUN source /opt/rh/devtoolset-7/enable && cd /tmp && \
  curl -L https://dl.bintray.com/boostorg/release/1.68.0/source/boost_$BOOST_VERSION.tar.gz | \
  tar xvz && \
  cd boost_$BOOST_VERSION && \
  ./bootstrap.sh --prefix=/usr/local --without-libraries=python && \
  ./b2 install && \
  cd && \
  rm -rf /tmp/*
# Build stuff
ENV SOFA_VERSION "2018_0130_C"
ENV EIGEN_VERSION "3.3.4"
ENV LEVMAR_VERSION "2.6"
ENV FFTW_VERSION "3.3.8"
# FFTW
RUN source /opt/rh/devtoolset-7/enable && cd /tmp && curl -L http://fftw.org/fftw-$FFTW_VERSION.tar.gz | \
    tar xvz && \
    cd fftw-$FFTW_VERSION && \
    ./configure --prefix=/usr/local --enable-float && \
    make && \
    make install && \
    ./configure --prefix=/usr/local --enable-float --enable-threads && \
    make && \
    make install && \
    ./configure --prefix=/usr/local && \
    make && \
    make install && \
    ./configure --prefix=/usr/local --enable-threads && \
    make && \
    make install && \
    ./configure --prefix=/usr/local --enable-long-double && \
    make && \
    make install && \
    ./configure --prefix=/usr/local --enable-long-double --enable-threads && \
    make && \
    make install && \
    ./configure --prefix=/usr/local --enable-quad-precision && \
    make && \
    make install && \
    ./configure --prefix=/usr/local --enable-quad-precision --enable-threads && \
    make && \
    make install && \
    cd && \
    rm -rf /tmp/*
# CFITSIO
RUN source /opt/rh/devtoolset-7/enable && cd /tmp && curl -L http://heasarc.gsfc.nasa.gov/FTP/software/fitsio/c/cfitsio_latest.tar.gz | \
    tar xvz && \
    cd cfitsio && \
    ./configure --prefix=/usr/local && \
    make && \
    make install && \
    cd && \
    rm -rf /tmp/*
# Eigen
RUN source /opt/rh/devtoolset-7/enable && cd /tmp && curl -L http://bitbucket.org/eigen/eigen/get/$EIGEN_VERSION.tar.gz | tar xvz && \
    cp -R "$(readlink -e $(find . -type d -name 'eigen-eigen-*' | head -n 1))/Eigen" "/usr/local/include/" && \
    chmod -R u=rX,g=rX,o=rX /usr/local/include/Eigen && \
    cd && \
    rm -rf /tmp/*
# LevMar
RUN source /opt/rh/devtoolset-7/enable && cd /tmp && curl -LA "Mozilla/5.0" http://users.ics.forth.gr/~lourakis/levmar/levmar-$LEVMAR_VERSION.tgz | tar xvz && \
    cd ./levmar-$LEVMAR_VERSION && \
    make liblevmar.a && \
    install liblevmar.a "/usr/local/lib/" && \
    cd && \
    rm -rf /tmp/*
# SOFA
RUN source /opt/rh/devtoolset-7/enable && cd /tmp && curl http://www.iausofa.org/$SOFA_VERSION/sofa_c-$(echo $SOFA_VERSION | tr -d _C).tar.gz | tar xvz && \
    cd sofa/$(echo $SOFA_VERSION | tr -d _C)/c/src && \
    make "CFLAGX=-pedantic -Wall -W -O -fPIC" "CFLAGF=-c -pedantic -Wall -W -O -fPIC" && \
    make install INSTALL_DIR=/usr/local && \
    cd && \
    rm -rf /tmp/*
RUN mkdir -p /usr/local/src
# XPA
RUN yum install -y git
RUN source /opt/rh/devtoolset-7/enable && cd /tmp && git clone --depth=1 https://github.com/ericmandel/xpa.git && \
    cd xpa && \
    ./configure --prefix=/usr/local && \
    make && \
    make install && \
    cd && \
    rm -rf /tmp/*
# mxlib
RUN source /opt/rh/devtoolset-7/enable && cd /usr/local/src && \
    git clone --depth=1 https://github.com/jaredmales/mxlib.git && \
    cd mxlib && \
    git checkout klipReduce && \
    echo "PREFIX = /usr/local" >> local/Common.mk && \
    make && \
    make install
ENV MXMAKEFILE /usr/local/src/mxlib/mk/MxApp.mk
# klipReduce
RUN source /opt/rh/devtoolset-7/enable && cd /usr/local/src && \
    git clone --depth=1 https://github.com/jaredmales/klipReduce.git && \
    cd klipReduce && \
    make -B -f $MXMAKEFILE t=klipReduce && \
    make -B -f $MXMAKEFILE t=klipReduce install
ENV LD_LIBRARY_PATH "/opt/intel/mkl/lib/intel64_lin:/usr/local/lib:$LD_LIBRARY_PATH"
# Python 3.7
ENV MINICONDA_VERSION 4.5.11
ENV CONDA_DIR /opt/conda
RUN mkdir -p $CONDA_DIR
ENV PATH $CONDA_DIR/bin:$PATH
# from https://github.com/jupyter/docker-stacks/blob/master/base-notebook/Dockerfile#L64
RUN cd /tmp && \
    wget --quiet https://repo.continuum.io/miniconda/Miniconda3-${MINICONDA_VERSION}-Linux-x86_64.sh && \
    echo "e1045ee415162f944b6aebfe560b8fee *Miniconda3-${MINICONDA_VERSION}-Linux-x86_64.sh" | md5sum -c - && \
    /bin/bash Miniconda3-${MINICONDA_VERSION}-Linux-x86_64.sh -f -b -p $CONDA_DIR && \
    rm Miniconda3-${MINICONDA_VERSION}-Linux-x86_64.sh && \
    $CONDA_DIR/bin/conda config --system --prepend channels conda-forge && \
    $CONDA_DIR/bin/conda config --system --set auto_update_conda false && \
    $CONDA_DIR/bin/conda config --system --set show_channel_urls true && \
    $CONDA_DIR/bin/conda install --quiet --yes conda="${MINICONDA_VERSION%.*}.*" && \
    $CONDA_DIR/bin/conda update --all --quiet --yes && \
    conda clean -tipsy
# RUN conda install --quiet --yes pytest=4.3 && \
#     conda clean -tipsy
# UA HPC specific: make directories for mount points
RUN mkdir -p /extra
RUN mkdir -p /xdisk
RUN mkdir -p /rsgrps
RUN mkdir -p /cm/shared
RUN mkdir -p /cm/local

# Docker best practice: run as unprivileged user
RUN useradd -m krank
USER krank
ADD krank.sh /usr/local/bin/krank.sh
ENTRYPOINT ["krank.sh"]