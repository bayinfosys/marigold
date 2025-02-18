#!/bin/bash

#
# compile Lame for mp3 encoding
#   use to build an aws lambda compatible binary
#
yum install -y gcc make tar gzip wget

# Download and compile LAME
wget https://downloads.sourceforge.net/project/lame/lame/3.100/lame-3.100.tar.gz
tar -xvf lame-3.100.tar.gz
cd lame-3.100
./configure --prefix=/var/task/lame --disable-shared
make -j$(nproc)
make install
