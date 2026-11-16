"""Serve the phone UI and forward servo commands to the local IoT API."""

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class ServoDemoServer(ThreadingHTTPServer):
    def __init__(self, address, device_id, actuator, api_port, sensor="room", relay="relay"):
        self.device_url = f"http://127.0.0.1:{api_port}/devices/{device_id}"
        self.actuator = actuator
        self.sensor = sensor
        self.relay = relay
        self.page = Path(__file__).with_name("index.html").read_bytes()
        super().__init__(address, ServoDemoHandler)

    def command(self, name, args):
        body = {"name": name, "args": args}
        request = Request(f"{self.device_url}/commands", data=json.dumps(body).encode(),
                          headers={"Content-Type": "application/json"}, method="POST")
        with urlopen(request, timeout=15) as response:
            return json.load(response)

    def set_angle(self, angle):
        return self.command("servo_set", {"name": self.actuator, "angle": angle})

    def relay_state(self):
        return self.command("actuator_state", {"name": self.relay})

    def set_relay(self, on, duration_ms=None):
        args = {"name": self.relay, "on": on}
        if duration_ms is not None:
            args["duration_ms"] = duration_ms
        return self.command("relay_set", args)

    def latest_reading(self):
        with urlopen(f"{self.device_url}/telemetry/latest", timeout=5) as response:
            record = json.load(response)
        if record is None:
            return None
        readings = record["readings"]
        values = readings["values"].get(self.sensor, {})
        return {
            "temperature": values.get("temperature"),
            "humidity": values.get("humidity"),
            "received_at": record["received_at"],
            "sensor_error": readings["errors"].get(self.sensor),
        }


class ServoDemoHandler(BaseHTTPRequestHandler):
    def respond(self, status, body, content_type="application/json"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def json_response(self, status, body):
        self.respond(status, json.dumps(body).encode())

    def command_response(self, call, failure):
        try:
            result = call()
        except HTTPError as exc:
            message = {404: "Không tìm thấy thiết bị", 409: "Thiết bị đang offline",
                       504: "ESP32 chưa phản hồi"}.get(exc.code, failure)
            try:
                code = json.load(exc).get("code")
            except (ValueError, AttributeError):
                code = None
            if code == "unknown_command":
                message = "Firmware trên ESP32 chưa hỗ trợ lệnh này (cần nạp bản mới)"
            elif code == "actuator_not_found":
                message = "ESP32 chưa khai báo actuator này trong config.json"
            self.json_response(exc.code, {"error": message})
        except (TimeoutError, URLError, ValueError):
            self.json_response(502, {"error": "Không nhận được phản hồi từ backend"})
        else:
            self.json_response(200, result)

    def read_json(self, limit=128):
        if self.headers.get_content_type() != "application/json":
            raise ValueError
        size = int(self.headers.get("Content-Length", "0"))
        if not 0 < size <= limit:
            raise ValueError
        body = json.loads(self.rfile.read(size))
        if not isinstance(body, dict):
            raise ValueError
        return body

    def do_GET(self):
        if self.path == "/":
            self.respond(200, self.server.page, "text/html; charset=utf-8")
        elif self.path == "/relay":
            self.command_response(self.server.relay_state, "Không đọc được trạng thái relay")
        elif self.path == "/telemetry":
            try:
                reading = self.server.latest_reading()
            except (TimeoutError, URLError, ValueError, KeyError, TypeError):
                self.json_response(502, {"error": "Không đọc được số đo từ backend"})
            else:
                self.json_response(200, reading)
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path == "/relay":
            try:
                body = self.read_json()
                on, duration_ms = body.get("on"), body.get("duration_ms")
                if type(on) is not bool or not (duration_ms is None or (
                        type(duration_ms) is int and 100 <= duration_ms <= 86400000 and on)):
                    raise ValueError
            except ValueError:
                self.json_response(400, {"error": "Cần on true/false (duration_ms tùy chọn khi bật)"})
                return
            self.command_response(lambda: self.server.set_relay(on, duration_ms),
                                  "Backend từ chối lệnh relay")
            return
        if self.path != "/angle":
            self.send_error(404)
            return
        if self.headers.get_content_type() != "application/json":
            self.json_response(415, {"error": "Expected application/json"})
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 128:
                raise ValueError
            body = json.loads(self.rfile.read(size))
            angle = body.get("angle") if isinstance(body, dict) else None
            if type(angle) is not int or not 0 <= angle <= 180:
                raise ValueError
        except ValueError:
            self.json_response(400, {"error": "Angle must be an integer from 0 to 180"})
            return
        try:
            state = self.server.set_angle(angle)
        except HTTPError as exc:
            message = {404: "Không tìm thấy thiết bị", 409: "Thiết bị đang offline",
                       504: "ESP32 chưa phản hồi"}.get(exc.code, "Backend từ chối lệnh servo")
            self.json_response(exc.code, {"error": message})
        except (TimeoutError, URLError, ValueError):
            self.json_response(502, {"error": "Không nhận được phản hồi từ backend"})
        else:
            self.json_response(200, state)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", required=True)
    parser.add_argument("--actuator", default="servo")
    parser.add_argument("--sensor", default="room")
    parser.add_argument("--relay", default="relay")
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8081)
    parser.add_argument("--api-port", type=int, default=8000)
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z0-9-]{3,48}", args.device) or args.device == "provision":
        parser.error("invalid device ID")
    with ServoDemoServer((args.bind, args.port), args.device, args.actuator,
                         args.api_port, args.sensor, args.relay) as server:
        print(f"http://{args.bind}:{args.port}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
