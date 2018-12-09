# krank

> krank (comparative kränker, superlative am kränksten)
>
>   1. sick; ill
>   2. (slang) excellent
>
> — [Wiktionary](https://en.wiktionary.org/wiki/krank#German)

Turn the krank on your data reduction tasks with the magic of _containers_.

## Usage

0. Log in to [_Ocelote_](https://docs.hpc.arizona.edu/display/UAHPC/Ocelote+Quick+Start) or [_El Gato_](http://elgato.arizona.edu/getting-started)
1. `module load singularity` to make the `singularity` command available
2. (optional) `cd /extra/$USER` so that the image builds outside your (somewhat small) home directory quota
3. `singularity pull docker://magaox/krank`
4. **TODO: modify mounts, run**

## Development

0. Get access to https://hub.docker.com/r/magaox/krank/
1. Install Docker Community Edition locally
1. `pip install spython` the [Singularity CLI](https://singularityhub.github.io/singularity-cli/)
2. `git clone` this repository
3. `./build.sh` (equivalently, `docker build . -t magaox/krank && `)
4. `./push.sh` (equivalently, `docker login && docker push magaox/krank:latest`)
5. `git commit` and `git push` when it's all nice and kentucky

## Reference

  - [Dockerfile](https://docs.docker.com/engine/reference/builder/) documentation
  - [UA HPC Singularity tutorials](https://docs.hpc.arizona.edu/display/UAHPC/Singularity+Tutorials)