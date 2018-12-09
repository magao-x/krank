#!/bin/bash
set -exuo pipefail
docker build . -t magaox/krank
spython recipe Dockerfile > krank.def