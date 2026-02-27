# Copyright Contributors to the Open Cluster Management project
# Licensed under the Apache License 2.0

FROM registry.access.redhat.com/ubi9/go-toolset:1.24 AS builder

WORKDIR /workspace

COPY go.mod go.sum ./
RUN go mod download

COPY dev-previews/rightsizing-mcp/ dev-previews/rightsizing-mcp/

RUN CGO_ENABLED=0 GOFLAGS="" go build -o /workspace/bin/mco-rightsizing-mcp-demo ./dev-previews/rightsizing-mcp

FROM registry.access.redhat.com/ubi9/ubi-minimal:latest

ENV MAIN_BINARY=/usr/local/bin/mco-rightsizing-mcp-demo

COPY --from=builder /workspace/bin/mco-rightsizing-mcp-demo ${MAIN_BINARY}

USER 1001

ENTRYPOINT ["/usr/local/bin/mco-rightsizing-mcp-demo"]
