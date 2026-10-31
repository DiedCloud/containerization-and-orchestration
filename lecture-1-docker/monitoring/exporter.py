import http.client
import json
import socket
from http.server import BaseHTTPRequestHandler, HTTPServer

SOCKET = "/var/run/docker.sock"
CONTAINER = "lab1-api"


class DockerAPIError(RuntimeError):
    def __init__(self, status):
        self.status = status
        super().__init__(f"Docker API HTTP {status}")


class UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self):
        super().__init__("localhost", timeout=5)

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(5)
        self.sock.connect(SOCKET)


def docker_get(path):
    conn = UnixHTTPConnection()
    try:
        conn.request("GET", path)
        response = conn.getresponse()
        body = response.read()
        if response.status != 200:
            raise DockerAPIError(response.status)
        return json.loads(body)
    finally:
        conn.close()


def collect():
    try:
        info = docker_get(f"/containers/{CONTAINER}/json")
    except DockerAPIError as exc:
        if exc.status == 404:
            return "lab1_container_up 0\n"
        raise

    running = int(info["State"]["Running"])
    lines = [f"lab1_container_up {running}"]
    if running:
        stats = docker_get(f"/containers/{CONTAINER}/stats?stream=false&one-shot=true")
        memory = stats["memory_stats"]
        cpu = stats["cpu_stats"]
        throttling = cpu["throttling_data"]
        config = info["HostConfig"]
        quota = config.get("NanoCpus", 0) / 1e9
        if not quota and config.get("CpuQuota", 0) > 0:
            quota = config["CpuQuota"] / (config.get("CpuPeriod") or 100000)
        lines.extend([
            f'lab1_container_memory_bytes {memory["usage"]}',
            f'lab1_container_memory_limit_bytes {memory["limit"]}',
            '# TYPE lab1_container_cpu_seconds_total counter',
            f'lab1_container_cpu_seconds_total {cpu["cpu_usage"]["total_usage"] / 1e9}',
            f'lab1_container_pids {stats["pids_stats"]["current"]}',
            '# TYPE lab1_container_cpu_periods_total counter',
            f'lab1_container_cpu_periods_total {throttling["periods"]}',
            '# TYPE lab1_container_cpu_throttled_periods_total counter',
            f'lab1_container_cpu_throttled_periods_total {throttling["throttled_periods"]}',
            '# TYPE lab1_container_cpu_throttled_seconds_total counter',
            f'lab1_container_cpu_throttled_seconds_total {throttling["throttled_time"] / 1e9}',
        ])
        if quota:
            lines.append(f"lab1_container_cpu_limit_cores {quota}")
    return "\n".join(lines) + "\n"


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/metrics":
            self.send_error(404)
            return

        try:
            data = collect().encode()
        except Exception as exc:
            print(f"Collection error: {exc}", flush=True)
            self.send_error(503)
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


if __name__ == "__main__":
    print("Exporter listening on 0.0.0.0:9108", flush=True)
    HTTPServer(("0.0.0.0", 9108), Handler).serve_forever()
