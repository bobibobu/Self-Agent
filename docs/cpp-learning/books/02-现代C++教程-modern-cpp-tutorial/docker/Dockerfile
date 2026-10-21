# Pin to a concrete, current Node LTS. The toolchain (Hexo 8) requires
# Node >= 20.19; an unpinned `node:latest` silently drifts, and the build-env
# image was last rebuilt in 2020 (Node 15), which Hexo 8 will not run on.
FROM node:22-bookworm

LABEL "maintainer"="Changkun Ou <hi[at]changkun.de>"
LABEL "repository"="https://github.com/changkun/modern-cpp-tutorial"
LABEL "homepage"="https://changkun.de/modern-cpp/"

# For Unicode
ENV LANG C.UTF-8
ENV LC_ALL C.UTF-8

WORKDIR /modern-cpp-tutorial

# Node & Npm & Python3 are from node:latest
# Install Texlive & Pandoc
RUN apt update && \
    apt install wget texlive-full -y && \
    wget https://github.com/jgm/pandoc/releases/download/2.7.3/pandoc-2.7.3-1-amd64.deb && \
    dpkg -i pandoc-2.7.3-1-amd64.deb
