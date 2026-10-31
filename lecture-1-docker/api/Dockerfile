# Stage 1: Build
FROM golang:1.26 AS builder

WORKDIR /app

COPY go.mod ./
COPY main.go ./

RUN CGO_ENABLED=0 GOOS=linux go build -o api main.go

# Stage 2: Runtime
FROM alpine:3.22

WORKDIR /app

COPY --from=builder /app/api ./api

EXPOSE 8080

CMD ["./api"]
