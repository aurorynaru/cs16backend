# Copy the pinned 32-bit runtime without executing it during the build.
FROM --platform=linux/386 ghcr.io/balintsoos/cs16-web-server@sha256:75a410e3406cbc525329df93216c740ca76d92d45b0da7e850ef762b4f106148 AS game

# Rebuild the matching native engine: its prebuilt fragment cleanup double-frees.
FROM golang:1.25-bookworm AS native-build
RUN dpkg --add-architecture i386 \
    && apt-get update \
    && apt-get install -y --no-install-recommends git python3 build-essential \
       gcc-multilib g++-multilib pkg-config libbsd-dev:i386 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /native-src
RUN git init engine \
    && cd engine \
    && git remote add origin https://github.com/jklenner/xash3d-fwgs.git \
    && git fetch --depth 1 origin d3bc7fabeea8586f38a501b4cc6233fa0545f5f0 \
    && git checkout --detach FETCH_HEAD \
    && git submodule update --init --depth 1 3rdparty/libbacktrace/libbacktrace
RUN git init wrapper \
    && cd wrapper \
    && git remote add origin https://github.com/jklenner/goxash3d-fwgs.git \
    && git fetch --depth 1 origin 90b4aa816099db3c45cfa01dd8246f12473bce22 \
    && git checkout --detach FETCH_HEAD
COPY native /native-src/repair
RUN python3 repair/test_net_sendlong.py engine/engine/common/net_ws.c \
    && python3 repair/patch_engine.py engine/engine/common/net_ws.c
WORKDIR /native-src/engine
ENV PKG_CONFIG_PATH=/usr/lib/i386-linux-gnu/pkgconfig
RUN ./waf configure -T release -d --enable-lto --enable-openmp \
    && ./waf build -j2 \
    && cp build/engine/libxash.a build/public/libbuild_vcs.a build/public/libpublic.a \
       build/3rdparty/libbacktrace/libbacktrace.a /native-src/wrapper/pkg/
WORKDIR /native-src/repair
RUN go mod edit -replace github.com/yohimik/goxash3d-fwgs=/native-src/wrapper \
    && go mod download
RUN mkdir -p /out \
    && CGO_ENABLED=1 GOOS=linux GOARCH=386 CC="gcc -m32 -D__i386__" \
    CGO_CFLAGS="-fopenmp -m32" CGO_LDFLAGS="-fopenmp -m32" \
    go build -trimpath -o /out/xash ./server
RUN printf '%s\n' '{"repair":"FX_CS16_NET_SENDLONG_FREE_V1","engine":"d3bc7fabeea8586f38a501b4cc6233fa0545f5f0","wrapper":"90b4aa816099db3c45cfa01dd8246f12473bce22"}' > /out/FX_CS16_native_build.json

# Map-only changes reuse the repaired native-build cache.
FROM native-build AS content-build
COPY --from=game /xashds/public/gamefiles.zip /base/gamefiles.zip
COPY custom-maps/cstrike /custom/cstrike
COPY scripts/package_maps.py /package_maps.py
RUN python3 /package_maps.py --base-zip /base/gamefiles.zip --custom /custom/cstrike --output /content

FROM golang:1.25-bookworm AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN go test ./... && go vet ./... && CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -trimpath -o /gateway .

FROM debian:bookworm-slim
RUN dpkg --add-architecture i386 \
    && apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates libc6:i386 libgcc-s1:i386 libstdc++6:i386 libgomp1:i386 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 10001 --user-group --home-dir /xashds FX_CS16
COPY --from=game --chown=10001:10001 /xashds /xashds
COPY --from=native-build --chown=10001:10001 /out/xash /out/FX_CS16_native_build.json /xashds/
COPY --from=native-build --chown=10001:10001 /native-src/engine/build/filesystem/filesystem_stdio.so /xashds/filesystem_stdio.so
COPY --from=content-build --chown=10001:10001 /content/server/ /xashds/
COPY --from=content-build --chown=10001:10001 /content/gamefiles.zip /content/gamefiles.sha256 /xashds/public/
COPY --from=content-build --chown=10001:10001 /content/custom-maps.json /xashds/FX_CS16_custom_maps.json
COPY --from=build /gateway /usr/local/bin/FX_CS16_backend
ENV PORT=8080 ICE_TCP_PORT=8443 XASH3D_BASEDIR=/xashds LD_LIBRARY_PATH=/xashds
WORKDIR /xashds
RUN /usr/local/bin/FX_CS16_backend -check-files
USER 10001:10001
EXPOSE 8080 8443
ENTRYPOINT ["/usr/local/bin/FX_CS16_backend"]
