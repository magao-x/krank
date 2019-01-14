#!/bin/bash
set -exuo pipefail
docker build . -t magaox/krank
spython recipe Dockerfile > Singularityfile