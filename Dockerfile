ARG BASE_CONTAINER=ubuntu:bionic-20180526@sha256:c8c275751219dadad8fa56b3ac41ca6cb22219ff117ca98fe82b42f24e1ba64e
FROM $BASE_CONTAINER

USER root
# Freshen up, get build tools...
ENV DEBIAN_FRONTEND noninteractive
RUN apt-get update && apt-get -yq dist-upgrade \
 && apt-get install -yq --no-install-recommends \
    wget \
    cpio \
    build-essential \
    libboost-all-dev \
    libgsl-dev \
    git \
    curl \
    bzip2 \
    ca-certificates \
    sudo \
    locales \
    fonts-liberation \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/*

# Install MKL
# http://registrationcenter-download.intel.com/akdlm/irc_nas/tec/14895/l_mkl_2019.1.144.tgz
ARG MKL_VERSION="2019.1.144"
ARG MKL_MAGIC_NUMBER="14895"
ENV MKL_DOWNLOAD "l_mkl_$MKL_VERSION"
RUN cd /tmp && \
  wget -q http://registrationcenter-download.intel.com/akdlm/irc_nas/tec/$MKL_MAGIC_NUMBER/$MKL_DOWNLOAD.tgz && \
  tar -xzf $MKL_DOWNLOAD.tgz && \
  cd $MKL_DOWNLOAD && \
  sed -i 's/ACCEPT_EULA=decline/ACCEPT_EULA=accept/g' silent.cfg && \
  ./install.sh -s silent.cfg && \
  cd .. && \
  rm -rf *
ENV MKLROOT /opt/intel/compilers_and_libraries_$MKL_VERSION/linux/mkl
RUN echo "$MKLROOT/lib" > /etc/ld.so.conf.d/mkl.conf
# Build stuff
ARG SOFA_VERSION="2018_0130_C"
# SOFA_REV_DATE=
ARG EIGEN_VERSION="3.3.4"
ARG LEVMAR_VERSION="2.6"
ARG FFTW_VERSION="3.3.8"
# FFTW
RUN cd /tmp && curl -OL http://fftw.org/fftw-$FFTW_VERSION.tar.gz && \
    tar xzf fftw-$FFTW_VERSION.tar.gz && \
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
RUN cd /tmp && curl -OL http://heasarc.gsfc.nasa.gov/FTP/software/fitsio/c/cfitsio_latest.tar.gz && \
    tar xzf cfitsio_latest.tar.gz && \
    cd cfitsio && \
    ./configure --prefix=/usr/local && \
    make && \
    make install && \
    cd && \
    rm -rf /tmp/*
# Eigen
RUN cd /tmp && curl -L http://bitbucket.org/eigen/eigen/get/$EIGEN_VERSION.tar.gz | tar xvz && \
    cp -R "$(realpath $(find . -type d -name 'eigen-eigen-*' | head -n 1))/Eigen" "/usr/local/include/" && \
    chmod -R u=rX,g=rX,o=rX /usr/local/include/Eigen && \
    cd && \
    rm -rf /tmp/*
# LevMar
RUN cd /tmp && curl -LA "Mozilla/5.0" http://users.ics.forth.gr/~lourakis/levmar/levmar-$LEVMAR_VERSION.tgz | tar xvz && \
    cd ./levmar-$LEVMAR_VERSION && \
    make liblevmar.a && \
    install liblevmar.a "/usr/local/lib/" && \
    cd && \
    rm -rf /tmp/*
# SOFA
RUN cd /tmp && curl http://www.iausofa.org/$SOFA_VERSION/sofa_c-$(echo $SOFA_VERSION | tr -d _C).tar.gz | tar xvz && \
    cd sofa/$(echo $SOFA_VERSION | tr -d _C)/c/src && \
    make "CFLAGX=-pedantic -Wall -W -O -fPIC" "CFLAGF=-c -pedantic -Wall -W -O -fPIC" && \
    make install INSTALL_DIR=/usr/local && \
    cd && \
    rm -rf /tmp/*
RUN mkdir -p /usr/local/src
# XPA
RUN cd /tmp && git clone --depth=1 https://github.com/ericmandel/xpa.git && \
    cd xpa && \
    ./configure --prefix=/usr/local && \
    make && \
    make install && \
    cd && \
    rm -rf /tmp/*
# mxlib
RUN cd /usr/local/src && \
    git clone --depth=1 https://github.com/jaredmales/mxlib.git && \
    cd mxlib && \
    echo "PREFIX = /usr/local" >> local/Common.mk && \
    make && \
    make install
ENV MXMAKEFILE /usr/local/src/mxlib/mk/MxApp.mk
# klipReduce
RUN cd /usr/local/src && \
    git clone --depth=1 https://github.com/jaredmales/klipReduce.git && \
    cd klipReduce && \
    make -B -f $MXMAKEFILE t=klipReduce && \
    make -B -f $MXMAKEFILE t=klipReduce install
