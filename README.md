# krank

> krank (comparative kränker, superlative am kränksten)
>
>   1. sick; ill
>   2. (slang) excellent
>
> — [Wiktionary](https://en.wiktionary.org/wiki/krank#German)

Turn the krank on your data reduction tasks with the magic of _containers_.


## Usage via Docker

_TODO_

## Usage on UA HPC (Singularity)

0. Log in to [_Ocelote_](https://docs.hpc.arizona.edu/display/UAHPC/Ocelote+Quick+Start) or [_El Gato_](http://elgato.arizona.edu/getting-started)
1. `module load singularity` to make the `singularity` command available
2. Request a large temporary workspace with `xdisk -c create -m 1000` and then `cd /xdisk/$USER` so that the image builds outside your (somewhat small) home directory quota
3. `singularity build krank.img docker://magaox/krank`
4. Copy the images you want to analyze into `/xdisk/$USER` with rsync (e.g. `rsync ./data filexfer.hpc.arizona.edu:/xdisk/yournetid/data`)

## Weird quirks

  - UA HPC has a storage quota **and** a file count quota. Trying to retain intermediate files will quickly exhaust the latter, so be sure to delete those after combining.
  - Singularity only has two (useful) users, `root` at build time (as whom all build commands are run) and `$USER` (i.e. you) at run time.
  - UA-specific HPC network filesystem mount points are present as empty directories in the image to silence Singularity warnings (and let you access HPC shares when run on UA HPC)

## Development

### Inspecting the image

  - **In Singularity**: `singularity shell krank.img`
  - **In Docker**: `docker run -it magaox/krank bash` (After commenting out the entrypoint and rebuilding)

### Adding to the Docker image

0. Get access to https://hub.docker.com/r/magaox/krank/
1. Install Docker Community Edition locally
2. `git clone` this repository
3. `./build.sh`
4. `./push.sh`
5. `git commit` and `git push` when it's all nice and kentucky


## Reference

  - [Dockerfile](https://docs.docker.com/engine/reference/builder/) documentation
  - [UA HPC Singularity tutorials](https://docs.hpc.arizona.edu/display/UAHPC/Singularity+Tutorials)